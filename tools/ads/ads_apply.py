#!/usr/bin/env python3
"""
Google Ads : couche d'application des change-sets de La Régie.

Ce module généralise la logique d'écriture existante de ads_keyword_ops.py :
au lieu d'opérations codées en dur, il consomme un change-set (liste d'items
JSON) déjà passé par les gates de validation (audit -> plan -> Gate 2), et
applique chaque item selon son tier :

  - tier 1            : réversible, appliqué automatiquement (pause de mot-clé,
                         négatif exact, exclusion, etc.).
  - tier 2 ou 3        : nécessite une approbation humaine explicite et stricte
                         (item["approved"] is True, booléen strict). Sans
                         approbation, l'item est sauté avec la raison
                         "tier{n}_not_approved".
  - tier 4             : interdit (portée réglementaire, ex. allégations
                         restreintes). Toujours sauté, même si approved est
                         True, avec la raison "tier4_forbidden".

Principe directeur (fail-safe) : dans le doute, on n'applique jamais. Un item
sans "tier" valide (1 à 4), sans "type" reconnu, ou dont l'approbation n'est
pas un booléen strict True n'est jamais appliqué : il part en skipped/errors
avec une raison explicite, et le traitement des items suivants du change-set
continue normalement (un item malformé ne doit jamais faire planter la
fonction ni faire perdre les items déjà traités).

Le change-set peut porter des champs de métadonnées supplémentaires (id,
preuve, agent source pm-buyer/pm-tracking/pm-feed, etc.) : apply_changeset ne
se base que sur "type", "tier", "approved" et les champs propres au type. Tout
champ de métadonnée inconnu est ignoré proprement, sans jamais faire échouer
le traitement (à ne pas confondre avec le champ "type" de l'item lui-même,
qui doit être reconnu par la gate).

IMPORTANT : dry_run=True par défaut. En dry_run, aucun appel réseau n'est
effectué : chaque item applicable est simulé et journalisé. L'écriture réelle
(dry_run=False) n'est PAS encore câblée : tant que l'intégration réelle
(pause_keyword, update_cpc_bid de ads_keyword_ops.py) n'a pas été branchée au
rodage du client pilote (après GO explicite de l'opérateur), tout appel en dry_run=False lève
une erreur explicite plutôt que de simuler un succès. Un faux positif ("item
marqué appliqué" sans écriture réelle) serait pire qu'une erreur bruyante.
"""

import os
import sys
from dataclasses import dataclass, field

# Réutilise la logique d'écriture existante (pause de mot-clé, ajustement CPC)
# plutôt que de la redupliquer. Import local, tolérant à l'absence du package
# google-ads (utile en environnement de test où dry_run seul est exercé).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import ads_keyword_ops
except ImportError:
    ads_keyword_ops = None


# Types d'items qui seront gérés par écriture réelle via ads_keyword_ops.py
# une fois le câblage effectué (Task 11). Tant que ce câblage n'existe pas,
# ces types (comme tous les autres) lèvent une erreur explicite en
# dry_run=False plutôt que de simuler un succès.
KEYWORD_OPS_TYPES = {"negative_exact", "negative_phrase", "exclusion", "pause_keyword"}

# Types de "type" reconnus par la gate. Un item dont le champ "type" est
# absent ou ne figure pas dans cet ensemble n'est jamais appliqué (fail-safe) :
# il part en skipped avec la raison "type_unknown". À compléter explicitement
# au fil de la généralisation (nouveaux types pm-buyer/pm-tracking/pm-feed).
RECOGNIZED_TYPES = KEYWORD_OPS_TYPES | {"budget_change", "restricted_claim"}


@dataclass
class ApplyResult:
    """Résultat de l'application d'un change-set."""
    applied: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _tier_of(item: dict):
    """Extrait le tier d'un item sous forme d'entier valide (1 à 4).

    Retourne None si le champ "tier" est absent, ou si sa valeur n'est pas
    convertible en un entier compris entre 1 et 4 (valeur nulle, chaîne non
    numérique, booléen, valeur hors bornes, etc.). Comportement
    volontairement restrictif (fail-safe) : un tier absent ou invalide ne
    doit jamais être traité par défaut comme un tier 1 applicable.
    """
    if "tier" not in item:
        return None

    raw = item.get("tier")

    if isinstance(raw, bool):
        # Un booléen n'est pas un tier valide, même si bool est techniquement
        # une sous-classe d'int en Python.
        return None

    try:
        tier = int(raw)
    except (TypeError, ValueError):
        return None

    if tier not in (1, 2, 3, 4):
        return None

    return tier


def _decide(item: dict):
    """Détermine si un item doit être appliqué ou sauté, et pourquoi.

    Ne lève jamais d'exception : un item malformé (type absent/inconnu,
    tier absent/invalide, approbation non booléenne) est toujours renvoyé
    comme non applicable avec une raison explicite, jamais comme une erreur
    non gérée qui romprait la boucle d'application.

    Retourne un tuple (applicable: bool, reason: str ou None).
    """
    item_type = item.get("type") if isinstance(item, dict) else None

    if item_type not in RECOGNIZED_TYPES:
        return False, "type_unknown"

    tier = _tier_of(item)
    if tier is None:
        if "tier" not in item:
            return False, "tier_missing_blocked"
        return False, "tier_invalid_blocked"

    # Approbation reconnue uniquement si "approved" est le booléen strict
    # True. Une chaîne ("true", "false"), un entier ou toute autre valeur ne
    # neutralise jamais la gate (bool("false") vaut True en Python : piège
    # évité volontairement en comparant à "is True").
    approved = item.get("approved") is True

    if tier == 4:
        return False, "tier4_forbidden"

    if tier >= 2 and not approved:
        return False, f"tier{tier}_not_approved"

    # tier == 1, ou tier in (2, 3) et approuvé strictement
    return True, None


# Cache du contexte live (GoogleAdsClient + customer_id) par site, pour ne pas
# reconstruire le client a chaque item d'un meme change-set.
_LIVE_CTX = {}

# Types dont l'ecriture reelle est CABLEE (rodage du client pilote). Les autres
# types restent volontairement non cables et levent une erreur explicite plutot
# que de simuler un succes : l'edition RSA, le dayparting, l'ajout de mot-cle,
# la pause d'ad group et l'exclusion produit (listing group) passent par une
# execution manuelle ou une generalisation ulterieure de cette couche.
LIVE_WIRED_TYPES = {"negative_exact", "negative_phrase"}


def _live_ctx(site):
    """Retourne (client, customer_id) pour un site, mis en cache."""
    if site not in _LIVE_CTX:
        if ads_keyword_ops is None:
            raise NotImplementedError(
                "live_apply_unavailable : package google-ads absent, ecriture reelle impossible."
            )
        _LIVE_CTX[site] = ads_keyword_ops.get_client_and_customer(site)
    return _LIVE_CTX[site]


def _apply_item(client, item: dict, dry_run: bool) -> dict:
    """Applique un item individuel (simulé en dry_run, ecrit reellement sinon).

    En dry_run, chaque item applicable est simulé et journalisé, aucun appel
    reseau. En dry_run=False, seuls les types de LIVE_WIRED_TYPES sont ecrits
    reellement (aujourd'hui les negatifs de campagne, via ads_keyword_ops.py) ;
    tout autre type leve une erreur explicite plutot que de simuler un succes
    (un faux positif serait pire qu'une erreur bruyante).
    """
    item_type = item.get("type")
    label = client if isinstance(client, str) else "compte"

    if dry_run:
        print(f"  [DRY-RUN] {label} : application simulée : {item_type} : {item}")
        return item

    # --- Ecriture reelle ---
    site = client if isinstance(client, str) else None
    if not site:
        raise ValueError("live_apply_requires_site : passer le nom du site (str) comme premier argument en ecriture reelle.")

    if item_type in ("negative_exact", "negative_phrase"):
        ga_client, customer_id = _live_ctx(site)
        campaign_id = item.get("campaign_id")
        text = item.get("text")
        if not campaign_id or not text:
            raise ValueError(f"live_apply_missing_field : campaign_id et text requis pour {item_type} (item {item.get('id')}).")
        default_mt = "EXACT" if item_type == "negative_exact" else "PHRASE"
        match_type = item.get("match_type") or default_mt
        resource_name = ads_keyword_ops.add_campaign_negative(
            ga_client, customer_id, str(campaign_id), text, match_type
        )
        print(f"  [LIVE] {label} : negatif ajoute : '{text}' ({match_type}) sur campagne {campaign_id} -> {resource_name}")
        return {**item, "applied_resource_name": resource_name}

    raise NotImplementedError(
        f"live_apply_not_wired : ecriture reelle non cablee pour le type "
        f"'{item_type}' (item {item.get('id')}). Execution manuelle ou generalisation requise."
    )


def apply_changeset(client, changeset, dry_run: bool = True) -> ApplyResult:
    """Applique un change-set derrière les gates de tier.

    Args:
        client: identifiant ou client Google Ads (nom de site, ou instance
            GoogleAdsClient une fois le rodage câblé). Non utilisé en
            dry_run au-delà de la journalisation.
        changeset: liste d'items (dict) à évaluer et appliquer. Chaque item
            doit porter un "type" reconnu et un "tier" valide (1 à 4) pour
            être éligible ; "approved" est optionnel (défaut non approuvé).
            Tout champ de métadonnée supplémentaire est ignoré proprement.
        dry_run: si True (défaut), aucune écriture réelle n'est effectuée :
            chaque item applicable est simulé et journalisé. Si False,
            lève une erreur explicite tant que l'écriture réelle n'a pas
            été câblée (Task 11) plutôt que de simuler un succès.

    Returns:
        ApplyResult avec applied (items appliqués ou simulés), skipped
        (liste de dicts {"item": ..., "reason": ...}) et errors (liste de
        dicts {"item": ..., "error": ...} rencontrés pendant l'application).

    Comportement fail-safe : un item malformé (tier absent/invalide, type
    non reconnu, décision impossible à déterminer) n'est jamais appliqué et
    ne fait jamais planter la fonction. Il part en skipped ou en errors avec
    une raison explicite, et le traitement continue sur les items suivants.
    """
    result = ApplyResult()

    for item in changeset:
        try:
            applicable, reason = _decide(item)
        except Exception as exc:
            # Filet de sécurité supplémentaire : même si _decide est conçu
            # pour ne jamais lever, un item totalement malformé (ex. pas un
            # dict) ne doit jamais interrompre la boucle ni être appliqué.
            result.errors.append({"item": item, "error": f"decision_error : {exc}"})
            continue

        if not applicable:
            result.skipped.append({"item": item, "reason": reason})
            continue

        try:
            applied_item = _apply_item(client, item, dry_run)
            result.applied.append(applied_item)
        except Exception as exc:
            result.errors.append({"item": item, "error": str(exc)})

    return result
