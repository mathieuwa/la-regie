# Onboarding d'un nouveau compte Google Ads sur La Régie

Procédure pour brancher un nouveau client (exemple à venir : un domaine viticole)
sur la chaîne La Régie (`/regie`, agents pm-*, scripts `tools/ads/`).
Basée sur le code réel : `ads_fetch.py`, `apply_cli.py`, `.claude/commands/regie.md`
et la configuration partagée de `tools/seo-audit/`.

## Vue d'ensemble

Toute la configuration vit dans `tools/seo-audit/` (source unique, pas de
duplication de secrets) :

- `tools/seo-audit/sites.json` : registre des sites et de leurs identifiants
  (Ads, GA4, GSC, GTM). Tous les scripts `tools/ads/*.py` résolvent le client
  par `--site {name}` dans ce fichier.
- `tools/seo-audit/google-ads.yaml` : credentials API Google Ads
  (`developer_token`, `client_id`, `client_secret`, `refresh_token`,
  `use_proto_plus`). Un seul jeu pour tous les clients.
- `tools/seo-audit/ads-token.json` : token OAuth2 (généré par `ads_auth.py`).
- Venv Python : `tools/seo-audit/venv/bin/python3` (dépendances `google-ads`,
  `pyyaml`). Il n'y a pas de venv dans `tools/ads/`.

Aucun script ne porte de constante client : un compte qui n'est pas dans
`sites.json` est tout simplement inaccessible aux scripts. C'est le garde-fou.

## Étape 1 : entrée dans sites.json

Ajouter un objet au tableau `sites` de `tools/seo-audit/sites.json`
(faire un backup du fichier avant édition) :

```json
{
  "name": "domaine-x",
  "url": "https://www.domaine-x.fr",
  "gsc_url": "sc-domain:domaine-x.fr",
  "ga4_measurement_id": "G-XXXXXXXXXX",
  "ga4_property_id": "123456789",
  "gtm_id": "GTM-XXXXXXX",
  "ads_customer_id": "123-456-7890",
  "ads_conversion_id": "AW-XXXXXXXXX",
  "reports": ["seo", "ads"],
  "report_dir": "clients/domaine-x/livrables/Rapports"
}
```

Points d'attention :

- `name` : identifiant court, sans espace ni accent. C'est la valeur passée à
  `--site` partout, et le nom des dossiers `data/{name}/` et
  `clients/{name}/ads/`. Le choisir une fois et ne plus le changer.
- `ads_customer_id` : l'ID client Google Ads (avec ou sans tirets, les scripts
  normalisent). C'est LE champ qui détermine sur quel compte on lit et on
  écrit : le vérifier deux fois.
- Les champs GA4/GSC/GTM peuvent être remplis plus tard si le périmètre est
  Ads seul, mais `ads_customer_id` est indispensable dès le départ.

## Étape 2 : accès API au compte (MCC)

Le `google-ads.yaml` partagé authentifie un seul utilisateur OAuth (le compte
Google de Matt) avec un seul developer token. Pour qu'un nouveau
`ads_customer_id` soit interrogeable :

1. Le compte client doit être accessible par cet utilisateur : soit un accès
   direct au compte Ads, soit un rattachement au MCC depuis lequel les autres
   clients sont gérés (invitation depuis le MCC, acceptation côté client).
2. Le yaml actuel ne contient PAS de `login_customer_id`. Si le nouveau compte
   n'est accessible QUE via le MCC (pas d'accès direct), l'API exigera
   l'en-tête `login_customer_id: {id du MCC}` dans `google-ads.yaml`.
   Attention : ce fichier est partagé par tous les clients, tester que les
   comptes déjà configurés répondent toujours après modification.
3. Aucune régénération de token n'est nécessaire pour ajouter un compte :
   le scope OAuth `adwords` couvre tous les comptes accessibles par
   l'utilisateur. `ads_auth.py` ne sert que si le token est perdu ou révoqué.

## Étape 3 : ping de validation

Test de bout en bout (config + accès + customer id), en lecture seule :

```bash
cd tools/ads
../seo-audit/venv/bin/python3 ads_fetch.py --site domaine-x --days 1
```

- Succès attendu : un JSON écrit dans `data/domaine-x/{YYYY-MM}/ads.json`
  avec le résumé des campagnes. Même un compte sans campagne active doit
  répondre proprement (summary à zéro).
- `Site 'domaine-x' inconnu dans sites.json` : étape 1 incomplète ou faute de
  frappe sur `name`.
- Erreur `USER_PERMISSION_DENIED` ou `CUSTOMER_NOT_FOUND` : étape 2 incomplète
  (accès MCC pas encore effectif, ou `ads_customer_id` erroné).
- Ce ping ne fait AUCUNE écriture : uniquement des `search_stream` en lecture.

## Étape 4 : ouverture du dossier La Régie

Lancer la phase 0 du pipeline :

```
/regie dossier domaine-x
```

Cette phase crée `clients/domaine-x/ads/` et ses sous-dossiers (`dossier/`,
`fetch/`, `audit/`, `plan/`, `qc/`, `reports/`, `logs/`), initialise
`pipeline-state.json`, et rédige `dossier/client-dossier.md` : secteur,
réglementation applicable (pour un domaine viticole : encadrement de la
publicité pour l'alcool, loi Évin, mentions obligatoires, ciblage d'âge, à
nommer explicitement pour cadrer le Tier 4), modèle économique, landing pages,
concurrents. Ce dossier cadre tous les agents pm-* du pipeline.

Ensuite le cycle normal : `/regie fetch`, `/regie audit`, `/regie plan`, gates,
etc. Rappels de sécurité valables pour tout nouveau client :

- L'application passe par `apply_cli.py` (change-set + tiers), dry-run par
  défaut ; `--live` seulement après GO explicite de Matt.
- `ads_keyword_ops.py` (écriture directe) exige un `--ops-file` JSON par
  intervention : aucune liste de mots-clés n'est codée en dur. Modèle :
  `tools/ads/examples/keyword-ops.example.json`.

## Point "source de CA" (clients sans WooCommerce)

Le rapport de `pm-analyst` (phase report de `/regie`) croise par défaut les
données Ads avec le CA WooCommerce RÉEL du client (jamais le revenu GA4).
Ce n'est pas un paramètre de script : c'est une convention du pipeline.

Pour un client SANS WooCommerce (cas du domaine viticole si la vente passe par
un autre canal), il faut définir la source de vérité du chiffre d'affaires
dans `clients/{name}/CLAUDE.md` avant le premier cycle report : quel système
fait foi (autre e-commerce, caisse, CRM, export manuel), comment y accéder, et
à quelle granularité. `pm-analyst` lit le contexte client et s'y conforme ;
sans cette définition, le rapport ne doit pas inventer un CA à partir de GA4.

## Checklist récapitulative

1. [ ] Backup puis ajout de l'entrée dans `tools/seo-audit/sites.json`
   (`name` + `ads_customer_id` au minimum).
2. [ ] Accès API vérifié : compte rattaché au MCC ou accès direct ;
   `login_customer_id` ajouté au yaml si nécessaire (et non-régression des comptes déjà configurés).
3. [ ] Ping : `tools/seo-audit/venv/bin/python3 tools/ads/ads_fetch.py
   --site {name} --days 1` écrit un `data/{name}/{mois}/ads.json` valide.
4. [ ] `/regie dossier {name}` : dossier d'intelligence client rédigé,
   réglementation sectorielle nommée (cadre le Tier 4).
5. [ ] Source de CA définie dans `clients/{name}/CLAUDE.md` si le client
   n'a pas de WooCommerce.
