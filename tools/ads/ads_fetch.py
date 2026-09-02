#!/usr/bin/env python3
"""
Google Ads Fetch — Pull campaign, keyword, and landing page data.

Usage:
  python3 ads_fetch.py --site monsite [--days 30]

Requires prior authentication:
  python3 ads_auth.py --credentials ~/gsc-credentials.json --developer-token XXXXX

Output:
  data/{site}/{YYYY-MM}/ads.json

Structure:
{
  "site": "monsite",
  "month": "2026-04",
  "generated_at": "...",
  "customer_id": "...",
  "summary": {
    "total_campaigns": N,
    "active_campaigns": N,
    "total_spend": 0.00,
    "total_clicks": N,
    "total_conversions": N,
    "avg_cpc": 0.00,
    "avg_ctr": 0.00
  },
  "campaigns": [...],
  "keywords": [...],
  "landing_pages": [...],
  "search_terms": [...],
  "geo": [...],
  "ads": [...]
}
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, date

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Config partagee avec tools/seo-audit/ (source unique, pas de duplication
# de secrets : google-ads.yaml, ads-token.json et sites.json restent la-bas).
# Resolution relative au script (identique a l'ancien chemin absolu sur Hal),
# surchargeable par REGIE_CONFIG_DIR / REGIE_DATA_DIR pour une installation exportee.
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
YAML_PATH = os.path.join(CONFIG_DIR, "google-ads.yaml")
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")
DATA_DIR = os.environ.get(
    "REGIE_DATA_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "data"))
)


def load_site_config(site_name: str) -> dict:
    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next((s for s in sites if s["name"] == site_name), None)
    if not conf:
        raise ValueError(f"Site '{site_name}' inconnu dans sites.json")
    return conf


def micros_to_euros(micros) -> float:
    """Convertit les micro-unites Google Ads en euros."""
    return round(int(micros) / 1_000_000, 2)


def fetch_campaigns(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Campagnes actives et leurs metriques sur la periode."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign_budget.amount_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.average_cpc,
            metrics.ctr
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status IN ('ENABLED', 'PAUSED')
        ORDER BY metrics.cost_micros DESC
        LIMIT 50
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            c = row.campaign
            m = row.metrics
            results.append({
                "id": str(c.id),
                "name": c.name,
                "status": c.status.name,
                "type": c.advertising_channel_type.name,
                "budget": micros_to_euros(row.campaign_budget.amount_micros),
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "conversions_value": round(m.conversions_value, 2),
                "avg_cpc": micros_to_euros(m.average_cpc),
                "ctr": round(m.ctr * 100, 2),
            })
    return results


def fetch_keywords(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Mots-cles avec metriques de performance."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.status,
            ad_group_criterion.quality_info.quality_score,
            campaign.name,
            ad_group.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.average_cpc,
            metrics.historical_quality_score,
            metrics.bounce_rate,
            metrics.search_impression_share,
            metrics.search_top_impression_share
        FROM keyword_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status = 'ENABLED'
          AND ad_group_criterion.status != 'REMOVED'
        ORDER BY metrics.clicks DESC
        LIMIT 500
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            kw = row.ad_group_criterion.keyword
            m = row.metrics
            results.append({
                "keyword": kw.text,
                "match_type": kw.match_type.name,
                "status": row.ad_group_criterion.status.name,
                "quality_score": m.historical_quality_score if m.historical_quality_score else None,
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "avg_cpc": micros_to_euros(m.average_cpc),
                "bounce_rate": round(m.bounce_rate * 100, 1),
                "impression_share": round(m.search_impression_share * 100, 1) if m.search_impression_share else None,
                "top_impression_share": round(m.search_top_impression_share * 100, 1) if m.search_top_impression_share else None,
            })
    return results


def fetch_landing_pages(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Pages de destination avec metriques (pour croiser avec GSC/GA4)."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            landing_page_view.unexpanded_final_url,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.speed_score,
            metrics.mobile_friendly_clicks_percentage,
            metrics.ctr
        FROM landing_page_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY metrics.clicks DESC
        LIMIT 200
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            lp = row.landing_page_view
            m = row.metrics
            results.append({
                "url": lp.unexpanded_final_url,
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "conversions_value": round(m.conversions_value, 2),
                "ctr": round(m.ctr * 100, 2),
                "speed_score": m.speed_score if m.speed_score else None,
                "mobile_friendly_pct": round(m.mobile_friendly_clicks_percentage * 100, 1) if m.mobile_friendly_clicks_percentage else None,
            })
    return results


def fetch_search_terms(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Requetes reelles tapees par les utilisateurs."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            search_term_view.search_term,
            search_term_view.status,
            campaign.name,
            campaign.status,
            ad_group.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc
        FROM search_term_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status = 'ENABLED'
        ORDER BY metrics.clicks DESC
        LIMIT 500
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            st = row.search_term_view
            m = row.metrics
            results.append({
                "term": st.search_term,
                "status": st.status.name,
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "ctr": round(m.ctr * 100, 2),
                "avg_cpc": micros_to_euros(m.average_cpc),
            })
    return results


def fetch_geo(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Performance par zone geographique."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            geographic_view.country_criterion_id,
            geographic_view.location_type,
            campaign.name,
            campaign.status,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc,
            segments.geo_target_city,
            segments.geo_target_region
        FROM geographic_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status = 'ENABLED'
        ORDER BY metrics.clicks DESC
        LIMIT 100
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            m = row.metrics
            results.append({
                "campaign": row.campaign.name,
                "location_type": row.geographic_view.location_type.name,
                "city": row.segments.geo_target_city,
                "region": row.segments.geo_target_region,
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "ctr": round(m.ctr * 100, 2),
                "avg_cpc": micros_to_euros(m.average_cpc),
            })
    return results


def fetch_ads(client, customer_id: str, start_date: str, end_date: str) -> list:
    """Performance des annonces individuelles."""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            ad_group_ad.ad.id,
            ad_group_ad.ad.type,
            ad_group_ad.ad.final_urls,
            ad_group_ad.status,
            ad_group_ad.policy_summary.approval_status,
            ad_group.name,
            ad_group.status,
            campaign.name,
            campaign.status,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND ad_group_ad.status = 'ENABLED'
          AND campaign.status = 'ENABLED'
        ORDER BY metrics.clicks DESC
        LIMIT 100
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            ad = row.ad_group_ad.ad
            m = row.metrics
            results.append({
                "id": str(ad.id),
                "type": ad.type_.name,
                "final_urls": list(ad.final_urls),
                "status": row.ad_group_ad.status.name,
                "approval": row.ad_group_ad.policy_summary.approval_status.name,
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "impressions": m.impressions,
                "clicks": m.clicks,
                "cost": micros_to_euros(m.cost_micros),
                "conversions": round(m.conversions, 1),
                "ctr": round(m.ctr * 100, 2),
                "avg_cpc": micros_to_euros(m.average_cpc),
            })
    return results


def fetch_schedule(client, customer_id: str, start_date: str, end_date: str) -> dict:
    """Performance par heure du jour et jour de la semaine (toutes campagnes actives)."""
    ga_service = client.get_service("GoogleAdsService")

    query = f"""
        SELECT
            segments.hour,
            segments.day_of_week,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.average_cpc
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status = 'ENABLED'
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)

    by_hour = {}
    by_day = {}
    for batch in stream:
        for row in batch.results:
            h = row.segments.hour
            dow = row.segments.day_of_week.name
            m = row.metrics
            cost = micros_to_euros(m.cost_micros)
            convs = round(m.conversions, 2)

            if h not in by_hour:
                by_hour[h] = {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0}
            by_hour[h]["impressions"] += m.impressions
            by_hour[h]["clicks"] += m.clicks
            by_hour[h]["cost"] = round(by_hour[h]["cost"] + cost, 2)
            by_hour[h]["conversions"] = round(by_hour[h]["conversions"] + convs, 2)

            if dow not in by_day:
                by_day[dow] = {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0}
            by_day[dow]["impressions"] += m.impressions
            by_day[dow]["clicks"] += m.clicks
            by_day[dow]["cost"] = round(by_day[dow]["cost"] + cost, 2)
            by_day[dow]["conversions"] = round(by_day[dow]["conversions"] + convs, 2)

    day_order = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    return {
        "by_hour": [{"hour": h, **by_hour.get(h, {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0})} for h in range(24)],
        "by_day": [{"day": d, **by_day.get(d, {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0})} for d in day_order],
    }


def build_summary(campaigns: list, keywords: list) -> dict:
    active = [c for c in campaigns if c["status"] == "ENABLED"]
    total_cost = sum(c["cost"] for c in campaigns)
    total_clicks = sum(c["clicks"] for c in campaigns)
    total_impressions = sum(c["impressions"] for c in campaigns)
    total_conversions = sum(c["conversions"] for c in campaigns)

    return {
        "total_campaigns": len(campaigns),
        "active_campaigns": len(active),
        "total_spend": total_cost,
        "total_clicks": total_clicks,
        "total_impressions": total_impressions,
        "total_conversions": total_conversions,
        "avg_cpc": round(total_cost / total_clicks, 2) if total_clicks else 0,
        "avg_ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions else 0,
        "roas": round(
            sum(c["conversions_value"] for c in campaigns) / total_cost, 2
        ) if total_cost else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Google Ads data fetcher")
    parser.add_argument("--site", required=True, help="Nom du site (ex: monsite)")
    parser.add_argument("--days", type=int, default=30, help="Periode en jours (defaut: 30)")
    parser.add_argument("--month", help="Mois cible YYYY-MM (defaut: mois courant)")
    parser.add_argument("--yaml", default=YAML_PATH,
                        help=f"Chemin vers google-ads.yaml (defaut: {YAML_PATH})")
    args = parser.parse_args()

    conf = load_site_config(args.site)
    customer_id = conf.get("ads_customer_id")
    if not customer_id:
        print(f"ads_customer_id manquant dans sites.json pour '{args.site}'")
        print("Ajouter: \"ads_customer_id\": \"6788396743\"")
        return

    if not os.path.exists(args.yaml):
        print(f"google-ads.yaml introuvable : {args.yaml}")
        print("Lancer d'abord : python3 ads_auth.py --credentials ... --developer-token ...")
        return

    month = args.month or datetime.now().strftime("%Y-%m")
    end = date.today()
    start = end - timedelta(days=args.days)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    print(f"Fetch Google Ads : {args.site} | {start_date} -> {end_date}")

    try:
        client = GoogleAdsClient.load_from_storage(path=args.yaml)
    except Exception as e:
        print(f"Erreur chargement config Google Ads : {e}")
        return

    try:
        campaigns = fetch_campaigns(client, customer_id, start_date, end_date)
        keywords = fetch_keywords(client, customer_id, start_date, end_date)
        landing_pages = fetch_landing_pages(client, customer_id, start_date, end_date)
        search_terms = fetch_search_terms(client, customer_id, start_date, end_date)
        geo = fetch_geo(client, customer_id, start_date, end_date)
        ads = fetch_ads(client, customer_id, start_date, end_date)
        schedule = fetch_schedule(client, customer_id, start_date, end_date)
    except GoogleAdsException as ex:
        print(f"Erreur API Google Ads :")
        for error in ex.failure.errors:
            print(f"  {error.message} (code: {error.error_code})")
        return

    summary = build_summary(campaigns, keywords)
    output = {
        "site": args.site,
        "month": month,
        "generated_at": datetime.now().isoformat(),
        "customer_id": customer_id,
        "period": {"start": start_date, "end": end_date, "days": args.days},
        "summary": summary,
        "campaigns": campaigns,
        "keywords": keywords,
        "landing_pages": landing_pages,
        "search_terms": search_terms,
        "geo": geo,
        "ads": ads,
        "schedule": schedule,
    }

    out_dir = os.path.join(DATA_DIR, args.site, month)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ads.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Genere : {out_path}")
    print(f"  Campagnes       : {summary['total_campaigns']} ({summary['active_campaigns']} actives)")
    print(f"  Depense totale  : {summary['total_spend']} EUR")
    print(f"  Clics           : {summary['total_clicks']}")
    print(f"  Conversions     : {summary['total_conversions']}")
    print(f"  CPC moyen       : {summary['avg_cpc']} EUR")
    print(f"  ROAS            : {summary['roas']}")
    print(f"  Search terms    : {len(search_terms)}")
    print(f"  Zones geo       : {len(geo)}")
    print(f"  Annonces        : {len(ads)}")
    print(f"  Schedule        : {len(schedule['by_hour'])}h x {len(schedule['by_day'])}j")


if __name__ == "__main__":
    main()
