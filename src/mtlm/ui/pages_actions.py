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
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mtlm import APP_NAME, ENGINE_VERSION, __version__
from mtlm.app.deletion import DeletionService
from mtlm.app.organize import OrganizeService, Preview
from mtlm.app.presenters import human_size
from mtlm.app.quarantine import QuarantineService, Simulation
from mtlm.app.reports import KINDS, ReportService
from mtlm.app.settings import SPECS, SettingsService
from mtlm.ui.base import fill_table, make_table, selected_value
from mtlm.ui.pages_main import Page, two_columns
from mtlm.ui.window import UiApp


class QuarantinePage(Page):
    key, title, icon = "quarantaine", "Quarantaine", "🛡"
    subtitle = (
        "Mettez de côté les copies en trop par copie vérifiée, puis validez leur mise à la "
        "Corbeille du Mac."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            "La quarantaine est une <b>copie vérifiée</b> des doublons exacts vers un "
            "dossier séparé ; une simulation est obligatoire avant toute copie. Ensuite, "
            "<b>vous validez</b> la mise à la <b>Corbeille du Mac</b> des originaux en trop : "
            "une copie identique est toujours conservée et vérifiée octet par octet, et un "
            "fichier mis à la Corbeille peut être remis en place.",
            "bannerSafe",
        )
        self.destination: Path | None = None
        self.destination_label = QLabel("Destination : non choisie")
        self.layout_.addWidget(self.destination_label)
        self.simulation: Simulation | None = None
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("quarantaine.resume")
        self.summary.setMaximumHeight(80)
        self.summary.setPlaceholderText(
            "Comment faire : 1) choisissez un dossier de quarantaine sur un autre disque ou en "
            "dehors de vos bibliothèques ; 2) cliquez sur « Simuler » pour voir ce qui serait "
            "copié ; 3) si tout vous convient, « Confirmer et copier »."
        )
        self.layout_.addWidget(self.summary)
        self.button_row(
            self.btn("destination", "1. Choisir la destination…", self.choose),
            self.btn("simuler", "2. Simuler (aucune copie)", self.simulate),
            self.btn("executer", "3. Confirmer et copier", self.execute),
        )
        self.batches = make_table(
            ["Lot", "État", "Fichiers", "Vérifiés", "Volume", "Destination", "Créé le"],
            badge_columns=(1,),
        )
        self.batches.itemSelectionChanged.connect(self.load_entries)
        self.entries = make_table(["Fichier", "État", "Original", "Erreur"], badge_columns=(1,))
        tabs = QTabWidget()
        lots = QWidget()
        lots_layout = QVBoxLayout(lots)
        lots_layout.setContentsMargins(0, 10, 0, 0)
        lots_layout.addWidget(two_columns(self.batches, self.entries), 1)
        lots_layout.addLayout(
            self._row(
                self.btn("restaurer", "Restaurer le lot", lambda: self.restore(False)),
                self.btn(
                    "recopier",
                    "Restaurer et recopier les originaux absents",
                    lambda: self.restore(True),
                ),
                self.btn("annuler", "Annuler le lot", self.cancel_batch),
            )
        )
        lots_layout.addLayout(
            self._row(
                self.btn(
                    "corbeille",
                    "4. Valider : originaux du lot à la Corbeille",
                    self.trash_batch,
                )
            )
        )
        tabs.addTab(lots, "Lots de quarantaine")
        bin_tab = QWidget()
        bin_layout = QVBoxLayout(bin_tab)
        bin_layout.setContentsMargins(0, 10, 0, 0)
        hint = QLabel(
            "Fichiers mis à la Corbeille du Mac, depuis la quarantaine, les doublons ou les "
            "familles : récupérables tant que la Corbeille n'est pas vidée."
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        bin_layout.addWidget(hint)
        self.trashed = make_table(
            ["N°", "Fichier", "Origine", "Copie conservée", "État", "Chemin d'origine", "Le"],
            badge_columns=(4,),
        )
        bin_layout.addWidget(self.trashed, 1)
        bin_layout.addLayout(
            self._row(self.btn("remettre", "Remettre en place le fichier choisi", self.put_back))
        )
        tabs.addTab(bin_tab, "Corbeille")
        self.layout_.addWidget(tabs, 1)
        self.button_row(self.btn("actualiser", "Actualiser", self.refresh))

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
        batch = self._batch()
        if batch is None:
            self.app.dialogs.info(self.win, "Corbeille", "Sélectionnez un lot de quarantaine.")
            return
        originals = self._deletion().originals_of_batch(batch)
        if not originals:
            self.app.dialogs.info(
                self.win,
                "Corbeille",
                "Ce lot n'a aucune copie vérifiée : lancez d'abord « Confirmer et copier ».",
            )
            return
        self.trash_with_confirmation(
            originals,
            "quarantaine",
            f"Lot {batch} : les {len(originals)} original(aux) en trop, déjà copiés et vérifiés "
            "en quarantaine, partent à la Corbeille. La référence de chaque groupe et la copie "
            "de quarantaine sont conservées.",
        )

    def put_back(self) -> None:
        value = selected_value(self.trashed)
        if value is None:
            self.app.dialogs.info(
                self.win, "Remettre en place", "Sélectionnez un fichier mis à la Corbeille."
            )
            return
        self._deletion().put_back(int(value))
        self.app.dialogs.info(
            self.win,
            "Remettre en place",
            "Fichier remis à son emplacement d'origine. Relancez l'analyse pour mettre à jour "
            "les doublons.",
        )
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
        states = {"trashed": "à la Corbeille", "restored": "remis en place"}
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
            self, "Dossier de quarantaine (en dehors de vos bibliothèques)"
        )
        if chosen is not None:
            self.destination = chosen
            self.destination_label.setText(f"Destination : {chosen}")
            self.simulation = None

    def simulate(self) -> None:
        if self.destination is None:
            self.app.dialogs.info(self.win, "Quarantaine", "Choisissez d'abord la destination.")
            return
        self.simulation = sim = self._service().simulate(self.destination)
        self.summary.setPlainText(
            f"SIMULATION — aucun fichier copié.\nLot {sim.batch_id} : {sim.entries} doublon(s) "
            f"exact(s), {human_size(sim.total_bytes)} vers {sim.destination}\n"
            f"Rapport : {sim.report_path}\nVérifiez puis cliquez sur « Confirmer et copier »."
        )
        self.refresh()

    def execute(self) -> None:
        sim = self.simulation
        if sim is None:
            self.app.dialogs.info(self.win, "Quarantaine", "Lancez d'abord une simulation.")
            return
        if not self.app.dialogs.confirm(
            self,
            "Confirmer la quarantaine",
            f"Copier {sim.entries} doublon(s) exact(s) ({human_size(sim.total_bytes)}) vers\n"
            f"{sim.destination} ?\n\nLes originaux ne seront ni modifiés ni déplacés.",
        ):
            return

        def work(ctx: Any, control: Any, _report: Any) -> Any:
            return QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).execute(
                sim.batch_id, sim.token, control=control
            )

        def done(result: Any) -> None:
            self.summary.setPlainText(
                f"Lot {result.batch_id} : {result.status} — {result.verified} copie(s) "
                f"vérifiée(s), {result.failed} échec(s)."
                + (f"\nArrêt : {result.stopped_reason}" if result.stopped_reason else "")
            )
            self.refresh()

        self.app.run_task("Quarantaine", work, done)

    def restore(self, recopy: bool) -> None:
        batch = self._batch()
        if batch is None:
            self.app.dialogs.info(self.win, "Restauration", "Sélectionnez un lot.")
            return
        if recopy and not self.app.dialogs.confirm(
            self,
            "Recopier les originaux absents",
            "Les originaux supprimés hors de l'application seront recopiés depuis la "
            "quarantaine (avec vérification). Aucun fichier existant ne sera écrasé. "
            "Continuer ?",
        ):
            return
        restored, recopied, conflicts = self._service().restore(batch, recopy_missing=recopy)
        self.app.dialogs.info(
            self.win,
            "Restauration",
            f"{restored} fichier(s) sorti(s) de quarantaine, {recopied} "
            f"original(aux) recopié(s), {conflicts} conflit(s) (rien écrasé).",
        )
        self.refresh()

    def cancel_batch(self) -> None:
        batch = self._batch()
        if batch is None:
            self.app.dialogs.info(self.win, "Annuler", "Sélectionnez un lot.")
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
            "Crée une <b>copie rangée</b> de votre bibliothèque (par plateforme, type, "
            "famille, version, statut des SET) dans un nouveau dossier. Les originaux "
            "ne sont pas modifiés.",
            "banner",
        )
        self.destination: Path | None = None
        self.destination_label = QLabel("Destination : non choisie")
        self.layout_.addWidget(self.destination_label)
        self.with_duplicates = QCheckBox(
            "Copier aussi chaque doublon exact (sinon une seule copie par contenu)"
        )
        self.layout_.addWidget(self.with_duplicates)
        self.preview: Preview | None = None
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("organisation.resume")
        self.summary.setMaximumHeight(140)
        self.summary.setPlaceholderText(
            "Comment faire : 1) choisissez un dossier de destination (un nouveau sous-dossier y "
            "sera créé) ; 2) « Prévisualiser » montre le rangement prévu ; 3) « Confirmer et "
            "copier » crée la copie rangée. Vos originaux ne bougent pas."
        )
        self.layout_.addWidget(self.summary)
        self.button_row(
            self.btn("destination", "1. Choisir la destination…", self.choose),
            self.btn("previsualiser", "2. Prévisualiser (aucune copie)", self.make_preview),
            self.btn("executer", "3. Confirmer et copier", self.execute),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self.plans = make_table(
            ["Plan", "Destination", "État", "Fichiers", "Copiés", "Collisions"], badge_columns=(2,)
        )
        self.plans.itemSelectionChanged.connect(self.load_items)
        self.items = make_table(["Fichier", "Cible", "État", "Collision avec"], badge_columns=(2,))
        self.layout_.addWidget(two_columns(self.plans, self.items), 1)
        self.banner(
            "<b>Isoler les sources MQ4/MQ5</b> — à ne pas confondre avec le dossier d'une "
            "famille : ici, <b>toutes</b> vos sources MQ4/MQ5 sont copiées, chacune dans "
            "« MQ4 » ou « MQ5 / nom du robot », avec ses SET associés et ses fichiers liés "
            "(images, sons, includes). Vous voyez d'abord la proposition, puis vous validez.",
            "banner",
        )
        self.button_row(
            self.btn("isoler", "Isoler les MQ4/MQ5 avec leurs SET…", self.propose_sources),
        )

    def propose_sources(self) -> None:
        self.propose_folder(
            "Isoler les MQ4/MQ5",
            "Chaque source MQ4/MQ5 dans « MQ4 » ou « MQ5 / <nom du robot> », avec les SET qui "
            "lui sont associés (acceptés par vous, ou de niveau « forte » non rejetés) et ses "
            "fichiers liés (images, sons, includes cités dans son code ou rangés avec lui).",
            lambda service, destination: service.preview_sources(destination),
        )

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
            self, "Dossier de destination (en dehors de vos bibliothèques)"
        )
        if chosen is not None:
            self.destination = chosen
            self.destination_label.setText(f"Destination : {chosen}")
            self.preview = None

    def make_preview(self) -> None:
        if self.destination is None:
            self.app.dialogs.info(self.win, "Organisation", "Choisissez d'abord la destination.")
            return
        self.preview = p = self._service().preview(
            self.destination, include_duplicates=self.with_duplicates.isChecked()
        )
        tree = "\n".join(f"  {folder}/ : {n}" for folder, n in p.tree.items())
        self.summary.setPlainText(
            f"PRÉVISUALISATION — aucun fichier copié. Plan {p.plan_id} : {p.items} fichier(s), "
            f"{human_size(p.total_bytes)} vers {p.destination}\nCollisions de noms résolues : "
            f"{p.collisions} ; exclus : {p.excluded_quarantine} en quarantaine, "
            f"{p.excluded_duplicates} doublon(s).\n{tree}"
        )
        self.refresh()

    def execute(self) -> None:
        preview = self.preview
        if preview is None:
            self.app.dialogs.info(self.win, "Organisation", "Lancez d'abord une prévisualisation.")
            return
        if not self.app.dialogs.confirm(
            self,
            "Confirmer la copie organisée",
            f"Copier {preview.items} fichier(s) ({human_size(preview.total_bytes)}) vers\n"
            f"{preview.destination} ?\n\nLes originaux ne seront pas modifiés.",
        ):
            return

        def work(ctx: Any, control: Any, _report: Any) -> Any:
            return OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).execute(
                preview.plan_id, preview.token, control=control
            )

        def done(result: Any) -> None:
            self.summary.setPlainText(
                f"Plan {result.plan_id} : {result.status} — {result.verified} copie(s) "
                f"vérifiée(s), {result.skipped} déjà faite(s), {result.failed} échec(s)."
                + (f"\nArrêt : {result.stopped_reason}" if result.stopped_reason else "")
            )
            self.refresh()

        self.app.run_task("Organisation", work, done)


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
            self.kind.addItem(spec.label, key)
        form.addRow("Export", self.kind)
        self.layout_.addLayout(form)
        self.button_row(
            self.btn("exporter", "Exporter (CSV ou JSON)…", self.export),
            self.btn("audit_exporter", "Exporter le journal d'audit…", self.export_audit),
            self.btn("audit_verifier", "Vérifier le journal d'audit", self.verify_audit),
            self.btn("sauvegarder", "Sauvegarder la base", self.backup),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self.audit = make_table(
            ["N°", "Date (UTC)", "Acteur", "Action", "Objet", "Résultat"], badge_columns=(5,)
        )
        self.layout_.addWidget(QLabel("Journal d'audit (200 derniers événements, non modifiable)"))
        self.layout_.addWidget(self.audit, 1)

    def refresh(self) -> None:
        rows = self.conn.execute(
            "SELECT id, ts, actor, action, object, result FROM audit_event"
            " ORDER BY id DESC LIMIT 200"
        ).fetchall()
        fill_table(self.audit, rows)

    def export(self) -> None:
        kind = self.kind.currentData()
        path = self.app.dialogs.save_file(self, "Enregistrer l'export", f"{kind}.csv")
        if path is None:
            return
        ctx = self.app.ctx
        count = ReportService(ctx.conn, ctx.journal, ctx.paths).export(kind, path)
        self.app.dialogs.info(self.win, "Export", f"{count} ligne(s) écrite(s) dans {path}")
        self.refresh()

    def export_audit(self) -> None:
        path = self.app.dialogs.save_file(self, "Exporter le journal d'audit", "audit.jsonl")
        if path is None:
            return
        count = self.app.ctx.journal.export_jsonl(path)
        self.app.ctx.journal.append(
            "utilisateur", "audit.export", str(path), details={"events": count}
        )
        self.app.dialogs.info(
            self.win, "Journal d'audit", f"{count} événement(s) exporté(s) vers {path}"
        )
        self.refresh()

    def verify_audit(self) -> None:
        result = self.app.ctx.journal.verify()
        if result.ok:
            self.app.dialogs.info(
                self.win,
                "Journal d'audit",
                f"Journal intact : {result.checked} événement(s) vérifié(s).",
            )
        else:
            self.app.dialogs.error(
                self.win,
                "Journal d'audit",
                f"ALTÉRATION détectée à l'événement {result.first_invalid_id} : {result.reason}",
            )

    def backup(self) -> None:
        path = self.app.ctx.backup("interface")
        self.app.ctx.journal.append("utilisateur", "db.backup", str(path))
        self.app.dialogs.info(self.win, "Sauvegarde", f"Sauvegarde vérifiée : {path}")
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
            field.setToolTip(spec.help)
            field.setAccessibleName(spec.label)
            self.fields[key] = field
            form.addRow(spec.label, field)
        self.layout_.addLayout(form)
        self.button_row(
            self.btn("enregistrer", "Enregistrer", self.save),
            self.btn("defaut", "Rétablir les valeurs par défaut", self.defaults),
        )
        paths = app.ctx.paths
        location = QLabel(
            f"Base : {paths.database}<br>Sauvegardes : {paths.backups_dir}<br>"
            f"Journaux : {paths.logs_dir}"
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
        self.app.status(f"{changed} paramètre(s) enregistré(s).")
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
il part dans la <b>Corbeille du Mac</b> (récupérable), et seulement si une copie identique est
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
        self.button_row(self.btn("demarrer", "Commencer : ajouter une source", self.start))

    def start(self) -> None:
        self.win.navigate("sources")
