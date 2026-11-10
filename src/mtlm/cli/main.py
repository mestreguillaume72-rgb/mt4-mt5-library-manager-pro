"""Commande ``mtlm`` — socle (Phase 1).

Toutes les commandes ne touchent qu'aux dossiers propres à l'application
(base, sauvegardes, journaux). Aucune n'accède à un dossier source.

Codes de sortie : 0 succès, 1 erreur, 2 utilisation incorrecte ou confirmation manquante.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from mtlm import APP_NAME, ENGINE_VERSION, __version__
from mtlm.app.context import AppContext, open_app
from mtlm.audit.journal import ACTOR_USER
from mtlm.audit.logs import setup_logging, shutdown_logging
from mtlm.core.clock import Clock, SystemClock
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths, default_paths
from mtlm.store.backup import BACKUP_SUFFIX, restore_database
from mtlm.store.database import integrity_ok
from mtlm.store.migrations_engine import packaged_migrations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mtlm",
        description=f"{APP_NAME} — outil en ligne de commande (socle).",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMANDE")

    sub.add_parser("version", help="Affiche la version de l'application et du moteur.")
    sub.add_parser("init", help="Crée ou met à jour la base locale de l'application.")
    sub.add_parser("etat", help="Affiche l'état de la base, du journal d'audit et des sauvegardes.")

    save = sub.add_parser("sauvegarder", help="Crée une sauvegarde vérifiée de la base.")
    save.add_argument("--libelle", default="manuelle", help="Libellé ajouté au nom du fichier.")

    restore = sub.add_parser(
        "restaurer",
        help="Remplace la base par une sauvegarde (la base actuelle est d'abord sauvegardée).",
    )
    restore.add_argument("fichier", type=Path, help="Fichier de sauvegarde (.sqlite).")
    restore.add_argument(
        "--confirmer",
        action="store_true",
        help="Confirmation explicite obligatoire : sans elle, rien n'est modifié.",
    )

    audit = sub.add_parser("audit", help="Journal d'audit.")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True, metavar="ACTION")
    audit_sub.add_parser("verifier", help="Vérifie l'intégrité de la chaîne du journal d'audit.")
    export = audit_sub.add_parser("exporter", help="Exporte le journal en JSON Lines.")
    export.add_argument("fichier", type=Path, help="Fichier de destination (ne doit pas exister).")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
    clock: Clock | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stdout = out or sys.stdout
    stderr = err or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse : --help (0) ou erreur d'usage (2)
        return int(exc.code or 0)

    paths = default_paths(environ)
    used_clock = clock or SystemClock()
    try:
        return _dispatch(args, paths, used_clock, stdout, stderr)
    except MtlmError as exc:
        print(f"Erreur : {exc}", file=stderr)
        return EXIT_ERROR
    finally:
        shutdown_logging()


def _dispatch(
    args: argparse.Namespace, paths: AppPaths, clock: Clock, out: TextIO, err: TextIO
) -> int:
    if args.command == "version":
        print(f"{APP_NAME} {__version__} (moteur {ENGINE_VERSION})", file=out)
        return EXIT_OK
    if args.command == "restaurer":
        return _restore(args, paths, clock, out, err)

    with open_app(paths, clock) as ctx:
        if args.command == "init":
            return _init(ctx, out)
        if args.command == "etat":
            return _status(ctx, out)
        if args.command == "sauvegarder":
            path = ctx.backup(args.libelle)
            ctx.journal.append(ACTOR_USER, "db.backup", str(path))
            print(f"Sauvegarde créée et vérifiée : {path}", file=out)
            return EXIT_OK
        if args.command == "audit":
            return _audit(args, ctx, out, err)
    raise AssertionError(f"commande non gérée : {args.command}")  # pragma: no cover


def _init(ctx: AppContext, out: TextIO) -> int:
    status = ctx.migrator.status()
    print(f"Base : {ctx.paths.database}", file=out)
    if ctx.applied_migrations:
        applied = ", ".join(str(v) for v in ctx.applied_migrations)
        print(f"Migrations appliquées : {applied}", file=out)
    else:
        print("Base déjà à jour, aucune migration appliquée.", file=out)
    print(f"Version du schéma : {status.current_version}/{status.latest_version}", file=out)
    return EXIT_OK


def _status(ctx: AppContext, out: TextIO) -> int:
    status = ctx.migrator.status()
    verification = ctx.journal.verify()
    backups = sorted(ctx.paths.backups_dir.glob(f"*{BACKUP_SUFFIX}"))
    healthy = integrity_ok(ctx.conn)
    print(f"Application : {__version__} (moteur {ENGINE_VERSION})", file=out)
    print(f"Base : {ctx.paths.database}", file=out)
    print(f"Version du schéma : {status.current_version}/{status.latest_version}", file=out)
    print(f"Intégrité de la base : {'OK' if healthy else 'ERREUR'}", file=out)
    chain = "OK" if verification.ok else f"ERREUR ({verification.reason})"
    print(f"Journal d'audit : {ctx.journal.count()} événement(s), chaîne {chain}", file=out)
    print(f"Sauvegardes : {len(backups)} dans {ctx.paths.backups_dir}", file=out)
    print(f"Journal technique : {ctx.log_file}", file=out)
    return EXIT_OK if healthy and verification.ok else EXIT_ERROR


def _audit(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    if args.audit_command == "verifier":
        result = ctx.journal.verify()
        if result.ok:
            print(f"Journal d'audit intact : {result.checked} événement(s) vérifié(s).", file=out)
            return EXIT_OK
        print(
            f"Journal d'audit ALTÉRÉ à l'événement {result.first_invalid_id} : {result.reason}",
            file=err,
        )
        return EXIT_ERROR
    if args.audit_command == "exporter":
        count = ctx.journal.export_jsonl(args.fichier)
        ctx.journal.append(ACTOR_USER, "audit.export", str(args.fichier), details={"events": count})
        print(f"{count} événement(s) exporté(s) vers {args.fichier}", file=out)
        return EXIT_OK
    raise AssertionError(f"action non gérée : {args.audit_command}")  # pragma: no cover


def _restore(
    args: argparse.Namespace, paths: AppPaths, clock: Clock, out: TextIO, err: TextIO
) -> int:
    if not args.confirmer:
        print(
            "Restauration NON effectuée : ajoutez --confirmer pour remplacer la base actuelle.\n"
            "La base actuelle sera d'abord sauvegardée automatiquement.",
            file=err,
        )
        return EXIT_USAGE
    paths.ensure()
    setup_logging(paths.logs_dir)
    latest = packaged_migrations()[-1].version
    safety = restore_database(args.fichier, paths.database, paths.backups_dir, clock, latest)
    with open_app(paths, clock) as ctx:
        ctx.journal.append(
            ACTOR_USER,
            "db.restore",
            str(args.fichier),
            details={"sauvegarde_de_securite": str(safety) if safety else None},
        )
    if safety:
        print(f"Base actuelle sauvegardée avant restauration : {safety}", file=out)
    print(f"Base restaurée depuis : {args.fichier}", file=out)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
