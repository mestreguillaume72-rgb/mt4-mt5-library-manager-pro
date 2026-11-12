"""Écrans : SET et associations, familles/versions, doublons et similarités."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mtlm.app.companions import DEPENDENCY_LABELS, KIND_LABELS, CompanionService
from mtlm.app.companions import PLACEMENT_LABELS as LINK_PLACEMENTS
from mtlm.app.deletion import DeletionService
from mtlm.app.duplicates import DuplicateService
from mtlm.app.families import TYPE_LABELS, FamilyService
from mtlm.app.presenters import RELATION_LABELS, human_size
from mtlm.app.sets import LEVEL_LABELS, PLACEMENT_LABELS, AssociationService, SetService
from mtlm.ui.base import fill_table, make_table, selected_value, selected_values
from mtlm.ui.pages_main import Page, two_columns
from mtlm.ui.window import UiApp

DECISIONS = {"none": "non décidée", "accepted": "ACCEPTÉE", "rejected": "rejetée"}
POLARITY = {"pour": "+ pour", "contre": "− contre", "incertitude": "? incertitude"}
EVIDENCE_LABELS = {
    "couverture_parametres": "Paramètres en commun",
    "compatibilite_types": "Types de valeurs compatibles",
    "valeurs_par_defaut": "Valeurs par défaut identiques",
    "parametres_inconnus_du_robot": "Paramètres inconnus du robot",
    "parametres_inaccessibles": "Paramètres du robot illisibles (EX4/EX5 seul)",
    "similarite_noms": "Ressemblance des noms de fichiers",
    "nom_du_robot_dans_le_set": "Nom du robot écrit dans le SET par MetaTrader",
    "crees_ensemble": "Créés ensemble (même date, petit lot de fichiers)",
    "emplacement": "Emplacement",
    "plateforme": "Plateforme MT4 / MT5",
}


class SetsPage(Page):
    key, title, icon = "sets", "Robots et SET", "🤖"
    subtitle = (
        "Pour chaque SET, les robots correspondants proposés avec un score et des preuves. "
        "Rien n'est validé sans vous : acceptez ou rejetez."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        filters = QHBoxLayout()
        self.only_orphans = QCheckBox("SET orphelins uniquement")
        self.only_orphans.stateChanged.connect(lambda _s: self.refresh())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer par nom de SET…")
        self.search.returnPressed.connect(self.refresh)
        self.placement = QComboBox()
        self.placement.setAccessibleName("Placement des SET")
        for label, value in (
            ("Tous les SET", None),
            (PLACEMENT_LABELS["avec_son_robot"], "avec_son_robot"),
            (PLACEMENT_LABELS["en_vrac"], "en_vrac"),
            (PLACEMENT_LABELS["avec_autre_robot"], "avec_autre_robot"),
            (PLACEMENT_LABELS["dossier_standard"], "dossier_standard"),
        ):
            self.placement.addItem(label, value)
        self.placement.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.search)
        filters.addWidget(self.placement)
        filters.addWidget(self.only_orphans)
        self.layout_.addLayout(filters)
        self.sets = make_table(
            ["N°", "SET", "Format", "Paramètres", "Associations", "Placement"],
            badge_columns=(5,),
            multi=True,
        )
        self.sets.itemSelectionChanged.connect(self.load_selected)
        self.params = make_table(
            ["Paramètre", "Valeur brute", "Normalisée", "Type", "Optimisation"]
        )
        self.layout_.addWidget(two_columns(self.sets, self.params), 2)
        self.assoc = make_table(
            ["N°", "Score", "Niveau", "Décision", "Placement", "Outil (robot, indicateur…)"],
            badge_columns=(2, 3, 4),
            multi=True,
        )
        self.assoc.itemSelectionChanged.connect(self.load_evidence)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setObjectName("sets.preuves")
        self.layout_.addWidget(two_columns(self.assoc, self.evidence), 2)
        compare_row = QHBoxLayout()
        self.compare_with = QSpinBox()
        self.compare_with.setRange(1, 2_000_000_000)
        self.compare_with.setAccessibleName("SET à comparer")
        compare_row.addWidget(QLabel("Comparer le SET choisi avec le SET n°"))
        compare_row.addWidget(self.compare_with)
        compare_row.addStretch(1)
        self.layout_.addLayout(compare_row)
        self.button_row(
            *self.select_buttons("sets", self.sets),
            self.btn(
                "accepter_meilleure",
                "Accepter la meilleure proposition des SET choisis",
                self.accept_best,
            ),
        )
        self.button_row(
            *self.select_buttons("associations", self.assoc),
            self.btn("accepter", "Accepter l'association", lambda: self.decide("accepted")),
            self.btn("rejeter", "Rejeter l'association", lambda: self.decide("rejected")),
            self.btn("annuler", "Annuler ma décision", lambda: self.decide("none")),
            self.btn("comparer", "Comparer", self.compare),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self._robot_filter: int | None = None

    def _assoc(self) -> AssociationService:
        ctx = self.app.ctx
        return AssociationService(ctx.conn, ctx.clock, ctx.journal)

    def show_item(self, file_id: int) -> None:
        """Depuis le détail d'un fichier : SET du fichier, ou SET associés au robot."""
        is_set = self.conn.execute(
            "SELECT 1 FROM set_file WHERE file_id = ?", (file_id,)
        ).fetchone()
        self._robot_filter = None if is_set else file_id
        self.refresh()
        if is_set:
            self._select_set(file_id)

    def _select_set(self, file_id: int) -> None:
        for row in range(self.sets.rowCount()):
            item = self.sets.item(row, 0)
            if item is not None and int(item.text()) == file_id:
                self.sets.selectRow(row)
                return

    def refresh(self) -> None:
        sql = (
            "SELECT f.id, f.rel_path, sf.format, sf.param_count,"
            " (SELECT count(*) FROM association a WHERE a.set_file_id = f.id)"
            " FROM set_file sf JOIN file_record f ON f.id = sf.file_id"
            " WHERE f.presence = 'present'"
        )
        params: list[object] = []
        if self.only_orphans.isChecked():
            sql += " AND NOT EXISTS (SELECT 1 FROM association a WHERE a.set_file_id = f.id)"
        if self.search.text().strip():
            sql += " AND f.rel_path LIKE ?"
            params.append(f"%{self.search.text().strip()}%")
        if self._robot_filter is not None:
            sql += " AND f.id IN (SELECT set_file_id FROM association WHERE robot_file_id = ?)"
            params.append(self._robot_filter)
        rows = self.conn.execute(sql + " ORDER BY f.rel_path LIMIT 5000", params).fetchall()
        placements = self._assoc().placements()
        wanted = self.placement.currentData()
        fill_table(
            self.sets,
            [
                (*r, PLACEMENT_LABELS.get(placements.get(int(r[0]), ""), "sans robot"))
                for r in rows
                if wanted is None or placements.get(int(r[0])) == wanted
            ],
        )
        self.load_selected()

    def _set_id(self) -> int | None:
        value = selected_value(self.sets)
        return int(value) if value else None

    def load_selected(self) -> None:
        set_id = self._set_id()
        if set_id is None:
            fill_table(self.params, [])
            fill_table(self.assoc, [])
            self.evidence.clear()
            return
        ctx = self.app.ctx
        doc = SetService(ctx.conn, ctx.clock, ctx.journal).document(set_id)
        fill_table(
            self.params,
            [
                (
                    p.name,
                    p.raw_value,
                    p.normalized_value,
                    p.estimated_type,
                    ""
                    if p.opt_start is None
                    else f"{'oui' if p.opt_enabled else 'non'} : {p.opt_start} → "
                    f"{p.opt_stop} ({p.opt_step})",
                )
                for p in (doc.params if doc else [])
            ],
        )
        rows = self._assoc().find(set_file_id=set_id, limit=50)
        fill_table(
            self.assoc,
            [
                (
                    a.id,
                    a.score,
                    LEVEL_LABELS[a.level],
                    DECISIONS[a.user_decision],
                    PLACEMENT_LABELS[a.placement],
                    a.robot_path,
                )
                for a in rows
            ],
        )
        self.evidence.setPlainText(
            "Sélectionnez une association pour voir ses preuves."
            if rows
            else "Aucun robot correspondant trouvé (SET orphelin)."
        )

    def _assoc_id(self) -> int | None:
        value = selected_value(self.assoc)
        return int(value) if value else None

    def load_evidence(self) -> None:
        assoc_id = self._assoc_id()
        if assoc_id is None:
            return
        lines = [
            f"{POLARITY[polarity]} — {EVIDENCE_LABELS.get(kind, kind)} "
            f"(poids {weight:g}, valeur {value:.2f}) : {detail}"
            for kind, weight, value, polarity, detail in self._assoc().evidence(assoc_id)
        ]
        self.evidence.setPlainText("\n".join(lines))

    def decide(self, decision: str) -> None:
        assoc_ids = [int(v) for v in selected_values(self.assoc)]
        if not assoc_ids:
            self.app.dialogs.info(
                self.win, "Associations", "Sélectionnez une ou plusieurs associations."
            )
            return
        if len(assoc_ids) > 1 and not self.app.dialogs.confirm(
            self,
            "Associations",
            f"Marquer {len(assoc_ids)} associations comme « {DECISIONS[decision]} » ?",
        ):
            return
        service = self._assoc()
        for assoc_id in assoc_ids:
            service.decide(assoc_id, decision)
        self.app.status(f"{len(assoc_ids)} association(s) : {DECISIONS[decision]}")
        self.load_selected()

    def accept_best(self) -> None:
        """Pour chaque SET choisi : accepte sa meilleure proposition (non rejetée)."""
        set_ids = [int(v) for v in selected_values(self.sets)]
        if not set_ids:
            self.app.dialogs.info(self.win, "Associations", "Sélectionnez un ou plusieurs SET.")
            return
        service = self._assoc()
        best = []
        for set_id in set_ids:
            rows = [
                a
                for a in service.find(set_file_id=set_id, limit=20)
                if a.user_decision != "rejected"
            ]
            if rows:
                best.append(rows[0])
        if not best:
            self.app.dialogs.info(
                self.win, "Associations", "Aucune proposition pour les SET choisis."
            )
            return
        weak = sum(a.level != "forte" for a in best)
        if not self.app.dialogs.confirm(
            self,
            "Accepter les meilleures propositions",
            f"Accepter la meilleure proposition de {len(best)} SET "
            f"({len(set_ids) - len(best)} sans proposition)."
            + (
                f"\n⚠️ {weak} de ces propositions ne sont pas de niveau « forte » : "
                "vérifiez leurs preuves avant d'accepter."
                if weak
                else ""
            ),
        ):
            return
        for association in best:
            service.decide(association.id, "accepted")
        self.app.status(f"{len(best)} association(s) acceptée(s).")
        self.refresh()

    def compare(self) -> None:
        set_id = self._set_id()
        if set_id is None:
            self.app.dialogs.info(self.win, "Comparer", "Sélectionnez un SET.")
            return
        ctx = self.app.ctx
        diffs = SetService(ctx.conn, ctx.clock, ctx.journal).compare(
            set_id, self.compare_with.value()
        )
        if diffs is None:
            self.app.dialogs.info(
                self.win, "Comparer", "Les deux numéros doivent désigner des SET analysés."
            )
            return
        labels = {
            "same": "=",
            "different": "≠",
            "only_left": "seulement A",
            "only_right": "seulement B",
        }
        same = sum(d.status == "same" for d in diffs)
        text = [f"{same} identique(s) sur {len(diffs)} paramètre(s)."] + [
            f"{labels[d.status]}  {d.name} : A={d.left} B={d.right}"
            for d in diffs
            if d.status != "same"
        ]
        self.evidence.setPlainText("\n".join(text))


class FamiliesPage(Page):
    key, title, icon = "familles", "Familles et versions", "🧬"
    subtitle = (
        "Chaque robot, indicateur ou script avec tout ce qui va avec : versions, copies, "
        "compilés, SET, modèles, indicateurs utilisés, DLL, images, sons, documents."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher une famille…")
        self.search.returnPressed.connect(self.refresh)
        self.tool_type = QComboBox()
        self.tool_type.setAccessibleName("Type d'outil")
        self.tool_type.addItem("Tous les outils", None)
        for value, label in TYPE_LABELS.items():
            self.tool_type.addItem(f"{label}s" if not label.endswith("s") else label, value)
        self.tool_type.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(self.search)
        row.addWidget(self.tool_type)
        self.layout_.addLayout(row)
        self.button_row(
            self.btn("rechercher", "Rechercher", self.refresh),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self.banner(
            "<b>Une famille = un robot, un indicateur ou un script et tout ce qui va avec</b> "
            ": versions, copies (même sous un autre nom), compilés, SET, modèles .tpl, "
            "indicateurs qu'il utilise, DLL et bibliothèques importées, images, sons, "
            "documents. Sélectionnez une ou plusieurs familles (Cmd+clic, Maj+clic) puis "
            "« Proposer un dossier » : vous voyez d'abord la proposition, puis vous validez.",
            "banner",
        )
        self.families = make_table(
            ["N°", "Famille", "Plateforme", "Membres", "Versions", "Confiance", "Type"],
            badge_columns=(5,),
            multi=True,
        )
        self.families.itemSelectionChanged.connect(self.load_members)
        self.button_row(*self.select_buttons("familles", self.families))
        self.reasons = QPlainTextEdit()
        self.reasons.setReadOnly(True)
        self.members = make_table(
            ["Fichier", "Relation", "Version estimée", "Base", "Chemin"],
            badge_columns=(1,),
            multi=True,
        )
        self.linked = make_table(
            ["Fichier", "Type", "Lien", "Placement", "Outil", "Indices", "Chemin"],
            badge_columns=(2, 3),
            multi=True,
        )
        self.deps = make_table(["Outil", "A besoin de", "Comment", "Fichier utilisé"])
        self.layout_.addWidget(self.families, 2)
        self.layout_.addWidget(self.reasons, 1)
        tabs = QTabWidget()
        tabs.addTab(self.members, "Fichiers de la famille")
        tabs.addTab(self.linked, "Fichiers liés (images, sons, modèles, DLL…)")
        tabs.addTab(self.deps, "Dépendances (indicateurs utilisés, bibliothèques)")
        self.tabs = tabs
        self.layout_.addWidget(tabs, 2)
        self.button_row(
            self.btn(
                "dossier", "Proposer un dossier pour les familles choisies…", self.propose_family
            ),
            self.btn("corbeille", "Mettre les fichiers choisis à la Corbeille", self.trash_member),
            *self.select_buttons("fichiers", self.members),
        )

    def _families_selected(self) -> list[int]:
        return [int(v) for v in selected_values(self.families)]

    def propose_family(self) -> None:
        families = self._families_selected()
        if not families:
            self.app.dialogs.info(
                self.win, "Dossier de famille", "Sélectionnez une ou plusieurs familles."
            )
            return
        names = selected_values(self.families, 1)
        what = (
            f"Toute la famille « {names[0]} » réunie dans un dossier au nom du robot"
            if len(families) == 1
            else f"Les {len(families)} familles choisies réunies dans un dossier, un "
            "sous-dossier par robot"
        )
        self.propose_folder(
            "Dossier de famille",
            f"{what} : versions, copies, compilés, SET, modèles, indicateurs utilisés, DLL et "
            "bibliothèques, images, sons et documents. Chaque fichier garde le nom de son "
            "dossier d'origine ; les fichiers liés sont rangés dans « Images », « Modèles », "
            "« Bibliothèques »…",
            lambda service, destination: service.preview_families(destination, families),
        )

    def trash_member(self) -> None:
        table = self.linked if self.tabs.currentIndex() == 1 else self.members
        path_column = 6 if table is self.linked else 4
        file_ids = [int(v) for v in selected_values(table)]
        if not file_ids:
            self.app.dialogs.info(
                self.win,
                "Corbeille",
                "Sélectionnez un ou plusieurs fichiers dans « Fichiers de la famille » ou "
                "« Fichiers liés ».",
            )
            return
        unique = [
            file_id
            for file_id in file_ids
            if not int(
                self.conn.execute(
                    "SELECT count(*) FROM file_record o JOIN file_record f ON f.id = ?"
                    " WHERE o.content_id = f.content_id AND o.id <> f.id"
                    " AND o.presence = 'present'",
                    (file_id,),
                ).fetchone()[0]
            )
        ]
        paths = selected_values(table, path_column)
        intro = f"{len(file_ids)} fichier(s) choisi(s) : " + ", ".join(paths[:5])
        if len(paths) > 5:
            intro += " …"
        if unique:
            intro += (
                f"\n{len(unique)} d'entre eux sont le SEUL exemplaire de leur contenu "
                "(version unique) : aucune autre copie ne sera conservée."
            )
        self.trash_with_confirmation(file_ids, "familles", intro, allow_unique=bool(unique))

    def _service(self) -> FamilyService:
        ctx = self.app.ctx
        return FamilyService(ctx.conn, ctx.clock, ctx.journal)

    def refresh(self) -> None:
        rows = self._service().find(
            text=self.search.text().strip() or None,
            limit=2000,
            tool_type=self.tool_type.currentData(),
        )
        fill_table(
            self.families,
            [
                (
                    r.id,
                    r.display_name,
                    r.platform,
                    r.members,
                    r.versions,
                    r.confidence,
                    TYPE_LABELS.get(r.tool_type, ""),
                )
                for r in rows
            ],
        )
        self.load_members()

    def show_item(self, file_id: int) -> None:
        family_id = self._service().family_of(file_id)
        self.search.clear()
        self.tool_type.setCurrentIndex(0)
        self.refresh()
        if family_id is None:
            self.reasons.setPlainText(
                f"Le fichier {file_id} n'appartient à aucune famille "
                "(relancez l'étape « Familles »)."
            )
            return
        for row in range(self.families.rowCount()):
            item = self.families.item(row, 0)
            if item is not None and int(item.text()) == family_id:
                self.families.selectRow(row)
                return

    def load_members(self) -> None:
        families = self._families_selected()
        if not families:
            for table in (self.members, self.linked, self.deps):
                fill_table(table, [])
            self.reasons.clear()
            return
        reasons: list[str] = []
        members = []
        for family_id in families[:50]:
            found = self._service().detail(family_id)
            if found is None:
                continue
            _row, basis, family_members = found
            if len(families) == 1:
                reasons += [f"Raison : {b}" for b in basis]
            members += family_members
        if len(families) > 1:
            reasons.append(
                f"{len(families)} familles choisies : leurs fichiers sont listés ensemble."
            )
        self.reasons.setPlainText("\n".join(reasons))
        ctx = self.app.ctx
        companions = CompanionService(ctx.conn, ctx.clock, ctx.journal)
        member_ids = [m.file_id for m in members]
        seen: set[int] = set()
        rows = []
        for link in companions.for_tools(member_ids):
            if link.companion_id in seen:
                continue
            seen.add(link.companion_id)
            rows.append(
                (
                    link.companion_id,
                    KIND_LABELS.get(link.kind, link.kind),
                    link.confidence,
                    LINK_PLACEMENTS[link.placement],
                    link.tool_path.rpartition("/")[2],
                    " ; ".join(link.evidence),
                    link.companion_path,
                )
            )
        fill_table(self.linked, rows)
        self.tabs.setTabText(1, f"Fichiers liés (images, sons, modèles, DLL…) : {len(rows)}")
        dependencies = companions.dependencies(member_ids)
        fill_table(
            self.deps,
            [
                (
                    d.user_path.rpartition("/")[2],
                    d.used_path.rpartition("/")[2],
                    DEPENDENCY_LABELS.get(d.kind, d.kind),
                    d.used_path,
                )
                for d in dependencies
            ],
        )
        self.tabs.setTabText(
            2, f"Dépendances (indicateurs utilisés, bibliothèques) : {len(dependencies)}"
        )
        fill_table(
            self.members,
            [
                (
                    m.file_id,
                    RELATION_LABELS.get(m.relation, m.relation),
                    m.estimated_version,
                    m.version_basis,
                    m.rel_path,
                )
                for m in members
            ],
        )


class DuplicatesPage(Page):
    key, title, icon = "doublons", "Doublons", "👯"
    subtitle = (
        "Doublons exacts (identiques octet pour octet) et fichiers seulement similaires, "
        "toujours séparés."
    )

    def __init__(self, app: UiApp) -> None:
        super().__init__(app)
        self.banner(
            "<b>Doublons exacts</b> : contenu identique octet pour octet (seuls "
            "candidats possibles à la quarantaine). <b>Similaires</b> : jamais des "
            "doublons, uniquement informatifs.",
            "banner",
        )
        tabs = QTabWidget()
        exact = QWidget()
        exact_layout = QVBoxLayout(exact)
        self.groups = make_table(
            ["Groupe", "Fichiers", "Taille", "SHA-256", "Référence", "Choisie par vous"],
            badge_columns=(5,),
            multi=True,
        )
        self.groups.itemSelectionChanged.connect(self.load_members)
        self.members = make_table(
            ["Fichier", "Rôle", "Chemin", "Groupe"], badge_columns=(1,), multi=True
        )
        exact_layout.addWidget(self.groups, 1)
        group_buttons = QHBoxLayout()
        for button in self.select_buttons("groupes", self.groups):
            group_buttons.addWidget(button)
        group_buttons.addStretch(1)
        exact_layout.addLayout(group_buttons)
        exact_layout.addWidget(self.members, 1)
        member_buttons = QHBoxLayout()
        for button in self.select_buttons("fichiers", self.members):
            member_buttons.addWidget(button)
        member_buttons.addStretch(1)
        exact_layout.addLayout(member_buttons)
        tabs.addTab(exact, "Doublons exacts")
        similar = QWidget()
        similar_layout = QVBoxLayout(similar)
        self.kind = QComboBox()
        for label, value in (
            ("Toutes les similarités", None),
            ("Équivalents normalisés", "text_normalized_equal"),
            ("Sources similaires", "text_similar"),
            ("SET similaires", "set_similar"),
        ):
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(lambda _i: self.refresh())
        self.similar = make_table(
            ["Score", "Type", "Fichier A", "Fichier B", "Méthode"], badge_columns=(1,)
        )
        similar_layout.addWidget(self.kind)
        similar_layout.addWidget(self.similar, 1)
        tabs.addTab(similar, "Similaires")
        self.layout_.addWidget(tabs, 1)
        self.button_row(
            self.btn("reference", "Conserver ce fichier comme référence", self.set_reference),
            self.btn("octets", "Vérifier octet par octet", self.verify_bytes),
            self.btn("actualiser", "Actualiser", self.refresh),
        )
        self.button_row(
            self.btn(
                "corbeille_groupe",
                "Mettre à la Corbeille les copies en trop des groupes choisis",
                self.trash_group,
            ),
            self.btn(
                "corbeille_fichier", "Mettre les fichiers choisis à la Corbeille", self.trash_one
            ),
        )

    def _deletion(self) -> DeletionService:
        ctx = self.app.ctx
        return DeletionService(ctx.conn, ctx.clock, ctx.journal, ctx.trash)

    def _groups_selected(self) -> list[int]:
        return [int(v) for v in selected_values(self.groups)]

    def trash_group(self) -> None:
        groups = self._groups_selected()
        if not groups:
            self.app.dialogs.info(
                self.win, "Corbeille", "Sélectionnez un ou plusieurs groupes de doublons."
            )
            return
        deletion = self._deletion()
        surplus = [f for group in groups for f in deletion.surplus_of_group(group)]
        self.trash_with_confirmation(
            surplus,
            "doublons",
            f"{len(groups)} groupe(s) choisi(s) : la référence de chaque groupe est conservée, "
            f"leurs {len(surplus)} copie(s) identique(s) partent à la Corbeille.",
        )

    def trash_one(self) -> None:
        members = [int(v) for v in selected_values(self.members)]
        if not members:
            self.app.dialogs.info(
                self.win,
                "Corbeille",
                "Sélectionnez un ou plusieurs groupes, puis les fichiers à supprimer.",
            )
            return
        marks = ",".join("?" * len(members))
        references = {
            int(r[0])
            for r in self.conn.execute(
                "SELECT reference_file_id FROM duplicate_group"
                f" WHERE reference_file_id IN ({marks})",
                members,
            )
        }
        kept = [m for m in members if m not in references]
        if not kept:
            self.app.dialogs.info(
                self.win,
                "Corbeille",
                "Les fichiers choisis sont des RÉFÉRENCES conservées. Choisissez d'abord une "
                "autre référence (« Conserver ce fichier comme référence »).",
            )
            return
        note = (
            f"\n{len(references)} référence(s) sélectionnée(s) ignorée(s) : elles restent en place."
            if references
            else ""
        )
        self.trash_with_confirmation(
            kept, "doublons", f"{len(kept)} fichier(s) choisi(s) dans les doublons.{note}"
        )

    def _service(self) -> DuplicateService:
        ctx = self.app.ctx
        return DuplicateService(ctx.conn, ctx.clock, ctx.journal)

    def refresh(self) -> None:
        service = self._service()
        fill_table(
            self.groups,
            [
                (
                    g.id,
                    g.member_count,
                    human_size(g.size),
                    g.sha256_hex[:20],
                    g.reference_file_id,
                    "oui" if g.reference_chosen_by_user else "non",
                )
                for g in service.groups(limit=5000)
            ],
        )
        labels = {
            "text_normalized_equal": "équivalent normalisé",
            "text_similar": "source similaire",
            "set_similar": "SET similaire",
        }
        fill_table(
            self.similar,
            [
                (round(r.score, 3), labels[r.kind], r.path_a, r.path_b, r.method)
                for r in service.similar(self.kind.currentData(), limit=5000)
            ],
        )
        self.load_members()

    def _group(self) -> int | None:
        value = selected_value(self.groups)
        return int(value) if value else None

    def load_members(self) -> None:
        groups = self._groups_selected()
        service = self._service()
        fill_table(
            self.members,
            [
                (
                    m.file_id,
                    "RÉFÉRENCE (conservée)"
                    if m.is_reference
                    else (
                        "admissible à la quarantaine"
                        if m.admissible
                        else f"non admissible : {m.reason}"
                    ),
                    m.rel_path,
                    group,
                )
                for group in groups[:500]
                for m in service.members(group)
            ],
        )

    def set_reference(self) -> None:
        member = selected_value(self.members)
        group = selected_value(self.members, 3)
        if member is None or group is None:
            self.app.dialogs.info(
                self.win, "Référence", "Sélectionnez un groupe puis le fichier à conserver."
            )
            return
        self._service().set_reference(int(group), int(member))
        self.load_members()

    def verify_bytes(self) -> None:
        groups = self._groups_selected()
        if not groups:
            self.app.dialogs.info(self.win, "Vérification", "Sélectionnez un ou plusieurs groupes.")
            return
        different = [g for g in groups if not self._service().verify_bytewise(g)]
        self.app.dialogs.info(
            self.win,
            "Vérification octet par octet",
            f"{len(groups) - len(different)} groupe(s) identique(s) octet par octet."
            + (
                f"\n{len(different)} groupe(s) DIFFÉRENT(S) : {', '.join(map(str, different))} "
                "— leurs fichiers ne sont plus admissibles."
                if different
                else ""
            ),
        )
        self.load_members()
