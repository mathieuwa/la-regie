#!/usr/bin/env python3
"""
Google Ads Analyzer — Analyse complete des campagnes.

Usage:
  python3 ads_analyze.py --site monsite [--month 2026-04]

Inputs:
  data/{site}/{month}/ads.json         (requis)
  data/{site}/{month}/gsc_queries.csv  (optionnel — croisement SEO/SEA)

Outputs:
  data/{site}/{month}/ads_analysis.json
  reports/{site}/ads-YYYY-MM-DD.html

Modules d'analyse :
  1. Quality Score — keywords actifs a QS faible
  2. Search Terms — candidats negatifs + nouveaux keywords
  3. Performance keywords — CPA, impression share, efficacite
  4. Campagnes — ROAS, efficacite budget
  5. Landing pages — vitesse, CTR
  6. Schedule — plages horaires et jours creux/peak
  7. Overlap SEO/SEA — doublons et opportunites
"""

import argparse
import csv
import json
import os
from datetime import datetime, date

# Config partagee avec tools/seo-audit/ (source unique, pas de duplication
# de secrets : sites.json reste la-bas).
# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR /
# REGIE_DATA_DIR (meme motif que ads_fetch.py, pour une installation exportee).
# REPORTS_DIR reste relatif au depot (pas de variable d'env dediee, hors
# perimetre REGIE_CONFIG_DIR/REGIE_DATA_DIR defini par l'overlay).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
SITES_JSON = os.path.join(CONFIG_DIR, "sites.json")
DATA_DIR = os.environ.get(
    "REGIE_DATA_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "data"))
)
REPORTS_DIR = os.path.abspath(os.path.join(_ADS_DIR, "..", "..", "reports"))

# Seuils d'analyse (ajustables)
QS_CRITICAL = 3       # QS <= ce seuil + ENABLED = alerte critique
QS_WARNING = 5        # QS <= ce seuil + ENABLED = avertissement
NEGATIVE_MIN_COST = 5.0   # Euros depenses sans conv = candidat negatif
NEGATIVE_MIN_CLICKS = 5   # Clics minimum pour etre candidat negatif
NEW_KW_MIN_CONV = 1.0     # Conversions minimum pour etre candidat nouveau keyword
CPA_MAX_RATIO = 2.5       # CPA > N * CPA_moyen = alerte
ROAS_MIN = 3.0            # ROAS < ce seuil = alerte campagne


# ─────────────────────────────────────────────
# Chargement des donnees
# ─────────────────────────────────────────────

def load_ads(site: str, month: str) -> dict:
    path = os.path.join(DATA_DIR, site, month, "ads.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"ads.json introuvable : {path}\nLancer d'abord : python3 ads_fetch.py --site {site}")
    with open(path) as f:
        return json.load(f)


def load_site_url(site: str) -> str:
    """Retourne l'URL du site (champ 'url' de l'entree correspondante dans
    sites.json), utilisee pour raccourcir l'affichage des landing pages dans
    le rapport HTML. Repli : chaine vide si sites.json, l'entree ou le champ
    est absent (pas de raccourcissement, l'URL complete reste affichee)."""
    try:
        with open(SITES_JSON, encoding="utf-8") as f:
            sites = json.load(f).get("sites", [])
        for entry in sites:
            if entry.get("name") == site:
                return entry.get("url", "") or ""
    except (FileNotFoundError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return ""


def load_gsc_queries(site: str, month: str) -> list:
    path = os.path.join(DATA_DIR, site, month, "gsc_queries.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "query": row.get("query", "").lower().strip(),
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "position": float(row.get("position", 0)),
            })
    return rows


# ─────────────────────────────────────────────
# Module 1 : Quality Score
# ─────────────────────────────────────────────

def analyze_quality_scores(keywords: list) -> dict:
    """Detecte les keywords actifs avec QS insuffisant."""
    critical = []
    warnings = []
    healthy = []

    for kw in keywords:
        qs = kw.get("quality_score")
        status = kw.get("status", "")
        if qs is None:
            continue

        entry = {
            "keyword": kw["keyword"],
            "match_type": kw["match_type"],
            "campaign": kw["campaign"],
            "ad_group": kw["ad_group"],
            "status": status,
            "qs": qs,
            "cost": kw["cost"],
            "conversions": kw["conversions"],
            "impression_share": kw.get("impression_share"),
        }
        if status == "ENABLED" and qs <= QS_CRITICAL:
            entry["action"] = "PAUSE_RECOMMANDE" if kw["cost"] == 0 else "PAUSE_URGENT"
            entry["reason"] = f"QS {qs}/10 actif — risque de depense inefficace ou blocage d'affichage"
            critical.append(entry)
        elif status == "ENABLED" and qs <= QS_WARNING:
            entry["action"] = "AMELIORATION_LANDING_PAGE_OU_ANNONCE"
            entry["reason"] = f"QS {qs}/10 — performance sous-optimale, CPC surevalue"
            warnings.append(entry)
        elif status == "ENABLED" and qs >= 7:
            healthy.append(entry)

    critical.sort(key=lambda x: x["cost"], reverse=True)
    warnings.sort(key=lambda x: x["cost"], reverse=True)

    return {
        "critical": critical,
        "warnings": warnings,
        "healthy_count": len(healthy),
        "summary": f"{len(critical)} critique(s), {len(warnings)} avertissement(s), {len(healthy)} sain(s)",
    }


# ─────────────────────────────────────────────
# Module 2 : Search Terms
# ─────────────────────────────────────────────

def analyze_search_terms(search_terms: list, keywords: list) -> dict:
    """
    - Candidats mots-cles negatifs : depensent sans convertir
    - Candidats nouveaux keywords : convertissent mais ne sont pas encore ciblés
    - Requetes a fort potentiel : CTR eleve, faibles conversions
    """
    existing_kw_texts = {kw["keyword"].lower() for kw in keywords}

    negatives_candidates = []
    new_kw_candidates = []
    high_potential = []

    for st in search_terms:
        term = st["term"].lower()
        cost = st["cost"]
        clicks = st["clicks"]
        convs = st["conversions"]
        ctr = st["ctr"]

        # Candidats negatifs : cost eleve, 0 conv, non deja ajoute comme keyword
        if convs == 0 and cost >= NEGATIVE_MIN_COST and clicks >= NEGATIVE_MIN_CLICKS and st["status"] != "ADDED":
            negatives_candidates.append({
                "term": st["term"],
                "campaign": st["campaign"],
                "ad_group": st["ad_group"],
                "cost": cost,
                "clicks": clicks,
                "ctr": ctr,
                "status": st["status"],
                "priority": "HIGH" if cost >= 15 else "MEDIUM",
            })

        # Nouveaux keywords : convertissent et ne sont pas deja dans la liste
        if convs >= NEW_KW_MIN_CONV and term not in existing_kw_texts and st["status"] != "ADDED":
            cpa = round(cost / convs, 2) if convs > 0 else None
            new_kw_candidates.append({
                "term": st["term"],
                "campaign": st["campaign"],
                "ad_group": st["ad_group"],
                "clicks": clicks,
                "cost": cost,
                "conversions": convs,
                "cpa": cpa,
                "ctr": ctr,
                "avg_cpc": st["avg_cpc"],
                "suggested_match": "PHRASE",
                "priority": "HIGH" if convs >= 3 else "MEDIUM",
            })

        # Fort potentiel : CTR > 5%, plus de 10 clics, 0 ou peu de conv
        if ctr >= 5.0 and clicks >= 10 and convs == 0 and st["status"] != "ADDED":
            high_potential.append({
                "term": st["term"],
                "campaign": st["campaign"],
                "clicks": clicks,
                "cost": cost,
                "ctr": ctr,
                "note": "CTR eleve mais 0 conversion — verifier landing page",
            })

    negatives_candidates.sort(key=lambda x: x["cost"], reverse=True)
    new_kw_candidates.sort(key=lambda x: x["conversions"], reverse=True)

    return {
        "negatives_candidates": negatives_candidates,
        "new_kw_candidates": new_kw_candidates,
        "high_potential": high_potential,
        "summary": (
            f"{len(negatives_candidates)} candidats negatifs, "
            f"{len(new_kw_candidates)} nouveaux keywords potentiels, "
            f"{len(high_potential)} termes fort potentiel"
        ),
    }


# ─────────────────────────────────────────────
# Module 3 : Performance keywords
# ─────────────────────────────────────────────

def analyze_keyword_performance(keywords: list, avg_cpa: float) -> dict:
    """CPA, impression share, efficacite par keyword actif."""
    enabled = [kw for kw in keywords if kw["status"] == "ENABLED" and kw["cost"] > 0]

    high_cpa = []
    low_impression_share = []
    efficient = []

    for kw in enabled:
        cost = kw["cost"]
        convs = kw["conversions"]
        imp_share = kw.get("impression_share")

        cpa = round(cost / convs, 2) if convs > 0 else None
        roas_kw = None  # pas disponible au niveau keyword sans valeur conv

        entry = {
            "keyword": kw["keyword"],
            "campaign": kw["campaign"],
            "ad_group": kw["ad_group"],
            "cost": cost,
            "clicks": kw["clicks"],
            "conversions": convs,
            "cpa": cpa,
            "avg_cpc": kw["avg_cpc"],
            "qs": kw.get("quality_score"),
            "impression_share": imp_share,
            "top_impression_share": kw.get("top_impression_share"),
        }

        if cpa is not None and avg_cpa > 0 and cpa > avg_cpa * CPA_MAX_RATIO:
            entry["flag"] = f"CPA {cpa}€ = {round(cpa/avg_cpa, 1)}x la moyenne ({avg_cpa}€)"
            high_cpa.append(entry)
        elif imp_share is not None and imp_share < 30 and cost > 20:
            entry["flag"] = f"Impression share {imp_share}% sur {cost}€ depenses — limite de budget ou QS"
            low_impression_share.append(entry)
        elif convs > 0 and cpa is not None and cpa <= avg_cpa:
            efficient.append(entry)

    high_cpa.sort(key=lambda x: x["cost"], reverse=True)

    return {
        "high_cpa": high_cpa,
        "low_impression_share": low_impression_share,
        "efficient": efficient,
        "summary": f"{len(high_cpa)} CPA eleve, {len(low_impression_share)} impression share faible, {len(efficient)} efficaces",
    }


# ─────────────────────────────────────────────
# Module 4 : Campagnes
# ─────────────────────────────────────────────

def analyze_campaigns(campaigns: list) -> dict:
    """ROAS, efficacite budget, alertes par campagne."""
    active = [c for c in campaigns if c["status"] == "ENABLED"]
    alerts = []
    efficient = []

    for c in active:
        cost = c["cost"]
        conv_value = c.get("conversions_value", 0)
        convs = c["conversions"]
        roas = round(conv_value / cost, 2) if cost > 0 else None
        cpa = round(cost / convs, 2) if convs > 0 else None
        budget_daily = c.get("budget", 0)
        actual_daily = round(cost / 30, 2)

        entry = {
            "name": c["name"],
            "type": c["type"],
            "budget_daily": budget_daily,
            "actual_daily_avg": actual_daily,
            "cost_30d": cost,
            "clicks": c["clicks"],
            "conversions": convs,
            "cpa": cpa,
            "roas": roas,
            "ctr": c["ctr"],
            "avg_cpc": c["avg_cpc"],
            "impression_share_lost": None,
        }

        if roas is not None and roas < ROAS_MIN and cost > 50:
            entry["flag"] = f"ROAS {roas} < seuil minimum {ROAS_MIN}"
            alerts.append(entry)
        elif convs == 0 and cost > 20:
            entry["flag"] = f"{cost}€ depenses, 0 conversion"
            alerts.append(entry)
        else:
            efficient.append(entry)

    return {
        "alerts": alerts,
        "efficient": efficient,
        "summary": f"{len(alerts)} campagne(s) en alerte, {len(efficient)} efficace(s)",
    }


# ─────────────────────────────────────────────
# Module 5 : Landing Pages
# ─────────────────────────────────────────────

def analyze_landing_pages(landing_pages: list) -> dict:
    """Vitesse, CTR, cout par landing page."""
    slow_pages = []
    low_ctr = []
    efficient = []

    for lp in landing_pages:
        if lp["clicks"] < 5:
            continue
        speed = lp.get("speed_score")
        ctr = lp["ctr"]
        cost = lp["cost"]
        convs = lp["conversions"]
        mobile_pct = lp.get("mobile_friendly_pct")

        entry = {
            "url": lp["url"],
            "clicks": lp["clicks"],
            "cost": cost,
            "conversions": convs,
            "ctr": ctr,
            "speed_score": speed,
            "mobile_friendly_pct": mobile_pct,
        }

        flagged = False
        if speed is not None and speed < 50:
            entry["flag"] = f"Vitesse {speed}/100 — impact CPC et Quality Score"
            slow_pages.append(entry)
            flagged = True
        if not flagged and ctr < 1.0 and cost > 20:
            entry["flag"] = f"CTR {ctr}% faible pour {cost}€ depenses"
            low_ctr.append(entry)
            flagged = True
        if not flagged and convs > 0:
            efficient.append(entry)

    slow_pages.sort(key=lambda x: x["cost"], reverse=True)

    return {
        "slow_pages": slow_pages,
        "low_ctr": low_ctr,
        "efficient": efficient,
        "summary": f"{len(slow_pages)} page(s) lente(s), {len(low_ctr)} CTR faible, {len(efficient)} performante(s)",
    }


# ─────────────────────────────────────────────
# Module 6 : Schedule (horaire + jour)
# ─────────────────────────────────────────────

def analyze_schedule(schedule: dict) -> dict:
    """Identifie les plages horaires et jours creux/peak."""
    if not schedule:
        return {"available": False}

    by_hour = schedule.get("by_hour", [])
    by_day = schedule.get("by_day", [])

    def score_slots(slots, key_label):
        total_cost = sum(s["cost"] for s in slots)
        total_convs = sum(s["conversions"] for s in slots)
        avg_conv_rate = total_convs / total_cost if total_cost > 0 else 0

        enriched = []
        for s in slots:
            cost = s["cost"]
            convs = s["conversions"]
            clicks = s["clicks"]
            conv_rate = round(convs / cost * 100, 1) if cost > 0 else 0
            cpa = round(cost / convs, 2) if convs > 0 else None

            flag = None
            if cost > 5 and convs == 0:
                flag = "CREUX"
            elif conv_rate > avg_conv_rate * 1.5 and cost > 2:
                flag = "PEAK"

            enriched.append({
                key_label: s.get("hour") if "hour" in s else s.get("day"),
                "cost": cost,
                "clicks": clicks,
                "conversions": convs,
                "conv_rate_pct": conv_rate,
                "cpa": cpa,
                "flag": flag,
            })
        return enriched

    hours_analysis = score_slots(by_hour, "hour")
    days_analysis = score_slots(by_day, "day")

    creux_hours = [h for h in hours_analysis if h["flag"] == "CREUX"]
    peak_hours = [h for h in hours_analysis if h["flag"] == "PEAK"]
    creux_days = [d for d in days_analysis if d["flag"] == "CREUX"]
    peak_days = [d for d in days_analysis if d["flag"] == "PEAK"]

    return {
        "available": True,
        "by_hour": hours_analysis,
        "by_day": days_analysis,
        "creux_hours": creux_hours,
        "peak_hours": peak_hours,
        "creux_days": creux_days,
        "peak_days": peak_days,
        "summary": (
            f"Heures creuses : {[h['hour'] for h in creux_hours]}, "
            f"Heures peak : {[h['hour'] for h in peak_hours]}, "
            f"Jours creux : {[d['day'] for d in creux_days]}"
        ),
    }


# ─────────────────────────────────────────────
# Module 7 : Overlap SEO / SEA
# ─────────────────────────────────────────────

def analyze_seo_sea_overlap(search_terms: list, gsc_queries: list) -> dict:
    """
    Croise les search terms Ads avec les requetes GSC.
    Detecte les doublons (payants sur des requetes deja bien positionnées en SEO).
    """
    if not gsc_queries:
        return {"available": False, "message": "gsc_queries.csv absent — skip"}

    gsc_index = {q["query"]: q for q in gsc_queries}
    doublons = []
    opportunites = []

    for st in search_terms:
        if st["conversions"] == 0 or st["cost"] < 3:
            continue
        term = st["term"].lower()
        gsc = gsc_index.get(term)
        if not gsc:
            continue

        position = gsc["position"]
        gsc_clicks = gsc["clicks"]

        if position <= 3 and gsc_clicks >= 50:
            doublons.append({
                "term": st["term"],
                "ads_cost": st["cost"],
                "ads_conversions": st["conversions"],
                "gsc_position": position,
                "gsc_clicks": gsc_clicks,
                "action": "PAUSE_POTENTIELLE" if position <= 2 else "A_SURVEILLER",
                "saving_estimate": st["cost"],
            })
        elif position > 10 and st["conversions"] >= 1:
            opportunites.append({
                "term": st["term"],
                "ads_cost": st["cost"],
                "ads_conversions": st["conversions"],
                "gsc_position": position,
                "note": "Position SEO faible — Ads pertinent, envisager renforcement SEO",
            })

    doublons.sort(key=lambda x: x["ads_cost"], reverse=True)
    saving_total = round(sum(d["saving_estimate"] for d in doublons if d["action"] == "PAUSE_POTENTIELLE"), 2)

    return {
        "available": True,
        "doublons": doublons,
        "opportunites": opportunites,
        "saving_estimate_eur": saving_total,
        "summary": f"{len(doublons)} doublon(s) SEO/SEA, economie potentielle {saving_total}€",
    }


# ─────────────────────────────────────────────
# Rapport HTML
# ─────────────────────────────────────────────

def _badge(text: str, color: str) -> str:
    colors = {
        "red": "#dc2626", "orange": "#ea580c", "green": "#16a34a",
        "blue": "#2563eb", "gray": "#6b7280", "purple": "#7c3aed",
    }
    bg = {"red": "#fef2f2", "orange": "#fff7ed", "green": "#f0fdf4",
          "blue": "#eff6ff", "gray": "#f9fafb", "purple": "#f5f3ff"}
    c = colors.get(color, "#6b7280")
    b = bg.get(color, "#f9fafb")
    return f'<span style="background:{b};color:{c};border:1px solid {c}33;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{text}</span>'


def _row_flag(flag: str) -> str:
    if not flag:
        return ""
    mapping = {"CREUX": ("CREUX", "orange"), "PEAK": ("PEAK", "green"),
               "HIGH": ("HAUT", "red"), "MEDIUM": ("MOYEN", "orange")}
    label, color = mapping.get(flag, (flag, "gray"))
    return _badge(label, color)


def _kw_table(rows: list, cols: list) -> str:
    if not rows:
        return "<p style='color:#888;font-size:12px;'>Aucun element.</p>"
    headers = "".join(f"<th>{c['label']}</th>" for c in cols)
    body = ""
    for r in rows:
        cells = ""
        for c in cols:
            val = r.get(c["key"], "")
            if val is None:
                val = "-"
            if c.get("badge"):
                val = _badge(str(val), c["badge"](val))
            elif c.get("flag_key"):
                val = f"{val} {_row_flag(r.get(c['flag_key'], ''))}"
            cells += f"<td>{val}</td>"
        body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>"


def _heatmap_hour(hours: list) -> str:
    """Genere un heatmap 24 cases pour la performance horaire."""
    if not hours:
        return ""
    max_conv_rate = max((h.get("conv_rate_pct", 0) for h in hours), default=1) or 1
    cells = ""
    for h in sorted(hours, key=lambda x: x.get("hour", 0)):
        hour_val = h.get("hour", 0)
        cr = h.get("conv_rate_pct", 0)
        cost = h.get("cost", 0)
        convs = h.get("conversions", 0)
        flag = h.get("flag", "")

        intensity = cr / max_conv_rate if max_conv_rate > 0 else 0
        r = int(255 - intensity * 100)
        g = int(200 + intensity * 55)
        b = int(200 - intensity * 100)
        bg = f"rgb({r},{g},{b})"
        if cost == 0:
            bg = "#f3f4f6"
        elif flag == "CREUX":
            bg = "#fee2e2"

        label = f"{hour_val:02d}h"
        tooltip = f"Cost: {cost}€ | Conv: {convs} | Taux: {cr}%"
        cells += f'<div title="{tooltip}" style="background:{bg};padding:8px 4px;text-align:center;font-size:11px;border-radius:4px;min-width:36px;">{label}<br><small>{convs}</small></div>'

    return f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;">{cells}</div>'


def _heatmap_day(days: list) -> str:
    """Genere un affichage par jour de la semaine."""
    if not days:
        return ""
    day_labels = {"MONDAY": "Lun", "TUESDAY": "Mar", "WEDNESDAY": "Mer",
                  "THURSDAY": "Jeu", "FRIDAY": "Ven", "SATURDAY": "Sam", "SUNDAY": "Dim"}
    max_conv_rate = max((d.get("conv_rate_pct", 0) for d in days), default=1) or 1
    cells = ""
    for d in days:
        day_key = d.get("day", "")
        cr = d.get("conv_rate_pct", 0)
        cost = d.get("cost", 0)
        convs = d.get("conversions", 0)
        flag = d.get("flag", "")
        label = day_labels.get(day_key, day_key[:3])

        intensity = cr / max_conv_rate if max_conv_rate > 0 else 0
        r = int(255 - intensity * 100)
        g = int(200 + intensity * 55)
        b = int(200 - intensity * 100)
        bg = f"rgb({r},{g},{b})"
        if cost == 0:
            bg = "#f3f4f6"
        elif flag == "CREUX":
            bg = "#fee2e2"

        tooltip = f"Cost: {cost}€ | Conv: {convs} | Taux: {cr}%"
        cells += f'<div title="{tooltip}" style="background:{bg};padding:12px 16px;text-align:center;font-size:13px;border-radius:6px;flex:1;">{label}<br><b style="font-size:18px;">{convs}</b><br><small style="color:#666;">{cost}€</small></div>'

    return f'<div style="display:flex;gap:6px;margin-top:8px;">{cells}</div>'


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Google Ads Analysis — {site} — {date}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; color: #1a1a1a; background: #f5f5f5; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}
header {{ background: #0f172a; color: white; padding: 28px 0; margin-bottom: 24px; }}
header .container {{ padding-top: 0; padding-bottom: 0; }}
h1 {{ font-size: 20px; font-weight: 700; }}
h1 span {{ color: #38bdf8; }}
.subtitle {{ color: #94a3b8; font-size: 12px; margin-top: 4px; }}
.section {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
.section-title {{ font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #f1f5f9; display: flex; align-items: center; gap: 8px; }}
.section-title .count {{ background: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
.metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.metric {{ background: #f8fafc; border-radius: 8px; padding: 14px; border: 1px solid #e2e8f0; }}
.metric-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .5px; }}
.metric-value {{ font-size: 24px; font-weight: 800; color: #0f172a; margin: 4px 0; }}
.metric-sub {{ font-size: 12px; color: #64748b; }}
.metric.green {{ border-color: #bbf7d0; background: #f0fdf4; }}
.metric.green .metric-value {{ color: #16a34a; }}
.metric.red {{ border-color: #fecaca; background: #fef2f2; }}
.metric.red .metric-value {{ color: #dc2626; }}
.metric.orange {{ border-color: #fed7aa; background: #fff7ed; }}
.metric.orange .metric-value {{ color: #ea580c; }}
.alert-box {{ border-left: 4px solid #dc2626; background: #fef2f2; padding: 12px 16px; border-radius: 0 6px 6px 0; margin-bottom: 10px; }}
.alert-box.warning {{ border-color: #ea580c; background: #fff7ed; }}
.alert-box.info {{ border-color: #2563eb; background: #eff6ff; }}
.alert-box.success {{ border-color: #16a34a; background: #f0fdf4; }}
.alert-title {{ font-weight: 700; font-size: 13px; margin-bottom: 4px; }}
.alert-detail {{ font-size: 12px; color: #555; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th {{ background: #f8fafc; text-align: left; padding: 8px 10px; font-weight: 600; color: #475569; font-size: 11px; text-transform: uppercase; letter-spacing: .4px; border-bottom: 2px solid #e2e8f0; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }}
tr:hover td {{ background: #f8fafc; }}
.qs-badge {{ display: inline-block; width: 28px; height: 28px; border-radius: 50%; text-align: center; line-height: 28px; font-weight: 800; font-size: 13px; }}
.qs-1, .qs-2, .qs-3 {{ background: #fecaca; color: #991b1b; }}
.qs-4, .qs-5 {{ background: #fed7aa; color: #9a3412; }}
.qs-6, .qs-7 {{ background: #fef08a; color: #713f12; }}
.qs-8, .qs-9, .qs-10 {{ background: #bbf7d0; color: #14532d; }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
.action-tag {{ display: inline-block; background: #dbeafe; color: #1d4ed8; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
.action-urgent {{ background: #fecaca; color: #991b1b; }}
.action-medium {{ background: #fed7aa; color: #9a3412; }}
</style>
</head>
<body>
<header>
  <div class="container">
    <h1>Google Ads <span>Analysis</span> — {site_upper}</h1>
    <p class="subtitle">Periode : {period_start} au {period_end} ({days}j) &nbsp;|&nbsp; Genere le {date}</p>
  </div>
</header>
<div class="container">

  <!-- KPIs -->
  <div class="metrics-grid">
    <div class="metric {roas_class}">
      <div class="metric-label">ROAS</div>
      <div class="metric-value">{roas}x</div>
      <div class="metric-sub">valeur / depenses</div>
    </div>
    <div class="metric">
      <div class="metric-label">Depenses 30j</div>
      <div class="metric-value">{spend}€</div>
      <div class="metric-sub">{daily_avg}€/j moy.</div>
    </div>
    <div class="metric green">
      <div class="metric-label">Conversions</div>
      <div class="metric-value">{conversions}</div>
      <div class="metric-sub">CPA moy. {cpa}€</div>
    </div>
    <div class="metric">
      <div class="metric-label">Clics</div>
      <div class="metric-value">{clicks}</div>
      <div class="metric-sub">CPC moy. {avg_cpc}€</div>
    </div>
    <div class="metric">
      <div class="metric-label">CTR moyen</div>
      <div class="metric-value">{ctr}%</div>
      <div class="metric-sub">{impressions} impressions</div>
    </div>
    <div class="metric {alerts_class}">
      <div class="metric-label">Alertes</div>
      <div class="metric-value">{alerts_count}</div>
      <div class="metric-sub">{opportunities_count} opportunites</div>
    </div>
  </div>

  {sections_html}

</div>
</body>
</html>"""


def _qs_badge(qs) -> str:
    if qs is None:
        return '<span style="color:#888">-</span>'
    cls = f"qs-{min(10, max(1, int(qs)))}"
    return f'<span class="qs-badge {cls}">{qs}</span>'


def generate_html(data: dict, analysis: dict, site: str, period: dict) -> str:
    summary = data.get("summary", {})
    spend = summary.get("total_spend", 0)
    conversions = summary.get("total_conversions", 0)
    clicks = summary.get("total_clicks", 0)
    impressions = summary.get("total_impressions", 0)
    roas = summary.get("roas", 0)
    avg_cpc = summary.get("avg_cpc", 0)
    ctr = summary.get("avg_ctr", 0)
    cpa = round(spend / conversions, 2) if conversions > 0 else 0
    daily_avg = round(spend / period.get("days", 30), 2)

    qs_analysis = analysis["quality_scores"]
    st_analysis = analysis["search_terms"]
    kw_analysis = analysis["keyword_performance"]
    camp_analysis = analysis["campaigns"]
    lp_analysis = analysis["landing_pages"]
    sched_analysis = analysis["schedule"]
    seo_analysis = analysis["seo_sea"]

    alerts_count = (
        len(qs_analysis["critical"]) +
        len(camp_analysis["alerts"]) +
        len(lp_analysis["slow_pages"])
    )
    opps_count = (
        len(st_analysis["new_kw_candidates"]) +
        len(st_analysis["negatives_candidates"])
    )

    sections = []

    # ── Section 1 : Quality Score ────────────────────────────────────────────
    qs_rows_crit = ""
    for kw in qs_analysis["critical"]:
        action_cls = "action-urgent"
        qs_rows_crit += f"""<tr>
          <td>{kw['keyword']}</td>
          <td>{kw['campaign']}</td>
          <td>{_qs_badge(kw['qs'])}</td>
          <td>{kw['status']}</td>
          <td>{kw['cost']}€</td>
          <td>{kw['conversions']}</td>
          <td><span class="action-tag {action_cls}">{kw['action']}</span></td>
        </tr>"""
    qs_rows_warn = ""
    for kw in qs_analysis["warnings"]:
        qs_rows_warn += f"""<tr>
          <td>{kw['keyword']}</td>
          <td>{kw['campaign']}</td>
          <td>{_qs_badge(kw['qs'])}</td>
          <td>{kw['cost']}€</td>
          <td>{kw['conversions']}</td>
          <td><small style="color:#666">{kw['reason']}</small></td>
        </tr>"""

    qs_crit_table = f"""
      <h3 style="color:#dc2626;font-size:12px;margin-bottom:8px;">CRITIQUES — action immediate</h3>
      <table><thead><tr>
        <th>Keyword</th><th>Campagne</th><th>QS</th><th>Statut</th><th>Cost</th><th>Conv</th><th>Action</th>
      </tr></thead><tbody>{qs_rows_crit}</tbody></table>
    """ if qs_analysis["critical"] else "<p style='color:#888;font-size:12px;margin-bottom:12px;'>Aucun keyword critique.</p>"

    qs_warn_table = f"""
      <h3 style="color:#ea580c;font-size:12px;margin:12px 0 8px;">AVERTISSEMENTS — amelioration recommandee</h3>
      <table><thead><tr>
        <th>Keyword</th><th>Campagne</th><th>QS</th><th>Cost</th><th>Conv</th><th>Raison</th>
      </tr></thead><tbody>{qs_rows_warn}</tbody></table>
    """ if qs_analysis["warnings"] else "<p style='color:#888;font-size:12px;'>Aucun avertissement QS.</p>"

    sections.append(f"""
    <div class="section">
      <div class="section-title">Quality Score
        <span class="count">{len(qs_analysis['critical'])} critique(s) / {len(qs_analysis['warnings'])} avert.</span>
      </div>
      {qs_crit_table}
      {qs_warn_table}
    </div>""")

    # ── Section 2 : Negatifs ────────────────────────────────────────────────
    neg_rows = ""
    for st in st_analysis["negatives_candidates"]:
        prio_cls = "action-urgent" if st["priority"] == "HIGH" else "action-medium"
        neg_rows += f"""<tr>
          <td>{st['term']}</td>
          <td>{st['campaign']}</td>
          <td>{st['cost']}€</td>
          <td>{st['clicks']}</td>
          <td>{st['ctr']}%</td>
          <td><span class="action-tag {prio_cls}">{st['priority']}</span></td>
        </tr>"""

    neg_table = f"""<table><thead><tr>
      <th>Terme</th><th>Campagne</th><th>Cost</th><th>Clics</th><th>CTR</th><th>Priorite</th>
    </tr></thead><tbody>{neg_rows}</tbody></table>""" if neg_rows else "<p style='color:#888;font-size:12px;'>Aucun candidat negatif detecte.</p>"

    # Nouveaux keywords
    nkw_rows = ""
    for kw in st_analysis["new_kw_candidates"]:
        prio_cls = "action-urgent" if kw["priority"] == "HIGH" else "action-medium"
        nkw_rows += f"""<tr>
          <td><strong>{kw['term']}</strong></td>
          <td>{kw['campaign']}</td>
          <td>{kw['conversions']}</td>
          <td>{kw['cpa']}€</td>
          <td>{kw['clicks']}</td>
          <td>{kw['avg_cpc']}€</td>
          <td><span class="action-tag {prio_cls}">{kw['suggested_match']}</span></td>
        </tr>"""

    nkw_table = f"""<table><thead><tr>
      <th>Terme</th><th>Campagne</th><th>Conv</th><th>CPA</th><th>Clics</th><th>CPC moy</th><th>Match suggere</th>
    </tr></thead><tbody>{nkw_rows}</tbody></table>""" if nkw_rows else "<p style='color:#888;font-size:12px;'>Aucun nouveau keyword identifie.</p>"

    sections.append(f"""
    <div class="section">
      <div class="two-col">
        <div>
          <div class="section-title">Candidats Mots-cles Negatifs
            <span class="count">{len(st_analysis['negatives_candidates'])}</span>
          </div>
          {neg_table}
        </div>
        <div>
          <div class="section-title">Nouveaux Keywords Potentiels
            <span class="count">{len(st_analysis['new_kw_candidates'])}</span>
          </div>
          {nkw_table}
        </div>
      </div>
    </div>""")

    # ── Section 3 : Performance keywords ────────────────────────────────────
    high_cpa_rows = ""
    for kw in kw_analysis["high_cpa"]:
        high_cpa_rows += f"""<tr>
          <td>{kw['keyword']}</td>
          <td>{kw['campaign']}</td>
          <td>{_qs_badge(kw['qs'])}</td>
          <td>{kw['cost']}€</td>
          <td>{kw['conversions']}</td>
          <td style="color:#dc2626;font-weight:700;">{kw['cpa']}€</td>
          <td>{kw.get('impression_share', '-')}</td>
        </tr>"""
    high_cpa_table = f"""<table><thead><tr>
      <th>Keyword</th><th>Campagne</th><th>QS</th><th>Cost</th><th>Conv</th><th>CPA</th><th>Imp. share</th>
    </tr></thead><tbody>{high_cpa_rows}</tbody></table>""" if high_cpa_rows else "<p style='color:#888;font-size:12px;'>Aucun CPA anormal.</p>"

    sections.append(f"""
    <div class="section">
      <div class="section-title">Keywords CPA Eleve
        <span class="count">CPA moyen global : {cpa}€</span>
      </div>
      {high_cpa_table}
    </div>""")

    # ── Section 4 : Campagnes ────────────────────────────────────────────────
    camp_rows = ""
    all_camps = camp_analysis["alerts"] + camp_analysis["efficient"]
    for c in sorted(all_camps, key=lambda x: x["cost_30d"], reverse=True):
        roas_str = f"{c['roas']}x" if c["roas"] else "-"
        roas_color = "color:#16a34a" if (c["roas"] or 0) >= 5 else ("color:#dc2626" if (c["roas"] or 0) < ROAS_MIN else "color:#ea580c")
        flag_str = f"<br><small style='color:#dc2626'>{c.get('flag','')}</small>" if c.get("flag") else ""
        camp_rows += f"""<tr>
          <td>{c['name']}{flag_str}</td>
          <td>{c['type']}</td>
          <td>{c['cost_30d']}€</td>
          <td>{c['budget_daily']}€/j</td>
          <td>{c['clicks']}</td>
          <td>{c['conversions']}</td>
          <td style="{roas_color};font-weight:700;">{roas_str}</td>
          <td>{c['cpa']}€</td>
        </tr>"""
    sections.append(f"""
    <div class="section">
      <div class="section-title">Campagnes
        <span class="count">{len(camp_analysis['alerts'])} alerte(s)</span>
      </div>
      <table><thead><tr>
        <th>Campagne</th><th>Type</th><th>Cost 30j</th><th>Budget</th><th>Clics</th><th>Conv</th><th>ROAS</th><th>CPA</th>
      </tr></thead><tbody>{camp_rows}</tbody></table>
    </div>""")

    # ── Section 5 : Schedule ────────────────────────────────────────────────
    if sched_analysis.get("available"):
        creux_h = [f"{h['hour']:02d}h" for h in sched_analysis.get("creux_hours", [])]
        peak_h = [f"{h['hour']:02d}h" for h in sched_analysis.get("peak_hours", [])]
        creux_d = [d["day"] for d in sched_analysis.get("creux_days", [])]
        day_labels_fr = {"MONDAY": "Lundi", "TUESDAY": "Mardi", "WEDNESDAY": "Mercredi",
                         "THURSDAY": "Jeudi", "FRIDAY": "Vendredi", "SATURDAY": "Samedi", "SUNDAY": "Dimanche"}
        creux_d_fr = [day_labels_fr.get(d, d) for d in creux_d]

        alerts_sched = ""
        if creux_h:
            alerts_sched += f'<div class="alert-box warning"><div class="alert-title">Heures creuses detectees</div><div class="alert-detail">{", ".join(creux_h)} — depenses sans conversion. Envisager bid adjustment -40% a -70%.</div></div>'
        if peak_h:
            alerts_sched += f'<div class="alert-box success"><div class="alert-title">Heures peak</div><div class="alert-detail">{", ".join(peak_h)} — taux de conversion superieur a la moyenne.</div></div>'
        if creux_d_fr:
            alerts_sched += f'<div class="alert-box warning"><div class="alert-title">Jours creux</div><div class="alert-detail">{", ".join(creux_d_fr)} — envisager reduction budget ou bid adjustment.</div></div>'

        sections.append(f"""
    <div class="section">
      <div class="section-title">Performance Horaire et Journaliere</div>
      {alerts_sched}
      <h3 style="font-size:12px;color:#475569;margin:16px 0 4px;">Conversions par heure</h3>
      {_heatmap_hour(sched_analysis.get("by_hour", []))}
      <h3 style="font-size:12px;color:#475569;margin:16px 0 4px;">Conversions par jour de la semaine</h3>
      {_heatmap_day(sched_analysis.get("by_day", []))}
    </div>""")
    else:
        sections.append("""<div class="section"><div class="section-title">Performance Horaire</div>
          <div class="alert-box info"><div class="alert-title">Donnees non disponibles</div>
          <div class="alert-detail">Relancer ads_fetch.py pour inclure les donnees horaires.</div></div>
        </div>""")

    # ── Section 6 : Landing Pages ───────────────────────────────────────────
    site_url = load_site_url(site)
    lp_rows = ""
    for lp in (lp_analysis["slow_pages"] + lp_analysis["low_ctr"])[:20]:
        speed_color = "color:#dc2626;font-weight:700" if (lp.get("speed_score") or 100) < 50 else ""
        lp_url_display = lp['url'].replace(site_url, '') if site_url else lp['url']
        lp_rows += f"""<tr>
          <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{lp['url']}">{lp_url_display}</td>
          <td>{lp['clicks']}</td>
          <td>{lp['cost']}€</td>
          <td>{lp['conversions']}</td>
          <td style="{speed_color}">{lp.get('speed_score') or '-'}</td>
          <td>{lp['ctr']}%</td>
          <td><small style="color:#dc2626">{lp.get('flag','')}</small></td>
        </tr>"""
    lp_table = f"""<table><thead><tr>
      <th>URL</th><th>Clics</th><th>Cost</th><th>Conv</th><th>Vitesse</th><th>CTR</th><th>Flag</th>
    </tr></thead><tbody>{lp_rows}</tbody></table>""" if lp_rows else "<p style='color:#888;font-size:12px;'>Aucune landing page problematique.</p>"

    sections.append(f"""
    <div class="section">
      <div class="section-title">Landing Pages
        <span class="count">{len(lp_analysis['slow_pages'])} lente(s) / {len(lp_analysis['low_ctr'])} CTR faible</span>
      </div>
      {lp_table}
    </div>""")

    # ── Section 7 : SEO/SEA ──────────────────────────────────────────────────
    if seo_analysis.get("available") and seo_analysis.get("doublons"):
        seo_rows = ""
        for d in seo_analysis["doublons"]:
            action_cls = "action-urgent" if d["action"] == "PAUSE_POTENTIELLE" else "action-medium"
            seo_rows += f"""<tr>
              <td>{d['term']}</td>
              <td>{d['ads_cost']}€</td>
              <td>{d['ads_conversions']}</td>
              <td style="color:#16a34a;font-weight:700;">#{d['gsc_position']}</td>
              <td>{d['gsc_clicks']}</td>
              <td><span class="action-tag {action_cls}">{d['action']}</span></td>
            </tr>"""
        seo_note = f'<div class="alert-box info" style="margin-bottom:12px;"><div class="alert-title">Economie potentielle estimee : {seo_analysis["saving_estimate_eur"]}€/mois</div><div class="alert-detail">Termes ou la position SEO organique justifierait une pause ou reduction des encheres Ads.</div></div>'
        sections.append(f"""
    <div class="section">
      <div class="section-title">Doublons SEO / SEA
        <span class="count">{len(seo_analysis['doublons'])}</span>
      </div>
      {seo_note}
      <table><thead><tr>
        <th>Terme</th><th>Cost Ads</th><th>Conv Ads</th><th>Position GSC</th><th>Clics GSC</th><th>Action</th>
      </tr></thead><tbody>{seo_rows}</tbody></table>
    </div>""")
    elif not seo_analysis.get("available"):
        sections.append("""<div class="section"><div class="section-title">Doublons SEO / SEA</div>
          <div class="alert-box info"><div class="alert-title">gsc_queries.csv absent</div>
          <div class="alert-detail">Relancer gsc_fetch.py pour activer cette analyse.</div></div>
        </div>""")

    roas_class = "green" if roas >= 5 else ("orange" if roas >= 3 else "red")
    alerts_class = "red" if alerts_count >= 3 else ("orange" if alerts_count >= 1 else "green")

    return HTML_TEMPLATE.format(
        site=site,
        site_upper=site.upper(),
        date=date.today().strftime("%d/%m/%Y"),
        period_start=period["start"],
        period_end=period["end"],
        days=period["days"],
        roas=roas,
        roas_class=roas_class,
        spend=spend,
        daily_avg=daily_avg,
        conversions=conversions,
        cpa=cpa,
        clicks=clicks,
        avg_cpc=avg_cpc,
        ctr=ctr,
        impressions=impressions,
        alerts_count=alerts_count,
        alerts_class=alerts_class,
        opportunities_count=opps_count,
        sections_html="\n".join(sections),
    )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Google Ads Analyzer")
    parser.add_argument("--site", required=True, help="Nom du site (ex: monsite)")
    parser.add_argument("--month", help="Mois YYYY-MM (defaut: mois courant)")
    args = parser.parse_args()

    month = args.month or datetime.now().strftime("%Y-%m")
    site = args.site

    print(f"Analyse Google Ads : {site} | {month}")

    # Chargement
    data = load_ads(site, month)
    gsc_queries = load_gsc_queries(site, month)
    if gsc_queries:
        print(f"  GSC queries : {len(gsc_queries)} requetes chargees")
    else:
        print("  GSC queries : absent (analyse SEO/SEA desactivee)")

    period = data.get("period", {"start": "?", "end": "?", "days": 30})
    campaigns = data.get("campaigns", [])
    keywords = data.get("keywords", [])
    search_terms = data.get("search_terms", [])
    landing_pages = data.get("landing_pages", [])
    schedule = data.get("schedule", {})
    summary = data.get("summary", {})

    # CPA moyen global
    total_spend = summary.get("total_spend", 0)
    total_conv = summary.get("total_conversions", 0)
    avg_cpa = round(total_spend / total_conv, 2) if total_conv > 0 else 0

    print(f"  Campagnes : {len(campaigns)} | Keywords : {len(keywords)} | Search terms : {len(search_terms)}")
    print(f"  Depenses : {total_spend}€ | Conversions : {total_conv} | CPA moyen : {avg_cpa}€ | ROAS : {summary.get('roas', 0)}")

    # Analyses
    analysis = {
        "quality_scores": analyze_quality_scores(keywords),
        "search_terms": analyze_search_terms(search_terms, keywords),
        "keyword_performance": analyze_keyword_performance(keywords, avg_cpa),
        "campaigns": analyze_campaigns(campaigns),
        "landing_pages": analyze_landing_pages(landing_pages),
        "schedule": analyze_schedule(schedule),
        "seo_sea": analyze_seo_sea_overlap(search_terms, gsc_queries),
    }

    # Resume console
    print()
    print("=== RESULTATS ===")
    for key, res in analysis.items():
        print(f"  {key:25} : {res.get('summary', 'N/A')}")

    # Export JSON
    out_dir = os.path.join(DATA_DIR, site, month)
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "ads_analysis.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "site": site,
            "month": month,
            "generated_at": datetime.now().isoformat(),
            "period": period,
            "summary": summary,
            "avg_cpa": avg_cpa,
            "analysis": analysis,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON : {json_path}")

    # Export HTML
    html = generate_html(data, analysis, site, period)
    report_dir = os.path.join(REPORTS_DIR, site)
    os.makedirs(report_dir, exist_ok=True)
    html_path = os.path.join(report_dir, f"ads-{date.today().strftime('%Y-%m-%d')}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML : {html_path}")


if __name__ == "__main__":
    main()
