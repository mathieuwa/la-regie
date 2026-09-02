#!/usr/bin/env python3
"""Themes de requetes (search term insights) sur une plage.

Cette vue regroupe les requetes reelles en categories semantiques cote Google.
Elle repond a une question que le search_term_view ne sait pas traiter : sur
quels THEMES de demande le compte est expose, et lesquels il capte mal.

Note importante pour le codex : la ressource auction_insight (statistiques sur
les encheres, donc les concurrents nommes) N'EXISTE PAS dans l'API Google Ads,
verifie le 05/08/2026 en v24 ("is not a valid resource name"). La donnee
concurrentielle nominative ne s'obtient que dans l'interface Google Ads. Ne
jamais l'estimer ni la deduire d'une SERP : le dire.

Usage :
  python3 ads_fetch_themes.py --site monsite --start 2026-01-01 --end 2026-08-05 \
      --out clients/monsite/ads/fetch-2026-08/themes-requetes.json
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next(s for s in sites if s["name"] == args.site)
    cid = str(conf["ads_customer_id"]).replace("-", "")
    client = GoogleAdsClient.load_from_storage(YAML_PATH)
    svc = client.get_service("GoogleAdsService")

    query = """
        SELECT
            customer_search_term_insight.category_label,
            customer_search_term_insight.id,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM customer_search_term_insight
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.impressions DESC
        LIMIT 300
    """ % (args.start, args.end)

    themes = []
    erreur = None
    try:
        for batch in svc.search_stream(customer_id=cid, query=query):
            for row in batch.results:
                m = row.metrics
                lab = row.customer_search_term_insight.category_label
                themes.append({
                    "theme": lab if lab else "(non categorise)",
                    "impressions": m.impressions,
                    "clicks": m.clicks,
                    "ctr": round(m.clicks / m.impressions * 100, 2) if m.impressions else 0,
                    "conversions": round(m.conversions, 1),
                    "conv_value": round(m.conversions_value, 2),
                })
    except GoogleAdsException as e:
        erreur = [err.message for err in e.failure.errors]
        print("ERREUR :", erreur)

    data = {
        "site": args.site,
        "customer_id": cid,
        "periode": {"start": args.start, "end": args.end},
        "source": "customer_search_term_insight (themes de requetes Google Ads)",
        "limite_connue": "La ressource auction_insight n'existe pas dans l'API Google Ads (verifie le 05/08/2026, v24). Les concurrents nommes ne s'obtiennent que dans l'interface, onglet Statistiques sur les encheres.",
        "themes": themes,
        "erreur": erreur,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("Genere : %s (%d themes)" % (args.out, len(themes)))
    tot_imp = sum(t["impressions"] for t in themes)
    print("\n%-46s %10s %8s %6s %8s %10s" % ("theme", "impr.", "clics", "CTR", "conv", "valeur"))
    for t in themes[:45]:
        print("%-46s %10d %8d %5.2f%% %8.1f %10.2f"
              % (t["theme"][:46], t["impressions"], t["clicks"], t["ctr"],
                 t["conversions"], t["conv_value"]))
    print("\nTotal impressions couvertes par les themes : %d" % tot_imp)


if __name__ == "__main__":
    main()
