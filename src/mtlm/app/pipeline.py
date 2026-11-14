"""Pipeline d'analyse complet, partagé par l'interface et la ligne de commande (F11, F12).

Ordre : inventaire → empreintes → formats/archives → reconnaissance → SET → associations →
familles → doublons/similarités. Chaque étape est incrémentale (ne refait que ce qui a changé)
et accepte pause, reprise et annulation. Les paramètres utilisateur sont appliqués.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mtlm.app.archives import ArchiveService
from mtlm.app.companions import CompanionService
from mtlm.app.context import AppContext
from mtlm.app.duplicates import DuplicateService
from mtlm.app.families import FamilyService
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sets import AssociationService, SetService
from mtlm.app.settings import SettingsService
from mtlm.app.sources import SourceService
from mtlm.core.control import Cancelled, TaskControl

Report = Callable[[str], None]


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    run: Callable[[AppContext, TaskControl, Report], str]


def _scan(ctx: AppContext, control: TaskControl, report: Report) -> str:
    sources = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).list()
    if not sources:
        return "Aucune source : ajoutez d'abord un dossier."
    service = ScanService(ctx.conn, ctx.clock, ctx.journal)
    parts = []
    for source in sources:
        summary = service.scan(
            source.id,
            control=control,
            progress=lambda s: report(f"Inventaire : {s.seen} fichier(s) vu(s)…"),
        )
        parts.append(
            f"{source.display_name} : {summary.seen} vus, {summary.new} nouveaux, "
            f"{summary.changed} modifiés, {summary.missing} disparus, "
            f"{summary.errors} erreur(s)"
        )
        if summary.state == "cancelled":
            raise Cancelled
    return " ; ".join(parts)


def _hash(ctx: AppContext, control: TaskControl, report: Report) -> str:
    workers = int(SettingsService(ctx.conn, ctx.journal).get("empreintes.travailleurs"))
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(
        workers=workers,
        control=control,
        progress=lambda s: report(f"Empreintes : {s.hashed + s.errors}/{s.candidates}…"),
    )
    if summary.state == "cancelled":
        raise Cancelled
    return (
        f"{summary.hashed} empreinte(s) calculée(s), {summary.errors} erreur(s) "
        f"({summary.mib_per_second:.1f} Mio/s)"
    )


def _formats(ctx: AppContext, control: TaskControl, report: Report) -> str:
    settings = SettingsService(ctx.conn, ctx.journal)
    limits = settings.archive_limits()
    service = FormatService(ctx.conn, ctx.clock, ctx.journal, limits)
    summary = service.run(
        control=control, progress=lambda s: report(f"Formats : {s.signatures} signature(s)…")
    )
    text = (
        f"{summary.signatures} signature(s), {summary.misleading} extension(s) trompeuse(s), "
        f"{summary.archives} archive(s) dont {summary.archives_problem} avec problème"
    )
    if int(settings.get("archives.decompresser")):
        archives = ArchiveService(ctx.conn, ctx.clock, ctx.journal)
        eligible = archives.eligible()
        if eligible:
            report(f"Décompression de {len(eligible)} archive(s)…")
            done = archives.extract(eligible, ctx.trash, trash_archive=True)
            text += (
                f" ; {done.extracted} archive(s) décompressée(s) ({done.files} fichier(s)), "
                f"{done.trashed} mise(s) à la Corbeille, {len(done.refused)} laissée(s) intacte(s)"
            )
            if done.extracted:
                # Les fichiers extraits rejoignent l'analyse : inventaire, empreintes, formats.
                _scan(ctx, control, report)
                _hash(ctx, control, report)
                service.run(control=control)
    return text


def _recognize(ctx: AppContext, control: TaskControl, report: Report) -> str:
    summary = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(
        control=control, progress=lambda s: report(f"Reconnaissance : {s.classified}…")
    )
    return (
        f"{summary.classified} fichier(s) classé(s), {summary.sources_parsed} source(s) "
        f"analysée(s), {summary.warnings} avertissement(s)"
    )


def _sets(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    summary = SetService(ctx.conn, ctx.clock, ctx.journal).parse_all(control=control)
    return f"{summary.parsed} SET analysé(s) ({summary.mt4} MT4, {summary.mt5} MT5)"


def _associate(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    summary = AssociationService(ctx.conn, ctx.clock, ctx.journal).compute(control=control)
    return (
        f"{summary.associations} association(s) proposée(s), {summary.orphans} SET "
        "orphelin(s) — aucune validée automatiquement"
    )


def _families(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    control.checkpoint()
    summary = FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    linked = CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    return (
        f"{summary.families} famille(s), {summary.homonym_groups} homonyme(s) séparé(s), "
        f"{linked.linked} fichier(s) annexe(s) relié(s) à leur outil sur {linked.companions}"
    )


def _duplicates(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    control.checkpoint()
    threshold = float(SettingsService(ctx.conn, ctx.journal).get("similarite.seuil"))
    summary = DuplicateService(ctx.conn, ctx.clock, ctx.journal).compute(threshold=threshold)
    return (
        f"{summary.groups} groupe(s) de doublons exacts ({summary.admissible} admissible(s) "
        f"à la quarantaine), {summary.similar_text + summary.similar_sets} similarité(s)"
    )


STEPS: tuple[Step, ...] = (
    Step("inventaire", "Inventaire (lecture seule)", _scan),
    Step("empreintes", "Empreintes SHA-256", _hash),
    Step("formats", "Formats et archives", _formats),
    Step("reconnaissance", "Reconnaissance MetaTrader", _recognize),
    Step("sets", "Analyse des SET", _sets),
    Step("associations", "Associations robot ↔ SET", _associate),
    Step("familles", "Familles et versions", _families),
    Step("doublons", "Doublons et similarités", _duplicates),
)
STEP_BY_KEY = {s.key: s for s in STEPS}


def run_steps(
    ctx: AppContext, keys: list[str], control: TaskControl, report: Report
) -> list[tuple[str, str]]:
    """Exécute les étapes demandées dans l'ordre ; retourne (libellé, résumé) par étape."""
    results = []
    for step in STEPS:
        if step.key not in keys:
            continue
        control.checkpoint()
        report(f"{step.label}…")
        results.append((step.label, step.run(ctx, control, report)))
    return results
