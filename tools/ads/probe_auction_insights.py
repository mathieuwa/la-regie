#!/usr/bin/env python3
"""Sonde : les statistiques sur les encheres sont-elles accessibles par l'API ?

Question tranchee une fois pour toutes plutot que supposee. On teste les
ressources candidates et on journalise la reponse exacte de l'API. Le resultat
alimente le codex : si l'API ne les expose pas, la donnee concurrentielle doit
venir de l'interface Google Ads, et il faut le dire au lieu de l'estimer.
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
# Dossier clients : relatif au depot, hors perimetre REGIE_CONFIG_DIR/REGIE_DATA_DIR.
CLIENTS_DIR = os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "clients"))

START, END = "2026-01-01", "2026-08-05"

TESTS = [
    ("auction_insight", """
        SELECT campaign.name FROM auction_insight
        WHERE segments.date BETWEEN '%s' AND '%s' LIMIT 5
    """ % (START, END)),
    ("campaign_search_term_insight", """
        SELECT campaign_search_term_insight.category_label,
               campaign_search_term_insight.id,
               metrics.impressions, metrics.clicks
        FROM campaign_search_term_insight
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.impressions DESC LIMIT 40
    """ % (START, END)),
    ("customer_search_term_insight", """
        SELECT customer_search_term_insight.category_label,
               metrics.impressions, metrics.clicks
        FROM customer_search_term_insight
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.impressions DESC LIMIT 40
    """ % (START, END)),
    ("keyword_plan_idea_placeholder", """
        SELECT campaign.name, metrics.impressions FROM campaign
        WHERE segments.date BETWEEN '%s' AND '%s' LIMIT 1
    """ % (START, END)),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True,
                        help="Nom du site dans sites.json (determine le compte Ads vise)")
    args = parser.parse_args()

    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next(s for s in sites if s["name"] == args.site)
    cid = str(conf["ads_customer_id"]).replace("-", "")
    client = GoogleAdsClient.load_from_storage(YAML_PATH)
    svc = client.get_service("GoogleAdsService")

    resultats = {}
    for nom, query in TESTS:
        print("\n=== %s ===" % nom)
        try:
            rows = []
            for batch in svc.search_stream(customer_id=cid, query=query):
                for row in batch.results:
                    rows.append(str(row).replace("\n", " ")[:400])
            resultats[nom] = {"ok": True, "lignes": len(rows), "extrait": rows[:20]}
            print("OK, %d lignes" % len(rows))
            for r in rows[:20]:
                print("   ", r)
        except GoogleAdsException as e:
            msgs = [err.message for err in e.failure.errors]
            resultats[nom] = {"ok": False, "erreur": msgs}
            print("INDISPONIBLE :", "; ".join(msgs)[:300])
        except Exception as e:  # noqa: BLE001
            resultats[nom] = {"ok": False, "erreur": str(e)}
            print("ERREUR :", str(e)[:300])

    out = os.path.join(CLIENTS_DIR, args.site, "ads", "probe-auction-insights.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(resultats, f, indent=2, ensure_ascii=False)
    print("\nGenere :", out)


if __name__ == "__main__":
    main()
