"""Pipeline d'analyse complet, partagé par l'interface et la ligne de commande (F11, F12).

Ordre : inventaire → empreintes → formats/archives → reconnaissance → SET → associations →
familles → doublons/similarités. Chaque étape est incrémentale (ne refait que ce qui a changé)
et accepte pause, reprise et annulation. Les paramètres utilisateur sont appliqués.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from mtlm.app.archives import ArchiveService
from mtlm.app.companions import CompanionService
from mtlm.app.context import AppContext
from mtlm.app.duplicates import DuplicateService
from mtlm.app.families import FamilyService
from mtlm.app.formats import FormatService, FormatSummary
from mtlm.app.hashing import HashService, HashSummary
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sets import AssociationService, SetService
from mtlm.app.settings import SettingsService
from mtlm.app.sources import SourceService
from mtlm.core.control import Cancelled, TaskControl
from mtlm.core.i18n import tr

Report = Callable[[str], None]


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    run: Callable[[AppContext, TaskControl, Report], str]


def _scan(ctx: AppContext, control: TaskControl, report: Report) -> str:
    sources = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).list()
    if not sources:
        return tr("Aucune source : ajoutez d'abord un dossier.")
    service = ScanService(ctx.conn, ctx.clock, ctx.journal)
    parts = []
    for source in sources:
        summary = service.scan(
            source.id,
            control=control,
            progress=lambda s: report(tr("Inventaire : {seen} fichier(s) vu(s)…", seen=s.seen)),
        )
        parts.append(
            tr(
                "{display_name} : {seen} vus, {new} nouveaux, {changed} modifiés, "
                "{missing} disparus, {errors} erreur(s)",
                display_name=source.display_name,
                seen=summary.seen,
                new=summary.new,
                changed=summary.changed,
                missing=summary.missing,
                errors=summary.errors,
            )
        )
        if summary.state == "cancelled":
            raise Cancelled
    return " ; ".join(parts)


def _hash(ctx: AppContext, control: TaskControl, report: Report) -> str:
    settings = SettingsService(ctx.conn, ctx.journal)
    workers = int(settings.get("empreintes.travailleurs"))
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(
        workers=workers,
        control=control,
        progress=lambda s: report(hash_progress_text(s)),
        useful_only=not int(settings.get("empreintes.tout_lire")),
        retry_errors=True,  # les fichiers en erreur la dernière fois sont réessayés
    )
    if summary.state == "cancelled":
        raise Cancelled
    text = tr(
        "{hashed} empreinte(s) calculée(s), {errors} erreur(s) ({mib_per_second:.1f} Mio/s)",
        hashed=summary.hashed,
        errors=summary.errors,
        mib_per_second=summary.mib_per_second,
    )
    if summary.skipped_unrelated:
        text += tr(
            " ; {skipped_unrelated} fichier(s) sans rapport avec MetaTrader seulement listé(s)",
            skipped_unrelated=summary.skipped_unrelated,
        )
    if summary.errors:
        from mtlm.app.inventory import InventoryService

        causes = InventoryService(ctx.conn).hash_error_summary(limit=1)
        if causes:
            message, count, example = causes[0]
            text += tr(
                " — cause principale ({count} fichier(s)) : {message} ; exemple : {example}",
                count=count,
                message=message,
                example=example,
            )
    return text


def duration_text(seconds: float) -> str:
    """Durée lisible en français : « 2 h 05 min », « 7 min », « moins d'une minute »."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return tr("moins d'une minute")
    hours, minutes = divmod(minutes, 60)
    if hours:
        return tr("{hours} h {minutes:02d} min", hours=hours, minutes=minutes)
    return f"{minutes} min"


def hash_progress_text(summary: HashSummary) -> str:
    done = summary.hashed + summary.errors
    text = tr("Empreintes : {done}/{candidates}", done=done, candidates=summary.candidates)
    if summary.bytes_total:
        text += tr(
            " ({v:.1f}/{v2:.1f} Go", v=summary.bytes_read / 2**30, v2=summary.bytes_total / 2**30
        )
        if summary.seconds >= 2:
            text += tr(", {mib_per_second:.1f} Mio/s", mib_per_second=summary.mib_per_second)
        text += ")"
    remaining = summary.remaining_seconds
    if remaining is not None:
        text += tr(" — reste environ {v}", v=duration_text(remaining))
    return text + "…"


def eta_text(done: int, total: int, seconds: float) -> str:
    """« (12 %, reste environ 5 min) » d'après la vitesse mesurée ; vide si inconnu."""
    if total <= 0:
        return ""
    text = f" ({min(100, done * 100 // total)} %"
    if done > 0 and seconds >= 2 and done < total:
        text += tr(", reste environ {v}", v=duration_text(seconds / done * (total - done)))
    return text + ")"


def _formats_progress(summary: FormatSummary, started: float) -> str:
    elapsed = time.perf_counter() - started
    if summary.phase == "signatures":
        done, total = summary.signatures + summary.signature_errors, summary.to_sign
        return tr(
            "Formats : {done}/{total} fichier(s){v}…",
            done=done,
            total=total,
            v=eta_text(done, total, elapsed),
        )
    done, total = summary.archives, summary.archives_total
    return tr(
        "Archives : {done}/{total} lue(s){v}…",
        done=done,
        total=total,
        v=eta_text(done, total, elapsed),
    )


def _formats(ctx: AppContext, control: TaskControl, report: Report) -> str:
    started = time.perf_counter()
    settings = SettingsService(ctx.conn, ctx.journal)
    limits = settings.archive_limits()
    service = FormatService(ctx.conn, ctx.clock, ctx.journal, limits)
    summary = service.run(control=control, progress=lambda s: report(_formats_progress(s, started)))
    text = tr(
        "{signatures} signature(s), {misleading} extension(s) trompeuse(s), "
        "{archives} archive(s) dont {archives_problem} avec problème",
        signatures=summary.signatures,
        misleading=summary.misleading,
        archives=summary.archives,
        archives_problem=summary.archives_problem,
    )
    if int(settings.get("archives.decompresser")):
        archives = ArchiveService(ctx.conn, ctx.clock, ctx.journal)
        eligible = archives.eligible()
        if eligible:
            report(tr("Décompression de {v} archive(s)…", v=len(eligible)))
            done = archives.extract(eligible, ctx.trash, trash_archive=True)
            text += tr(
                " ; {extracted} archive(s) décompressée(s) ({files} fichier(s)), "
                "{trashed} mise(s) à la Corbeille, {v} laissée(s) intacte(s)",
                extracted=done.extracted,
                files=done.files,
                trashed=done.trashed,
                v=len(done.refused),
            )
            if done.refused:
                text += " (" + " ; ".join(why for _a, why in done.refused[:3]) + ")"
            if done.extracted:
                # Les fichiers extraits rejoignent l'analyse : inventaire, empreintes, formats.
                _scan(ctx, control, report)
                _hash(ctx, control, report)
                service.run(control=control)
    return text


def _recognize(ctx: AppContext, control: TaskControl, report: Report) -> str:
    started = time.perf_counter()
    summary = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(
        control=control,
        progress=lambda s: report(
            tr(
                "Reconnaissance : {done}/{total} fichier(s){v}…",
                done=s.done,
                total=s.total,
                v=eta_text(s.done, s.total, time.perf_counter() - started),
            )
        ),
    )
    return tr(
        "{classified} fichier(s) classé(s), {sources_parsed} source(s) "
        "analysée(s), {warnings} avertissement(s)",
        classified=summary.classified,
        sources_parsed=summary.sources_parsed,
        warnings=summary.warnings,
    )


def _sets(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    summary = SetService(ctx.conn, ctx.clock, ctx.journal).parse_all(control=control)
    return f"{summary.parsed} SET analysé(s) ({summary.mt4} MT4, {summary.mt5} MT5)"


def _associate(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    summary = AssociationService(ctx.conn, ctx.clock, ctx.journal).compute(control=control)
    return tr(
        "{associations} association(s) proposée(s), {orphans} SET orphelin(s) — "
        "aucune validée automatiquement",
        associations=summary.associations,
        orphans=summary.orphans,
    )


def _families(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    control.checkpoint()
    summary = FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    linked = CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    return tr(
        "{families} famille(s), {homonym_groups} homonyme(s) séparé(s), {linked} "
        "fichier(s) annexe(s) relié(s) à leur outil sur {companions}",
        families=summary.families,
        homonym_groups=summary.homonym_groups,
        linked=linked.linked,
        companions=linked.companions,
    )


def _duplicates(ctx: AppContext, control: TaskControl, _report: Report) -> str:
    control.checkpoint()
    threshold = float(SettingsService(ctx.conn, ctx.journal).get("similarite.seuil"))
    summary = DuplicateService(ctx.conn, ctx.clock, ctx.journal).compute(threshold=threshold)
    return tr(
        "{groups} groupe(s) de doublons exacts ({admissible} admissible(s) à la "
        "quarantaine), {v} similarité(s)",
        groups=summary.groups,
        admissible=summary.admissible,
        v=summary.similar_text + summary.similar_sets,
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
    chosen = [step for step in STEPS if step.key in keys]
    for number, step in enumerate(chosen, start=1):
        control.checkpoint()
        prefix = tr("Étape {number}/{v} — ", number=number, v=len(chosen))

        def prefixed(text: str, prefix: str = prefix) -> None:
            report(prefix + text)

        prefixed(f"{step.label}…")
        results.append((step.label, step.run(ctx, control, prefixed)))
    return results
