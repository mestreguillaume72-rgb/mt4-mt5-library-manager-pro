"""Écrans : tableau de bord, sources, analyse, explorateur, détail fichier."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mtlm.app.inventory import FileFilter, InventoryService
from mtlm.app.jobs import JobStore
from mtlm.app.pipeline import STEPS, run_steps
from mtlm.app.presenters import (
    JOB_KIND_LABELS,
    JOB_STATE_LABELS,
    TYPE_LABELS,
    file_detail_lines,
    human_size,
)
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.ui.base import fill_table, make_table, selected_value
from mtlm.ui.theme import glow
from mtlm.ui.window import MainWindow, UiApp


class Page(QWidget):
    key = ""
    title = ""
    icon = "•"
    subtitle = ""

    def __init__(self, app: UiApp) -> None:
        super().__init__()
        self.app = app
        self.setObjectName(f"page-{self.key}")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(14)
        heading = QLabel(self.title)
        heading.setObjectName("pageTitle")
        self.layout_.addWidget(heading)
        if self.subtitle:
            sub = QLabel(self.subtitle)
            sub.setObjectName("pageSubtitle")
            sub.setWordWrap(True)
            self.layout_.addWidget(sub)
        self.layout_.addSpacing(4)

    @property
    def conn(self) -> Any:
        return self.app.ctx.conn

    @property
    def win(self) -> MainWindow:
        if self.app.window is None:
            raise RuntimeError("fenêtre principale non initialisée")
        return self.app.window

    def button_row(self, *buttons: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        self.layout_.addLayout(row)
        return row

    def btn(
        self, action_id: str, label: str, handler: Any, tooltip: str = "", role: str = ""
    ) -> QPushButton:
        return self.app.registry.button(f"{self.key}.{action_id}", label, handler, tooltip, role)

    def banner(self, text: str, kind: str = "banner") -> QFrame:
        frame = QFrame()
        frame.setObjectName(kind)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label, 1)
        self.layout_.addWidget(frame)
        return frame

    def refresh(self) -> None:
        """Recharge l'écran depuis la base (aucune donnée fictive)."""


class ClickCard(QFrame):
    """Carte entièrement cliquable (en plus de son bouton, pour le clavier)."""

    def __init__(self, on_click: Any = None) -> None:
        super().__init__()
        self._on_click = on_click
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._on_click is not None and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


def card(on_click: Any = None) -> QFrame:
    frame = ClickCard(on_click)
    frame.setObjectName("card")
    glow(frame, None)
    return frame


def restyle(widget: QWidget) -> None:
    """Réapplique la feuille de style après un changement de propriété (état d'une carte)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ---------------------------------------------------------------------------------------------
class DashboardPage(Page):
    key, title, icon = "tableau", "Accueil", "🏠"
    subtitle = (
        "Rangez et analysez votre bibliothèque MetaTrader en 3 étapes — sans jamais "
        "toucher à vos fichiers d'origine."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.empty = QLabel()
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        # --- les 3 étapes ---------------------------------------------------------------
        steps = QHBoxLayout()
        steps.setSpacing(14)
        self.step_cards: list[QFrame] = []
        self.step_numbers: list[QLabel] = []
        self.step_status: list[QLabel] = []
        definitions = [
            (
                "1",
                "Ma bibliothèque",
                "Choisissez le dossier qui contient vos robots, "
                "indicateurs et SET. Il est seulement lu.",
                self.btn(
                    "ajouter",
                    "📁  Choisir un dossier…",
                    self.add_source,
                    "Ajouter un dossier à analyser (lecture seule).",
                    role="big",
                ),
            ),
            (
                "2",
                "Analyser",
                "Inventaire, empreintes, reconnaissance des robots, SET, "
                "familles et doublons — automatiquement.",
                self.btn(
                    "analyser",
                    "▶  Tout analyser",
                    self.analyse_all,
                    "Lance toutes les étapes d'analyse.",
                    role="big",
                ),
            ),
            (
                "3",
                "Résultats",
                "Vérifiez les associations robot ↔ SET, les doublons, puis "
                "rangez votre bibliothèque.",
                self.btn(
                    "resultats",
                    "✨  Voir les résultats",
                    self.open_results,
                    "Ouvre les associations robot ↔ SET.",
                    role="big",
                ),
            ),
        ]
        for number, title, text, button in definitions:
            frame = card()
            box = QVBoxLayout(frame)
            box.setContentsMargins(18, 16, 18, 16)
            box.setSpacing(8)
            top = QHBoxLayout()
            circle = QLabel(number)
            circle.setObjectName("stepNumber")
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            top.addWidget(circle)
            top.addWidget(heading, 1)
            box.addLayout(top)
            desc = QLabel(text)
            desc.setObjectName("cardText")
            desc.setWordWrap(True)
            box.addWidget(desc, 1)
            status = QLabel("")
            box.addWidget(status)
            box.addWidget(button)
            steps.addWidget(frame, 1)
            self.step_cards.append(frame)
            self.step_numbers.append(circle)
            self.step_status.append(status)
        self.layout_.addLayout(steps)
        # --- progression de l'analyse en cours -------------------------------------------
        self.progress_card = card()
        progress_box = QVBoxLayout(self.progress_card)
        progress_box.setContentsMargins(18, 12, 18, 12)
        self.progress_text = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.btn("pause", "⏸  Pause", self.toggle_pause, role="ghost"))
        progress_row.addWidget(self.btn("annuler", "Annuler", self.cancel, role="danger"))
        progress_box.addWidget(self.progress_text)
        progress_box.addLayout(progress_row)
        self.progress_card.setVisible(False)
        self.layout_.addWidget(self.progress_card)
        # --- résumé en phrases + chiffres clés --------------------------------------------
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.layout_.addWidget(self.summary)
        self.layout_.addWidget(self.empty)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.values: dict[str, QLabel] = {}
        tiles = [
            ("robots", "🤖  Robots, indicateurs, scripts", "sets", "Voir"),
            ("sets", "🧾  Fichiers SET", "sets", "Voir"),
            ("assoc_strong", "✅  SET reliés avec certitude", "sets", "Voir"),
            ("assoc_check", "🟠  Associations à vérifier", "sets", "Vérifier"),
            ("dup_groups", "👯  Groupes de doublons exacts", "doublons", "Voir"),
            ("reclaim", "♻️  Copies en trop (quarantaine possible)", "quarantaine", "Traiter"),
            ("families", "🧬  Familles de robots", "familles", "Voir"),
            ("files", "📄  Fichiers analysés", "explorateur", "Explorer"),
        ]
        self.tiles: dict[str, QFrame] = {}
        self.hints: dict[str, QLabel] = {}
        for i, (key, label, target, action) in enumerate(tiles):
            frame = card(lambda t=target: self.win.navigate(t))
            box = QVBoxLayout(frame)
            box.setContentsMargins(22, 18, 22, 16)
            box.setSpacing(6)
            caption = QLabel(label)
            caption.setObjectName("cardTitle")
            value = QLabel("—")
            value.setObjectName("cardValue")
            value.setAccessibleName(label)
            go = self.btn(
                f"voir_{key}", f"{action} →", lambda t=target: self.win.navigate(t), role="ghost"
            )
            row = QHBoxLayout()
            row.addWidget(value, 1)
            row.addWidget(go)
            hint = QLabel("")
            hint.setObjectName("cardHint")
            box.addWidget(caption)
            box.addLayout(row)
            box.addWidget(hint)
            grid.addWidget(frame, i // 4, i % 4)
            self.values[key] = value
            self.tiles[key] = frame
            self.hints[key] = hint
        self.layout_.addLayout(grid)
        # Valeurs secondaires (lues par les tests et le résumé).
        for key in (
            "sources",
            "size",
            "missing",
            "hashed",
            "hash_todo",
            "assoc_ok",
            "orphans",
            "quarantined",
        ):
            self.values[key] = QLabel("—")
        self.layout_.addStretch(1)
        self.button_row(self.btn("actualiser", "Actualiser", self.refresh, role="ghost"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(400)

    # -- actions --------------------------------------------------------------------------------
    def add_source(self) -> None:
        self.win.pages["sources"].add()
        self.refresh()

    def analyse_all(self) -> None:
        self.win.pages["analyse"].start_all()
        self._tick()

    def open_results(self) -> None:
        self.win.navigate("sets")

    def toggle_pause(self) -> None:
        control = self.app.control
        if not self.app.busy or control is None:
            return
        if control.paused:
            control.resume()
        else:
            control.pause()
        self._tick()

    def cancel(self) -> None:
        if self.app.busy and self.app.control is not None:
            self.app.control.cancel()

    def _tick(self) -> None:
        busy = self.app.busy
        self.progress_card.setVisible(busy)
        if busy:
            paused = self.app.control is not None and self.app.control.paused
            text = (
                "En pause — cliquez sur « Pause » pour reprendre."
                if paused
                else (self.app.last_message or "Analyse en cours…")
            )
            self.progress_text.setText(f"⏳  {text}")

    def _apply_tones(self, values: dict[str, Any], analysed: bool) -> None:
        """Ton de chaque carte KPI selon les données réelles : vert = en ordre,
        ambre = action recommandée, bleu = information."""
        attention = {
            "assoc_check": "à vérifier",
            "dup_groups": "doublons exacts",
            "reclaim": "copies en trop",
        }
        for key, frame in self.tiles.items():
            if not analysed:
                tone, hint = "", ""
            elif key in attention:
                busy = int(values[key]) > 0
                tone = "warning" if busy else "success"
                hint = "Action recommandée" if busy else "Tout est en ordre"
            elif key == "assoc_strong":
                tone, hint = ("success", "Reliés avec preuves") if values[key] else ("", "")
            else:
                tone, hint = "info", ""
            frame.setProperty("tone", tone)
            self.hints[key].setText(hint)
            restyle(frame)
            glow(frame, tone or None, 55)

    def _count(self, sql: str) -> int:
        return int(self.conn.execute(sql).fetchone()[0] or 0)

    def refresh(self) -> None:
        stats = InventoryService(self.conn).stats()
        sources = self._count("SELECT count(*) FROM source_root WHERE status <> 'removed'")
        analysed = self._count(
            "SELECT count(*) FROM job WHERE kind = 'duplicates' AND state = 'completed'"
        )
        values: dict[str, Any] = {
            "sources": sources,
            "files": stats.files,
            "size": human_size(stats.total_bytes),
            "missing": stats.missing,
            "hashed": stats.by_hash_state.get("validated", 0),
            "hash_todo": sum(v for k, v in stats.by_hash_state.items() if k != "validated"),
            "robots": self._count(
                "SELECT count(*) FROM file_analysis WHERE detected_type IN"
                " ('ea', 'indicator', 'script')"
            ),
            "sets": self._count("SELECT count(*) FROM set_file"),
            "assoc_strong": self._count(
                "SELECT count(DISTINCT set_file_id) FROM association"
                " WHERE level = 'forte' AND user_decision <> 'rejected'"
                " OR user_decision = 'accepted'"
            ),
            "assoc_check": self._count(
                "SELECT count(*) FROM association WHERE user_decision = 'none' AND level <> 'forte'"
            ),
            "assoc_ok": self._count(
                "SELECT count(*) FROM association WHERE user_decision = 'accepted'"
            ),
            "orphans": self._count(
                "SELECT count(*) FROM set_file sf WHERE NOT EXISTS (SELECT 1"
                " FROM association a WHERE a.set_file_id = sf.file_id)"
            ),
            "families": self._count("SELECT count(*) FROM file_family"),
            "dup_groups": self._count("SELECT count(*) FROM duplicate_group"),
            "reclaim": self._count(
                "SELECT count(*) FROM duplicate_member WHERE admissible_for_quarantine = 1"
            ),
            "quarantined": self._count("SELECT count(*) FROM file_record WHERE in_quarantine = 1"),
        }
        for key, value in values.items():
            self.values[key].setText(fmt(value) if isinstance(value, int) else str(value))
        self._apply_tones(values, analysed > 0)
        # États des 3 étapes.
        done = [sources > 0, analysed > 0, values["assoc_ok"] > 0 or values["quarantined"] > 0]
        texts = [
            f"✓  {sources} dossier(s) ajouté(s)" if sources else "À faire",
            f"✓  {fmt(stats.files)} fichier(s) analysé(s)"
            if analysed
            else ("Prêt à lancer" if sources else "Ajoutez d'abord un dossier"),
            "✓  Résultats consultés" if done[2] else ("Prêt" if analysed else "Après l'analyse"),
        ]
        current = next((i for i, d in enumerate(done) if not d), None)
        for i, frame in enumerate(self.step_cards):
            state = "done" if done[i] else ("current" if i == current else "")
            frame.setProperty("state", state)
            self.step_numbers[i].setProperty("state", "done" if done[i] else "")
            self.step_numbers[i].setText("✓" if done[i] else str(i + 1))
            self.step_status[i].setText(texts[i])
            self.step_status[i].setObjectName("badgeOk" if done[i] else "badgeTodo")
            for widget in (frame, self.step_numbers[i], self.step_status[i]):
                restyle(widget)
            glow(frame, "success" if done[i] else ("info" if i == current else None), 60)
        if sources == 0:
            self.empty.setText(
                "Aucune source n'est encore ajoutée. Commencez par l'étape 1 : "
                "rien ne sera modifié dans vos dossiers."
            )
            self.summary.setText("")
        else:
            self.empty.setText(
                "Toutes les valeurs proviennent de l'analyse réelle de vos dossiers."
            )
            if analysed:
                self.summary.setText(
                    f"<b>Votre bibliothèque</b> : {fmt(stats.files)} fichiers "
                    f"({values['size']}), dont <b>{fmt(int(values['robots']))}</b> robots, "
                    f"indicateurs ou scripts et <b>{fmt(int(values['sets']))}</b> SET. "
                    f"<b>{fmt(int(values['assoc_check']))}</b> association(s) attendent votre "
                    f"vérification ; <b>{fmt(int(values['reclaim']))}</b> copie(s) en trop "
                    "peuvent être mises en quarantaine."
                )
            else:
                self.summary.setText("Étape suivante : cliquez sur <b>« Tout analyser »</b>.")
        self._tick()


# ---------------------------------------------------------------------------------------------
class SourcesPage(Page):
    key, title, icon = "sources", "Mes dossiers", "📁"
    subtitle = (
        "Les dossiers de votre bibliothèque MetaTrader. Ils sont seulement lus : "
        "l'application n'y écrit, ne renomme et ne supprime jamais rien."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            "Les dossiers sources sont lus en <b>lecture seule</b> : l'application n'y "
            "écrit, ne renomme et ne supprime jamais rien.",
            "bannerSafe",
        )
        self.table = make_table(
            ["N°", "Nom", "Chemin", "État", "Dernier inventaire"], badge_columns=(3,)
        )
        self.layout_.addWidget(self.table, 1)
        self.button_row(
            self.btn("ajouter", "Ajouter un dossier…", self.add),
            self.btn("inventorier", "Inventorier la source choisie", self.scan_selected),
            self.btn(
                "retirer",
                "Retirer la source choisie",
                self.remove,
                "Retire la source de l'application ; aucun fichier n'est supprimé.",
            ),
            self.btn("actualiser", "Actualiser", self.refresh),
        )

    def _service(self) -> SourceService:
        ctx = self.app.ctx
        return SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)

    def refresh(self) -> None:
        fill_table(
            self.table,
            [
                (
                    s.id,
                    s.display_name,
                    s.path,
                    s.status,
                    f"tâche {s.last_scan_job_id}" if s.last_scan_job_id else "jamais",
                )
                for s in self._service().list()
            ],
        )

    def add(self) -> None:
        folder = self.app.dialogs.choose_directory(self, "Choisir un dossier à analyser")
        if folder is None:
            return
        source = self._service().add(folder)
        self.app.status(f"Source n° {source.id} ajoutée : {source.path}")
        self.refresh()

    def _selected(self) -> int | None:
        value = selected_value(self.table)
        if value is None:
            self.app.dialogs.info(self.win, "Sources", "Sélectionnez d'abord une source.")
            return None
        return int(value)

    def remove(self) -> None:
        source_id = self._selected()
        if source_id is None:
            return
        if self.app.dialogs.confirm(
            self,
            "Retirer la source",
            "Retirer cette source de l'application ?\nAucun fichier ne sera supprimé ni modifié.",
        ):
            self._service().remove(source_id)
            self.refresh()

    def scan_selected(self) -> None:
        source_id = self._selected()
        if source_id is None:
            return

        def work(ctx: Any, control: Any, report: Any) -> str:
            summary = ScanService(ctx.conn, ctx.clock, ctx.journal).scan(
                source_id,
                control=control,
                progress=lambda s: report(f"Inventaire : {s.seen} fichier(s)…"),
            )
            return f"{summary.seen} vus, {summary.new} nouveaux, {summary.errors} erreur(s)"

        self.app.run_task("Inventaire", work, lambda r: self.app.status(f"Inventaire : {r}"))


# ---------------------------------------------------------------------------------------------
class AnalysisPage(Page):
    key, title, icon = "analyse", "Analyse", "🔎"
    subtitle = (
        "Lancez l'analyse complète ou certaines étapes. Vous pouvez mettre en pause, "
        "reprendre ou annuler à tout moment sans risque."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        box = QGroupBox("Étapes (chacune ne refait que ce qui a changé)")
        steps_layout = QVBoxLayout(box)
        self.checks: dict[str, QCheckBox] = {}
        for step in STEPS:
            check = QCheckBox(step.label)
            check.setChecked(True)
            check.setObjectName(f"analyse.etape.{step.key}")
            steps_layout.addWidget(check)
            self.checks[step.key] = check
        self.layout_.addWidget(box)
        self.button_row(
            self.btn("lancer", "Lancer les étapes cochées", self.start_selected),
            self.btn("tout", "Tout analyser", self.start_all),
            self.btn("pause", "Pause", self.pause),
            self.btn("reprendre", "Reprendre", self.resume),
            self.btn(
                "annuler", "Annuler", self.cancel, "Arrête à un point sûr : aucun état incohérent."
            ),
        )
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.current = QLabel("Aucune analyse en cours.")
        self.layout_.addWidget(self.progress)
        self.layout_.addWidget(self.current)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("analyse.journal")
        self.layout_.addWidget(self.log, 1)
        self.jobs = make_table(
            ["Tâche", "Type", "État", "Traités", "Erreurs", "Créée le"], badge_columns=(2,)
        )
        self.layout_.addWidget(self.jobs, 1)
        self.button_row(
            self.btn("erreurs", "Voir les erreurs de la tâche choisie", self.show_errors)
        )

    def refresh(self) -> None:
        jobs = JobStore(self.conn, self.app.ctx.clock).recent(30)
        fill_table(
            self.jobs,
            [
                (
                    j.id,
                    JOB_KIND_LABELS.get(j.kind, j.kind),
                    JOB_STATE_LABELS.get(j.state, j.state),
                    j.progress_done,
                    j.errors_count,
                    j.created_at,
                )
                for j in jobs
            ],
        )
        if not self.app.busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

    def start_all(self) -> None:
        for check in self.checks.values():
            check.setChecked(True)
        self.start_selected()

    def start_selected(self) -> None:
        keys = [k for k, c in self.checks.items() if c.isChecked()]
        if not keys:
            self.app.dialogs.info(self.win, "Analyse", "Cochez au moins une étape.")
            return

        def work(ctx: Any, control: Any, report: Any) -> list[tuple[str, str]]:
            return run_steps(ctx, keys, control, report)

        def done(results: list[tuple[str, str]]) -> None:
            for label, summary in results:
                self.log.appendPlainText(f"✔ {label} : {summary}")
            self.current.setText("Analyse terminée.")

        if self.app.run_task("Analyse", work, done, self.current.setText):
            self.progress.setRange(0, 0)  # indéterminé pendant le travail
            self.log.appendPlainText(f"▶ Étapes lancées : {', '.join(keys)}")

    def pause(self) -> None:
        if self.app.busy and self.app.control is not None:
            self.app.control.pause()
            self.current.setText("En pause — cliquez sur « Reprendre ».")
        else:
            self.current.setText("Aucune tâche en cours.")

    def resume(self) -> None:
        if self.app.control is not None:
            self.app.control.resume()
            self.current.setText("Reprise…")

    def cancel(self) -> None:
        if self.app.busy and self.app.control is not None:
            self.app.control.cancel()
            self.current.setText("Annulation demandée : arrêt au prochain point sûr.")
        else:
            self.current.setText("Aucune tâche en cours.")

    def show_errors(self) -> None:
        value = selected_value(self.jobs)
        if value is None:
            self.app.dialogs.info(self.win, "Erreurs", "Sélectionnez une tâche.")
            return
        errors = InventoryService(self.conn).errors(int(value))
        text = "\n".join(f"{e.rel_path or '(racine)'} : {e.message}" for e in errors)
        self.app.dialogs.info(
            self.win,
            f"Erreurs de la tâche {value}",
            text or "Aucune erreur pour cette tâche.",
        )


# ---------------------------------------------------------------------------------------------
class ExplorerPage(Page):
    key, title, icon = "explorateur", "Explorer", "🗂"
    subtitle = (
        "Tous les fichiers analysés. Cherchez par nom (les accents sont ignorés) et filtrez "
        "par type ou plateforme ; double-cliquez pour le détail."
    )
    PAGE_SIZE = 500

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        form = QFormLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Nom, chemin, description… (sans tenir compte des accents)")
        self.text.returnPressed.connect(self.search)
        self.ext = QLineEdit()
        self.ext.setPlaceholderText("ex. mq4 ex4 set")
        self.kind = QComboBox()
        self.kind.addItem("Tous les types", None)
        for key, label in TYPE_LABELS.items():
            self.kind.addItem(label, key)
        self.platform = QComboBox()
        for label, value in (
            ("Toutes plateformes", None),
            ("MT4", "mt4"),
            ("MT5", "mt5"),
            ("Inconnue", "unknown"),
        ):
            self.platform.addItem(label, value)
        self.missing = QCheckBox("Fichiers disparus uniquement")
        form.addRow("Recherche", self.text)
        form.addRow("Extensions", self.ext)
        form.addRow("Type", self.kind)
        form.addRow("Plateforme", self.platform)
        form.addRow("", self.missing)
        self.layout_.addLayout(form)
        self.button_row(
            self.btn("rechercher", "Rechercher", self.search),
            self.btn("precedente", "Page précédente", self.previous),
            self.btn("suivante", "Page suivante", self.next),
            self.btn("detail", "Afficher le détail", self.open_detail),
        )
        self.counter = QLabel()
        self.layout_.addWidget(self.counter)
        self.table = make_table(
            ["N°", "Nom", "Type", "Plateforme", "Taille", "Dossier"], badge_columns=(2,)
        )
        self.table.doubleClicked.connect(lambda _i: self.open_detail())
        self.layout_.addWidget(self.table, 1)
        self._cursors: list[int] = [0]

    def _filter(self) -> FileFilter:
        return FileFilter(
            extensions=tuple(self.ext.text().replace(",", " ").split()),
            presence="missing" if self.missing.isChecked() else "present",
            text=self.text.text().strip() or None,
            detected_type=self.kind.currentData(),
            platform=self.platform.currentData(),
        )

    def _load(self) -> None:
        service = InventoryService(self.conn)
        flt = self._filter()
        rows = service.page(flt, after_id=self._cursors[-1], limit=self.PAGE_SIZE)
        total = service.count(flt)
        kinds: dict[int, tuple[str, str]] = {}
        if rows:
            marks = ",".join("?" * len(rows))
            for file_id, detected, platform in self.conn.execute(
                f"SELECT file_id, detected_type, platform FROM file_analysis"
                f" WHERE file_id IN ({marks})",
                [r.id for r in rows],
            ):
                kinds[int(file_id)] = (detected, platform)
        fill_table(
            self.table,
            [
                (
                    r.id,
                    r.name,
                    TYPE_LABELS.get(kinds.get(r.id, ("", ""))[0], "non analysé"),
                    {"mt4": "MT4", "mt5": "MT5"}.get(kinds.get(r.id, ("", ""))[1], "—"),
                    human_size(r.size),
                    r.rel_path.rpartition("/")[0] or "(racine)",
                )
                for r in rows
            ],
        )
        start = (len(self._cursors) - 1) * self.PAGE_SIZE
        self.counter.setText(
            f"{total} fichier(s) correspondant(s) — affichés "
            f"{start + 1 if rows else 0} à {start + len(rows)}"
        )
        self._last = rows[-1].id if rows else self._cursors[-1]
        self._full = len(rows) == self.PAGE_SIZE

    def refresh(self) -> None:
        self._load()

    def search(self) -> None:
        self._cursors = [0]
        self._load()

    def next(self) -> None:
        if getattr(self, "_full", False):
            self._cursors.append(self._last)
            self._load()

    def previous(self) -> None:
        if len(self._cursors) > 1:
            self._cursors.pop()
            self._load()

    def open_detail(self) -> None:
        value = selected_value(self.table)
        if value is None:
            self.app.dialogs.info(self.win, "Détail", "Sélectionnez un fichier.")
            return
        self.win.navigate("detail", file_id=int(value))


# ---------------------------------------------------------------------------------------------
class DetailPage(Page):
    key, title, icon = "detail", "Détail d'un fichier", "📄"
    subtitle = (
        "Tout ce que l'application sait d'un fichier, avec ses preuves et ses limites (rien "
        "n'est inventé)."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        row = QHBoxLayout()
        self.file_id = QSpinBox()
        self.file_id.setRange(1, 2_000_000_000)
        self.file_id.setAccessibleName("Numéro du fichier")
        row.addWidget(QLabel("Fichier n°"))
        row.addWidget(self.file_id)
        row.addStretch(1)
        self.layout_.addLayout(row)
        self.button_row(
            self.btn("afficher", "Afficher", self.show_current),
            self.btn("famille", "Voir sa famille", self.open_family),
            self.btn("associations", "Voir ses associations SET", self.open_sets),
        )
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setObjectName("detail.texte")
        self.layout_.addWidget(self.text, 1)

    def show_item(self, file_id: int) -> None:
        self.file_id.setValue(file_id)
        self.show_current()

    def show_current(self) -> None:
        lines = file_detail_lines(self.conn, self.file_id.value())
        self.text.setPlainText(
            "\n".join(lines) if lines else f"Fichier {self.file_id.value()} inconnu."
        )

    def refresh(self) -> None:
        if self.text.toPlainText():
            self.show_current()

    def open_family(self) -> None:
        self.win.navigate("familles", file_id=self.file_id.value())

    def open_sets(self) -> None:
        self.win.navigate("sets", file_id=self.file_id.value())


def two_columns(left: QWidget, right: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(left, 1)
    layout.addWidget(right, 1)
    return container
