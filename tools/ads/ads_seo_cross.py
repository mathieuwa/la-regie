#!/usr/bin/env python3
"""
Ads x SEO Cross-Analysis — Croise Google Ads avec GSC et GA4.

Usage:
  python3 ads_seo_cross.py --site monsite [--month 2026-04]

Requires:
  data/{site}/{YYYY-MM}/ads.json   (from ads_fetch.py)
  data/{site}/{YYYY-MM}/gsc.csv    (from gsc_fetch.py)
  data/{site}/{YYYY-MM}/ga4.csv    (from ga4_fetch.py)

Output:
  data/{site}/{YYYY-MM}/ads_seo_cross.json

Analyses produites :
  1. Doublons paid/organique : mots-cles Ads ou position GSC <= 5
  2. Opportunites SEO depuis search terms Ads : requetes payantes sans presence organique
  3. Pages a fort trafic organique sans support Ads : candidates a renforcer
  4. Qualite des landing pages : croisement cout Ads + bounce rate GA4
  5. ROAS reel par URL : revenus GA4 / cout Ads par page
"""

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR /
# REGIE_DATA_DIR (meme motif que ads_fetch.py, pour une installation exportee).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get(
    "REGIE_DATA_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "data"))
)
# Config partagee avec tools/seo-audit/ (source unique, pas de duplication
# de secrets : sites.json reste la-bas).
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")


def load_json(path: str) -> dict | list | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize_url(url: str, site_domain: str = "") -> str:
    """Normalise une URL pour la comparaison : supprime trailing slash et query string.
    Gere les URLs relatives GA4 (ex: '/produit/foo') en les rendant absolues."""
    if not url:
        return ""
    if url.startswith("/") and site_domain:
        url = f"https://{site_domain}{url}"
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def safe_float(v) -> float:
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return 0.0


def analyze_paid_organic_overlap(ads_keywords: list, gsc_query_rows: list) -> list:
    """
    Doublons paid/organique : mots-cles Ads presents en position GSC <= 10.
    Gaspillage potentiel : on paie pour une position deja gagnee en organique.
    """
    # Index GSC queries par terme
    gsc_by_query = {}
    for row in gsc_query_rows:
        query = row.get("query", "").lower().strip()
        if query:
            gsc_by_query[query] = {
                "position": safe_float(row.get("position", 99)),
                "clicks_organic": safe_float(row.get("clicks", 0)),
                "impressions_organic": safe_float(row.get("impressions", 0)),
                "ctr_organic": safe_float(row.get("ctr", 0)),
            }

    results = []
    for kw in ads_keywords:
        term = kw.get("keyword", "").lower().strip()
        if not term:
            continue
        gsc = gsc_by_query.get(term)
        if gsc and gsc["position"] <= 10:
            monthly_waste = kw.get("cost", 0)
            results.append({
                "keyword": kw["keyword"],
                "match_type": kw.get("match_type", ""),
                "campaign": kw.get("campaign", ""),
                "ads_clicks": kw.get("clicks", 0),
                "ads_cost": kw.get("cost", 0),
                "ads_conversions": kw.get("conversions", 0),
                "gsc_position": round(gsc["position"], 1),
                "gsc_clicks": gsc["clicks_organic"],
                "gsc_ctr": gsc["ctr_organic"],
                "overlap_type": "fort" if gsc["position"] <= 3 else "moyen",
                "monthly_waste_eur": round(monthly_waste, 2),
            })

    return sorted(results, key=lambda x: x["ads_cost"], reverse=True)


def analyze_search_terms_seo_gap(search_terms: list, gsc_query_rows: list) -> list:
    """
    Search terms Ads avec clics mais absence en GSC.
    = Requetes a cibler en SEO pour reduire la dependance paid.
    """
    gsc_queries = {r.get("query", "").lower().strip() for r in gsc_query_rows}

    results = []
    for st in search_terms:
        term = st.get("term", "").lower().strip()
        if not term or term in gsc_queries:
            continue
        if st.get("clicks", 0) >= 5:
            results.append({
                "term": st["term"],
                "campaign": st.get("campaign", ""),
                "clicks_paid": st.get("clicks", 0),
                "cost": st.get("cost", 0),
                "conversions": st.get("conversions", 0),
                "ctr": st.get("ctr", 0),
                "seo_presence": "absente",
                "action": "Creer contenu SEO cible sur ce terme",
            })

    return sorted(results, key=lambda x: x["clicks_paid"], reverse=True)


def analyze_organic_pages_no_ads(gsc_rows: list, landing_pages: list) -> list:
    """
    Pages avec fort trafic organique mais sans support Ads.
    = Opportunites pour amplifier avec du paid.
    """
    ads_urls = {normalize_url(lp.get("url", "")) for lp in landing_pages}

    results = []
    seen = set()
    for row in gsc_rows:
        page = row.get("page", "").strip()
        if not page or page in seen:
            continue
        seen.add(page)
        norm = normalize_url(page)
        clicks = safe_float(row.get("clicks", 0))
        position = safe_float(row.get("position", 99))

        if clicks >= 20 and norm not in ads_urls:
            results.append({
                "url": page,
                "gsc_clicks": int(clicks),
                "gsc_position": round(position, 1),
                "gsc_ctr": safe_float(row.get("ctr", 0)),
                "action": "Candidat pour campagne Ads ou RLSA",
            })

    return sorted(results, key=lambda x: x["gsc_clicks"], reverse=True)[:20]


def analyze_landing_page_quality(landing_pages: list, ga4_rows: list, site_domain: str = "") -> list:
    """
    Croise le cout Ads par page avec le taux de rebond GA4.
    Pages couteuses + rebond eleve = probleme de relevance ou d'UX.
    """
    # Index GA4 par page (normalise)
    ga4_by_page = {}
    for row in ga4_rows:
        page = row.get("page", "").strip()
        if page:
            norm = normalize_url(page, site_domain)
            ga4_by_page[norm] = {
                "sessions": safe_float(row.get("sessions", 0)),
                # bounce_rate est deja en % dans ga4.csv (ex: 28.9 = 28.9%)
                "bounce_rate_pct": safe_float(row.get("bounce_rate", 0)),
                "avg_duration": safe_float(row.get("avg_session_duration_s", 0)),
                "revenue": safe_float(row.get("revenue", 0)),
            }

    results = []
    for lp in landing_pages:
        url = lp.get("url", "")
        norm = normalize_url(url)
        cost = lp.get("cost", 0)
        if cost < 5:
            continue
        ga4 = ga4_by_page.get(norm, {})
        bounce_pct = ga4.get("bounce_rate_pct", None)

        results.append({
            "url": url,
            "ads_clicks": lp.get("clicks", 0),
            "ads_cost": cost,
            "ads_conversions": lp.get("conversions", 0),
            "ads_ctr": lp.get("ctr", 0),
            "speed_score": lp.get("speed_score"),
            "mobile_friendly_pct": lp.get("mobile_friendly_pct"),
            "ga4_sessions": ga4.get("sessions", 0),
            "ga4_bounce_rate": bounce_pct,
            "ga4_revenue": ga4.get("revenue", 0),
            "roas_real": round(ga4.get("revenue", 0) / cost, 2) if cost else None,
            "alert": "rebond_eleve" if bounce_pct and bounce_pct > 70 and cost > 20 else None,
        })

    return sorted(results, key=lambda x: x["ads_cost"], reverse=True)


def build_cross_summary(overlaps, gaps, organic_opps, lp_quality) -> dict:
    waste = sum(o["monthly_waste_eur"] for o in overlaps if o["overlap_type"] == "fort")
    high_bounce_cost = sum(
        lp["ads_cost"] for lp in lp_quality if lp.get("alert") == "rebond_eleve"
    )
    return {
        "paid_organic_overlaps": len(overlaps),
        "strong_overlaps": len([o for o in overlaps if o["overlap_type"] == "fort"]),
        "estimated_waste_eur": round(waste, 2),
        "search_terms_seo_gaps": len(gaps),
        "organic_pages_no_ads": len(organic_opps),
        "landing_pages_high_bounce_cost": round(high_bounce_cost, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Ads x SEO cross-analysis")
    parser.add_argument("--site", required=True, help="Nom du site (ex: monsite)")
    parser.add_argument("--month", help="Mois YYYY-MM (defaut: mois courant)")
    args = parser.parse_args()

    month = args.month or datetime.now().strftime("%Y-%m")
    data_dir = os.path.join(DATA_DIR, args.site, month)

    # Charger la config site pour le domaine
    site_domain = ""
    if os.path.exists(SITES_JSON):
        with open(SITES_JSON) as f:
            sites_conf = json.load(f)["sites"]
        site_conf = next((s for s in sites_conf if s["name"] == args.site), None)
        if site_conf:
            site_domain = site_conf["url"].replace("https://", "").replace("http://", "").rstrip("/")

    # Charger les sources
    ads = load_json(os.path.join(data_dir, "ads.json"))
    gsc_rows = load_csv(os.path.join(data_dir, "gsc.csv"))
    gsc_query_rows = load_csv(os.path.join(data_dir, "gsc_queries.csv"))
    ga4_rows = load_csv(os.path.join(data_dir, "ga4.csv"))

    if not ads:
        print(f"ads.json introuvable dans {data_dir}")
        print("Lancer d'abord : python3 ads_fetch.py --site {site}")
        return
    if not gsc_query_rows:
        print(f"gsc_queries.csv introuvable — relancer : python3 gsc_fetch.py --name {args.site}")
    if not ga4_rows:
        print(f"ga4.csv introuvable dans {data_dir} — croisement GA4 desactive")

    print(f"Cross-analysis Ads x SEO : {args.site} | {month}")
    print(f"  Ads : {len(ads.get('keywords', []))} mots-cles, "
          f"{len(ads.get('search_terms', []))} search terms")
    print(f"  GSC queries : {len(gsc_query_rows)} requetes")
    print(f"  GSC pages   : {len(gsc_rows)} pages")
    print(f"  GA4 pages   : {len(ga4_rows)} pages")

    # Analyses
    overlaps = analyze_paid_organic_overlap(
        ads.get("keywords", []), gsc_query_rows
    )
    gaps = analyze_search_terms_seo_gap(
        ads.get("search_terms", []), gsc_query_rows
    )
    organic_opps = analyze_organic_pages_no_ads(
        gsc_rows, ads.get("landing_pages", [])
    )
    lp_quality = analyze_landing_page_quality(
        ads.get("landing_pages", []), ga4_rows, site_domain
    )

    summary = build_cross_summary(overlaps, gaps, organic_opps, lp_quality)

    output = {
        "site": args.site,
        "month": month,
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "paid_organic_overlaps": overlaps,
        "search_terms_seo_gaps": gaps,
        "organic_pages_no_ads": organic_opps,
        "landing_page_quality": lp_quality,
    }

    out_path = os.path.join(data_dir, "ads_seo_cross.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nGenere : {out_path}")
    print(f"  Doublons paid/organique   : {summary['paid_organic_overlaps']} "
          f"({summary['strong_overlaps']} forts, ~{summary['estimated_waste_eur']} EUR/mois)")
    print(f"  Search terms sans SEO     : {summary['search_terms_seo_gaps']}")
    print(f"  Pages organiques sans Ads : {summary['organic_pages_no_ads']}")
    print(f"  Cout sur pages rebond eleve : {summary['landing_pages_high_bounce_cost']} EUR")


if __name__ == "__main__":
    main()
