"""
Tests pour ads_apply.py -- couche d'application des change-sets de La Régie.

Garde-fou de tier : un item de tier 2/3 ne s'applique jamais sans approbation
explicite (approved=True) ; un item de tier 4 est toujours refusé, même
approuvé (interdiction réglementaire).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ads_apply import apply_changeset


def test_apply_refuses_unapproved_tier2():
    changeset = [{"type": "budget_change", "tier": 2, "approved": False, "campaign_id": "X", "value": 40}]
    result = apply_changeset("monsite", changeset, dry_run=True)
    assert result.applied == []
    assert changeset[0] in [s["item"] for s in result.skipped]
    assert result.skipped[0]["reason"] == "tier2_not_approved"


def test_apply_tier1_applied_and_tier4_blocked():
    cs = [{"type": "negative_exact", "tier": 1, "approved": False, "text": "pharmacie"},
          {"type": "restricted_claim", "tier": 4, "approved": True, "text": "guerit"}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert any(a["type"] == "negative_exact" for a in r.applied)
    assert r.skipped[0]["reason"] == "tier4_forbidden"


def test_apply_tier3_approved_is_applied():
    """Un item de tier 3 explicitement approuvé doit s'appliquer, pas être sauté."""
    cs = [{"type": "budget_change", "tier": 3, "approved": True, "campaign_id": "Y", "value": 25}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.skipped == []
    assert any(a["campaign_id"] == "Y" for a in r.applied)


def test_apply_ignores_unknown_metadata_fields():
    """Un item peut porter des champs de métadonnées supplémentaires (id, preuve,
    agent source pm-buyer/pm-tracking/pm-feed) sans faire échouer l'application."""
    cs = [{
        "type": "negative_exact",
        "tier": 1,
        "approved": False,
        "text": "gratuit",
        "id": "chg-042",
        "source_agent": "pm-buyer",
        "preuve": {"search_term": "masque yeux gratuit", "clics": 12, "conversions": 0},
        "qc_verdict": "OK",
    }]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.errors == []
    assert r.skipped == []
    assert any(a["id"] == "chg-042" for a in r.applied)


def test_apply_dry_run_default_true():
    """dry_run doit être True par défaut (aucune écriture réelle sans le demander explicitement)."""
    cs = [{"type": "negative_exact", "tier": 1, "approved": False, "text": "occasion"}]
    r = apply_changeset("monsite", cs)
    assert any(a["text"] == "occasion" for a in r.applied)
    assert r.errors == []


# --- Regression : correctifs findings CRITICAL 1/2 et IMPORTANT 3, MINOR 6 ---

def test_apply_item_without_tier_is_blocked():
    """Un item sans champ tier ne doit jamais être appliqué par défaut : le
    défaut restrictif est de le bloquer, pas de le traiter comme tier 1."""
    cs = [{"type": "negative_exact", "approved": False, "text": "sans_tier"}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.applied == []
    assert cs[0] in [s["item"] for s in r.skipped]
    assert r.skipped[0]["reason"] == "tier_missing_blocked"


def test_apply_approved_string_false_does_not_bypass_gate():
    """approved="false" (chaîne) sur un tier 2 ne doit pas être appliqué :
    bool("false") vaut True en Python, la gate ne doit pas s'y laisser prendre."""
    cs = [{"type": "budget_change", "tier": 2, "approved": "false", "campaign_id": "Z", "value": 10}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.applied == []
    assert r.skipped[0]["reason"] == "tier2_not_approved"


def test_apply_approved_string_true_does_not_bypass_gate():
    """approved="true" (chaîne) sur un tier 2 ne doit pas être appliqué non plus :
    seul le booléen strict True vaut approbation."""
    cs = [{"type": "budget_change", "tier": 2, "approved": "true", "campaign_id": "Z2", "value": 10}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.applied == []
    assert r.skipped[0]["reason"] == "tier2_not_approved"


def test_apply_tier_null_does_not_crash_and_loop_continues():
    """Un item avec tier: null ne doit jamais faire planter apply_changeset ni
    perdre les items suivants du même change-set."""
    cs = [
        {"type": "negative_exact", "tier": None, "approved": True, "text": "casse_pas"},
        {"type": "negative_exact", "tier": 1, "approved": False, "text": "suivant_valide"},
    ]
    r = apply_changeset("monsite", cs, dry_run=True)
    # Le premier item (tier invalide) ne doit jamais être appliqué.
    assert not any(a.get("text") == "casse_pas" for a in r.applied)
    assert any(
        s["item"].get("text") == "casse_pas" for s in r.skipped
    ) or any(
        e["item"].get("text") == "casse_pas" for e in r.errors
    )
    # Le second item, valide, doit être traité normalement malgré le premier.
    assert any(a.get("text") == "suivant_valide" for a in r.applied)


def test_apply_item_with_unrecognized_type_is_blocked():
    """Un item sans type reconnu (absent ou inconnu) ne doit jamais être
    compté comme appliqué."""
    cs = [{"tier": 1, "approved": True, "text": "type_absent"}]
    r = apply_changeset("monsite", cs, dry_run=True)
    assert r.applied == []
    assert r.skipped[0]["reason"] == "type_unknown"


def test_apply_live_write_not_wired_never_reports_false_success():
    """Un type reconnu mais NON câblé en écriture réelle (ex. exclusion produit,
    listing group) ne doit jamais renvoyer un faux succès en dry_run=False :
    l'item part en errors avec live_apply_not_wired, jamais en applied."""
    cs = [{"type": "exclusion", "tier": 1, "approved": False, "product_id": "17928"}]
    r = apply_changeset("monsite", cs, dry_run=False)
    assert r.applied == []
    assert len(r.errors) == 1
    assert "live_apply_not_wired" in r.errors[0]["error"]


def test_apply_live_negative_missing_field_never_false_success():
    """Un négatif câblé mais mal formé (campaign_id/text manquant) part en
    errors, jamais en applied : le câblage réel ne crée pas de faux succès sur
    un item incomplet."""
    cs = [{"type": "negative_exact", "tier": 1, "approved": False, "text": "sans_campagne"}]
    r = apply_changeset("monsite", cs, dry_run=False)
    assert r.applied == []
    assert len(r.errors) == 1
    # Soit champ manquant (campaign_id absent), soit package google-ads absent
    # en environnement de test : dans les deux cas, jamais un faux succès.
    assert r.errors[0]["error"]  # une raison explicite est presente
