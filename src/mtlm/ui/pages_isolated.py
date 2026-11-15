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
from mtlm.ui.base import fill_table, make_table, selected_values
from mtlm.ui.pages_main import Page
from mtlm.ui.window import UiApp


class IsolatedToolsPage(Page):
    tool_type = "ea"
    singular, plural = "robot", "robots"

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.groups: dict[int, str] = {}
        self.banner(
            f"Un endroit à part pour vos <b>{self.plural}</b>, séparé des sources MQ4/MQ5. "
            f"Cliquez sur les {self.plural} voulus (un clic ajoute, un autre retire), "
            "réunissez-les si vous voulez dans des <b>groupes</b> (« Mettre dans un "
            "groupe… »), puis choisissez <b>un dossier par "
            f"{self.singular}</b> ou <b>un seul grand dossier</b>. Chaque {self.singular} vient "
            "avec tout ce qui va avec : versions MQ4/MQ5, compilés EX4/EX5, SET, indicateurs "
            "utilisés, DLL, modèles, images. Vos originaux ne bougent pas.",
            "banner",
        )
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Rechercher un {self.singular} par son nom…")
        self.search.returnPressed.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.layout_.addLayout(filters)
        self.tools = make_table(
            ["N°", "Nom", "Plateforme", "Fichiers", "Versions", "Groupe"], multi=True
        )
        self.layout_.addWidget(self.tools, 1)
        self.button_row(
            *self.select_buttons("outils", self.tools),
            self.btn("grouper", "Mettre dans un groupe…", self.group_selected),
            self.btn("degrouper", "Retirer du groupe", self.ungroup_selected),
        )
        self.mode = QComboBox()
        self.mode.setAccessibleName("Rangement")
        self.mode.addItem(f"Un dossier par {self.singular}, avec tout dedans", "par_outil")
        self.mode.addItem("Un seul grand dossier : tous les fichiers ensemble", "un_dossier")
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode)
        mode_row.addStretch(1)
        self.layout_.addLayout(mode_row)
        self.button_row(
            self.btn("isoler", f"Isoler les {self.plural} choisis…", self.isolate_selected),
            self.btn("isoler_tout", f"Isoler tous les {self.plural}…", self.isolate_all),
            self.btn("actualiser", "Actualiser", self.refresh),
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
                "Mettre dans un groupe",
                f"Cliquez d'abord sur les {self.plural} à réunir, puis recommencez.",
            )
            return
        existing = sorted(set(self.groups.values()))
        hint = f" Groupes existants : {', '.join(existing)}." if existing else ""
        name = self.app.dialogs.ask_text(
            self,
            "Mettre dans un groupe",
            f"Nom du groupe (il deviendra un dossier) pour {len(chosen)} {self.singular}(s)."
            + hint,
            existing[-1] if existing else "",
        )
        if name is None or not name.strip():
            self.app.status("Aucun groupe créé.")
            return
        for family_id in chosen:
            self.groups[family_id] = name.strip()
        self.refresh()
        self.app.status(f"{len(chosen)} {self.singular}(s) dans le groupe « {name.strip()} ».")

    def ungroup_selected(self) -> None:
        chosen = self._chosen()
        for family_id in chosen:
            self.groups.pop(family_id, None)
        self.refresh()
        self.app.status(f"{len(chosen)} {self.singular}(s) retiré(s) de leur groupe.")

    def isolate_selected(self) -> None:
        chosen = self._chosen()
        if not chosen:
            self.app.dialogs.info(
                self.win,
                f"Isoler les {self.plural}",
                f"Cliquez sur les {self.plural} à isoler (un, deux, trois ou plus), puis "
                "recommencez.",
            )
            return
        self._propose(chosen)

    def isolate_all(self) -> None:
        ids = [r.id for r in self._rows()]
        if not ids:
            self.app.dialogs.info(
                self.win,
                f"Isoler les {self.plural}",
                f"Aucun {self.singular} reconnu : lancez d'abord l'analyse.",
            )
            return
        self._propose(ids)

    def _propose(self, ids: list[int]) -> None:
        mode = str(self.mode.currentData())
        groups = {i: g for i, g in self.groups.items() if i in ids}
        names = sorted(set(groups.values()))
        where = (
            f"un dossier par {self.singular}" if mode == "par_outil" else "un seul grand dossier"
        )
        grouped = (
            f" Groupes : {', '.join(names)} ({len(groups)} {self.singular}(s)) ; les autres "
            "sont à la racine."
            if names
            else ""
        )
        tool_type = self.tool_type
        self.propose_folder(
            f"Isoler les {self.plural}",
            f"{len(ids)} {self.singular}(s), rangés à part ({where}), chacun avec tout ce "
            f"qui va avec.{grouped}",
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
