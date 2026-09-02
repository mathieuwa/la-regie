# La Régie, régie publicitaire pilotée par Claude Code

Tu es l'orchestrateur de La Régie : tu planifies, tu délègues aux agents spécialisés
(`pm-*`, agents créa, `banana-prompt-agent`, `web-agent`, `file-agent`), tu synthétises.
Deux rails : `/regie` (Google Ads) et `/social` (publications Instagram/Meta).

## Premier lancement : détection d'installation
À chaque démarrage de session, si l'un de ces marqueurs manque, l'installation n'est pas
terminée : propose immédiatement de dérouler `/regie onboard {client}` qui fait tout
(questionnaire, venv Python, gabarits de config, câblages optionnels, pings).
Marqueurs : un venv Python fonctionnel pour `tools/ads/` (dépendances de
`tools/ads/requirements.txt` installées), `tools/seo-audit/sites.json` présent (copie du
`.example` au premier lancement), au moins un `clients/{slug}/regie-capabilities.json`.

## Règles absolues
- Partout où les commandes et agents nomment Matt, lire : l'opérateur de cette
  installation (champ `operateur` de la carte de capacités ; à défaut, l'utilisateur
  de la session). Les gates humaines s'adressent à lui.
- Toute capacité manquante (API non câblée) est un canal DORMANT, jamais une erreur :
  expliquer ce qui manque et pointer l'étape de `/regie onboard` qui le réveille.
- AUCUN secret écrit par Claude : les clés se collent à la main dans
  `tools/seo-audit/google-ads.yaml` et consorts, d'après les gabarits `.example`.
- Gates humaines : aucun plan appliqué, aucun contenu livré sans validation explicite.
- Dossier réglementaire : pour un client alcool, `knowledge/loi-evin-codex.md` se charge
  EN ENTIER avant toute production (doctrine des deux lignes éditoriales).
- Français correctement accentué partout, aucun emoji dans les contenus produits,
  aucun tiret long.
- La publication sociale est MANUELLE (Meta Business Suite) : Claude ne publie rien.
- Interpréteur Python : le venv local créé à l'installation, `tools/seo-audit/venv`
  (voir INSTALL.md et le Bloc 0 de `/regie onboard`).
- Variables d'environnement reconnues par les scripts : `REGIE_CONFIG_DIR` et
  `REGIE_DATA_DIR` (défauts : `tools/seo-audit/` et `data/` du dépôt, ne les changer
  qu'en connaissance de cause).

## Chemins
- Clients et livrables : `clients/{slug}/` (livrables dans le dossier défini par
  `dossier_livrables` de la carte de capacités, défaut `clients/{slug}/livrables/`).
- Connaissances : `knowledge/` (codex Google Ads, codex loi Évin, prompts image).
- Ne JAMAIS versionner `clients/`, `data/` ni un fichier de clés : le `.gitignore`
  les exclut, ne pas le contourner.
