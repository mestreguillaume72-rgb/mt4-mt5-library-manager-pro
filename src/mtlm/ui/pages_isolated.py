"""Écrans « Robots isolés » et « Indicateurs isolés » (1.6.0).

Un endroit à part, sans mélange avec l'écran « Sources MQ4/MQ5 » : les robots d'un côté,
les indicateurs de l'autre, chacun avec tout ce qui va avec. L'utilisateur choisit les
outils (un, deux, trois ou plus), peut les réunir en **groupes de dossiers** qu'il nomme, et
choisit un **dossier par outil** ou **un seul grand dossier**. Copie vérifiée après
validation : les originaux ne bougent pas.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit

from mtlm.app.families import FamilyRow, FamilyService
from mtlm.core.i18n import tr
from mtlm.ui.base import fill_table, make_table, selected_values
from mtlm.ui.pages_main import Page
from mtlm.ui.window import UiApp


class IsolatedToolsPage(Page):
    tool_type = "ea"
    singular, plural = "robot", "robots"

    def __init__(self, app: UiApp) -> None:
        self.singular, self.plural = tr(self.singular), tr(self.plural)
        super().__init__(app)
        self.groups: dict[int, str] = {}
        self.banner(
            tr(
                "Un endroit à part pour vos <b>{plural}</b>, séparé des sources MQ4/MQ5. "
                "Cliquez sur les {plural} voulus (un clic ajoute, un autre retire), "
                "réunissez-les si vous voulez dans des <b>groupes</b> (« Mettre dans un "
                "groupe… »), puis choisissez <b>un dossier par {singular}</b> ou <b>un "
                "seul grand dossier</b>. Chaque {singular} vient avec <b>son dossier "
                "entier</b> (même s'il n'y a que l'EX4/EX5) et tout ce qui va avec : "
                "versions, SET, indicateurs utilisés, DLL, modèles, images. <b>Aucun "
                "doublon</b> : un fichier identique n'est copié qu'une fois. Vos "
                "originaux ne bougent pas.",
                plural=self.plural,
                singular=self.singular,
            ),
            "banner",
        )
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            tr("Rechercher un {singular} par son nom…", singular=self.singular)
        )
        self.search.returnPressed.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.layout_.addLayout(filters)
        self.tools = make_table(
            ["N°", tr("Nom"), tr("Plateforme"), tr("Fichiers"), tr("Versions"), tr("Groupe")],
            multi=True,
            noun=self.singular,
        )
        self.layout_.addWidget(self.tools, 1)
        self.button_row(
            *self.select_buttons("outils", self.tools),
            self.btn("grouper", tr("Mettre dans un groupe…"), self.group_selected),
            self.btn("degrouper", tr("Retirer du groupe"), self.ungroup_selected),
            self.btn(
                "corbeille",
                tr("Mettre les {plural} choisis à la Corbeille", plural=self.plural),
                self.trash,
            ),
        )
        self.mode = QComboBox()
        self.mode.setAccessibleName(tr("Rangement"))
        self.mode.addItem(
            tr("Un dossier par {singular}, avec tout dedans", singular=self.singular), "par_outil"
        )
        self.mode.addItem(tr("Un seul grand dossier : tous les fichiers ensemble"), "un_dossier")
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode)
        mode_row.addStretch(1)
        self.layout_.addLayout(mode_row)
        self.button_row(
            self.btn(
                "isoler",
                tr("Isoler les {plural} choisis…", plural=self.plural),
                self.isolate_selected,
            ),
            self.btn(
                "isoler_tout", tr("Isoler tous les {plural}…", plural=self.plural), self.isolate_all
            ),
            self.btn("actualiser", tr("Actualiser"), self.refresh),
        )

    def _rows(self) -> list[FamilyRow]:
        ctx = self.app.ctx
        return FamilyService(ctx.conn, ctx.clock, ctx.journal).find(
            text=self.search.text().strip() or None, tool_type=self.tool_type, limit=20000
        )

    def refresh(self) -> None:
        fill_table(
            self.tools,
            [
                (
                    r.id,
                    r.display_name,
                    (r.platform or "").upper(),
                    r.members,
                    r.versions,
                    self.groups.get(r.id, ""),
                )
                for r in self._rows()
            ],
        )

    def _chosen(self) -> list[int]:
        return [int(v) for v in selected_values(self.tools)]

    def group_selected(self) -> None:
        chosen = self._chosen()
        if not chosen:
            self.app.dialogs.info(
                self.win,
                tr("Mettre dans un groupe"),
                tr(
                    "Cliquez d'abord sur les {plural} à réunir, puis recommencez.",
                    plural=self.plural,
                ),
            )
            return
        existing = sorted(set(self.groups.values()))
        hint = tr(" Groupes existants : {v}.", v=", ".join(existing)) if existing else ""
        name = self.app.dialogs.ask_text(
            self,
            tr("Mettre dans un groupe"),
            tr(
                "Nom du groupe (il deviendra un dossier) pour {v} {singular}(s).",
                v=len(chosen),
                singular=self.singular,
            )
            + hint,
            existing[-1] if existing else "",
        )
        if name is None or not name.strip():
            self.app.status(tr("Aucun groupe créé."))
            return
        for family_id in chosen:
            self.groups[family_id] = name.strip()
        self.refresh()
        self.app.status(
            tr(
                "{v} {singular}(s) dans le groupe « {v2} ».",
                v=len(chosen),
                singular=self.singular,
                v2=name.strip(),
            )
        )

    def ungroup_selected(self) -> None:
        chosen = self._chosen()
        for family_id in chosen:
            self.groups.pop(family_id, None)
        self.refresh()
        self.app.status(
            tr("{v} {singular}(s) retiré(s) de leur groupe.", v=len(chosen), singular=self.singular)
        )

    def trash(self) -> None:
        """Tous les fichiers des outils choisis (versions MQ4/MQ5, compilés EX4/EX5, SET de
        la famille) partent à la Corbeille, après confirmation."""
        chosen = self._chosen()
        if not chosen:
            self.app.dialogs.info(
                self.win,
                tr("Corbeille"),
                tr("Cliquez d'abord sur les {plural} à supprimer.", plural=self.plural),
            )
            return
        marks = ",".join("?" * len(chosen))
        files = [
            int(r[0])
            for r in self.conn.execute(
                "SELECT fm.file_id FROM family_member fm JOIN file_record f ON f.id = fm.file_id"
                f" WHERE fm.family_id IN ({marks}) AND f.presence = 'present' ORDER BY f.rel_path",
                chosen,
            )
        ]
        names = [
            item.text()
            for r in self.tools.selectionModel().selectedRows()[:5]
            if (item := self.tools.item(r.row(), 1)) is not None
        ]
        self.trash_with_confirmation(
            files,
            "outils",
            tr(
                "{v} {singular}(s) choisi(s) ({v2}{v3}) : leurs {v4} fichier(s) "
                "(versions, compilés, SET de la famille) partent à la Corbeille.",
                v=len(chosen),
                singular=self.singular,
                v2=", ".join(names),
                v3=" …" if len(chosen) > 5 else "",
                v4=len(files),
            ),
        )

    def isolate_selected(self) -> None:
        chosen = self._chosen()
        if not chosen:
            self.app.dialogs.info(
                self.win,
                tr("Isoler les {plural}", plural=self.plural),
                tr(
                    "Cliquez sur les {plural} à isoler (un, deux, trois ou plus), puis "
                    "recommencez.",
                    plural=self.plural,
                ),
            )
            return
        self._propose(chosen)

    def isolate_all(self) -> None:
        ids = [r.id for r in self._rows()]
        if not ids:
            self.app.dialogs.info(
                self.win,
                tr("Isoler les {plural}", plural=self.plural),
                tr("Aucun {singular} reconnu : lancez d'abord l'analyse.", singular=self.singular),
            )
            return
        self._propose(ids)

    def _propose(self, ids: list[int]) -> None:
        mode = str(self.mode.currentData())
        groups = {i: g for i, g in self.groups.items() if i in ids}
        names = sorted(set(groups.values()))
        where = (
            tr("un dossier par {singular}", singular=self.singular)
            if mode == "par_outil"
            else tr("un seul grand dossier")
        )
        grouped = (
            tr(
                " Groupes : {v} ({v2} {singular}(s)) ; les autres sont à la racine.",
                v=", ".join(names),
                v2=len(groups),
                singular=self.singular,
            )
            if names
            else ""
        )
        tool_type = self.tool_type
        self.propose_folder(
            tr("Isoler les {plural}", plural=self.plural),
            tr(
                "{v} {singular}(s), rangés à part ({where}), chacun avec tout ce qui va "
                "avec.{grouped}",
                v=len(ids),
                singular=self.singular,
                where=where,
                grouped=grouped,
            ),
            lambda svc, destination: svc.preview_isolated(
                destination, tool_type, ids, groups=groups, mode=mode
            ),
        )


class RobotsPage(IsolatedToolsPage):
    key, title, icon = "robots_isoles", "Robots isolés", "🤖"
    subtitle = "Vos robots à part, seuls ou en groupes de dossiers, avec tout ce qui va avec."
    tool_type = "ea"
    singular, plural = "robot", "robots"


class IndicatorsPage(IsolatedToolsPage):
    key, title, icon = "indicateurs_isoles", "Indicateurs isolés", "📈"
    subtitle = "Vos indicateurs à part, seuls ou en groupes de dossiers, avec tout ce qui va avec."
    tool_type = "indicator"
    singular, plural = "indicateur", "indicateurs"
