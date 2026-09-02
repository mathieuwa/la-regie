# Installer La Régie (Mac)

## Prérequis (à faire une fois, hors Claude)
1. Claude Code installé et connecté (abonnement Claude).
2. Codex CLI installé et connecté à votre abonnement ChatGPT (`codex --version`
   doit répondre, 0.137 minimum) : sert à générer les images.
3. Connecteur Canva activé sur votre compte claude.ai (Paramètres, Connecteurs) :
   sert au montage des visuels.
4. Python 3.12 ou plus récent (`python3 --version`).

## Installation
Ouvrez un terminal DANS ce dossier, lancez `claude`, et dites-lui :
« installe la régie ». Claude détecte ce qui manque et déroule tout avec vous
(Bloc 0 machine de `/regie onboard` : création du venv Python à `tools/seo-audit/venv`,
installation des dépendances, gabarits de config), questionnaire d'onboarding client
compris (`/regie onboard`).

Les clés API (Google Ads notamment) sont OPTIONNELLES : tout ce qui n'est pas
câblé reste dormant et s'active plus tard en relançant `/regie onboard {client}`.
Vos clés se collent à la main dans les fichiers de config (Claude vous guide,
il ne les manipule jamais).

## Vérification post-installation
Déroulez ce parcours et notez toute friction :
1. `/regie onboard {votre-domaine}` terminé, carte de capacités créée.
2. `/social brief {votre-domaine}` : un brief se génère jusqu'à la Gate 1.
3. Une image de test générée par Codex arrive dans le dossier du client.
Frictions et questions : envoyez-les à Matt, elles font la version suivante.
