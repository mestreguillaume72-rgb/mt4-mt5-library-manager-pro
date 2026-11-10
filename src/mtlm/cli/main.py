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
from mtlm.app.duplicates import DuplicateService
from mtlm.app.families import FamilyService
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.inventory import FileFilter, InventoryService, analysis_of
from mtlm.app.jobs import JobStore
from mtlm.app.organize import OrganizeService
from mtlm.app.pipeline import STEPS, run_steps
from mtlm.app.quarantine import QuarantineService
from mtlm.app.recognize import RecognitionService
from mtlm.app.reports import KINDS, ReportService
from mtlm.app.scan import ScanService, ScanSummary
from mtlm.app.sets import LEVEL_LABELS, AssociationService, SetService
from mtlm.app.settings import SPECS, SettingsService
from mtlm.app.sources import SourceService
from mtlm.audit.journal import ACTOR_USER
from mtlm.audit.logs import setup_logging, shutdown_logging
from mtlm.core.clock import Clock, SystemClock
from mtlm.core.control import TaskControl
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
    files.add_argument("--type", default=None, help="Type reconnu (ea, indicator, script, set…).")
    files.add_argument("--plateforme", choices=["mt4", "mt5", "unknown"], default=None)
    files.add_argument("--limite", type=int, default=50)
    files.add_argument("--apres", type=int, default=0, help="Identifiant de départ (pagination).")

    hashes = sub.add_parser("empreintes", help="Calcule les empreintes SHA-256 (lecture seule).")
    hashes.add_argument("--source", type=int, default=None)
    hashes.add_argument(
        "--reessayer-erreurs", action="store_true", help="Recalcule aussi les fichiers en erreur."
    )
    hashes.add_argument("--travailleurs", type=int, default=None, help="Calculs en parallèle.")

    formats = sub.add_parser(
        "formats",
        help="Identifie les formats réels et inspecte les archives ZIP (sans extraction).",
    )
    formats.add_argument("--source", type=int, default=None)
    recognize = sub.add_parser(
        "reconnaitre", help="Classe les fichiers MetaTrader (type, plateforme, certitude)."
    )
    recognize.add_argument("--source", type=int, default=None)
    archive = sub.add_parser("archive", help="Contenu inspecté d'une archive.")
    archive.add_argument("id", type=int, help="Identifiant du fichier archive.")

    detail = sub.add_parser("fichier", help="Détail d'un fichier inventorié.")
    detail.add_argument("id", type=int)

    sets = sub.add_parser("sets", help="Analyse les fichiers SET (paramètres bruts et normalisés).")
    sets.add_argument("--source", type=int, default=None)
    set_detail = sub.add_parser("set", help="Paramètres d'un fichier SET analysé.")
    set_detail.add_argument("id", type=int)
    compare = sub.add_parser("comparer-sets", help="Compare deux SET paramètre par paramètre.")
    compare.add_argument("a", type=int)
    compare.add_argument("b", type=int)
    sub.add_parser("associer", help="Calcule les associations robot ↔ SET (score et preuves).")
    assoc = sub.add_parser("associations", help="Liste des associations proposées.")
    assoc.add_argument("--set", dest="set_id", type=int, default=None)
    assoc.add_argument("--robot", type=int, default=None)
    assoc.add_argument("--niveau", choices=["forte", "moyenne", "faible", "a_verifier"])
    assoc.add_argument("--limite", type=int, default=50)
    one = sub.add_parser("association", help="Détail d'une association : preuves et incertitudes.")
    one.add_argument("id", type=int)
    decide = sub.add_parser("valider", help="Accepte ou rejette une association (vous seul).")
    decide.add_argument("id", type=int)
    choice = decide.add_mutually_exclusive_group(required=True)
    choice.add_argument("--accepter", action="store_true")
    choice.add_argument("--rejeter", action="store_true")
    choice.add_argument("--annuler", action="store_true", help="Revient à « non décidée ».")
    sub.add_parser("orphelins", help="SET sans aucun robot correspondant.")
    sub.add_parser("regrouper", help="Recalcule les familles (copies, versions, compilés, SET).")
    fams = sub.add_parser("familles", help="Liste des familles.")
    fams.add_argument("--recherche", default=None)
    fams.add_argument("--min-membres", type=int, default=2)
    fams.add_argument("--limite", type=int, default=50)
    fam = sub.add_parser("famille", help="Détail d'une famille (ou de celle d'un fichier).")
    fam.add_argument("id", type=int)
    fam.add_argument("--fichier", action="store_true", help="ID est un identifiant de fichier.")

    dups = sub.add_parser("doublons", help="Calcule doublons exacts et similarités.")
    dups.add_argument("--seuil", type=float, default=0.80, help="Seuil de similarité (0-1).")
    groups = sub.add_parser("groupes", help="Groupes de doublons exacts.")
    groups.add_argument("--limite", type=int, default=50)
    group = sub.add_parser("groupe", help="Membres d'un groupe de doublons exacts.")
    group.add_argument("id", type=int)
    ref = sub.add_parser("reference", help="Choisit le fichier conservé (référence) d'un groupe.")
    ref.add_argument("groupe", type=int)
    ref.add_argument("fichier", type=int)
    bytewise = sub.add_parser(
        "verifier-octets", help="Compare octet par octet les membres d'un groupe."
    )
    bytewise.add_argument("groupe", type=int)
    similar = sub.add_parser("similaires", help="Fichiers similaires (jamais des doublons).")
    similar.add_argument(
        "--type", choices=["text_normalized_equal", "text_similar", "set_similar"], default=None
    )
    similar.add_argument("--limite", type=int, default=50)

    quarantine = sub.add_parser("quarantaine", help="Quarantaine par copie vérifiée.")
    q_sub = quarantine.add_subparsers(dest="q_command", required=True, metavar="ACTION")
    q_sim = q_sub.add_parser("simuler", help="Prépare un lot (aucune copie).")
    q_sim.add_argument("destination", type=Path)
    q_sim.add_argument("--fichiers", type=int, nargs="*", default=None)
    q_exec = q_sub.add_parser("executer", help="Exécute un lot simulé (confirmation exigée).")
    q_exec.add_argument("lot", type=int)
    q_exec.add_argument("--jeton", required=True, help="Jeton donné par la simulation.")
    q_sub.add_parser("lots", help="Lots de quarantaine.")
    q_lot = q_sub.add_parser("lot", help="Contenu d'un lot.")
    q_lot.add_argument("lot", type=int)
    q_rest = q_sub.add_parser("restaurer", help="Sort les fichiers d'un lot de la quarantaine.")
    q_rest.add_argument("lot", type=int)
    q_rest.add_argument(
        "--recopier-originaux-absents",
        action="store_true",
        help="Recopie depuis la quarantaine un original disparu (sans écraser).",
    )
    q_cancel = q_sub.add_parser("annuler", help="Annule un lot non terminé.")
    q_cancel.add_argument("lot", type=int)

    organize = sub.add_parser("organiser", help="Bibliothèque organisée par copie vérifiée.")
    o_sub = organize.add_subparsers(dest="o_command", required=True, metavar="ACTION")
    o_prev = o_sub.add_parser("previsualiser", help="Calcule l'arborescence (aucune copie).")
    o_prev.add_argument("destination", type=Path)
    o_prev.add_argument("--avec-doublons", action="store_true")
    o_exec = o_sub.add_parser("executer", help="Copie selon un plan (confirmation exigée).")
    o_exec.add_argument("plan", type=int)
    o_exec.add_argument("--jeton", required=True)
    o_sub.add_parser("plans", help="Plans d'organisation.")
    o_items = o_sub.add_parser("plan", help="Contenu d'un plan.")
    o_items.add_argument("plan", type=int)
    o_items.add_argument("--limite", type=int, default=100)

    exporter = sub.add_parser("exporter", help="Exporte des résultats en CSV ou JSON.")
    exporter.add_argument("type", choices=sorted(KINDS))
    exporter.add_argument("fichier", type=Path, help="Destination .csv ou .json (nouvelle).")

    analyse = sub.add_parser(
        "analyser", help="Lance tout le pipeline d'analyse (ou certaines étapes)."
    )
    analyse.add_argument("--etapes", nargs="*", choices=[s.key for s in STEPS], default=None)
    settings = sub.add_parser("parametres", help="Affiche ou modifie les paramètres.")
    settings.add_argument("--definir", nargs=2, metavar=("CLE", "VALEUR"))
    settings.add_argument("--reinitialiser", metavar="CLE")

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
            "empreintes": _hashes,
            "fichier": _detail,
            "formats": _formats,
            "archive": _archive,
            "reconnaitre": _recognize,
            "sets": _sets,
            "set": _set_detail,
            "comparer-sets": _compare_sets,
            "associer": _associate,
            "associations": _associations,
            "association": _association,
            "valider": _decide,
            "orphelins": _orphans,
            "regrouper": _regroup,
            "familles": _families,
            "famille": _family,
            "doublons": _duplicates,
            "groupes": _groups,
            "groupe": _group,
            "reference": _reference,
            "verifier-octets": _bytewise,
            "similaires": _similar,
            "quarantaine": _quarantine,
            "organiser": _organize,
            "exporter": _export,
            "analyser": _analyse,
            "parametres": _settings,
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
        detected_type=args.type,
        platform=args.plateforme,
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


def _hashes(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    if args.travailleurs is not None and args.travailleurs < 1:
        print("--travailleurs doit être au moins 1.", file=err)
        return EXIT_USAGE
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(
        args.source, retry_errors=args.reessayer_erreurs, workers=args.travailleurs
    )
    print(
        f"Empreintes (tâche {summary.job_id}) : {summary.hashed} calculée(s), "
        f"{summary.errors} erreur(s) sur {summary.candidates} fichier(s) ; "
        f"{human_size(summary.bytes_read)} lus en {summary.seconds:.1f} s "
        f"({summary.mib_per_second:.1f} Mio/s).",
        file=out,
    )
    if summary.errors:
        print(
            "  Fichiers en erreur : mtlm fichiers (colonne « error »), "
            "puis mtlm fichier ID pour le détail.",
            file=out,
        )
    return EXIT_OK


def _formats(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = FormatService(ctx.conn, ctx.clock, ctx.journal).run(args.source)
    print(
        f"Formats (tâche {summary.job_id}) : {summary.signatures} signature(s) lue(s), "
        f"{summary.signature_errors} illisible(s), {summary.misleading} extension(s) "
        f"trompeuse(s).",
        file=out,
    )
    print(
        f"Archives : {summary.archives} — {summary.archives_ok} saine(s), "
        f"{summary.archives_problem} avec problème(s), {summary.archive_entries} entrée(s) "
        "inspectée(s) sans extraction.",
        file=out,
    )
    return EXIT_OK


TYPE_LABELS = {
    "ea": "robot (EA)",
    "indicator": "indicateur",
    "script": "script",
    "library": "bibliothèque",
    "include": "fichier d'inclusion",
    "service": "service",
    "set": "jeu de paramètres (SET)",
    "dll": "DLL",
    "template": "modèle",
    "resource": "fichier annexe",
    "unknown": "inconnu",
}
CERTAINTY_LABELS = {
    "certain": "certain",
    "probable": "probable",
    "possible": "possible",
    "unknown": "inconnue",
}


def _recognize(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(args.source)
    print(
        f"Reconnaissance (tâche {summary.job_id}) : {summary.classified} fichier(s) classé(s), "
        f"{summary.sources_parsed} source(s) MQL analysée(s), {summary.warnings} "
        f"avertissement(s), {summary.waiting_for_hash} en attente d'empreinte.",
        file=out,
    )
    for kind, n in sorted(summary.by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {TYPE_LABELS.get(kind, kind)}\t{n}", file=out)
    print("Certitude :", file=out)
    for level, n in summary.by_certainty.items():
        print(f"  {CERTAINTY_LABELS.get(level, level)}\t{n}", file=out)
    return EXIT_OK


def _sets(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = SetService(ctx.conn, ctx.clock, ctx.journal).parse_all(args.source)
    print(
        f"SET (tâche {summary.job_id}) : {summary.parsed} analysé(s) — {summary.mt4} MT4, "
        f"{summary.mt5} MT5, {summary.unknown_format} format indéterminé ; "
        f"{summary.with_warnings} avec avertissement(s), {summary.errors} illisible(s).",
        file=out,
    )
    return EXIT_OK


def _set_detail(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    doc = SetService(ctx.conn, ctx.clock, ctx.journal).document(args.id)
    if doc is None:
        print(f"Le fichier {args.id} n'est pas un SET analysé (lancez « mtlm sets »).", file=err)
        return EXIT_ERROR
    print(f"Format : {doc.format} ({doc.format_basis})", file=out)
    print(f"Paramètres : {len(doc.params)}", file=out)
    for p in doc.params:
        opt = ""
        if p.opt_start is not None:
            state = "activée" if p.opt_enabled else "désactivée"
            opt = f"  [optimisation {state} : {p.opt_start} → {p.opt_stop} pas {p.opt_step}]"
        normalized = (
            f" (normalisé : {p.normalized_value})"
            if p.normalized_value not in (None, p.raw_value)
            else ""
        )
        print(f"  {p.name} = {p.raw_value}{normalized}  <{p.estimated_type}>{opt}", file=out)
    for warning in doc.warnings:
        print(f"  avertissement : {warning}", file=out)
    return EXIT_OK


_DIFF_LABELS = {"same": "=", "different": "≠", "only_left": "A seul", "only_right": "B seul"}


def _compare_sets(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = SetService(ctx.conn, ctx.clock, ctx.journal)
    diffs = service.compare(args.a, args.b)
    if diffs is None:
        print("Les deux fichiers doivent être des SET analysés.", file=err)
        return EXIT_ERROR
    same = sum(d.status == "same" for d in diffs)
    print(f"{same} identique(s) sur {len(diffs)} paramètre(s).", file=out)
    for d in diffs:
        if d.status != "same":
            print(f"  {_DIFF_LABELS[d.status]}\t{d.name}\tA={d.left}\tB={d.right}", file=out)
    return EXIT_OK


def _associate(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = AssociationService(ctx.conn, ctx.clock, ctx.journal).compute()
    print(
        f"Associations (tâche {summary.job_id}) : {summary.associations} proposée(s) pour "
        f"{summary.sets} SET et {summary.robots} robot(s) ; {summary.orphans} SET orphelin(s) ; "
        f"{summary.decisions_kept} décision(s) de votre part conservée(s).",
        file=out,
    )
    for level, n in (summary.by_level or {}).items():
        print(f"  {LEVEL_LABELS.get(level, level)}\t{n}", file=out)
    print(
        "Aucune association n'est validée automatiquement : « mtlm valider ID --accepter ».",
        file=out,
    )
    return EXIT_OK


_DECISION_LABELS = {"none": "non décidée", "accepted": "ACCEPTÉE", "rejected": "rejetée"}


def _associations(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = AssociationService(ctx.conn, ctx.clock, ctx.journal).find(
        set_file_id=args.set_id, robot_file_id=args.robot, level=args.niveau, limit=args.limite
    )
    if not rows:
        print("Aucune association (lancez « mtlm sets » puis « mtlm associer »).", file=out)
    for r in rows:
        print(
            f"{r.id}\t{r.score:5.1f}\t{LEVEL_LABELS[r.level]}\t"
            f"{_DECISION_LABELS[r.user_decision]}\t{r.robot_path}  ↔  {r.set_path}",
            file=out,
        )
    return EXIT_OK


_POLARITY = {"pour": "+", "contre": "−", "incertitude": "?"}


def _association(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = AssociationService(ctx.conn, ctx.clock, ctx.journal)
    row = next((r for r in service.find(limit=1_000_000) if r.id == args.id), None)
    if row is None:
        print(f"Association {args.id} inconnue.", file=err)
        return EXIT_ERROR
    print(f"Robot : {row.robot_path} (fichier {row.robot_file_id})", file=out)
    print(f"SET : {row.set_path} (fichier {row.set_file_id})", file=out)
    print(
        f"Score : {row.score:.1f}/100 — niveau {LEVEL_LABELS[row.level]} — "
        f"décision : {_DECISION_LABELS[row.user_decision]}",
        file=out,
    )
    print("Preuves (+ pour, − contre, ? incertitude) :", file=out)
    for kind, weight, value, polarity, detail in service.evidence(args.id):
        print(
            f"  {_POLARITY[polarity]} {kind} (poids {weight:g}, valeur {value:.2f}) : {detail}",
            file=out,
        )
    return EXIT_OK


def _decide(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    decision = "accepted" if args.accepter else "rejected" if args.rejeter else "none"
    row = AssociationService(ctx.conn, ctx.clock, ctx.journal).decide(args.id, decision)
    print(
        f"Association {row.id} : {_DECISION_LABELS[row.user_decision]} "
        f"({row.robot_path} ↔ {row.set_path}).",
        file=out,
    )
    return EXIT_OK


def _orphans(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = AssociationService(ctx.conn, ctx.clock, ctx.journal).orphans()
    print(f"{len(rows)} SET orphelin(s) (aucun robot correspondant trouvé) :", file=out)
    for file_id, path in rows:
        print(f"  {file_id}\t{path}", file=out)
    return EXIT_OK


RELATION_LABELS = {
    "exact_copy": "copie exacte",
    "renamed_copy": "copie renommée",
    "version_variant": "version",
    "source_of": "source",
    "compiled_variant": "compilé",
    "homonym_different": "homonyme distinct",
    "set_for": "SET associé",
}


def _regroup(_args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    print(
        f"Familles (tâche {summary.job_id}) : {summary.families} famille(s), {summary.members} "
        f"membre(s) ; {summary.multi_version} avec plusieurs versions ; "
        f"{summary.homonym_groups} homonyme(s) séparé(s) ; {summary.with_sets} avec SET.",
        file=out,
    )
    return EXIT_OK


def _families(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = FamilyService(ctx.conn, ctx.clock, ctx.journal).find(
        text=args.recherche, min_members=args.min_membres, limit=args.limite
    )
    if not rows:
        print("Aucune famille (lancez « mtlm regrouper »).", file=out)
    for r in rows:
        print(
            f"{r.id}\t{r.display_name}\t{r.platform}\t{r.members} membre(s)\t"
            f"{r.versions} version(s)\tconfiance {r.confidence}",
            file=out,
        )
    return EXIT_OK


def _family(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = FamilyService(ctx.conn, ctx.clock, ctx.journal)
    family_id = service.family_of(args.id) if args.fichier else args.id
    found = service.detail(family_id) if family_id is not None else None
    if found is None:
        print("Famille introuvable (lancez « mtlm regrouper »).", file=err)
        return EXIT_ERROR
    row, basis, members = found
    print(
        f"Famille {row.id} : {row.display_name} ({row.platform}) — confiance {row.confidence}",
        file=out,
    )
    for reason in basis:
        print(f"  raison : {reason}", file=out)
    for m in members:
        version = (
            f" — version {m.estimated_version} ({m.version_basis})" if m.estimated_version else ""
        )
        print(f"  {RELATION_LABELS.get(m.relation, m.relation)}\t{m.rel_path}{version}", file=out)
    return EXIT_OK


def _duplicates(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    summary = DuplicateService(ctx.conn, ctx.clock, ctx.journal).compute(threshold=args.seuil)
    print(
        f"Doublons exacts (tâche {summary.job_id}) : {summary.groups} groupe(s), "
        f"{summary.duplicate_files} copie(s) en trop, {summary.admissible} admissible(s) à la "
        f"quarantaine ({human_size(summary.reclaimable_bytes)}).",
        file=out,
    )
    print(
        f"Séparés des doublons (jamais mis en quarantaine) : {summary.normalized_equal} "
        f"équivalent(s) normalisé(s), {summary.similar_text} source(s) similaire(s), "
        f"{summary.similar_sets} SET similaire(s).",
        file=out,
    )
    return EXIT_OK


def _groups(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = DuplicateService(ctx.conn, ctx.clock, ctx.journal).groups(limit=args.limite)
    if not rows:
        print("Aucun doublon exact (lancez « mtlm doublons »).", file=out)
    for g in rows:
        chosen = " (choisie par vous)" if g.reference_chosen_by_user else ""
        print(
            f"{g.id}\t{g.member_count} fichiers\t{human_size(g.size)}\tSHA-256 "
            f"{g.sha256_hex[:16]}…\tréférence : fichier {g.reference_file_id}{chosen}",
            file=out,
        )
    return EXIT_OK


def _group(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    members = DuplicateService(ctx.conn, ctx.clock, ctx.journal).members(args.id)
    if not members:
        print(f"Groupe {args.id} inconnu.", file=err)
        return EXIT_ERROR
    for m in members:
        role = (
            "RÉFÉRENCE"
            if m.is_reference
            else ("admissible" if m.admissible else f"non admissible ({m.reason})")
        )
        print(f"{m.file_id}\t{role}\t{m.rel_path}", file=out)
    return EXIT_OK


def _reference(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    DuplicateService(ctx.conn, ctx.clock, ctx.journal).set_reference(args.groupe, args.fichier)
    print(
        f"Fichier {args.fichier} désormais conservé comme référence du groupe {args.groupe}.",
        file=out,
    )
    return EXIT_OK


def _bytewise(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    identical = DuplicateService(ctx.conn, ctx.clock, ctx.journal).verify_bytewise(args.groupe)
    if identical:
        print(f"Groupe {args.groupe} : contenus identiques octet par octet.", file=out)
        return EXIT_OK
    print(f"Groupe {args.groupe} : contenus DIFFÉRENTS — aucun membre n'est admissible.", file=err)
    return EXIT_ERROR


_SIMILAR_LABELS = {
    "text_normalized_equal": "équivalent normalisé",
    "text_similar": "source similaire",
    "set_similar": "SET similaire",
}


def _similar(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    rows = DuplicateService(ctx.conn, ctx.clock, ctx.journal).similar(args.type, args.limite)
    if not rows:
        print("Aucune similarité (lancez « mtlm doublons »).", file=out)
    for r in rows:
        print(
            f"{r.score:.2f}\t{_SIMILAR_LABELS[r.kind]}\t{r.path_a}  ~  {r.path_b}\t({r.method})",
            file=out,
        )
    return EXIT_OK


def _quarantine(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    if args.q_command == "simuler":
        sim = service.simulate(args.destination, file_ids=args.fichiers)
        print(
            f"SIMULATION — aucun fichier copié. Lot {sim.batch_id} : {sim.entries} doublon(s) "
            f"exact(s), {human_size(sim.total_bytes)} vers {sim.destination}",
            file=out,
        )
        for file_id, reason in sim.excluded:
            print(f"  exclu : fichier {file_id} — {reason}", file=out)
        print(f"Rapport : {sim.report_path}", file=out)
        print("Les originaux ne seront ni modifiés ni déplacés (copie vérifiée).", file=out)
        print(
            f"Pour confirmer : mtlm quarantaine executer {sim.batch_id} --jeton {sim.token}",
            file=out,
        )
        return EXIT_OK
    if args.q_command == "executer":
        result = service.execute(args.lot, args.jeton)
        print(
            f"Lot {result.batch_id} : {result.status} — {result.verified} copie(s) vérifiée(s), "
            f"{result.failed} échec(s).",
            file=out,
        )
        if result.stopped_reason:
            print(f"Arrêt : {result.stopped_reason}", file=err)
            return EXIT_ERROR
        return EXIT_OK
    if args.q_command == "lots":
        batches = service.batches()
        if not batches:
            print("Aucun lot de quarantaine.", file=out)
        for b in batches:
            print(
                f"{b.id}\t{b.status}\t{b.verified}/{b.entries} vérifié(s)\t"
                f"{human_size(b.total_bytes)}\t{b.destination}\t{b.created_at}",
                file=out,
            )
        return EXIT_OK
    if args.q_command == "lot":
        for file_id, path, state, error in service.entries(args.lot):
            print(f"{file_id}\t{state}\t{path}" + (f"\t{error}" if error else ""), file=out)
        return EXIT_OK
    if args.q_command == "restaurer":
        restored, recopied, conflicts = service.restore(
            args.lot, recopy_missing=args.recopier_originaux_absents
        )
        print(
            f"Lot {args.lot} : {restored} fichier(s) sorti(s) de quarantaine, {recopied} "
            f"original(aux) recopié(s), {conflicts} conflit(s) (rien d'écrasé).",
            file=out,
        )
        return EXIT_OK if conflicts == 0 else EXIT_ERROR
    service.cancel(args.lot)
    print(f"Lot {args.lot} annulé.", file=out)
    return EXIT_OK


def _organize(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    if args.o_command == "previsualiser":
        preview = service.preview(args.destination, include_duplicates=args.avec_doublons)
        print(
            f"PRÉVISUALISATION — aucun fichier copié. Plan {preview.plan_id} : "
            f"{preview.items} fichier(s), {human_size(preview.total_bytes)} vers "
            f"{preview.destination}",
            file=out,
        )
        print(
            f"Collisions de noms résolues : {preview.collisions} ; exclus : "
            f"{preview.excluded_quarantine} en quarantaine, {preview.excluded_duplicates} "
            "doublon(s) (une seule copie par contenu).",
            file=out,
        )
        for folder, n in preview.tree.items():
            print(f"  {folder}/\t{n}", file=out)
        print(
            f"Pour confirmer : mtlm organiser executer {preview.plan_id} --jeton {preview.token}",
            file=out,
        )
        return EXIT_OK
    if args.o_command == "executer":
        result = service.execute(args.plan, args.jeton)
        print(
            f"Plan {result.plan_id} : {result.status} — {result.verified} copie(s) "
            f"vérifiée(s), {result.skipped} déjà faite(s), {result.failed} échec(s).",
            file=out,
        )
        if result.stopped_reason:
            print(f"Arrêt : {result.stopped_reason}", file=err)
            return EXIT_ERROR
        return EXIT_OK
    if args.o_command == "plans":
        plans = service.plans()
        if not plans:
            print("Aucun plan d'organisation.", file=out)
        for plan_id, dest, status, total, done, collisions in plans:
            print(
                f"{plan_id}\t{status}\t{done}/{total} copié(s)\t{collisions} collision(s)\t{dest}",
                file=out,
            )
        return EXIT_OK
    for file_id, target, state, collision in service.items(args.plan, args.limite):
        note = f"\t(collision avec le fichier {collision})" if collision else ""
        print(f"{file_id}\t{state}\t{target}{note}", file=out)
    return EXIT_OK


def _export(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    count = ReportService(ctx.conn, ctx.journal, ctx.paths).export(args.type, args.fichier)
    print(
        f"Export « {KINDS[args.type].label} » : {count} ligne(s) écrite(s) dans {args.fichier}",
        file=out,
    )
    return EXIT_OK


def _analyse(args: argparse.Namespace, ctx: AppContext, out: TextIO, _err: TextIO) -> int:
    keys = args.etapes or [s.key for s in STEPS]
    for label, summary in run_steps(ctx, keys, TaskControl(), lambda _m: None):
        print(f"{label} : {summary}", file=out)
    return EXIT_OK


def _settings(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    service = SettingsService(ctx.conn, ctx.journal)
    if args.definir:
        key, raw = args.definir
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            print(f"Valeur numérique attendue : {raw}", file=err)
            return EXIT_USAGE
        print(f"{key} = {service.set(key, value):g}", file=out)
        return EXIT_OK
    if args.reinitialiser:
        print(
            f"{args.reinitialiser} = {service.reset(args.reinitialiser):g} (valeur par défaut)",
            file=out,
        )
        return EXIT_OK
    for key, value in service.all().items():
        spec = SPECS[key]
        print(
            f"{key} = {value:g}\t({spec.label} ; {spec.minimum:g}–{spec.maximum:g}, "
            f"défaut {spec.default:g})",
            file=out,
        )
    return EXIT_OK


_ARCHIVE_STATUS = {
    "ok": "saine",
    "partial": "partiellement inspectée",
    "corrupt": "corrompue",
    "encrypted": "chiffrée (non lue)",
    "not_supported": "format identifié, non ouvert",
    "rejected": "refusée",
}


def _archive(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    scan = ctx.conn.execute(
        "SELECT format, status, entries_total, entries_read, bytes_read, reason"
        " FROM archive_scan WHERE file_id = ?",
        (args.id,),
    ).fetchone()
    if scan is None:
        print(
            f"Le fichier {args.id} n'a pas été inspecté comme archive (lancez « mtlm formats »).",
            file=err,
        )
        return EXIT_ERROR
    print(f"Format : {scan[0]} — état : {_ARCHIVE_STATUS.get(scan[1], scan[1])}", file=out)
    print(
        f"Entrées : {scan[2]} ; lues : {scan[3]} ; octets décompressés en mémoire : "
        f"{human_size(scan[4])}",
        file=out,
    )
    if scan[5]:
        print(f"Motif : {scan[5]}", file=out)
    for inner, status, size, reason in ctx.conn.execute(
        "SELECT inner_path, status, size, reason FROM archive_entry"
        " WHERE archive_file_id = ? ORDER BY id",
        (args.id,),
    ):
        note = f" — {reason}" if reason else ""
        print(f"  {status}\t{human_size(size)}\t{inner}{note}", file=out)
    return EXIT_OK


def _detail(args: argparse.Namespace, ctx: AppContext, out: TextIO, err: TextIO) -> int:
    detail = InventoryService(ctx.conn).detail(args.id)
    if detail is None:
        print(f"Fichier {args.id} inconnu.", file=err)
        return EXIT_ERROR
    row = detail.row
    lines = [
        ("Chemin", row.rel_path),
        ("Source", detail.source_path),
        ("Nom", row.name),
        ("Extension", row.ext or "(aucune)"),
        ("Type d'entrée", row.file_type),
        (
            "Taille",
            f"{human_size(row.size)} ({row.size} octets)" if row.size is not None else "inconnue",
        ),
        ("Présence", row.presence),
        ("iCloud non téléchargé", "oui (jamais lu)" if detail.is_dataless else "non"),
        ("État de l'empreinte", row.hash_state),
        ("SHA-256", detail.sha256_hex or "non calculée"),
        ("Erreur d'empreinte", detail.hash_error or "aucune"),
        (
            "Format réel (signature)",
            (detail.magic_label or "non identifié")
            + (" — EXTENSION TROMPEUSE" if detail.misleading_extension else ""),
        ),
        ("Moteur", detail.hashed_with_engine or "—"),
        ("Autres emplacements au contenu identique", str(detail.other_paths_same_content)),
        ("En quarantaine", "oui" if row.in_quarantine else "non"),
    ]
    for label, value in lines:
        print(f"{label} : {value}", file=out)
    info = analysis_of(ctx.conn, args.id)
    if info is None:
        print("Reconnaissance : non effectuée (lancez « mtlm reconnaitre »).", file=out)
        return EXIT_OK
    print(
        f"Type reconnu : {TYPE_LABELS.get(info.detected_type, info.detected_type)} — "
        f"plateforme {info.platform} — certitude {CERTAINTY_LABELS[info.certainty]}",
        file=out,
    )
    for reason in info.basis:
        print(f"  preuve : {reason}", file=out)
    if info.limits:
        print(f"  limite : {info.limits}", file=out)
    for warning in info.warnings:
        print(f"  avertissement : {warning}", file=out)
    if info.encoding is not None:
        print(f"Encodage : {info.encoding}", file=out)
        print(f"Version déclarée : {info.prop_version or 'aucune'}", file=out)
        print(f"Copyright déclaré : {info.prop_copyright or 'aucun'}", file=out)
        if info.prop_description:
            print(f"Description : {info.prop_description}", file=out)
        print(f"Fonctions d'entrée : {', '.join(info.entry_points) or 'aucune'}", file=out)
        print(f"Paramètres ({len(info.inputs)}) :", file=out)
        for name, mql_type, default, modifier in info.inputs:
            print(
                f"  {modifier} {mql_type} {name}" + (f" = {default}" if default else ""), file=out
            )
        if info.includes:
            print(f"Inclusions : {', '.join(info.includes)}", file=out)
        if info.imports:
            print(f"Imports (jamais chargés) : {', '.join(info.imports)}", file=out)
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
