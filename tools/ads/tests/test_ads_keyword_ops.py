"""
Tests pour ads_keyword_ops.py -- neutralisation des listes client en dur.

Garde-fou : le script ne doit JAMAIS tourner sans un fichier d'operations
explicite (--ops-file). Relance tel quel sur un autre compte, l'ancien script
aurait mute des mots-cles client codes en dur.

Aucun appel API : on ne teste que le refus de demarrer et la validation du
fichier d'operations (load_ops_file).
"""

import json
import os
import re
import subprocess
import sys

import pytest

TOOLS_ADS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(TOOLS_ADS, "ads_keyword_ops.py")
SCRIPT_SEO_AUDIT = os.path.abspath(
    os.path.join(TOOLS_ADS, "..", "seo-audit", "ads_keyword_ops.py")
)
EXAMPLE = os.path.join(TOOLS_ADS, "examples", "keyword-ops.example.json")

sys.path.insert(0, TOOLS_ADS)

from ads_keyword_ops import load_ops_file


# --- Refus de demarrer sans --ops-file (les deux copies) ---

@pytest.mark.parametrize("script", [SCRIPT, SCRIPT_SEO_AUDIT])
def test_script_refuses_to_run_without_ops_file(script):
    """Sans --ops-file, le script doit refuser de tourner (exit != 0) avec un
    message mentionnant l'argument manquant, AVANT tout appel API."""
    r = subprocess.run(
        [sys.executable, script, "--site", "n_importe_quel_site", "--campaign", "X"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "--ops-file" in r.stderr


@pytest.mark.parametrize("script", [SCRIPT, SCRIPT_SEO_AUDIT])
def test_script_refuses_missing_ops_file_path(script):
    """Un chemin --ops-file inexistant doit etre refuse avec un message clair,
    AVANT tout appel API (aucune config sites.json chargee)."""
    r = subprocess.run(
        [sys.executable, script, "--site", "n_importe_quel_site",
         "--campaign", "X", "--ops-file", "/chemin/inexistant/ops.json"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "introuvable" in r.stderr


@pytest.mark.parametrize("script", [SCRIPT, SCRIPT_SEO_AUDIT])
def test_no_hardcoded_client_keyword_lists_left(script):
    """Aucune liste de mots-cles ni chemin de sortie propre a un client en dur
    ne doit subsister dans le code (le chemin de sortie doit toujours passer
    par la variable --site, jamais un slug de client fige dans le source)."""
    with open(script, encoding="utf-8") as f:
        src = f.read()
    assert "masque chauffant yeux" not in src
    assert "remede yeux secs" not in src
    assert not re.search(r"data/[a-z0-9_-]+/ops_keyword", src)


# --- Validation du fichier d'operations ---

def test_load_ops_file_accepts_example_file():
    to_pause, to_reduce = load_ops_file(EXAMPLE)
    assert isinstance(to_pause, list) and to_pause
    assert isinstance(to_reduce, dict)
    for params in to_reduce.values():
        assert isinstance(params["target_cpc"], (int, float))


def test_load_ops_file_rejects_empty_operations(tmp_path):
    """Un fichier valide mais sans aucune operation est refuse : rien a
    appliquer signale une erreur de preparation, pas un run legitime."""
    p = tmp_path / "empty-ops.json"
    p.write_text(json.dumps({"keywords_to_pause": [], "keywords_to_reduce_cpc": {}}))
    with pytest.raises(SystemExit):
        load_ops_file(str(p))


def test_load_ops_file_rejects_invalid_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{pas du json")
    with pytest.raises(SystemExit):
        load_ops_file(str(p))


def test_load_ops_file_rejects_bad_target_cpc(tmp_path):
    p = tmp_path / "bad-cpc.json"
    p.write_text(json.dumps({"keywords_to_reduce_cpc": {"kw": {"target_cpc": "0,35"}}}))
    with pytest.raises(SystemExit):
        load_ops_file(str(p))
