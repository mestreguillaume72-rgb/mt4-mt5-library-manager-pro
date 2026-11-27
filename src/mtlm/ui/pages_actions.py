"""Écrans : quarantaine/restauration, organisation, rapports, paramètres, aide."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mtlm import APP_NAME, ENGINE_VERSION, __version__
from mtlm.app.deletion import DeletionService
from mtlm.app.organize import MqSourceRow, OrganizeService, Preview
from mtlm.app.presenters import human_size
from mtlm.app.quarantine import QuarantineService, Simulation
from mtlm.app.reports import KINDS, ReportService
from mtlm.app.settings import SPECS, SettingsService
from mtlm.core.errors import MtlmError
from mtlm.core.i18n import tr
from mtlm.ui.base import fill_table, make_table, selected_value, selected_values
from mtlm.ui.pages_main import Page, two_columns
from mtlm.ui.window import UiApp


class QuarantinePage(Page):
    key, title, icon = "quarantaine", "Quarantaine", "🛡"
    subtitle = (
        "Mettez de côté les copies en trop par copie vérifiée, puis validez leur mise à la "
        "Corbeille."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            tr(
                "La quarantaine est une <b>copie vérifiée</b> des doublons exacts vers "
                "un dossier séparé ; une simulation est obligatoire avant toute copie. "
                "Ensuite, <b>vous validez</b> la mise à la <b>Corbeille</b> des "
                "originaux en trop : une copie identique est toujours conservée et "
                "vérifiée octet par octet, et un fichier mis à la Corbeille peut être "
                "remis en place."
            ),
            "bannerSafe",
        )
        self.destination: Path | None = None
        self.destination_label = QLabel(tr("Destination : non choisie"))
        self.layout_.addWidget(self.destination_label)
        self.simulation: Simulation | None = None
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("quarantaine.resume")
        self.summary.setMaximumHeight(80)
        self.summary.setPlaceholderText(
            tr(
                "Comment faire : 1) choisissez un dossier de quarantaine sur un autre "
                "disque ou en dehors de vos bibliothèques ; 2) cliquez sur « Simuler » "
                "pour voir ce qui serait copié ; 3) si tout vous convient, « Confirmer "
                "et copier »."
            )
        )
        self.layout_.addWidget(self.summary)
        self.button_row(
            self.btn("destination", tr("1. Choisir la destination…"), self.choose),
            self.btn("simuler", tr("2. Simuler (aucune copie)"), self.simulate),
            self.btn("executer", tr("3. Confirmer et copier"), self.execute),
        )
        self.batches = make_table(
            [
                tr("Lot"),
                tr("État"),
                tr("Fichiers"),
                tr("Vérifiés"),
                tr("Volume"),
                tr("Destination"),
                tr("Créé le"),
            ],
            badge_columns=(1,),
            multi=True,
            noun="lot",
        )
        self.batches.itemSelectionChanged.connect(self.load_entries)
        self.entries = make_table(
            [tr("Fichier"), tr("État"), tr("Original"), tr("Erreur")],
            badge_columns=(1,),
            noun="fichier",
        )
        tabs = QTabWidget()
        lots = QWidget()
        lots_layout = QVBoxLayout(lots)
        lots_layout.setContentsMargins(0, 10, 0, 0)
        lots_layout.addWidget(two_columns(self.batches, self.entries), 1)
        lots_layout.addLayout(
            self._row(
                self.btn("restaurer", tr("Restaurer le lot"), lambda: self.restore(False)),
                self.btn(
                    "recopier",
                    tr("Restaurer et recopier les originaux absents"),
                    lambda: self.restore(True),
                ),
                self.btn("annuler", tr("Annuler le lot"), self.cancel_batch),
            )
        )
        lots_layout.addLayout(
            self._row(
                self.btn(
                    "corbeille",
                    tr("4. Valider : originaux des lots choisis à la Corbeille"),
                    self.trash_batch,
                ),
                *self.select_buttons("lots", self.batches),
            )
        )
        tabs.addTab(lots, tr("Lots de quarantaine"))
        bin_tab = QWidget()
        bin_layout = QVBoxLayout(bin_tab)
        bin_layout.setContentsMargins(0, 10, 0, 0)
        hint = QLabel(
            tr(
                "Fichiers mis à la Corbeille, depuis la quarantaine, les doublons ou les "
                "familles : récupérables tant que la Corbeille n'est pas vidée."
            )
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        bin_layout.addWidget(hint)
        self.trashed = make_table(
            [
                "N°",
                tr("Fichier"),
                tr("Origine"),
                tr("Copie conservée"),
                tr("État"),
                tr("Chemin d'origine"),
                tr("Le"),
            ],
            badge_columns=(4,),
            multi=True,
            noun="fichier",
        )
        bin_layout.addWidget(self.trashed, 1)
        bin_layout.addLayout(
            self._row(
                self.btn("remettre", tr("Remettre en place les fichiers choisis"), self.put_back),
                *self.select_buttons("corbeille", self.trashed),
            )
        )
        tabs.addTab(bin_tab, tr("Corbeille"))
        self.layout_.addWidget(tabs, 1)
        self.button_row(self.btn("actualiser", tr("Actualiser"), self.refresh))

    @staticmethod
    def _row(*buttons: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _deletion(self) -> DeletionService:
        ctx = self.app.ctx
        return DeletionService(ctx.conn, ctx.clock, ctx.journal, ctx.trash)

    def trash_batch(self) -> None:
        batches = [int(v) for v in selected_values(self.batches)]
        if not batches:
            self.app.dialogs.info(
                self.win, tr("Corbeille"), tr("Sélectionnez un ou plusieurs lots de quarantaine.")
            )
            return
        deletion = self._deletion()
        originals = [f for batch in batches for f in deletion.originals_of_batch(batch)]
        if not originals:
            self.app.dialogs.info(
                self.win,
                tr("Corbeille"),
                tr(
                    "Ces lots n'ont aucune copie vérifiée : lancez d'abord « Confirmer et copier »."
                ),
            )
            return
        self.trash_with_confirmation(
            originals,
            "quarantaine",
            tr(
                "{v} lot(s) choisi(s) : les {v2} original(aux) en trop, déjà copiés et "
                "vérifiés en quarantaine, partent à la Corbeille. La référence de chaque "
                "groupe et la copie de quarantaine sont conservées.",
                v=len(batches),
                v2=len(originals),
            ),
            allow_unique=False,
        )

    def put_back(self) -> None:
        values = [int(v) for v in selected_values(self.trashed)]
        if not values:
            self.app.dialogs.info(
                self.win,
                tr("Remettre en place"),
                tr("Sélectionnez un ou plusieurs fichiers mis à la Corbeille."),
            )
            return
        deletion = self._deletion()
        done, failed = 0, []
        for deletion_id in values:
            try:
                deletion.put_back(deletion_id)
                done += 1
            except MtlmError as exc:
                failed.append(f"• n°{deletion_id} : {exc}")
        text = tr("{done} fichier(s) remis à leur emplacement d'origine.", done=done)
        if failed:
            text += tr("\n{v} non remis :\n", v=len(failed)) + "\n".join(failed[:10])
        if done:
            text += tr("\nRelancez l'analyse pour mettre à jour les doublons.")
        self.app.dialogs.info(self.win, tr("Remettre en place"), text)
        self.refresh()

    def _service(self) -> QuarantineService:
        ctx = self.app.ctx
        return QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)

    def refresh(self) -> None:
        fill_table(
            self.batches,
            [
                (
                    b.id,
                    b.status,
                    b.entries,
                    b.verified,
                    human_size(b.total_bytes),
                    b.destination,
                    b.created_at,
                )
                for b in self._service().batches()
            ],
        )
        states = {"trashed": tr("à la Corbeille"), "restored": tr("remis en place")}
        fill_table(
            self.trashed,
            [
                (
                    r.id,
                    r.file_id,
                    r.origin,
                    r.keeper,
                    states[r.state],
                    r.original_path,
                    r.created_at,
                )
                for r in self._deletion().records()
            ],
        )
        self.load_entries()

    def _batch(self) -> int | None:
        value = selected_value(self.batches)
        return int(value) if value else None

    def load_entries(self) -> None:
        batch = self._batch()
        fill_table(
            self.entries,
            []
            if batch is None
            else [
                (f, state, path, error) for f, path, state, error in self._service().entries(batch)
            ],
        )

    def choose(self) -> None:
        chosen = self.app.dialogs.choose_directory(
            self, tr("Dossier de quarantaine (en dehors de vos bibliothèques)")
        )
        if chosen is not None:
            self.destination = chosen
            self.destination_label.setText(tr("Destination : {chosen}", chosen=chosen))
            self.simulation = None

    def simulate(self) -> None:
        if self.destination is None:
            self.app.dialogs.info(self.win, "Quarantaine", tr("Choisissez d'abord la destination."))
            return
        self.simulation = sim = self._service().simulate(self.destination)
        self.summary.setPlainText(
            tr(
                "SIMULATION — aucun fichier copié.\nLot {batch_id} : {entries} doublon(s) "
                "exact(s), {v} vers {destination}\nRapport : {report_path}\nVérifiez puis "
                "cliquez sur « Confirmer et copier ».",
                batch_id=sim.batch_id,
                entries=sim.entries,
                v=human_size(sim.total_bytes),
                destination=sim.destination,
                report_path=sim.report_path,
            )
        )
        self.refresh()

    def execute(self) -> None:
        sim = self.simulation
        if sim is None:
            self.app.dialogs.info(self.win, "Quarantaine", tr("Lancez d'abord une simulation."))
            return
        if not self.app.dialogs.confirm(
            self,
            tr("Confirmer la quarantaine"),
            tr(
                "Copier {entries} doublon(s) exact(s) ({v}) vers\n{destination} ?\n\nLes "
                "originaux ne seront ni modifiés ni déplacés.",
                entries=sim.entries,
                v=human_size(sim.total_bytes),
                destination=sim.destination,
            ),
        ):
            return

        def work(ctx: Any, control: Any, _report: Any) -> Any:
            return QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).execute(
                sim.batch_id, sim.token, control=control
            )

        def done(result: Any) -> None:
            self.summary.setPlainText(
                tr(
                    "Lot {batch_id} : {status} — {verified} copie(s) vérifiée(s), {failed} "
                    "échec(s).",
                    batch_id=result.batch_id,
                    status=result.status,
                    verified=result.verified,
                    failed=result.failed,
                )
                + (
                    tr("\nArrêt : {stopped_reason}", stopped_reason=result.stopped_reason)
                    if result.stopped_reason
                    else ""
                )
            )
            self.refresh()

        self.app.run_task("Quarantaine", work, done)

    def restore(self, recopy: bool) -> None:
        batch = self._batch()
        if batch is None:
            self.app.dialogs.info(self.win, tr("Restauration"), tr("Sélectionnez un lot."))
            return
        if recopy and not self.app.dialogs.confirm(
            self,
            tr("Recopier les originaux absents"),
            tr(
                "Les originaux supprimés hors de l'application seront recopiés depuis la "
                "quarantaine (avec vérification). Aucun fichier existant ne sera écrasé. "
                "Continuer ?"
            ),
        ):
            return
        restored, recopied, conflicts = self._service().restore(batch, recopy_missing=recopy)
        self.app.dialogs.info(
            self.win,
            tr("Restauration"),
            tr(
                "{restored} fichier(s) sorti(s) de quarantaine, {recopied} original(aux) "
                "recopié(s), {conflicts} conflit(s) (rien écrasé).",
                restored=restored,
                recopied=recopied,
                conflicts=conflicts,
            ),
        )
        self.refresh()

    def cancel_batch(self) -> None:
        batch = self._batch()
        if batch is None:
            self.app.dialogs.info(self.win, tr("Annuler"), tr("Sélectionnez un lot."))
            return
        self._service().cancel(batch)
        self.refresh()


class OrganizePage(Page):
    key, title, icon = "organisation", "Bibliothèque rangée", "📦"
    subtitle = (
        "Créez une copie bien rangée de votre bibliothèque (par plateforme, type, robot et "
        "version) dans un nouveau dossier."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            tr(
                "Crée une <b>copie rangée</b> de votre bibliothèque (par plateforme, "
                "type, famille, version, statut des SET) dans un nouveau dossier. Les "
                "originaux ne sont pas modifiés."
            ),
            "banner",
        )
        self.destination: Path | None = None
        self.destination_label = QLabel(tr("Destination : non choisie"))
        self.layout_.addWidget(self.destination_label)
        self.with_duplicates = QCheckBox(
            tr("Copier aussi chaque doublon exact (sinon une seule copie par contenu)")
        )
        self.layout_.addWidget(self.with_duplicates)
        self.preview: Preview | None = None
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("organisation.resume")
        self.summary.setMaximumHeight(140)
        self.summary.setPlaceholderText(
            tr(
                "Comment faire : 1) choisissez un dossier de destination (un nouveau "
                "sous-dossier y sera créé) ; 2) « Prévisualiser » montre le rangement "
                "prévu ; 3) « Confirmer et copier » crée la copie rangée. Vos originaux "
                "ne bougent pas."
            )
        )
        self.layout_.addWidget(self.summary)
        self.button_row(
            self.btn("destination", tr("1. Choisir la destination…"), self.choose),
            self.btn("previsualiser", tr("2. Prévisualiser (aucune copie)"), self.make_preview),
            self.btn("executer", tr("3. Confirmer et copier"), self.execute),
            self.btn("actualiser", tr("Actualiser"), self.refresh),
        )
        self.plans = make_table(
            [
                tr("Plan"),
                tr("Destination"),
                tr("État"),
                tr("Fichiers"),
                tr("Copiés"),
                tr("Collisions"),
            ],
            badge_columns=(2,),
            noun="plan",
        )
        self.plans.itemSelectionChanged.connect(self.load_items)
        self.items = make_table(
            [tr("Fichier"), tr("Cible"), tr("État"), tr("Collision avec")],
            badge_columns=(2,),
            noun="fichier",
        )
        self.layout_.addWidget(two_columns(self.plans, self.items), 1)

    def _service(self) -> OrganizeService:
        ctx = self.app.ctx
        return OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)

    def refresh(self) -> None:
        fill_table(
            self.plans, [(p[0], p[1], p[2], p[3], p[4], p[5]) for p in self._service().plans()]
        )
        self.load_items()

    def load_items(self) -> None:
        value = selected_value(self.plans)
        fill_table(
            self.items, [] if value is None else self._service().items(int(value), limit=5000)
        )

    def choose(self) -> None:
        chosen = self.app.dialogs.choose_directory(
            self, tr("Dossier de destination (en dehors de vos bibliothèques)")
        )
        if chosen is not None:
            self.destination = chosen
            self.destination_label.setText(tr("Destination : {chosen}", chosen=chosen))
            self.preview = None

    def make_preview(self) -> None:
        if self.destination is None:
            self.app.dialogs.info(
                self.win, tr("Organisation"), tr("Choisissez d'abord la destination.")
            )
            return
        self.preview = p = self._service().preview(
            self.destination, include_duplicates=self.with_duplicates.isChecked()
        )
        tree = "\n".join(f"  {folder}/ : {n}" for folder, n in p.tree.items())
        self.summary.setPlainText(
            tr(
                "PRÉVISUALISATION — aucun fichier copié. Plan {plan_id} : {items} "
                "fichier(s), {v} vers {destination}\nCollisions de noms résolues : "
                "{collisions} ; exclus : {excluded_quarantine} en quarantaine, "
                "{excluded_duplicates} doublon(s).\n{tree}",
                plan_id=p.plan_id,
                items=p.items,
                v=human_size(p.total_bytes),
                destination=p.destination,
                collisions=p.collisions,
                excluded_quarantine=p.excluded_quarantine,
                excluded_duplicates=p.excluded_duplicates,
                tree=tree,
            )
        )
        self.refresh()

    def execute(self) -> None:
        preview = self.preview
        if preview is None:
            self.app.dialogs.info(
                self.win, tr("Organisation"), tr("Lancez d'abord une prévisualisation.")
            )
            return
        if not self.app.dialogs.confirm(
            self,
            tr("Confirmer la copie organisée"),
            tr(
                "Copier {items} fichier(s) ({v}) vers\n{destination} ?\n\nLes originaux ne "
                "seront pas modifiés.",
                items=preview.items,
                v=human_size(preview.total_bytes),
                destination=preview.destination,
            ),
        ):
            return

        def work(ctx: Any, control: Any, _report: Any) -> Any:
            return OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).execute(
                preview.plan_id, preview.token, control=control
            )

        def done(result: Any) -> None:
            self.summary.setPlainText(
                tr(
                    "Plan {plan_id} : {status} — {verified} copie(s) vérifiée(s), {skipped} "
                    "déjà faite(s), {failed} échec(s).",
                    plan_id=result.plan_id,
                    status=result.status,
                    verified=result.verified,
                    skipped=result.skipped,
                    failed=result.failed,
                )
                + (
                    tr("\nArrêt : {stopped_reason}", stopped_reason=result.stopped_reason)
                    if result.stopped_reason
                    else ""
                )
            )
            self.refresh()

        self.app.run_task(tr("Organisation"), work, done)


class SourcesMqPage(Page):
    key, title, icon = "sources_mq", "Sources MQ4/MQ5", "📜"
    subtitle = (
        "Isolez vos codes sources MQ4/MQ5 (robots, indicateurs, scripts) dans un nouveau "
        "dossier, chacun avec ses SET, ses fichiers liés et les indicateurs qu'il utilise."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            tr(
                "Choisissez les sources à isoler : <b>cliquez sur chaque ligne "
                "voulue</b> (un clic ajoute, un autre clic retire), ou « Tout "
                "sélectionner ». Si un robot a <b>son propre dossier</b>, ce dossier est "
                "copié <b>complet, tel quel</b> (sous-dossiers compris) ; s'il est "
                "<b>seul</b> au milieu d'autres fichiers, il est copié seul. Les "
                "fichiers qui peuvent aller avec lui ailleurs (SET, images, modèles, "
                "DLL, indicateurs utilisés) vous sont <b>proposés à cocher</b> : seuls "
                "ceux que vous validez sont ajoutés. Vos originaux ne bougent pas."
            ),
            "banner",
        )
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Rechercher une source par son nom ou son dossier…"))
        self.search.returnPressed.connect(self.refresh)
        self.platform = QComboBox()
        self.platform.setAccessibleName(tr("Plateforme"))
        for label, value in (
            (tr("MQ4 et MQ5"), None),
            (tr("MQ4 seulement"), "mq4"),
            (tr("MQ5 seulement"), "mq5"),
        ):
            self.platform.addItem(label, value)
        self.platform.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.search, 1)
        filters.addWidget(self.platform)
        self.layout_.addLayout(filters)
        # 1.6.0 : deux cases, robots et indicateurs (MQ4 et MQ5), reconnus automatiquement.
        boxes = QHBoxLayout()
        self.show_robots = QCheckBox(tr("🤖 Robots MQ4 / MQ5"))
        self.show_indicators = QCheckBox(tr("📈 Indicateurs MQ4 / MQ5"))
        self.show_others = QCheckBox(tr("Autres (scripts, bibliothèques, non reconnus)"))
        for box in (self.show_robots, self.show_indicators, self.show_others):
            box.setChecked(True)
            box.toggled.connect(lambda _c: self.refresh())
            boxes.addWidget(box)
        self.counts = QLabel("")
        self.counts.setObjectName("cardHint")
        boxes.addStretch(1)
        boxes.addWidget(self.counts)
        self.layout_.addLayout(boxes)
        self.sources = make_table(
            [
                "N°",
                tr("Source"),
                tr("C'est un…"),
                tr("Reconnu par"),
                tr("Plateforme"),
                "SET liés",
                tr("Fichiers liés"),
                tr("Utilise"),
            ],
            badge_columns=(2,),
            multi=True,
            noun="source",
        )
        self.layout_.addWidget(self.sources, 1)
        self.button_row(
            *self.select_buttons("sources", self.sources),
            self.btn(
                "corbeille",
                tr("Mettre les sources choisies à la Corbeille"),
                lambda: self.trash_selected(self.sources, "sources", "source(s)"),
            ),
        )
        self.button_row(
            self.btn("isoler", tr("Isoler les sources choisies…"), self.isolate_selected),
            self.btn("isoler_tout", tr("Isoler toutes les sources…"), self.isolate_all),
            self.btn("actualiser", tr("Actualiser"), self.refresh),
        )

    def _service(self) -> OrganizeService:
        ctx = self.app.ctx
        return OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)

    def refresh(self) -> None:
        types = {
            "ea": tr("Robot"),
            "indicator": tr("Indicateur"),
            "script": tr("Script"),
            "library": tr("Bibliothèque"),
            "service": tr("Service"),
            "include": tr("Include"),
        }
        chosen = [
            t
            for t, box in (("ea", self.show_robots), ("indicator", self.show_indicators))
            if box.isChecked()
        ]
        rows = self._service().mq_sources(
            text=self.search.text().strip() or None,
            ext=self.platform.currentData(),
            tool_types=chosen,
            others=self.show_others.isChecked(),
        )

        def kind(r: MqSourceRow) -> str:
            label = types.get(r.detected_type, tr("Non reconnu"))
            if r.certainty in ("probable", "possible") and r.detected_type in types:
                label += f" ({r.certainty})"
            if r.misplaced:
                label += tr(" — peut-être mal rangé")
            return label

        fill_table(
            self.sources,
            [
                (
                    r.file_id,
                    r.rel_path,
                    kind(r),
                    r.how,
                    r.ext.upper(),
                    r.sets,
                    r.linked,
                    r.dependencies,
                )
                for r in rows
            ],
        )
        robots = sum(1 for r in rows if r.detected_type == "ea")
        indicators = sum(1 for r in rows if r.detected_type == "indicator")
        self.counts.setText(
            tr(
                "{robots} robot(s), {indicators} indicateur(s), {v} autre(s)",
                robots=robots,
                indicators=indicators,
                v=len(rows) - robots - indicators,
            )
        )

    def isolate_selected(self) -> None:
        chosen = [int(v) for v in selected_values(self.sources)]
        if not chosen:
            self.app.dialogs.info(
                self.win,
                tr("Isoler les MQ4/MQ5"),
                tr(
                    "Cliquez sur les sources à isoler (une, deux, trois ou plus), puis recommencez."
                ),
            )
            return
        self._propose(chosen)

    def isolate_all(self) -> None:
        self._propose(None)

    def _propose(self, chosen: list[int] | None) -> None:
        service = self._service()
        ids = chosen if chosen is not None else [r.file_id for r in service.mq_sources()]
        if not ids:
            self.app.dialogs.info(self.win, tr("Isoler les MQ4/MQ5"), tr("Aucune source MQ4/MQ5."))
            return
        layout = service.source_layout(ids)
        folders = sum(1 for mode, _d in layout.values() if mode == "dossier")
        names = {r.file_id: r.rel_path.rpartition("/")[2] for r in service.mq_sources()}
        extras: dict[int, int] = {}
        candidates = service.isolation_candidates(ids)
        if candidates:
            picked = self.app.dialogs.choose_items(
                self,
                tr("Fichiers qui peuvent aller avec"),
                tr(
                    "Ces fichiers semblent aller avec les sources choisies (SET reliés, "
                    "images, modèles, DLL, indicateurs utilisés…), mais ne sont pas dans "
                    "leur dossier. Cochez ceux que vous voulez ajouter (un clic coche ou "
                    "décoche) ; les autres ne seront pas copiés."
                ),
                [
                    (
                        f"{c.file_id}:{c.source_id}",
                        f"{names.get(c.source_id, c.source_id)}  ←  {c.rel_path}  ({c.reason})",
                    )
                    for c in candidates
                ],
            )
            if picked is None:
                self.app.status(tr("Isolement annulé : rien n'a été copié."))
                return
            for key in picked:
                file_id, _, source_id = key.partition(":")
                extras[int(file_id)] = int(source_id)
        what = (
            tr("Toutes vos sources MQ4/MQ5")
            if chosen is None
            else tr("{v} source(s) choisie(s)", v=len(ids))
        )
        self.propose_folder(
            tr("Isoler les MQ4/MQ5"),
            tr(
                "{what} : {folders} rangée(s) dans leur propre dossier, copié(s) "
                "complet(s) et tel(s) quel(s) ; {v} seule(s), copiée(s) seule(s). {v2} "
                "fichier(s) validé(s) par vous s'ajoute(nt) à leur outil.",
                what=what,
                folders=folders,
                v=len(ids) - folders,
                v2=len(extras),
            ),
            lambda svc, destination: svc.preview_sources(destination, ids, extras),
        )


class ReportsPage(Page):
    key, title, icon = "rapports", "Rapports et journal", "📊"
    subtitle = (
        "Exportez vos résultats pour Excel (CSV) ou en JSON, et consultez le journal de "
        "toutes les actions."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        form = QFormLayout()
        self.kind = QComboBox()
        for key, spec in KINDS.items():
            self.kind.addItem(tr(spec.label), key)
        form.addRow(tr("Export"), self.kind)
        self.layout_.addLayout(form)
        self.button_row(
            self.btn("exporter", tr("Exporter (CSV ou JSON)…"), self.export),
            self.btn("audit_exporter", tr("Exporter le journal d'audit…"), self.export_audit),
            self.btn("audit_verifier", tr("Vérifier le journal d'audit"), self.verify_audit),
            self.btn("sauvegarder", tr("Sauvegarder la base"), self.backup),
            self.btn("actualiser", tr("Actualiser"), self.refresh),
        )
        self.audit = make_table(
            ["N°", tr("Date (UTC)"), tr("Acteur"), tr("Action"), tr("Objet"), tr("Résultat")],
            badge_columns=(5,),
            noun="action",
        )
        self.layout_.addWidget(
            QLabel(tr("Journal d'audit (200 derniers événements, non modifiable)"))
        )
        self.layout_.addWidget(self.audit, 1)

    def refresh(self) -> None:
        rows = self.conn.execute(
            "SELECT id, ts, actor, action, object, result FROM audit_event"
            " ORDER BY id DESC LIMIT 200"
        ).fetchall()
        fill_table(self.audit, rows)

    def export(self) -> None:
        kind = self.kind.currentData()
        path = self.app.dialogs.save_file(self, tr("Enregistrer l'export"), f"{kind}.csv")
        if path is None:
            return
        ctx = self.app.ctx
        count = ReportService(ctx.conn, ctx.journal, ctx.paths).export(kind, path)
        self.app.dialogs.info(
            self.win,
            tr("Export"),
            tr("{count} ligne(s) écrite(s) dans {path}", count=count, path=path),
        )
        self.refresh()

    def export_audit(self) -> None:
        path = self.app.dialogs.save_file(self, tr("Exporter le journal d'audit"), "audit.jsonl")
        if path is None:
            return
        count = self.app.ctx.journal.export_jsonl(path)
        self.app.ctx.journal.append(
            "utilisateur", "audit.export", str(path), details={"events": count}
        )
        self.app.dialogs.info(
            self.win,
            tr("Journal d'audit"),
            tr("{count} événement(s) exporté(s) vers {path}", count=count, path=path),
        )
        self.refresh()

    def verify_audit(self) -> None:
        result = self.app.ctx.journal.verify()
        if result.ok:
            self.app.dialogs.info(
                self.win,
                tr("Journal d'audit"),
                tr("Journal intact : {checked} événement(s) vérifié(s).", checked=result.checked),
            )
        else:
            self.app.dialogs.error(
                self.win,
                tr("Journal d'audit"),
                tr(
                    "ALTÉRATION détectée à l'événement {first_invalid_id} : {reason}",
                    first_invalid_id=result.first_invalid_id,
                    reason=result.reason,
                ),
            )

    def backup(self) -> None:
        path = self.app.ctx.backup("interface")
        self.app.ctx.journal.append("utilisateur", "db.backup", str(path))
        self.app.dialogs.info(
            self.win, tr("Sauvegarde"), tr("Sauvegarde vérifiée : {path}", path=path)
        )
        self.refresh()


class SettingsPage(Page):
    key, title, icon = "parametres", "Paramètres", "⚙️"
    subtitle = "Réglages de l'analyse. Les valeurs par défaut conviennent dans la plupart des cas."

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        form = QFormLayout()
        self.fields: dict[str, QSpinBox | QDoubleSpinBox] = {}
        for key, spec in SPECS.items():
            field: QSpinBox | QDoubleSpinBox
            if spec.integer:
                field = QSpinBox()
                field.setRange(int(spec.minimum), int(spec.maximum))
            else:
                field = QDoubleSpinBox()
                field.setDecimals(2)
                field.setSingleStep(0.05)
                field.setRange(spec.minimum, spec.maximum)
            field.setObjectName(f"parametres.{key}")
            field.setToolTip(tr(spec.help))
            field.setAccessibleName(tr(spec.label))
            self.fields[key] = field
            form.addRow(tr(spec.label), field)
        self.layout_.addLayout(form)
        self.button_row(
            self.btn("enregistrer", tr("Enregistrer"), self.save),
            self.btn("defaut", tr("Rétablir les valeurs par défaut"), self.defaults),
        )
        paths = app.ctx.paths
        location = QLabel(
            tr(
                "Base : {database}<br>Sauvegardes : {backups_dir}<br>Journaux : {logs_dir}",
                database=paths.database,
                backups_dir=paths.backups_dir,
                logs_dir=paths.logs_dir,
            )
        )
        location.setTextFormat(Qt.TextFormat.RichText)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.layout_.addWidget(location)
        self.layout_.addStretch(1)

    def _service(self) -> SettingsService:
        return SettingsService(self.app.ctx.conn, self.app.ctx.journal)

    def refresh(self) -> None:
        for key, value in self._service().all().items():
            self.fields[key].setValue(value)  # type: ignore[arg-type]

    def save(self) -> None:
        service = self._service()
        current = service.all()
        changed = 0
        for key, field in self.fields.items():
            if field.value() != current[key]:
                service.set(key, field.value())
                changed += 1
        self.app.status(tr("{changed} paramètre(s) enregistré(s).", changed=changed))
        self.refresh()

    def defaults(self) -> None:
        service = self._service()
        for key in SPECS:
            service.reset(key)
        self.refresh()


HELP = f"""
<h3>{APP_NAME}</h3>
<p>Version {__version__} — moteur {ENGINE_VERSION}</p>
<h4>Par où commencer ?</h4>
<ol>
<li><b>Sources</b> : « Ajouter un dossier… » (votre bibliothèque MetaTrader).
Rien n'y sera écrit.</li>
<li><b>Analyse</b> : « Tout analyser ». Vous pouvez mettre en pause, reprendre ou annuler.</li>
<li><b>Tableau de bord</b> : chiffres réels de votre bibliothèque.</li>
<li><b>SET et associations</b> : acceptez ou rejetez les associations proposées.</li>
<li><b>Doublons</b>, puis <b>Quarantaine</b> (copie vérifiée après simulation et confirmation).</li>
<li><b>Bibliothèque organisée</b> : copie rangée dans un nouveau dossier.</li>
</ol>
<h4>Garanties</h4>
<ul>
<li>Vos fichiers d'origine ne sont <b>jamais</b> modifiés ni déplacés par l'analyse.</li>
<li>Un fichier n'est retiré de vos dossiers que si <b>vous</b> le demandez et le confirmez :
il part dans la <b>Corbeille</b> (récupérable), et seulement si une copie identique est
conservée, sauf accord explicite pour un exemplaire unique.</li>
<li>Aucun robot, indicateur, script ou DLL n'est jamais exécuté.</li>
<li>Aucune donnée n'est envoyée sur Internet.</li>
<li>Chaque action sensible est inscrite dans un journal d'audit infalsifiable.</li>
</ul>
<h4>Limites (formats opaques)</h4>
<ul>
<li>Les fichiers compilés <b>EX4/EX5</b> ne sont ni décompilés ni lus : leur type est déduit du
dossier ou d'une source de même nom (« probable » au mieux).</li>
<li>Une association SET ↔ robot sans source lisible reste « à vérifier ».</li>
<li>Seules les archives ZIP sont inspectées (RAR/7z identifiés mais non ouverts).</li>
<li>La similarité est textuelle : deux codes réécrits différemment ne sont pas rapprochés.</li>
</ul>
"""


class HelpPage(Page):
    key, title, icon = "aide", "Aide", "❓"
    subtitle = "Mode d'emploi, garanties et limites de l'application."

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        browser = QTextBrowser()
        browser.setHtml(HELP)
        browser.setObjectName("aide.texte")
        self.layout_.addWidget(browser, 1)
        self.button_row(self.btn("demarrer", tr("Commencer : ajouter une source"), self.start))

    def start(self) -> None:
        self.win.navigate("sources")
