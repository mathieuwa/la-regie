#!/usr/bin/env python3
"""
Google Ads : point d'entrée CLI de la couche d'application de La Régie.

Pont exécutable entre le contrat de fichier `changeset-approved.json` (produit
par la commande /regie apres la Gate 2) et la fonction `apply_changeset` de
`ads_apply.py`. La commande /regie n'appelle jamais Python inline en Bash : elle
invoque ce script par son chemin, ce qui evite le garde-fou "code/JSON inline"
et garde une invocation stable, allowlist-friendly.

Principe fail-safe herite de ads_apply.py : dry_run par defaut. L'ecriture
reelle (--live) n'est pas encore cablee (Task 11) et remonte chaque item
applicable en erreur explicite plutot que de simuler un succes. Ce CLI ne
decide donc jamais du tier ni de l'approbation : il se contente de charger le
change-set deja valide et de journaliser le resultat.

Usage :
  python3 apply_cli.py --site monsite \
      --changeset clients/monsite/ads/plan/changeset-approved.json \
      --out clients/monsite/ads/logs/change-log-2026-07.json
  # ajouter --live UNIQUEMENT au rodage du client pilote, apres GO explicite de Matt.

Sortie : ecrit un change-log JSON (applied / skipped / errors + metadonnees)
et imprime une synthese lisible sur STDOUT. Code de sortie 0 si le run s'est
deroule (meme avec des items skipped/errors, qui sont un resultat legitime),
1 uniquement en cas d'echec de chargement (fichier ou JSON invalide).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ads_apply import apply_changeset


def _load_changeset(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Le contrat accepte soit une liste d'items directement, soit un objet
    # enveloppe {"items": [...]} : on normalise vers la liste attendue par
    # apply_changeset.
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    else:
        items = data
    if not isinstance(items, list):
        raise ValueError(
            "change-set invalide : attendu une liste d'items (ou un objet "
            "{'items': [...]}), recu " + type(items).__name__
        )
    return items


def main():
    parser = argparse.ArgumentParser(
        description="Applique un change-set Google Ads valide derriere les gates de tier."
    )
    parser.add_argument("--site", required=True, help="Identifiant du site/client (ex. monsite).")
    parser.add_argument(
        "--changeset", required=True,
        help="Chemin du change-set valide (changeset-approved.json).",
    )
    parser.add_argument(
        "--out", required=True,
        help="Chemin du change-log JSON a ecrire.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Ecriture reelle (dry_run=False). Reserve au rodage du client pilote, apres GO explicite de l'operateur. "
             "Tant que le cablage reel n'existe pas, chaque item applicable remonte en erreur.",
    )
    args = parser.parse_args()

    try:
        changeset = _load_changeset(args.changeset)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERREUR chargement change-set : {exc}", file=sys.stderr)
        return 1

    dry_run = not args.live
    result = apply_changeset(args.site, changeset, dry_run=dry_run)

    change_log = {
        "site": args.site,
        "changeset_path": os.path.abspath(args.changeset),
        "dry_run": dry_run,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "applied": result.applied,
        "skipped": result.skipped,
        "errors": result.errors,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(change_log, fh, ensure_ascii=False, indent=2)

    mode = "DRY-RUN (simulation)" if dry_run else "LIVE (ecriture reelle)"
    print(f"Mode : {mode}")
    print(f"Site : {args.site}")
    print(f"Change-set : {args.changeset} ({len(changeset)} item(s))")
    print(f"  applied : {len(result.applied)}")
    print(f"  skipped : {len(result.skipped)}")
    for s in result.skipped:
        item_id = s.get("item", {}).get("id") if isinstance(s.get("item"), dict) else None
        print(f"    - {item_id or '?'} : {s.get('reason')}")
    print(f"  errors  : {len(result.errors)}")
    for e in result.errors:
        item_id = e.get("item", {}).get("id") if isinstance(e.get("item"), dict) else None
        print(f"    - {item_id or '?'} : {e.get('error')}")
    print(f"Change-log ecrit : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
