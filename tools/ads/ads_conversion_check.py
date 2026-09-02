#!/usr/bin/env python3
"""
Google Ads Conversion Check — Diagnostic complet des actions de conversion,
auto-tagging, Consent Mode, et attribution.

Usage:
  python3 ads_conversion_check.py --site monsite

Checks:
  1. Actions de conversion configurees (actives, type, statut)
  2. Auto-tagging actif
  3. Historique de conversions sur 30 jours (par jour)
  4. Conversion value rules
  5. Conversion windows
"""

import argparse
import json
import os
from datetime import datetime, timedelta, date

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


def load_site_config(site_name):
    with open(SITES_JSON) as f:
        sites = json.load(f)["sites"]
    conf = next((s for s in sites if s["name"] == site_name), None)
    if not conf:
        raise ValueError(f"Site '{site_name}' inconnu dans sites.json")
    return conf


def check_conversion_actions(client, customer_id):
    """Liste toutes les actions de conversion avec leur statut."""
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            conversion_action.id,
            conversion_action.name,
            conversion_action.status,
            conversion_action.type,
            conversion_action.category,
            conversion_action.counting_type,
            conversion_action.value_settings.default_value,
            conversion_action.view_through_lookback_window_days,
            conversion_action.click_through_lookback_window_days,
            conversion_action.tag_snippets,
            conversion_action.include_in_conversions_metric,
            conversion_action.primary_for_goal
        FROM conversion_action
        WHERE conversion_action.status != 'REMOVED'
        ORDER BY conversion_action.status
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    results = []
    for batch in stream:
        for row in batch.results:
            ca = row.conversion_action
            results.append({
                "id": str(ca.id),
                "name": ca.name,
                "status": ca.status.name,
                "type": ca.type_.name,
                "category": ca.category.name,
                "counting_type": ca.counting_type.name,
                "default_value": ca.value_settings.default_value,
                "click_window_days": ca.click_through_lookback_window_days,
                "view_through_days": ca.view_through_lookback_window_days,
                "include_in_conversions": ca.include_in_conversions_metric,
                "primary_for_goal": ca.primary_for_goal,
            })
    return results


def check_daily_conversions(client, customer_id, days=30):
    """Conversions par jour sur les X derniers jours pour identifier le point de bascule."""
    ga_service = client.get_service("GoogleAdsService")
    end = date.today()
    start = end - timedelta(days=days)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    query = f"""
        SELECT
            segments.date,
            segments.conversion_action_name,
            metrics.conversions,
            metrics.conversions_value,
            metrics.all_conversions,
            metrics.view_through_conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND campaign.status = 'ENABLED'
        ORDER BY segments.date ASC
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)

    by_date = {}
    for batch in stream:
        for row in batch.results:
            d = row.segments.date
            conv_name = row.segments.conversion_action_name
            if d not in by_date:
                by_date[d] = {}
            if conv_name not in by_date[d]:
                by_date[d][conv_name] = {"conversions": 0.0, "value": 0.0, "all_conversions": 0.0}
            by_date[d][conv_name]["conversions"] += row.metrics.conversions
            by_date[d][conv_name]["value"] += row.metrics.conversions_value
            by_date[d][conv_name]["all_conversions"] += row.metrics.all_conversions

    return by_date


def check_auto_tagging(client, customer_id):
    """Verifie si l'auto-tagging (gclid) est actif."""
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            customer.id,
            customer.auto_tagging_enabled,
            customer.descriptive_name,
            customer.currency_code
        FROM customer
        LIMIT 1
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            return {
                "auto_tagging_enabled": row.customer.auto_tagging_enabled,
                "name": row.customer.descriptive_name,
                "currency": row.customer.currency_code,
            }
    return {}


def main():
    parser = argparse.ArgumentParser(description="Google Ads Conversion Diagnostic")
    parser.add_argument("--site", required=True)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    conf = load_site_config(args.site)
    customer_id = conf.get("ads_customer_id")
    if not customer_id:
        print(f"ads_customer_id manquant pour '{args.site}'")
        return

    print(f"\nGoogle Ads Conversion Diagnostic -- {args.site}")
    print(f"Customer ID: {customer_id}")
    print("=" * 60)

    try:
        client = GoogleAdsClient.load_from_storage(path=YAML_PATH)
    except Exception as e:
        print(f"Erreur chargement config: {e}")
        return

    try:
        # 1. Auto-tagging
        print("\n[1] AUTO-TAGGING (gclid)")
        account = check_auto_tagging(client, customer_id)
        status = "ACTIF" if account.get("auto_tagging_enabled") else "INACTIF -- CRITIQUE !"
        print(f"    Compte: {account.get('name')} ({account.get('currency')})")
        print(f"    Auto-tagging: {status}")
        if not account.get("auto_tagging_enabled"):
            print("    --> Si auto-tagging OFF, les gclid ne sont pas appends aux URLs de destination")
            print("    --> TOUTES les conversions Google Ads seront a 0 ou mal attribuees")

        # 2. Conversion actions
        print("\n[2] ACTIONS DE CONVERSION")
        conv_actions = check_conversion_actions(client, customer_id)
        print(f"    {len(conv_actions)} action(s) trouvee(s):")
        print(f"    {'Nom':<40} {'Statut':<12} {'Type':<20} {'Primaire':>8} {'In Conv':>8} {'Fenetre':>8}")
        print(f"    {'-'*40} {'-'*12} {'-'*20} {'-'*8} {'-'*8} {'-'*8}")
        for ca in conv_actions:
            primaire = "OUI" if ca["primary_for_goal"] else "non"
            in_conv = "OUI" if ca["include_in_conversions"] else "non"
            fenetre = f"{ca['click_window_days']}j"
            status_flag = ""
            if ca["status"] != "ENABLED":
                status_flag = " <-- PAUSE/REMOVED !"
            print(f"    {ca['name'][:38]:<40} {ca['status']:<12} {ca['type'][:18]:<20} {primaire:>8} {in_conv:>8} {fenetre:>8}{status_flag}")

        # Check: is there a purchase/purchase action active?
        purchase_actions = [ca for ca in conv_actions if "purchase" in ca["name"].lower() or "achat" in ca["name"].lower() or "Purchase" in ca["name"]]
        if not purchase_actions:
            print("    --> ALERTE: Aucune action de conversion 'purchase' trouvee !")
        else:
            for pa in purchase_actions:
                if pa["status"] != "ENABLED":
                    print(f"    --> ALERTE: Action '{pa['name']}' est {pa['status']} !")
                if not pa["include_in_conversions"]:
                    print(f"    --> ALERTE: Action '{pa['name']}' exclue des metriques de conversion !")

        # 3. Conversions par jour
        print(f"\n[3] CONVERSIONS PAR JOUR (derniers {args.days} jours)")
        daily = check_daily_conversions(client, customer_id, args.days)

        # Aggregate by date
        daily_totals = {}
        for d, conv_by_name in daily.items():
            total = sum(v["conversions"] for v in conv_by_name.values())
            total_val = sum(v["value"] for v in conv_by_name.values())
            all_conv = sum(v["all_conversions"] for v in conv_by_name.values())
            daily_totals[d] = {"conversions": total, "value": total_val, "all_conversions": all_conv}

        print(f"    {'Date':<12} {'Conversions':>12} {'Value EUR':>10} {'All Conv':>10}")
        print(f"    {'-'*12} {'-'*12} {'-'*10} {'-'*10}")
        for d in sorted(daily_totals.keys()):
            row = daily_totals[d]
            flag = ""
            if row["conversions"] == 0 and row["all_conversions"] > 0:
                flag = " <-- tracked mais non primaire"
            print(f"    {d:<12} {row['conversions']:>12.1f} {row['value']:>10.2f} {row['all_conversions']:>10.1f}{flag}")

        # Point de bascule
        dates_sorted = sorted(daily_totals.keys())
        if len(dates_sorted) >= 7:
            recent_7 = [daily_totals[d]["conversions"] for d in dates_sorted[-7:]]
            older_7 = [daily_totals[d]["conversions"] for d in dates_sorted[-14:-7]]
            avg_recent = sum(recent_7) / 7
            avg_older = sum(older_7) / 7 if older_7 else 0
            print(f"\n    Moy 7 derniers jours : {avg_recent:.1f} conv/j")
            print(f"    Moy 7-14 jours avant : {avg_older:.1f} conv/j")
            if avg_older > 0:
                drop_pct = (avg_older - avg_recent) / avg_older * 100
                if drop_pct > 50:
                    print(f"    --> CHUTE DE {drop_pct:.0f}% -- regression significative !")
                elif drop_pct > 20:
                    print(f"    --> Baisse de {drop_pct:.0f}% -- a surveiller")
                else:
                    print(f"    --> Variation normale ({drop_pct:.0f}%)")

        # 4. Conversion details par action sur les 7 derniers jours
        print(f"\n[4] DETAIL PAR ACTION (7 derniers jours)")
        recent_by_action = {}
        recent_dates = sorted(daily.keys())[-7:]
        for d in recent_dates:
            for name, vals in daily[d].items():
                if name not in recent_by_action:
                    recent_by_action[name] = {"conversions": 0.0, "value": 0.0}
                recent_by_action[name]["conversions"] += vals["conversions"]
                recent_by_action[name]["value"] += vals["value"]

        for name, vals in sorted(recent_by_action.items(), key=lambda x: -x[1]["conversions"]):
            print(f"    {name[:50]:<50} {vals['conversions']:>8.1f} conv / {vals['value']:>8.2f} EUR")

        print("\nDIAGNOSTIC TERMINE")

    except GoogleAdsException as ex:
        print(f"Erreur API Google Ads:")
        for error in ex.failure.errors:
            print(f"  {error.message}")


if __name__ == "__main__":
    main()
