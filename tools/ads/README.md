# tools/ads/ : scripts Google Ads (La Régie)

Copie isolée des scripts Google Ads, à destination des futurs agents de La Régie.
Les scripts originaux utilisés par `ads-agent` restent dans `tools/seo-audit/` et
ne sont pas touchés : ce dossier est une copie, pas un déplacement.

## Résolution de la configuration

Chaque script ci-dessous charge `google-ads.yaml`, `ads-token.json` et `sites.json`
depuis un chemin absolu pointant vers `tools/seo-audit/` (constante `CONFIG_DIR`
en tête de fichier). Choix retenu : ne pas dupliquer les secrets. La configuration
et le token OAuth2 restent une source unique dans `tools/seo-audit/`, partagée par
les deux copies de scripts. `ads_auth.py` (setup) écrit aussi son token et son yaml
générés dans `tools/seo-audit/`, même lancé depuis `tools/ads/`.

Le venv Python (dépendances `google-ads`, `pyyaml`, etc.) n'a pas été dupliqué non
plus : utiliser celui de `tools/seo-audit/venv/`.

## Tableau des scripts

| Script | Rôle | Nature | Commande d'exemple | Venv |
|---|---|---|---|---|
| `ads_auth.py` | Génère le token OAuth2 (scope adwords) et `google-ads.yaml` à partir des credentials Google Cloud existants | SETUP (écrit des fichiers locaux de config, aucune action sur le compte Ads) | `python3 ads_auth.py --credentials ~/gsc-credentials.json --developer-token XXXXX` | `tools/seo-audit/venv/bin/python3` |
| `ads_fetch.py` | Extrait campagnes, mots-clés, pages de destination, search terms, géo, annonces et planning horaire sur une période donnée | LECTURE (API Google Ads en lecture seule, écrit uniquement un JSON local dans `data/{site}/{mois}/ads.json`) | `python3 ads_fetch.py --site monsite --days 7` | `tools/seo-audit/venv/bin/python3` |
| `ads_analyze.py` | Analyse le JSON produit par `ads_fetch.py` (Quality Score, search terms candidats négatifs, ROAS, overlap SEO/SEA) et génère un rapport HTML | LECTURE (aucun appel API, travaille sur les fichiers déjà extraits) | `python3 ads_analyze.py --site monsite --month 2026-07` | `tools/seo-audit/venv/bin/python3` |
| `ads_conversion_check.py` | Diagnostic des actions de conversion, auto-tagging, Consent Mode et fenêtres d'attribution | LECTURE (API Google Ads en lecture seule) | `python3 ads_conversion_check.py --site monsite` | `tools/seo-audit/venv/bin/python3` |
| `ads_seo_cross.py` | Croise les données Ads avec GSC et GA4 (doublons paid/organique, opportunités SEO, ROAS réel par URL) | LECTURE (travaille sur des fichiers locaux déjà extraits, aucun appel API) | `python3 ads_seo_cross.py --site monsite --month 2026-07` | `tools/seo-audit/venv/bin/python3` |
| `ads_keyword_ops.py` | Applique des opérations de pause et d'ajustement de CPC sur les mots-clés d'une campagne, puis vérifie le résultat | **ECRITURE API** (mutation directe du compte Google Ads live via `mutate_ad_group_criteria`) | `python3 ads_keyword_ops.py --site {site} --campaign "NOM_CAMPAGNE" --ops-file ops.json` | `tools/seo-audit/venv/bin/python3` |

## Point d'attention sur `ads_keyword_ops.py`

Depuis le 25/08/2026, ce script ne contient plus aucune liste d'opérations
codée en dur : les listes (`keywords_to_pause`, `keywords_to_reduce_cpc`)
viennent obligatoirement d'un fichier JSON passé via `--ops-file`, et le
script refuse de tourner sans ce fichier (ou avec un fichier vide). Modèle :
`tools/ads/examples/keyword-ops.example.json`. La même neutralisation est
appliquée à la copie originale `tools/seo-audit/ads_keyword_ops.py`.
Cela reste un script d'ÉCRITURE directe : relire chaque entrée du fichier
d'opérations avant exécution, la voie normale pour les changements de La Régie
étant `apply_cli.py` (change-set + tiers + dry-run par défaut).

## Test de non-régression effectué

`ads_fetch.py --site monsite --days 7` exécuté avec succès depuis cette copie,
données live confirmées, aucune écriture sur le compte (uniquement des requêtes
`search_stream` en lecture et un JSON local en sortie).
