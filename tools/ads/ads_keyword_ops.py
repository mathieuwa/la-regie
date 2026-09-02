#!/usr/bin/env python3
"""
Google Ads — Operations sur les keywords : pause + ajustement CPC.

Usage:
  python3 ads_keyword_ops.py --site {site} --campaign "NOM_EXACT_CAMPAGNE" \
      --ops-file chemin/vers/keyword-ops.json

Le fichier --ops-file est OBLIGATOIRE : il porte les listes d'operations
(keywords_to_pause, keywords_to_reduce_cpc). Aucune liste n'est codee en dur :
le script REFUSE de tourner sans ce fichier. Modele :
tools/ads/examples/keyword-ops.example.json

Lit les keywords de la campagne, applique les modifications, verifie.
ATTENTION : ECRITURE API directe (mutate) sur le compte du site vise.
"""

import argparse
import json
import os
import sys

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Config partagee avec tools/seo-audit/ (source unique, pas de duplication
# de secrets : google-ads.yaml et sites.json restent la-bas).
# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR (meme
# motif que ads_fetch.py, pour une installation exportee).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
YAML_PATH = os.path.join(CONFIG_DIR, "google-ads.yaml")
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")
DATA_DIR = os.environ.get(
    "REGIE_DATA_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "data"))
)


def load_ops_file(path: str) -> tuple:
    """Charge et valide le fichier d'operations JSON (--ops-file).

    Schema attendu :
      {
        "keywords_to_pause": ["mot cle a", "mot cle b"],
        "keywords_to_reduce_cpc": {"mot cle c": {"target_cpc": 0.35}}
      }
    Retourne (keywords_to_pause, keywords_to_reduce_cpc).
    Leve SystemExit avec un message clair si le fichier est absent,
    invalide, ou ne contient aucune operation.
    """
    if not os.path.exists(path):
        sys.exit(f"ERREUR : fichier d'operations introuvable : {path}\n"
                 "Modele : tools/ads/examples/keyword-ops.example.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"ERREUR : JSON invalide dans {path} : {e}")
    if not isinstance(data, dict):
        sys.exit(f"ERREUR : {path} doit contenir un objet JSON "
                 "(cle keywords_to_pause et/ou keywords_to_reduce_cpc)")

    to_pause = data.get("keywords_to_pause", [])
    to_reduce = data.get("keywords_to_reduce_cpc", {})

    if not isinstance(to_pause, list) or not all(isinstance(k, str) for k in to_pause):
        sys.exit(f"ERREUR : keywords_to_pause doit etre une liste de chaines ({path})")
    if not isinstance(to_reduce, dict):
        sys.exit(f"ERREUR : keywords_to_reduce_cpc doit etre un objet "
                 f"{{keyword: {{\"target_cpc\": X}}}} ({path})")
    for kw, params in to_reduce.items():
        if not isinstance(params, dict) or not isinstance(params.get("target_cpc"), (int, float)):
            sys.exit(f"ERREUR : keywords_to_reduce_cpc['{kw}'] doit porter un "
                     f"target_cpc numerique ({path})")

    if not to_pause and not to_reduce:
        sys.exit(f"ERREUR : {path} ne contient aucune operation "
                 "(keywords_to_pause et keywords_to_reduce_cpc vides). "
                 "Refus de tourner : rien a appliquer.")
    return to_pause, to_reduce


def load_site_config(site_name: str) -> dict:
    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next((s for s in sites if s["name"] == site_name), None)
    if not conf:
        raise ValueError(f"Site '{site_name}' inconnu dans sites.json")
    return conf


def micros_to_euros(micros) -> float:
    return round(int(micros) / 1_000_000, 2)


def euros_to_micros(euros: float) -> int:
    return int(round(euros * 1_000_000))


def fetch_keywords_for_campaign(client, customer_id: str, campaign_name: str) -> list:
    """Recupere tous les keywords d'une campagne avec leurs resource names et statuts."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            ad_group_criterion.resource_name,
            ad_group_criterion.criterion_id,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.status,
            ad_group_criterion.cpc_bid_micros,
            ad_group.id,
            ad_group.name,
            campaign.id,
            campaign.name
        FROM ad_group_criterion
        WHERE campaign.name = '{campaign_name}'
          AND ad_group_criterion.type = 'KEYWORD'
          AND campaign.status IN ('ENABLED', 'PAUSED')
          AND ad_group.status IN ('ENABLED', 'PAUSED')
        ORDER BY ad_group_criterion.keyword.text
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            crit = row.ad_group_criterion
            results.append({
                "resource_name": crit.resource_name,
                "criterion_id": str(crit.criterion_id),
                "keyword": crit.keyword.text,
                "match_type": crit.keyword.match_type.name,
                "status": crit.status.name,
                "cpc_bid_micros": crit.cpc_bid_micros,
                "cpc_bid_eur": micros_to_euros(crit.cpc_bid_micros),
                "ad_group_id": str(row.ad_group.id),
                "ad_group_name": row.ad_group.name,
                "campaign_name": row.campaign.name,
            })
    return results


def pause_keyword(client, customer_id: str, resource_name: str) -> bool:
    """Met un keyword en pause. Retourne True si succes."""
    ad_group_criterion_service = client.get_service("AdGroupCriterionService")
    ad_group_criterion_operation = client.get_type("AdGroupCriterionOperation")

    criterion = ad_group_criterion_operation.update
    criterion.resource_name = resource_name
    criterion.status = client.enums.AdGroupCriterionStatusEnum.PAUSED

    # Champ mask
    from google.protobuf import field_mask_pb2
    field_mask = field_mask_pb2.FieldMask(paths=["status"])
    ad_group_criterion_operation.update_mask.CopyFrom(field_mask)

    try:
        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=customer_id,
            operations=[ad_group_criterion_operation]
        )
        return True
    except GoogleAdsException as ex:
        print(f"  ERREUR pause_keyword: {resource_name}")
        for error in ex.failure.errors:
            print(f"    {error.message}")
        return False


def update_cpc_bid(client, customer_id: str, resource_name: str, new_cpc_eur: float) -> bool:
    """Modifie le CPC bid d'un keyword. Retourne True si succes."""
    ad_group_criterion_service = client.get_service("AdGroupCriterionService")
    ad_group_criterion_operation = client.get_type("AdGroupCriterionOperation")

    criterion = ad_group_criterion_operation.update
    criterion.resource_name = resource_name
    criterion.cpc_bid_micros = euros_to_micros(new_cpc_eur)

    from google.protobuf import field_mask_pb2
    field_mask = field_mask_pb2.FieldMask(paths=["cpc_bid_micros"])
    ad_group_criterion_operation.update_mask.CopyFrom(field_mask)

    try:
        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=customer_id,
            operations=[ad_group_criterion_operation]
        )
        return True
    except GoogleAdsException as ex:
        print(f"  ERREUR update_cpc_bid: {resource_name}")
        for error in ex.failure.errors:
            print(f"    {error.message}")
        return False


def verify_keyword(client, customer_id: str, resource_name: str) -> dict:
    """Relit le statut et le CPC d'un keyword apres modification."""
    ga_service = client.get_service("GoogleAdsService")
    # Extraire ad_group_id et criterion_id du resource_name
    # Format: customers/{customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}
    query = f"""
        SELECT
            ad_group_criterion.resource_name,
            ad_group_criterion.status,
            ad_group_criterion.cpc_bid_micros,
            ad_group_criterion.keyword.text
        FROM ad_group_criterion
        WHERE ad_group_criterion.resource_name = '{resource_name}'
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            crit = row.ad_group_criterion
            return {
                "status": crit.status.name,
                "cpc_bid_eur": micros_to_euros(crit.cpc_bid_micros),
                "keyword": crit.keyword.text,
            }
    return {}


# ==========================================================
# Negatifs de campagne (utilises par ads_apply.py en ecriture reelle)
# ==========================================================

def get_client_and_customer(site: str):
    """Charge le GoogleAdsClient et resout le customer_id d'un site.

    Utilise par ads_apply.py quand dry_run=False. Leve une erreur explicite
    si la config ou le customer_id manque, plutot que d'ecrire a l'aveugle.
    """
    conf = load_site_config(site)
    customer_id = conf.get("ads_customer_id")
    if not customer_id:
        raise ValueError(f"ads_customer_id manquant pour le site '{site}'")
    if not os.path.exists(YAML_PATH):
        raise FileNotFoundError(f"google-ads.yaml introuvable : {YAML_PATH}")
    client = GoogleAdsClient.load_from_storage(path=YAML_PATH)
    return client, str(customer_id)


def add_campaign_negative(client, customer_id: str, campaign_id: str, text: str, match_type: str) -> str:
    """Ajoute un mot-cle negatif au niveau CAMPAGNE. Retourne le resource_name cree.

    match_type : 'EXACT', 'PHRASE' ou 'BROAD' (les negatifs sensibles se posent
    en EXACT/PHRASE, jamais en BROAD sur un terme court, cf. piege 5 du codex).
    Reversible : remove_campaign_negative(resource_name).
    """
    mt = (match_type or "EXACT").upper()
    if mt not in ("EXACT", "PHRASE", "BROAD"):
        raise ValueError(f"match_type invalide : {match_type}")

    campaign_service = client.get_service("CampaignService")
    criterion_service = client.get_service("CampaignCriterionService")
    op = client.get_type("CampaignCriterionOperation")
    crit = op.create
    crit.campaign = campaign_service.campaign_path(customer_id, campaign_id)
    crit.negative = True
    crit.keyword.text = text
    crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[mt]

    response = criterion_service.mutate_campaign_criteria(
        customer_id=customer_id, operations=[op]
    )
    return response.results[0].resource_name


def list_campaign_negatives(client, customer_id: str, campaign_id: str) -> list:
    """Liste les mots-cles negatifs d'une campagne (verification / rollback)."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            campaign_criterion.resource_name,
            campaign_criterion.keyword.text,
            campaign_criterion.keyword.match_type
        FROM campaign_criterion
        WHERE campaign.id = {campaign_id}
          AND campaign_criterion.negative = TRUE
          AND campaign_criterion.type = 'KEYWORD'
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    out = []
    for batch in stream:
        for row in batch.results:
            cc = row.campaign_criterion
            out.append({
                "resource_name": cc.resource_name,
                "keyword": cc.keyword.text,
                "match_type": cc.keyword.match_type.name,
            })
    return out


def remove_campaign_negative(client, customer_id: str, resource_name: str) -> bool:
    """Retire un mot-cle negatif de campagne (rollback d'un add_campaign_negative)."""
    criterion_service = client.get_service("CampaignCriterionService")
    op = client.get_type("CampaignCriterionOperation")
    op.remove = resource_name
    try:
        criterion_service.mutate_campaign_criteria(
            customer_id=customer_id, operations=[op]
        )
        return True
    except GoogleAdsException as ex:
        print(f"  ERREUR remove_campaign_negative: {resource_name}")
        for error in ex.failure.errors:
            print(f"    {error.message}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Operations keywords Google Ads (pause, ajustement CPC). "
                    "ECRITURE API directe : les operations viennent OBLIGATOIREMENT "
                    "d'un fichier JSON passe via --ops-file, jamais de listes en dur."
    )
    parser.add_argument("--site", required=True,
                        help="Nom du site dans sites.json (determine le compte Ads vise)")
    parser.add_argument("--campaign", required=True,
                        help="Nom EXACT de la campagne")
    parser.add_argument("--ops-file", required=True,
                        help="Fichier JSON des operations (keywords_to_pause, "
                             "keywords_to_reduce_cpc). OBLIGATOIRE. Modele : "
                             "tools/ads/examples/keyword-ops.example.json")
    args = parser.parse_args()

    keywords_to_pause, keywords_to_reduce_cpc = load_ops_file(args.ops_file)

    conf = load_site_config(args.site)
    customer_id = conf.get("ads_customer_id")
    if not customer_id:
        print(f"ads_customer_id manquant pour '{args.site}'")
        sys.exit(1)

    if not os.path.exists(YAML_PATH):
        print(f"google-ads.yaml introuvable : {YAML_PATH}")
        sys.exit(1)

    try:
        client = GoogleAdsClient.load_from_storage(path=YAML_PATH)
    except Exception as e:
        print(f"Erreur chargement config Google Ads : {e}")
        sys.exit(1)

    print(f"\n=== Fetch keywords : campagne '{args.campaign}' ===")
    keywords = fetch_keywords_for_campaign(client, customer_id, args.campaign)

    if not keywords:
        print(f"Aucun keyword trouve pour la campagne '{args.campaign}'")
        print("Verifier que le nom exact de la campagne est correct.")
        sys.exit(1)

    print(f"Keywords trouves : {len(keywords)}")
    for kw in keywords:
        print(f"  [{kw['status']:10}] {kw['keyword']:40} | {kw['match_type']:10} | CPC: {kw['cpc_bid_eur']} EUR | {kw['resource_name']}")

    # ==========================================================
    # OPERATIONS A APPLIQUER — chargees depuis --ops-file, jamais en dur
    # ==========================================================
    KEYWORDS_TO_PAUSE = keywords_to_pause
    KEYWORDS_TO_REDUCE_CPC = keywords_to_reduce_cpc
    print(f"\nOperations chargees depuis {args.ops_file} : "
          f"{len(KEYWORDS_TO_PAUSE)} pause(s), {len(KEYWORDS_TO_REDUCE_CPC)} reduction(s) CPC")

    # Index par texte de keyword (insensible a la casse)
    kw_index = {kw["keyword"].lower(): kw for kw in keywords}

    # Structure de resultat
    results = []

    # --- PAUSES ---
    for kw_text in KEYWORDS_TO_PAUSE:
        kw_lower = kw_text.lower()
        row = kw_index.get(kw_lower)

        if not row:
            results.append({
                "keyword": kw_text,
                "action": "PAUSE",
                "status_avant": "INTROUVABLE",
                "status_apres": "N/A",
                "resultat": "ERREUR - keyword non trouve dans la campagne",
            })
            continue

        status_avant = row["status"]

        if status_avant == "PAUSED":
            results.append({
                "keyword": kw_text,
                "action": "PAUSE",
                "status_avant": status_avant,
                "status_apres": "PAUSED (deja en pause)",
                "resultat": "OK - deja en pause",
            })
            continue

        print(f"\nPause : '{kw_text}' (statut actuel: {status_avant})")
        success = pause_keyword(client, customer_id, row["resource_name"])

        if success:
            # Verification immediate
            verified = verify_keyword(client, customer_id, row["resource_name"])
            status_apres = verified.get("status", "INCONNU")
            ok = "OK" if status_apres == "PAUSED" else "ERREUR - statut inattendu"
        else:
            status_apres = "ECHEC MUTATION"
            ok = "ERREUR"

        results.append({
            "keyword": kw_text,
            "action": "PAUSE",
            "status_avant": status_avant,
            "status_apres": status_apres,
            "resultat": ok,
        })

    # --- REDUCTION CPC ---
    for kw_text, params in KEYWORDS_TO_REDUCE_CPC.items():
        kw_lower = kw_text.lower()
        row = kw_index.get(kw_lower)

        if not row:
            results.append({
                "keyword": kw_text,
                "action": f"REDUCTION CPC -30% (cible {params['target_cpc']} EUR)",
                "status_avant": "INTROUVABLE",
                "status_apres": "N/A",
                "resultat": "ERREUR - keyword non trouve dans la campagne",
            })
            continue

        status_avant = row["status"]
        cpc_avant = row["cpc_bid_eur"]
        target_cpc = params["target_cpc"]

        print(f"\nReduction CPC : '{kw_text}' | {cpc_avant} EUR -> {target_cpc} EUR (-30%)")
        success = update_cpc_bid(client, customer_id, row["resource_name"], target_cpc)

        if success:
            verified = verify_keyword(client, customer_id, row["resource_name"])
            cpc_apres = verified.get("cpc_bid_eur", "INCONNU")
            ok = "OK" if abs(float(cpc_apres) - target_cpc) < 0.01 else f"ERREUR - CPC obtenu {cpc_apres} EUR"
        else:
            cpc_apres = "ECHEC MUTATION"
            ok = "ERREUR"

        results.append({
            "keyword": kw_text,
            "action": f"REDUCTION CPC -30% ({cpc_avant} EUR -> {target_cpc} EUR)",
            "status_avant": f"{status_avant} | CPC: {cpc_avant} EUR",
            "status_apres": f"{status_avant} | CPC: {cpc_apres} EUR",
            "resultat": ok,
        })

    # ==========================================================
    # TABLEAU DE CONFIRMATION
    # ==========================================================
    print("\n")
    print("=" * 100)
    print("TABLEAU DE CONFIRMATION")
    print("=" * 100)
    print(f"{'Keyword':<35} {'Action':<42} {'Statut avant':<28} {'Statut apres':<28} {'Resultat'}")
    print("-" * 100)
    for r in results:
        print(f"{r['keyword']:<35} {r['action']:<42} {r['status_avant']:<28} {r['status_apres']:<28} {r['resultat']}")
    print("=" * 100)

    # Export JSON pour trace
    out_path = os.path.join(
        DATA_DIR, args.site, f"ops_keyword_{args.campaign.replace(' ', '_')}.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "campaign": args.campaign,
            "customer_id": customer_id,
            "operations": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nTrace exportee : {out_path}")


if __name__ == "__main__":
    main()
