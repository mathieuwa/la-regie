#!/usr/bin/env python3
"""Releve exhaustif des TEXTES publicitaires du compte, pour controle d'allegations.

Objectif : savoir precisement ce qui est ecrit dans le compte avant de modifier
quoi que ce soit. On ratisse tout ce qui porte du texte visible par un
internaute : titres et descriptions des annonces responsives, ressources
(extensions de liens, accroches, extraits structures), et les mots-cles.

Distinction essentielle, a ne jamais confondre :
- un TEXTE D'ANNONCE qui affirme un effet therapeutique est une allegation, et
  c'est nous qui l'ecrivons : c'est corrigeable et c'est notre responsabilite ;
- un MOT-CLE qui cible la requete "chalazion traitement" n'est pas une
  allegation, c'est un ciblage de la demande telle que l'internaute la formule.
  Le supprimer ne met rien en conformite et detruit du chiffre d'affaires.

Sortie : JSON complet + rapport lisible.
"""
import argparse
import json
import os
import re
import unicodedata

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR (meme
# motif que ads_fetch.py, pour une installation exportee).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
YAML_PATH = os.path.join(CONFIG_DIR, "google-ads.yaml")
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")

# Vocabulaire a risque en publicite sante. Deux niveaux :
# ROUGE  : affirme un effet therapeutique, une guerison ou une caution medicale.
# ORANGE : ambigu selon la formulation, demande une lecture humaine.
ROUGE = [
    "traiter", "traitement", "guerir", "guerison", "soigner", "soin curatif",
    "prescrit", "prescription", "ordonnance", "recommande par les ophtalmo",
    "recommandee par les ophtalmo", "medicalement prouve", "cliniquement prouve",
    "efficacite prouvee", "remede", "therapeutique", "elimine la blepharite",
    "supprime le chalazion", "previent la maladie",
]
ORANGE = [
    "clinique", "cliniquement", "medical", "medicale", "dispositif medical",
    "ophtalmologiste", "ophtalmologue", "professionnel de sante", "validee",
    "certifie ce", "efficace contre", "agit sur", "pathologie",
]


def sansaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")


def analyse(texte):
    t = sansaccent(texte)
    return {
        "rouge": sorted({m for m in ROUGE if m in t}),
        "orange": sorted({m for m in ORANGE if m in t}),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site", required=True,
                   help="Nom du site dans sites.json (determine le compte Ads vise)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next(s for s in sites if s["name"] == args.site)
    cid = str(conf["ads_customer_id"]).replace("-", "")
    client = GoogleAdsClient.load_from_storage(YAML_PATH)
    svc = client.get_service("GoogleAdsService")

    data = {"customer_id": cid, "annonces": [], "assets": [], "mots_cles": [],
            "sitelinks": [], "erreurs": []}

    def run(query, label):
        rows = []
        try:
            for batch in svc.search_stream(customer_id=cid, query=query):
                for row in batch.results:
                    rows.append(row)
        except GoogleAdsException as e:
            msgs = [err.message for err in e.failure.errors]
            data["erreurs"].append({"bloc": label, "erreur": msgs})
            print("  [!] %s : %s" % (label, "; ".join(msgs))[:250])
        except Exception as e:  # noqa: BLE001
            data["erreurs"].append({"bloc": label, "erreur": str(e)})
        return rows

    # 1. Annonces responsives, toutes campagnes y compris en pause
    q_ads = """
        SELECT
            campaign.id, campaign.name, campaign.status,
            ad_group.id, ad_group.name,
            ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.ad.type,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.responsive_search_ad.path1,
            ad_group_ad.ad.responsive_search_ad.path2,
            ad_group_ad.ad.final_urls
        FROM ad_group_ad
        WHERE ad_group_ad.status != 'REMOVED'
    """
    for row in run(q_ads, "annonces"):
        a = row.ad_group_ad
        rsa = a.ad.responsive_search_ad
        titres = [h.text for h in rsa.headlines]
        descs = [d.text for d in rsa.descriptions]
        entree = {
            "campagne": row.campaign.name,
            "campagne_id": str(row.campaign.id),
            "campagne_statut": row.campaign.status.name,
            "ad_group": row.ad_group.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_id": str(a.ad.id),
            "statut": a.status.name,
            "type": a.ad.type_.name,
            "urls": list(a.ad.final_urls),
            "titres": [], "descriptions": [],
        }
        for t in titres:
            entree["titres"].append({"texte": t, **analyse(t)})
        for d in descs:
            entree["descriptions"].append({"texte": d, **analyse(d)})
        data["annonces"].append(entree)

    # 2. Ressources textuelles rattachees au compte (extensions)
    q_asset = """
        SELECT
            asset.id, asset.type, asset.name,
            asset.sitelink_asset.link_text,
            asset.sitelink_asset.description1,
            asset.sitelink_asset.description2,
            asset.callout_asset.callout_text,
            asset.structured_snippet_asset.header,
            asset.structured_snippet_asset.values,
            asset.promotion_asset.promotion_target,
            asset.final_urls
        FROM asset
    """
    for row in run(q_asset, "assets"):
        a = row.asset
        textes = []
        if a.sitelink_asset.link_text:
            textes.append(a.sitelink_asset.link_text)
        if a.sitelink_asset.description1:
            textes.append(a.sitelink_asset.description1)
        if a.sitelink_asset.description2:
            textes.append(a.sitelink_asset.description2)
        if a.callout_asset.callout_text:
            textes.append(a.callout_asset.callout_text)
        if a.structured_snippet_asset.header:
            textes.append(a.structured_snippet_asset.header)
        for v in a.structured_snippet_asset.values:
            textes.append(v)
        if not textes:
            continue
        for t in textes:
            res = analyse(t)
            data["assets"].append({
                "asset_id": str(a.id),
                "type": a.type_.name,
                "nom": a.name,
                "texte": t,
                "urls": list(a.final_urls),
                **res,
            })

    # 3. Mots-cles (releves pour information, PAS pour suppression au motif
    #    d'allegation : cibler une requete n'est pas affirmer un effet)
    q_kw = """
        SELECT
            campaign.name, ad_group.name,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.status,
            ad_group_criterion.criterion_id,
            metrics.cost_micros, metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE segments.date BETWEEN '2026-01-01' AND '2026-08-05'
          AND ad_group_criterion.status != 'REMOVED'
        ORDER BY metrics.cost_micros DESC
    """
    for row in run(q_kw, "mots_cles"):
        c = row.ad_group_criterion
        m = row.metrics
        txt = c.keyword.text
        res = analyse(txt)
        data["mots_cles"].append({
            "campagne": row.campaign.name,
            "ad_group": row.ad_group.name,
            "criterion_id": str(c.criterion_id),
            "mot_cle": txt,
            "match": c.keyword.match_type.name,
            "statut": c.status.name,
            "cout": round((m.cost_micros or 0) / 1e6, 2),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            **res,
        })

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # ---------------------------------------------------------------- rapport
    print("=" * 78)
    print("TEXTES D'ANNONCES (ce que nous ecrivons, donc notre responsabilite)")
    print("=" * 78)
    n_rouge = 0
    for ad in data["annonces"]:
        flags = [x for x in ad["titres"] + ad["descriptions"] if x["rouge"] or x["orange"]]
        if not flags:
            continue
        print("\n--- %s | %s | annonce %s | %s ---"
              % (ad["campagne"], ad["ad_group"], ad["ad_id"], ad["statut"]))
        print("    URL : %s" % (", ".join(ad["urls"])[:120]))
        for x in ad["titres"]:
            if x["rouge"] or x["orange"]:
                n_rouge += 1 if x["rouge"] else 0
                print("  TITRE   [%s%s] %s"
                      % ("ROUGE:" + ",".join(x["rouge"]) if x["rouge"] else "",
                         " ORANGE:" + ",".join(x["orange"]) if x["orange"] else "",
                         x["texte"]))
        for x in ad["descriptions"]:
            if x["rouge"] or x["orange"]:
                n_rouge += 1 if x["rouge"] else 0
                print("  DESCR   [%s%s] %s"
                      % ("ROUGE:" + ",".join(x["rouge"]) if x["rouge"] else "",
                         " ORANGE:" + ",".join(x["orange"]) if x["orange"] else "",
                         x["texte"]))

    print("\n" + "=" * 78)
    print("RESSOURCES / EXTENSIONS")
    print("=" * 78)
    for a in data["assets"]:
        if a["rouge"] or a["orange"]:
            print("  [%s] %-22s %s"
                  % ("ROUGE" if a["rouge"] else "orange", a["type"], a["texte"]))
            print("        motifs : %s %s" % (a["rouge"], a["orange"]))

    print("\n" + "=" * 78)
    print("MOTS-CLES contenant un terme du vocabulaire surveille")
    print("(RELEVE POUR INFORMATION : cibler une requete n'est PAS une allegation)")
    print("=" * 78)
    for k in data["mots_cles"]:
        if k["rouge"] or k["orange"]:
            print("  %-42s %-10s cout %7.2f conv %5.1f val %8.2f | %s %s"
                  % (k["mot_cle"][:42], k["match"], k["cout"], k["conversions"],
                     k["conv_value"], k["rouge"], k["orange"]))

    print("\nTotal annonces scannees : %d | ressources : %d | mots-cles : %d"
          % (len(data["annonces"]), len(data["assets"]), len(data["mots_cles"])))
    print("Genere : %s" % args.out)
    if data["erreurs"]:
        print("Blocs en erreur : %s" % data["erreurs"])


if __name__ == "__main__":
    main()
