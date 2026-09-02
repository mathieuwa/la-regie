#!/usr/bin/env python3
"""A quelles campagnes actives les ressources textuelles sont-elles rattachees ?

Une extension peut porter un texte non conforme sans diffuser, si elle n'est
rattachee qu'a une campagne supprimee. Avant de toucher quoi que ce soit, on
verifie le rattachement reel plutot que de supposer.

Usage : python3 ads_check_assets_links.py --site {site}
"""
import argparse
import json
import os

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

parser = argparse.ArgumentParser()
parser.add_argument("--site", required=True,
                    help="Nom du site dans sites.json (determine le compte Ads vise)")
args = parser.parse_args()

with open(SITES_JSON) as f:
    conf = next(s for s in json.load(f)["sites"] if s["name"] == args.site)
cid = str(conf["ads_customer_id"]).replace("-", "")
client = GoogleAdsClient.load_from_storage(YAML_PATH)
svc = client.get_service("GoogleAdsService")


def run(query, label):
    rows = []
    try:
        for batch in svc.search_stream(customer_id=cid, query=query):
            for row in batch.results:
                rows.append(row)
    except GoogleAdsException as e:
        print("[!] %s : %s" % (label, "; ".join(err.message for err in e.failure.errors))[:300])
    except Exception as e:  # noqa: BLE001
        print("[!] %s : %s" % (label, e))
    return rows


print("=== RESSOURCES RATTACHEES AU NIVEAU CAMPAGNE ===")
q = """
    SELECT campaign.name, campaign.status, campaign_asset.asset,
           campaign_asset.field_type, campaign_asset.status,
           asset.id, asset.type,
           asset.sitelink_asset.link_text,
           asset.callout_asset.callout_text,
           asset.structured_snippet_asset.values
    FROM campaign_asset
    WHERE campaign_asset.status != 'REMOVED'
"""
for row in run(q, "campaign_asset"):
    a = row.asset
    texte = (a.sitelink_asset.link_text or a.callout_asset.callout_text
             or ", ".join(a.structured_snippet_asset.values) or "")
    print("  %-30s [%-8s] champ=%-22s asset=%-14s %s"
          % (row.campaign.name[:30], row.campaign.status.name,
             row.campaign_asset.field_type.name, str(a.id), texte[:60]))

print("\n=== RESSOURCES AU NIVEAU COMPTE (s'appliquent a TOUTES les campagnes) ===")
q2 = """
    SELECT customer_asset.asset, customer_asset.field_type, customer_asset.status,
           asset.id, asset.type,
           asset.sitelink_asset.link_text,
           asset.sitelink_asset.description1,
           asset.sitelink_asset.description2,
           asset.callout_asset.callout_text,
           asset.structured_snippet_asset.values
    FROM customer_asset
    WHERE customer_asset.status != 'REMOVED'
"""
for row in run(q2, "customer_asset"):
    a = row.asset
    parts = [a.sitelink_asset.link_text, a.sitelink_asset.description1,
             a.sitelink_asset.description2, a.callout_asset.callout_text]
    parts += list(a.structured_snippet_asset.values)
    texte = " | ".join(p for p in parts if p)
    print("  champ=%-24s asset=%-14s statut=%-9s %s"
          % (row.customer_asset.field_type.name, str(a.id),
             row.customer_asset.status.name, texte[:80]))

print("\n=== RESSOURCES AU NIVEAU GROUPE D'ANNONCES ===")
q3 = """
    SELECT campaign.name, campaign.status, ad_group.name,
           ad_group_asset.field_type, ad_group_asset.status, asset.id,
           asset.sitelink_asset.link_text,
           asset.callout_asset.callout_text
    FROM ad_group_asset
    WHERE ad_group_asset.status != 'REMOVED'
"""
for row in run(q3, "ad_group_asset"):
    a = row.asset
    texte = a.sitelink_asset.link_text or a.callout_asset.callout_text or ""
    print("  %-26s [%-8s] %-24s champ=%-20s asset=%-14s %s"
          % (row.campaign.name[:26], row.campaign.status.name, row.ad_group.name[:24],
             row.ad_group_asset.field_type.name, str(a.id), texte[:50]))
