"""Commande ``mtlm`` — mêmes services que l'interface graphique.

Aucune commande n'écrit dans un dossier source. Les seules écritures ont lieu dans les
dossiers de l'application (base, sauvegardes, journaux) ou vers une destination choisie
par l'utilisateur (exports).

Codes de sortie : 0 succès, 1 erreur, 2 utilisation incorrecte ou confirmation manquante,
3 tâche annulée.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from mtlm import APP_NAME, ENGINE_VERSION, __version__
from mtlm.app.context import AppContext, open_app
from mtlm.app.inventory import FileFilter, InventoryService
from mtlm.app.jobs import JobStore
from mtlm.app.scan import ScanService, ScanSummary
from mtlm.app.sources import SourceService
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
EXIT_CANCELLED = 3


def human_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("o", "Kio", "Mio", "Gio"):
        if value < 1024 or unit == "Gio":
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} o"  # pragma: no cover


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mtlm", description=f"{APP_NAME} — ligne de commande.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMANDE")

    sub.add_parser("version", help="Affiche la version de l'application et du moteur.")
    sub.add_parser("init", help="Crée ou met à jour la base locale de l'application.")
    sub.add_parser("etat", help="État de la base, du journal d'audit et des sauvegardes.")

    save = sub.add_parser("sauvegarder", help="Crée une sauvegarde vérifiée de la base.")
    save.add_argument("--libelle", default="manuelle", help="Libellé ajouté au nom du fichier.")
    restore = sub.add_parser("restaurer", help="Remplace la base par une sauvegarde.")
    restore.add_argument("fichier", type=Path, help="Fichier de sauvegarde (.sqlite).")
    restore.add_argument("--confirmer", action="store_true", help="Confirmation obligatoire.")

    audit = sub.add_parser("audit", help="Journal d'audit.")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True, metavar="ACTION")
    audit_sub.add_parser("verifier", help="Vérifie l'intégrité de la chaîne du journal.")
    export = audit_sub.add_parser("exporter", help="Exporte le journal en JSON Lines.")
    export.add_argument("fichier", type=Path, help="Destination (ne doit pas exister).")

    source = sub.add_parser("source", help="Dossiers sources à analyser (lecture seule).")
    source_sub = source.add_subparsers(dest="source_command", required=True, metavar="ACTION")
    add = source_sub.add_parser("ajouter", help="Ajoute un dossier source (rien n'y est écrit).")
    add.add_argument("chemin", type=Path)
    add.add_argument("--nom", default=None, help="Nom affiché.")
    source_sub.add_parser("lister", help="Liste les sources.")
    remove = source_sub.add_parser(
        "retirer", help="Retire une source de l'application (aucun fichier supprimé)."
    )
    remove.add_argument("id", type=int)
    remove.add_argument("--confirmer", action="store_true", help="Confirmation obligatoire.")

    scan = sub.add_parser("scanner", help="Inventorie les sources en lecture seule.")
    scan.add_argument("ids", type=int, nargs="*", help="Sources à inventorier (toutes par défaut).")

    stats = sub.add_parser("inventaire", help="Statistiques de l'inventaire.")
    stats.add_argument("--source", type=int, default=None)

    files = sub.add_parser("fichiers", help="Liste paginée et filtrée des fichiers inventoriés.")
    files.add_argument("--source", type=int, default=None)
    files.add_argument("--ext", action="append", default=[], help="Extension (répétable).")
    files.add_argument("--recherche", default=None, help="Texte cherché dans le nom ou le chemin.")
    files.add_argument("--manquants", action="store_true", help="Fichiers disparus.")
    files.add_argument("--limite", type=int, default=50)
    files.add_argument("--apres", type=int, default=0, help="Identifiant de départ (pagination).")

    sub.add_parser("taches", help="Dernières tâches et leur état.")
    errors = sub.add_parser("erreurs", help="Erreurs d'une tâche d'inventaire.")
    errors.add_argument("tache", type=int)
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
        handlers = {
            "init": _init,
            "etat": _status,
            "sauvegarder": _save,
            "audit": _audit,
            "source": _source,
            "scanner": _scan,
            "inventaire": _inventory,
            "fichiers": _files,
            "taches": _jobs,
            "erreurs": _errors,
        }
        return handlers[args.command](args, ctx, out, err)


def _init(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    status = ctx.migrator.status()
    print(f"Base : {ctx.paths.database}", file=out)
    if ctx.applied_migrations:
        applied = ", ".join(str(v) for v in ctx.applied_migrations)
        print(f"Migrations appliquées : {applied}", file=out)
    else:
        print("Base déjà à jour, aucune migration appliquée.", file=out)
    print(f"Version du schéma : {status.current_version}/{status.latest_version}", file=out)
    return EXIT_OK


def _status(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
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


def _save(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    path = ctx.backup(args.libelle)
    ctx.journal.append(ACTOR_USER, "db.backup", str(path))
    print(f"Sauvegarde créée et vérifiée : {path}", file=out)
    return EXIT_OK


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
    count = ctx.journal.export_jsonl(args.fichier)
    ctx.journal.append(ACTOR_USER, "audit.export", str(args.fichier), details={"events": count})
    print(f"{count} événement(s) exporté(s) vers {args.fichier}", file=out)
    return EXIT_OK


def _sources(ctx: AppContext) -> SourceService:
    return SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)


def _source(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = _sources(ctx)
    if args.source_command == "ajouter":
        added = service.add(args.chemin, args.nom)
        print(f"Source n° {added.id} ajoutée : {added.path}", file=out)
        print(
            "Aucun fichier n'a été modifié. Lancez « mtlm scanner » pour l'inventorier.", file=out
        )
        return EXIT_OK
    if args.source_command == "lister":
        sources = service.list()
        if not sources:
            print(
                "Aucune source. Ajoutez un dossier avec « mtlm source ajouter CHEMIN ».", file=out
            )
        for s in sources:
            last = (
                f"dernier inventaire : tâche {s.last_scan_job_id}"
                if s.last_scan_job_id
                else "jamais inventoriée"
            )
            print(f"{s.id}\t{s.display_name}\t{s.status}\t{s.path}\t({last})", file=out)
        return EXIT_OK
    if not args.confirmer:
        print(
            "Retrait NON effectué : ajoutez --confirmer. Aucun fichier ne sera supprimé ; "
            "la source est seulement retirée de l'application.",
            file=err,
        )
        return EXIT_USAGE
    removed = service.remove(args.id)
    print(f"Source n° {removed.id} retirée de l'application (fichiers intacts).", file=out)
    return EXIT_OK


def _print_summary(summary: ScanSummary, out: TextIO) -> None:
    state = {"completed": "terminé", "cancelled": "annulé", "failed": "échec"}.get(
        summary.state, summary.state
    )
    print(
        f"Inventaire de la source {summary.source_id} {state} (tâche {summary.job_id}) : "
        f"{summary.seen} fichier(s) vu(s) — {summary.new} nouveau(x), {summary.changed} "
        f"modifié(s), {summary.unchanged} inchangé(s), {summary.missing} disparu(s), "
        f"{summary.errors} erreur(s), {summary.symlinks} lien(s) non suivi(s), "
        f"{summary.cycles_skipped} cycle(s) évité(s), {summary.directories} dossier(s).",
        file=out,
    )


def _scan(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    sources = _sources(ctx).list()
    ids = args.ids or [s.id for s in sources]
    if not ids:
        print("Aucune source à inventorier. Ajoutez d'abord un dossier.", file=err)
        return EXIT_USAGE
    service = ScanService(ctx.conn, ctx.clock, ctx.journal)
    code = EXIT_OK
    for source_id in ids:
        try:
            summary = service.scan(source_id)
        except MtlmError as exc:
            print(f"Erreur : {exc}", file=err)
            code = EXIT_ERROR
            continue
        _print_summary(summary, out)
        if summary.errors:
            print(f"  Détail des erreurs : mtlm erreurs {summary.job_id}", file=out)
    return code


def _inventory(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    stats = InventoryService(ctx.conn).stats(args.source)
    print(f"Fichiers présents : {stats.files} ({human_size(stats.total_bytes)})", file=out)
    print(f"Fichiers disparus depuis le dernier inventaire : {stats.missing}", file=out)
    print(f"Liens symboliques (non suivis) : {stats.symlinks}", file=out)
    print("Par extension :", file=out)
    for ext, n in stats.by_extension.items():
        print(f"  {ext}\t{n}", file=out)
    print("Empreintes :", file=out)
    for state, n in stats.by_hash_state.items():
        print(f"  {state}\t{n}", file=out)
    return EXIT_OK


def _files(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    flt = FileFilter(
        source_id=args.source,
        extensions=tuple(args.ext),
        presence="missing" if args.manquants else "present",
        text=args.recherche,
    )
    service = InventoryService(ctx.conn)
    rows = service.page(flt, after_id=args.apres, limit=max(1, min(args.limite, 10_000)))
    total = service.count(flt)
    for row in rows:
        print(
            f"{row.id}\t{row.ext or '-'}\t{human_size(row.size)}\t{row.hash_state}\t{row.rel_path}",
            file=out,
        )
    print(f"{len(rows)} affiché(s) sur {total}.", file=out)
    if rows and len(rows) == args.limite:
        print(f"Suite : ajoutez --apres {rows[-1].id}", file=out)
    return EXIT_OK


def _jobs(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    jobs = JobStore(ctx.conn, ctx.clock).recent()
    if not jobs:
        print("Aucune tâche.", file=out)
    for job in jobs:
        print(
            f"{job.id}\t{job.kind}\t{job.state}\t{job.progress_done} traité(s)\t"
            f"{job.errors_count} erreur(s)\t{job.created_at}",
            file=out,
        )
    return EXIT_OK


def _errors(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = InventoryService(ctx.conn).errors(args.tache)
    if not rows:
        print(f"Aucune erreur pour la tâche {args.tache}.", file=out)
    for row in rows:
        print(f"{row.rel_path or '(racine)'}\t{row.message}", file=out)
    return EXIT_OK


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
