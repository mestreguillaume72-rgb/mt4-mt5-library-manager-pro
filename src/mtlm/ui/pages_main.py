"""Écrans : tableau de bord, sources, analyse, explorateur, détail fichier."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
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
from mtlm.ui.window import MainWindow, UiApp


class Page(QWidget):
    key = ""
    title = ""

    def __init__(self, app: UiApp) -> None:
        super().__init__()
        self.app = app
        self.setObjectName(f"page-{self.key}")
        self.layout_ = QVBoxLayout(self)
        heading = QLabel(f"<h2>{self.title}</h2>")
        heading.setTextFormat(Qt.TextFormat.RichText)
        self.layout_.addWidget(heading)

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

    def btn(self, action_id: str, label: str, handler: Any, tooltip: str = "") -> QPushButton:
        return self.app.registry.button(f"{self.key}.{action_id}", label, handler, tooltip)

    def refresh(self) -> None:
        """Recharge l'écran depuis la base (aucune donnée fictive)."""


# ---------------------------------------------------------------------------------------------
class DashboardPage(Page):
    key, title = "tableau", "Tableau de bord"

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.empty = QLabel()
        self.empty.setWordWrap(True)
        self.layout_.addWidget(self.empty)
        grid = QGridLayout()
        self.values: dict[str, QLabel] = {}
        labels = [
            ("sources", "Sources"),
            ("files", "Fichiers présents"),
            ("size", "Volume"),
            ("missing", "Fichiers disparus"),
            ("hashed", "Empreintes validées"),
            ("hash_todo", "Empreintes à calculer"),
            ("robots", "Robots / indicateurs / scripts"),
            ("sets", "SET analysés"),
            ("assoc_strong", "Associations fortes"),
            ("assoc_check", "Associations à vérifier"),
            ("assoc_ok", "Associations acceptées"),
            ("orphans", "SET orphelins"),
            ("families", "Familles"),
            ("dup_groups", "Groupes de doublons exacts"),
            ("reclaim", "Doublons admissibles"),
            ("quarantined", "Fichiers en quarantaine"),
        ]
        for i, (key, label) in enumerate(labels):
            value = QLabel("—")
            value.setObjectName(f"tableau.valeur.{key}")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            self.values[key] = value
        self.layout_.addLayout(grid)
        self.button_row(
            self.btn(
                "analyser",
                "Tout analyser",
                self.analyse_all,
                "Lance toutes les étapes d'analyse (écran Analyse).",
            ),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self.jobs = make_table(["Tâche", "Type", "État", "Traités", "Erreurs", "Créée le"])
        self.layout_.addWidget(QLabel("Dernières tâches"))
        self.layout_.addWidget(self.jobs, 1)

    def analyse_all(self) -> None:
        self.win.navigate("analyse")
        self.win.pages["analyse"].start_all()

    def _count(self, sql: str) -> int:
        return int(self.conn.execute(sql).fetchone()[0] or 0)

    def refresh(self) -> None:
        stats = InventoryService(self.conn).stats()
        sources = self._count("SELECT count(*) FROM source_root WHERE status <> 'removed'")
        values = {
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
            "assoc_strong": self._count("SELECT count(*) FROM association WHERE level = 'forte'"),
            "assoc_check": self._count(
                "SELECT count(*) FROM association WHERE level = 'a_verifier'"
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
            self.values[key].setText(str(value))
        if sources == 0:
            self.empty.setText(
                "Aucune source n'est encore ajoutée. Allez dans « Sources » et "
                "cliquez sur « Ajouter un dossier… ». Rien n'y sera modifié."
            )
        else:
            self.empty.setText(
                "Toutes les valeurs ci-dessous proviennent de l'analyse réelle de vos dossiers."
            )
        jobs = JobStore(self.conn, self.app.ctx.clock).recent(15)
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


# ---------------------------------------------------------------------------------------------
class SourcesPage(Page):
    key, title = "sources", "Sources"

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        info = QLabel(
            "Les dossiers sources sont lus en <b>lecture seule</b> : l'application n'y "
            "écrit, ne renomme et ne supprime jamais rien."
        )
        info.setWordWrap(True)
        self.layout_.addWidget(info)
        self.table = make_table(["N°", "Nom", "Chemin", "État", "Dernier inventaire"])
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
    key, title = "analyse", "Analyse"

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
        self.jobs = make_table(["Tâche", "Type", "État", "Traités", "Erreurs", "Créée le"])
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
    key, title = "explorateur", "Explorateur"
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
        self.table = make_table(["N°", "Extension", "Taille", "Empreinte", "Chemin"])
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
        fill_table(
            self.table,
            [(r.id, r.ext or "—", human_size(r.size), r.hash_state, r.rel_path) for r in rows],
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
    key, title = "detail", "Détail fichier"

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
