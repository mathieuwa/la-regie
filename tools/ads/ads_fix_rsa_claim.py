#!/usr/bin/env python3
"""Correction ciblee d'un titre ou d'une description non conforme dans une RSA.

Contexte : la mise en conformite d'une annonce responsive doit remplacer le
texte fautif SANS detruire l'annonce. L'API permet de mettre a jour les titres
et descriptions d'une RSA existante en conservant son identifiant, donc son
historique de performance et son apprentissage. Recreer l'annonce reinitialise
tout cela : on ne le fait pas.

Securites :
- sauvegarde integrale de l'annonce AVANT toute ecriture, dans un fichier date ;
- dry-run par defaut, l'ecriture reelle exige --live ;
- relecture de l'annonce APRES ecriture pour confirmer sur la donnee live, on ne
  se fie jamais au retour de la mutation seule ;
- si le texte a remplacer est introuvable, on s'arrete sans rien ecrire.

Usage :
  python3 ads_fix_rsa_claim.py --site {site} --ad-id 798021072451 \
      --remplacer "Remède Yeux Secs" --par "Soulagement Yeux Secs" [--live]
"""
import argparse
import json
import os
from datetime import datetime

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import protobuf_helpers

# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR (meme
# motif que ads_fetch.py, pour une installation exportee).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
YAML_PATH = os.path.join(CONFIG_DIR, "google-ads.yaml")
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")
# Repertoire de backup derive du site vise (jamais un dossier client en dur).
# Dossier clients relatif au depot (hors perimetre REGIE_CONFIG_DIR/REGIE_DATA_DIR).
_CLIENTS_DIR = os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "clients"))
BACKUP_DIR_TEMPLATE = os.path.join(_CLIENTS_DIR, "{site}", "ads", "logs")

LIMITE_TITRE = 30
LIMITE_DESCRIPTION = 90


def lire_annonce(svc, cid, ad_id):
    query = """
        SELECT campaign.name, campaign.status, ad_group.id, ad_group.name,
               ad_group_ad.ad.id, ad_group_ad.status,
               ad_group_ad.ad.responsive_search_ad.headlines,
               ad_group_ad.ad.responsive_search_ad.descriptions,
               ad_group_ad.ad.responsive_search_ad.path1,
               ad_group_ad.ad.responsive_search_ad.path2,
               ad_group_ad.ad.final_urls,
               ad_group_ad.ad_strength
        FROM ad_group_ad
        WHERE ad_group_ad.ad.id = %s
    """ % ad_id
    for batch in svc.search_stream(customer_id=cid, query=query):
        for row in batch.results:
            return row
    return None


def snapshot(row):
    a = row.ad_group_ad
    rsa = a.ad.responsive_search_ad
    return {
        "campagne": row.campaign.name,
        "campagne_statut": row.campaign.status.name,
        "ad_group": row.ad_group.name,
        "ad_group_id": str(row.ad_group.id),
        "ad_id": str(a.ad.id),
        "statut_annonce": a.status.name,
        "force": a.ad_strength.name if a.ad_strength else None,
        "urls": list(a.ad.final_urls),
        "path1": rsa.path1,
        "path2": rsa.path2,
        "titres": [{"texte": h.text, "pin": h.pinned_field.name if h.pinned_field else None}
                   for h in rsa.headlines],
        "descriptions": [{"texte": d.text, "pin": d.pinned_field.name if d.pinned_field else None}
                         for d in rsa.descriptions],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site", required=True,
                   help="Nom du site dans sites.json (determine le compte Ads vise)")
    p.add_argument("--ad-id", required=True)
    p.add_argument("--remplacer", required=True, help="Texte exact a remplacer")
    p.add_argument("--par", required=True, help="Texte de remplacement conforme")
    p.add_argument("--live", action="store_true", help="Ecriture reelle (sinon simulation)")
    args = p.parse_args()

    with open(SITES_JSON) as f:
        conf = next(s for s in json.load(f)["sites"] if s["name"] == args.site)
    cid = str(conf["ads_customer_id"]).replace("-", "")
    client = GoogleAdsClient.load_from_storage(YAML_PATH)
    svc = client.get_service("GoogleAdsService")

    row = lire_annonce(svc, cid, args.ad_id)
    if row is None:
        print("ARRET : annonce %s introuvable." % args.ad_id)
        return

    avant = snapshot(row)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_DIR_TEMPLATE.format(site=args.site)
    os.makedirs(backup_dir, exist_ok=True)
    chemin_backup = os.path.join(backup_dir, "backup-annonce-%s-%s.json" % (args.ad_id, horodatage))
    with open(chemin_backup, "w") as f:
        json.dump(avant, f, indent=2, ensure_ascii=False)
    print("Sauvegarde avant modification : %s" % chemin_backup)

    print("\nAnnonce %s | campagne %s [%s] | groupe %s | statut %s"
          % (avant["ad_id"], avant["campagne"], avant["campagne_statut"],
             avant["ad_group"], avant["statut_annonce"]))
    print("Force actuelle : %s" % avant["force"])
    print("\nTitres actuels :")
    for i, h in enumerate(avant["titres"]):
        marque = " <-- A REMPLACER" if h["texte"] == args.remplacer else ""
        print("  %2d. %-34s (%d car.)%s" % (i + 1, h["texte"], len(h["texte"]), marque))
    print("\nDescriptions actuelles :")
    for i, dsc in enumerate(avant["descriptions"]):
        marque = " <-- A REMPLACER" if dsc["texte"] == args.remplacer else ""
        print("  %2d. %-64s (%d car.)%s" % (i + 1, dsc["texte"], len(dsc["texte"]), marque))

    dans_titres = any(h["texte"] == args.remplacer for h in avant["titres"])
    dans_desc = any(d["texte"] == args.remplacer for d in avant["descriptions"])
    if not dans_titres and not dans_desc:
        print("\nARRET : le texte a remplacer est introuvable dans cette annonce. Rien ecrit.")
        return

    limite = LIMITE_TITRE if dans_titres else LIMITE_DESCRIPTION
    if len(args.par) > limite:
        print("\nARRET : le remplacement fait %d caracteres, la limite est %d. Rien ecrit."
              % (len(args.par), limite))
        return

    print("\nRemplacement prevu : \"%s\" -> \"%s\" (%d caracteres, limite %d)"
          % (args.remplacer, args.par, len(args.par), limite))

    if not args.live:
        print("\nMODE SIMULATION. Aucune ecriture effectuee. Relancer avec --live pour appliquer.")
        return

    # ---------------------------------------------------------------- ecriture
    ad_service = client.get_service("AdService")
    op = client.get_type("AdOperation")
    ad = op.update
    ad.resource_name = client.get_service("AdService").ad_path(cid, args.ad_id)

    for h in avant["titres"]:
        asset = client.get_type("AdTextAsset")
        asset.text = args.par if h["texte"] == args.remplacer else h["texte"]
        if h["pin"] and h["pin"] != "UNSPECIFIED":
            asset.pinned_field = client.enums.ServedAssetFieldTypeEnum[h["pin"]]
        ad.responsive_search_ad.headlines.append(asset)
    for d in avant["descriptions"]:
        asset = client.get_type("AdTextAsset")
        asset.text = args.par if d["texte"] == args.remplacer else d["texte"]
        if d["pin"] and d["pin"] != "UNSPECIFIED":
            asset.pinned_field = client.enums.ServedAssetFieldTypeEnum[d["pin"]]
        ad.responsive_search_ad.descriptions.append(asset)

    # Le masque se deduit des champs reellement renseignes sur l'objet mis a
    # jour : c'est l'utilitaire protobuf qui le construit, le type FieldMask
    # n'existe pas dans le namespace Google Ads.
    client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ad._pb))

    try:
        reponse = ad_service.mutate_ads(customer_id=cid, operations=[op])
        print("\nEcriture acceptee : %s" % reponse.results[0].resource_name)
    except GoogleAdsException as e:
        print("\nECHEC DE L'ECRITURE :")
        for err in e.failure.errors:
            print("  - %s" % err.message)
            if err.location:
                for fp in err.location.field_path_elements:
                    print("      champ : %s" % fp.field_name)
        print("\nAucune modification appliquee. La sauvegarde reste disponible : %s" % chemin_backup)
        return

    # -------------------------------------------------- relecture de controle
    apres = snapshot(lire_annonce(svc, cid, args.ad_id))
    chemin_apres = os.path.join(backup_dir, "apres-annonce-%s-%s.json" % (args.ad_id, horodatage))
    with open(chemin_apres, "w") as f:
        json.dump(apres, f, indent=2, ensure_ascii=False)

    print("\nRelecture sur la donnee live :")
    reste = [h["texte"] for h in apres["titres"] + apres["descriptions"] if h["texte"] == args.remplacer]
    present = [h["texte"] for h in apres["titres"] + apres["descriptions"] if h["texte"] == args.par]
    print("  ancien texte encore present : %s" % ("OUI, PROBLEME" if reste else "non"))
    print("  nouveau texte confirme      : %s" % ("oui" if present else "NON, PROBLEME"))
    print("  force de l'annonce apres    : %s (avant : %s)" % (apres["force"], avant["force"]))
    print("  etat apres modification     : %s" % chemin_apres)


if __name__ == "__main__":
    main()
