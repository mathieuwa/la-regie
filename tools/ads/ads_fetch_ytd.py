#!/usr/bin/env python3
"""
Google Ads Fetch YTD, couverture et saisonnalite.

Complement de ads_fetch.py : ce script remonte ce que le fetch standard ne
couvre pas, en particulier l'impression share au niveau CAMPAGNE et sa
decomposition (perte au budget vs perte au rang), la tendance mensuelle du
compte, la performance produit Shopping, les devices et les segmentations
horaires.

Usage :
  python3 ads_fetch_ytd.py --site monsite --start 2026-01-01 --end 2026-08-05 \
      --out clients/monsite/ads/fetch/ads-ytd.json

Chaque bloc est isole : l'echec d'une requete (metrique indisponible sur un
type de campagne, resource absente selon la version d'API) n'interrompt pas
le reste du fetch, il est journalise dans la cle "errors".
"""

import argparse
import json
import os
import sys
from datetime import date

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

ERRORS = []


def load_site_config(site_name):
    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next((s for s in sites if s["name"] == site_name), None)
    if not conf:
        raise ValueError("Site '%s' inconnu dans sites.json" % site_name)
    return conf


def euros(micros):
    return round((micros or 0) / 1_000_000, 2)


def pct(value):
    """Google renvoie les impression share en fraction (0 a 1)."""
    if value is None:
        return None
    return round(value * 100, 1)


def run(client, customer_id, query, label):
    """Execute une requete GAQL et renvoie la liste des lignes, [] si echec."""
    svc = client.get_service("GoogleAdsService")
    rows = []
    try:
        for batch in svc.search_stream(customer_id=customer_id, query=query):
            for row in batch.results:
                rows.append(row)
    except GoogleAdsException as e:
        msgs = [err.message for err in e.failure.errors]
        ERRORS.append({"bloc": label, "erreur": msgs})
        print("  [!] %s : %s" % (label, "; ".join(msgs)), file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        ERRORS.append({"bloc": label, "erreur": str(e)})
        print("  [!] %s : %s" % (label, e), file=sys.stderr)
    return rows


# ---------------------------------------------------------------- couverture

def fetch_campaign_coverage(client, cid, start, end):
    """Impression share par campagne sur toute la periode, avec decomposition."""
    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign.bidding_strategy_type,
            campaign_budget.amount_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.average_cpc,
            metrics.search_impression_share,
            metrics.search_budget_lost_impression_share,
            metrics.search_rank_lost_impression_share,
            metrics.search_absolute_top_impression_share,
            metrics.search_top_impression_share,
            metrics.search_exact_match_impression_share,
            metrics.content_impression_share,
            metrics.content_budget_lost_impression_share,
            metrics.content_rank_lost_impression_share
        FROM campaign
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "campaign_coverage"):
        c, m = row.campaign, row.metrics
        out.append({
            "id": str(c.id),
            "name": c.name,
            "status": c.status.name,
            "type": c.advertising_channel_type.name,
            "bidding": c.bidding_strategy_type.name,
            "budget_jour": euros(row.campaign_budget.amount_micros),
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
            "avg_cpc": euros(m.average_cpc),
            "search_is": pct(m.search_impression_share),
            "search_lost_budget": pct(m.search_budget_lost_impression_share),
            "search_lost_rank": pct(m.search_rank_lost_impression_share),
            "search_abs_top_is": pct(m.search_absolute_top_impression_share),
            "search_top_is": pct(m.search_top_impression_share),
            "search_exact_is": pct(m.search_exact_match_impression_share),
            "content_is": pct(m.content_impression_share),
            "content_lost_budget": pct(m.content_budget_lost_impression_share),
            "content_lost_rank": pct(m.content_rank_lost_impression_share),
        })
    return out


def fetch_monthly(client, cid, start, end):
    """Tendance mensuelle par campagne : saisonnalite et derive de la couverture."""
    query = """
        SELECT
            segments.month,
            campaign.id,
            campaign.name,
            campaign.advertising_channel_type,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.average_cpc,
            metrics.search_impression_share,
            metrics.search_budget_lost_impression_share,
            metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY segments.month ASC
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "monthly"):
        m = row.metrics
        out.append({
            "mois": row.segments.month,
            "campaign_id": str(row.campaign.id),
            "campaign": row.campaign.name,
            "type": row.campaign.advertising_channel_type.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
            "avg_cpc": euros(m.average_cpc),
            "search_is": pct(m.search_impression_share),
            "search_lost_budget": pct(m.search_budget_lost_impression_share),
            "search_lost_rank": pct(m.search_rank_lost_impression_share),
        })
    return out


def fetch_adgroup_coverage(client, cid, start, end):
    query = """
        SELECT
            campaign.name,
            ad_group.id,
            ad_group.name,
            ad_group.status,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.search_impression_share,
            metrics.search_rank_lost_impression_share
        FROM ad_group
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "adgroup_coverage"):
        m = row.metrics
        out.append({
            "campaign": row.campaign.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_group": row.ad_group.name,
            "status": row.ad_group.status.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
            "search_is": pct(m.search_impression_share),
            "search_lost_rank": pct(m.search_rank_lost_impression_share),
        })
    return out


def fetch_keywords_ytd(client, cid, start, end):
    query = """
        SELECT
            campaign.name,
            ad_group.name,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.status,
            ad_group_criterion.quality_info.quality_score,
            ad_group_criterion.quality_info.creative_quality_score,
            ad_group_criterion.quality_info.post_click_quality_score,
            ad_group_criterion.quality_info.search_predicted_ctr,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.average_cpc,
            metrics.search_impression_share,
            metrics.search_rank_lost_impression_share,
            metrics.search_top_impression_share
        FROM keyword_view
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
        LIMIT 400
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "keywords_ytd"):
        m = row.metrics
        crit = row.ad_group_criterion
        q = crit.quality_info
        out.append({
            "campaign": row.campaign.name,
            "ad_group": row.ad_group.name,
            "keyword": crit.keyword.text,
            "match_type": crit.keyword.match_type.name,
            "status": crit.status.name,
            "quality_score": q.quality_score or None,
            "qs_creative": q.creative_quality_score.name if q.creative_quality_score else None,
            "qs_landing": q.post_click_quality_score.name if q.post_click_quality_score else None,
            "qs_ctr": q.search_predicted_ctr.name if q.search_predicted_ctr else None,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
            "avg_cpc": euros(m.average_cpc),
            "search_is": pct(m.search_impression_share),
            "search_lost_rank": pct(m.search_rank_lost_impression_share),
            "search_top_is": pct(m.search_top_impression_share),
        })
    return out


def fetch_search_terms_ytd(client, cid, start, end):
    """Requetes reelles sur toute la periode, triees par cout (gaspillage)."""
    query = """
        SELECT
            search_term_view.search_term,
            search_term_view.status,
            campaign.name,
            campaign.advertising_channel_type,
            ad_group.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.average_cpc
        FROM search_term_view
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
        LIMIT 1500
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "search_terms_ytd"):
        m = row.metrics
        out.append({
            "term": row.search_term_view.search_term,
            "status": row.search_term_view.status.name,
            "campaign": row.campaign.name,
            "type": row.campaign.advertising_channel_type.name,
            "ad_group": row.ad_group.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
            "avg_cpc": euros(m.average_cpc),
        })
    return out


def fetch_products(client, cid, start, end):
    """Performance produit Shopping / PMax."""
    query = """
        SELECT
            segments.product_item_id,
            segments.product_title,
            segments.product_brand,
            segments.product_type_l1,
            campaign.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value
        FROM shopping_performance_view
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
        LIMIT 300
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "shopping_products"):
        m, s = row.metrics, row.segments
        out.append({
            "item_id": s.product_item_id,
            "title": s.product_title,
            "brand": s.product_brand,
            "type_l1": s.product_type_l1,
            "campaign": row.campaign.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
        })
    return out


def fetch_device(client, cid, start, end):
    query = """
        SELECT
            segments.device,
            campaign.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr
        FROM campaign
        WHERE segments.date BETWEEN '%s' AND '%s'
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "device"):
        m = row.metrics
        out.append({
            "device": row.segments.device.name,
            "campaign": row.campaign.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
        })
    return out


def fetch_hourly(client, cid, start, end):
    query = """
        SELECT
            segments.day_of_week,
            segments.hour,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '%s' AND '%s'
    """ % (start, end)
    agg = {}
    for row in run(client, cid, query, "hourly"):
        m, s = row.metrics, row.segments
        key = (s.day_of_week.name, s.hour)
        e = agg.setdefault(key, {"jour": key[0], "heure": key[1], "impressions": 0,
                                 "clicks": 0, "cost": 0.0, "conversions": 0.0,
                                 "conv_value": 0.0})
        e["impressions"] += m.impressions
        e["clicks"] += m.clicks
        e["cost"] += euros(m.cost_micros)
        e["conversions"] += m.conversions
        e["conv_value"] += m.conversions_value
    out = []
    for e in agg.values():
        e["cost"] = round(e["cost"], 2)
        e["conversions"] = round(e["conversions"], 1)
        e["conv_value"] = round(e["conv_value"], 2)
        out.append(e)
    return out


def fetch_geo_ytd(client, cid, start, end):
    query = """
        SELECT
            geographic_view.country_criterion_id,
            campaign.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value
        FROM geographic_view
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "geo_ytd"):
        m = row.metrics
        out.append({
            "country_criterion_id": str(row.geographic_view.country_criterion_id),
            "campaign": row.campaign.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
        })
    return out


def fetch_ads_ytd(client, cid, start, end):
    query = """
        SELECT
            campaign.name,
            ad_group.name,
            ad_group_ad.ad.id,
            ad_group_ad.ad.type,
            ad_group_ad.status,
            ad_group_ad.ad_strength,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.final_urls,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr
        FROM ad_group_ad
        WHERE segments.date BETWEEN '%s' AND '%s'
        ORDER BY metrics.impressions DESC
        LIMIT 100
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "ads_ytd"):
        m = row.metrics
        a = row.ad_group_ad
        out.append({
            "campaign": row.campaign.name,
            "ad_group": row.ad_group.name,
            "ad_id": str(a.ad.id),
            "type": a.ad.type_.name,
            "status": a.status.name,
            "ad_strength": a.ad_strength.name if a.ad_strength else None,
            "headlines": [h.text for h in a.ad.responsive_search_ad.headlines],
            "descriptions": [d.text for d in a.ad.responsive_search_ad.descriptions],
            "final_urls": list(a.ad.final_urls),
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": euros(m.cost_micros),
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "ctr": round(m.ctr * 100, 2),
        })
    return out


def fetch_conversion_actions(client, cid, start, end):
    query = """
        SELECT
            segments.conversion_action_name,
            segments.conversion_action_category,
            metrics.all_conversions,
            metrics.all_conversions_value,
            metrics.conversions,
            metrics.conversions_value
        FROM customer
        WHERE segments.date BETWEEN '%s' AND '%s'
    """ % (start, end)
    out = []
    for row in run(client, cid, query, "conversion_actions"):
        m, s = row.metrics, row.segments
        out.append({
            "action": s.conversion_action_name,
            "categorie": s.conversion_action_category.name,
            "conversions": round(m.conversions, 1),
            "conv_value": round(m.conversions_value, 2),
            "all_conversions": round(m.all_conversions, 1),
            "all_conv_value": round(m.all_conversions_value, 2),
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--out", required=True, help="Chemin du JSON de sortie")
    p.add_argument("--yaml", default=YAML_PATH)
    args = p.parse_args()

    conf = load_site_config(args.site)
    cid = str(conf["ads_customer_id"]).replace("-", "")
    client = GoogleAdsClient.load_from_storage(args.yaml)

    print("Fetch YTD Google Ads : %s | %s -> %s" % (args.site, args.start, args.end))

    data = {
        "site": args.site,
        "customer_id": cid,
        "periode": {"start": args.start, "end": args.end},
        "generated_at": date.today().isoformat(),
        "campaign_coverage": fetch_campaign_coverage(client, cid, args.start, args.end),
        "monthly": fetch_monthly(client, cid, args.start, args.end),
        "adgroup_coverage": fetch_adgroup_coverage(client, cid, args.start, args.end),
        "keywords": fetch_keywords_ytd(client, cid, args.start, args.end),
        "search_terms": fetch_search_terms_ytd(client, cid, args.start, args.end),
        "products": fetch_products(client, cid, args.start, args.end),
        "device": fetch_device(client, cid, args.start, args.end),
        "hourly": fetch_hourly(client, cid, args.start, args.end),
        "geo": fetch_geo_ytd(client, cid, args.start, args.end),
        "ads": fetch_ads_ytd(client, cid, args.start, args.end),
        "conversion_actions": fetch_conversion_actions(client, cid, args.start, args.end),
    }
    data["errors"] = ERRORS

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("Genere : %s" % args.out)
    for k in ("campaign_coverage", "monthly", "adgroup_coverage", "keywords",
              "search_terms", "products", "device", "hourly", "geo", "ads",
              "conversion_actions"):
        print("  %-20s : %d lignes" % (k, len(data[k])))
    if ERRORS:
        print("  %-20s : %d" % ("BLOCS EN ERREUR", len(ERRORS)))


if __name__ == "__main__":
    main()
