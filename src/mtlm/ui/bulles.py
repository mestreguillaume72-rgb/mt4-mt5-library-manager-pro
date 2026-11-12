"""Bulles d'aide (infobulles) en français : à quoi sert chaque bouton, liste et zone.

Elles s'affichent quand la souris reste un instant sur un élément. Toutes les bulles sont
réunies ici pour être relues et corrigées facilement ; un test vérifie qu'aucun bouton n'en
est dépourvu et que chaque bulle de zone désigne un élément qui existe.
"""

from __future__ import annotations

_VOIR = "Ouvre l'écran qui détaille ce chiffre."

#: Boutons : identifiant de l'action → explication.
ACTION_TIPS: dict[str, str] = {
    # Accueil
    "tableau.ajouter": "Étape 1 : choisissez le dossier qui contient vos robots, indicateurs "
    "et SET. Il est seulement lu : rien n'y est modifié.",
    "tableau.analyser": "Étape 2 : lance toute l'analyse (inventaire, empreintes, "
    "reconnaissance, SET, familles, doublons). Vous pouvez la mettre en pause ou l'annuler.",
    "tableau.resultats": "Étape 3 : ouvre les résultats, en commençant par les associations "
    "robot ↔ SET à vérifier.",
    "tableau.pause": "Met l'analyse en pause, ou la relance si elle est déjà en pause.",
    "tableau.annuler": "Arrête l'analyse en cours. Ce qui est déjà fait est conservé ; vous "
    "pourrez relancer plus tard.",
    "tableau.voir_robots": _VOIR,
    "tableau.voir_sets": _VOIR,
    "tableau.voir_assoc_strong": _VOIR,
    "tableau.voir_assoc_check": "Ouvre les associations robot ↔ SET qui attendent votre avis.",
    "tableau.voir_dup_groups": _VOIR,
    "tableau.voir_reclaim": "Ouvre la quarantaine pour mettre de côté les copies en trop.",
    "tableau.voir_families": _VOIR,
    "tableau.voir_files": "Ouvre l'explorateur de tous les fichiers analysés.",
    "tableau.actualiser": "Recharge les chiffres de l'accueil.",
    # Mes dossiers
    "sources.ajouter": "Ajoute un dossier de votre bibliothèque MetaTrader. Il sera seulement lu.",
    "sources.inventorier": "Relit le dossier choisi dans la liste pour trouver les fichiers "
    "ajoutés, modifiés ou disparus.",
    "sources.retirer": "Retire le dossier choisi de l'application. Aucun fichier n'est "
    "supprimé sur votre disque.",
    "sources.actualiser": "Recharge la liste de vos dossiers.",
    # Analyse
    "analyse.lancer": "Lance seulement les étapes cochées ci-dessus.",
    "analyse.tout": "Lance toutes les étapes de l'analyse, dans l'ordre.",
    "analyse.pause": "Met l'analyse en pause (elle reprend là où elle s'est arrêtée).",
    "analyse.reprendre": "Reprend l'analyse mise en pause.",
    "analyse.annuler": "Arrête l'analyse en cours ; ce qui est fait est conservé.",
    "analyse.erreurs": "Affiche les fichiers qui n'ont pas pu être lus pendant la tâche "
    "choisie dans la liste, avec la raison.",
    # Explorer et détail
    "explorateur.rechercher": "Applique les filtres et la recherche à la liste des fichiers.",
    "explorateur.precedente": "Affiche la page précédente de la liste.",
    "explorateur.suivante": "Affiche la page suivante de la liste.",
    "explorateur.detail": "Ouvre la fiche complète du fichier choisi.",
    "detail.afficher": "Affiche la fiche du fichier dont vous avez saisi le numéro.",
    "detail.famille": "Ouvre la famille (versions, copies, SET, fichiers liés) de ce fichier.",
    "detail.associations": "Ouvre les SET associés à ce robot, ou les robots de ce SET.",
    # Robots et SET
    "sets.accepter": "Confirme que ce SET va bien avec ce robot. Rien n'est jamais validé "
    "sans vous.",
    "sets.rejeter": "Indique que ce SET ne va pas avec ce robot ; la proposition ne sera plus "
    "retenue.",
    "sets.annuler": "Efface votre décision : l'association redevient « non décidée ».",
    "sets.comparer": "Compare le SET choisi avec le SET dont vous avez saisi le numéro, "
    "paramètre par paramètre.",
    "sets.actualiser": "Recharge la liste des SET et des associations.",
    # Familles
    "familles.rechercher": "Cherche une famille par le nom du robot ou de l'outil.",
    "familles.actualiser": "Recharge la liste des familles.",
    "familles.dossier": "Propose de réunir CETTE famille (versions, copies, compilés, SET, "
    "images…) dans un nouveau dossier au nom du robot. Vous voyez la proposition avant de "
    "valider ; la copie est vérifiée et vos originaux ne bougent pas.",
    "familles.corbeille": "Met le fichier choisi dans « Fichiers de la famille » à la "
    "Corbeille du Mac, après confirmation. Si c'est le seul exemplaire, vous êtes prévenu.",
    # Doublons
    "doublons.reference": "Garde le fichier choisi comme exemplaire de référence du groupe : "
    "c'est lui qui reste en place.",
    "doublons.octets": "Compare octet par octet tous les fichiers du groupe pour être "
    "absolument sûr qu'ils sont identiques.",
    "doublons.actualiser": "Recharge la liste des doublons.",
    "doublons.corbeille_groupe": "Met à la Corbeille du Mac toutes les copies en trop du "
    "groupe choisi ; la référence reste. Chaque copie est revérifiée avant.",
    "doublons.corbeille_fichier": "Met à la Corbeille du Mac le fichier choisi du groupe, "
    "après confirmation. La référence est protégée.",
    # Quarantaine
    "quarantaine.destination": "Étape 1 : choisissez un dossier de quarantaine, de préférence "
    "sur un autre disque et en dehors de vos bibliothèques.",
    "quarantaine.simuler": "Étape 2 : montre ce qui serait copié en quarantaine, sans rien copier.",
    "quarantaine.executer": "Étape 3 : copie les doublons en quarantaine et vérifie chaque "
    "copie. Vos originaux restent en place.",
    "quarantaine.restaurer": "Sort les fichiers du lot choisi de la quarantaine (ils "
    "réapparaissent normalement dans l'application).",
    "quarantaine.recopier": "Comme « Restaurer », et recopie depuis la quarantaine les "
    "originaux disparus entre-temps, sans rien écraser.",
    "quarantaine.annuler": "Annule un lot simulé ou interrompu.",
    "quarantaine.corbeille": "Étape 4 : vous validez la suppression des originaux en trop "
    "du lot choisi. Ils vont dans la Corbeille du Mac ; une copie identique est conservée.",
    "quarantaine.remettre": "Remet le fichier choisi à son emplacement d'origine (s'il est "
    "encore dans la Corbeille), sans rien écraser.",
    "quarantaine.actualiser": "Recharge les lots et la liste de la Corbeille.",
    # Bibliothèque rangée
    "organisation.destination": "Étape 1 : choisissez où créer la copie rangée (un nouveau "
    "dossier y sera créé).",
    "organisation.previsualiser": "Étape 2 : montre le rangement prévu, sans rien copier.",
    "organisation.executer": "Étape 3 : crée la copie rangée et vérifie chaque fichier.",
    "organisation.actualiser": "Recharge la liste des plans de rangement.",
    # Rapports
    "rapports.exporter": "Enregistre le rapport choisi dans un fichier CSV (tableur) ou JSON.",
    "rapports.audit_exporter": "Enregistre le journal de toutes les actions sensibles.",
    "rapports.audit_verifier": "Vérifie que le journal d'audit n'a pas été modifié.",
    "rapports.sauvegarder": "Crée une sauvegarde vérifiée de la base de l'application (pas de "
    "vos fichiers MetaTrader).",
    "rapports.actualiser": "Recharge le journal et les rapports.",
    # Paramètres et aide
    "parametres.enregistrer": "Enregistre les réglages modifiés.",
    "parametres.defaut": "Remet tous les réglages à leur valeur d'origine.",
    "aide.demarrer": "Ouvre l'écran « Mes dossiers » pour ajouter votre bibliothèque.",
}

#: Zones des écrans : (écran, attribut) → explication.
WIDGET_TIPS: dict[tuple[str, str], str] = {
    ("sets", "search"): "Tapez une partie du nom d'un SET puis Entrée pour filtrer la liste.",
    ("sets", "placement"): "Filtre les SET selon leur rangement : avec leur robot, en vrac "
    "(robot retrouvé ailleurs) ou rangés avec un autre robot.",
    ("sets", "only_orphans"): "N'affiche que les SET pour lesquels aucun robot n'a été trouvé.",
    ("sets", "sets"): "Tous vos SET. Cliquez sur un SET pour voir ses paramètres et les robots "
    "proposés. Colonne « Placement » : où il est rangé par rapport à son robot.",
    ("sets", "params"): "Paramètres du SET choisi, tels qu'écrits dans le fichier.",
    ("sets", "assoc"): "Robots proposés pour ce SET, du plus probable au moins probable. "
    "Choisissez une ligne puis Accepter ou Rejeter.",
    ("sets", "evidence"): "Les preuves de l'association choisie : ce qui va pour, ce qui va "
    "contre, et leur poids dans la note.",
    ("sets", "compare_with"): "Numéro (colonne N°) du SET à comparer avec le SET choisi.",
    ("familles", "search"): "Tapez le nom d'un robot ou d'un outil, puis Entrée.",
    ("familles", "families"): "Chaque ligne est un robot ou outil avec tout ce qui va avec. "
    "Cliquez pour voir ses fichiers.",
    ("familles", "reasons"): "Pourquoi ces fichiers ont été regroupés dans cette famille.",
    ("familles", "members"): "Versions, copies, fichiers compilés et SET de la famille choisie.",
    ("familles", "linked"): "Images, sons, documents et includes reliés à cette famille, avec "
    "l'indice (cité dans le code, même dossier, créés ensemble…) et leur placement.",
    ("doublons", "groups"): "Groupes de fichiers identiques octet pour octet. Cliquez pour voir "
    "les fichiers du groupe.",
    ("doublons", "members"): "Fichiers du groupe : la RÉFÉRENCE reste en place, les autres "
    "peuvent aller en quarantaine ou à la Corbeille.",
    ("doublons", "similar"): "Fichiers seulement ressemblants : ce ne sont PAS des doublons, "
    "rien n'est proposé à la suppression.",
    ("quarantaine", "batches"): "Vos lots de quarantaine. Choisissez un lot pour voir ses "
    "fichiers ou valider leur suppression.",
    ("quarantaine", "entries"): "Fichiers du lot choisi et l'état de leur copie.",
    ("quarantaine", "trashed"): "Tout ce qui a été mis à la Corbeille, avec la copie conservée. "
    "Choisissez une ligne pour la remettre en place.",
    ("organisation", "with_duplicates"): "Cochez pour copier aussi chaque doublon exact ; "
    "sinon une seule copie de chaque contenu.",
    ("organisation", "plans"): "Vos plans de rangement et leur état.",
    ("organisation", "items"): "Fichiers du plan choisi et leur emplacement dans la copie rangée.",
}

_TOUT = "Sélectionne toutes les lignes de la liste (raccourci : Cmd+A dans la liste). Pour en "
_TOUT += "choisir plusieurs : Cmd+clic ajoute une ligne, Maj+clic sélectionne une plage."
_AUCUN = "Désélectionne toutes les lignes de la liste."
for _name in (
    "familles.tout_familles",
    "familles.tout_fichiers",
    "doublons.tout_groupes",
    "doublons.tout_fichiers",
    "sets.tout_sets",
    "sets.tout_associations",
    "quarantaine.tout_lots",
    "quarantaine.tout_corbeille",
    "sources_mq.tout_sources",
):
    ACTION_TIPS[_name] = _TOUT
    ACTION_TIPS[_name.replace(".tout_", ".aucun_")] = _AUCUN
ACTION_TIPS.update(
    {
        "sets.accepter_meilleure": "Pour chaque SET sélectionné, accepte la proposition la "
        "mieux notée (jamais une proposition que vous avez rejetée). Vous confirmez une seule "
        "fois ; les propositions qui ne sont pas « forte » sont signalées.",
        "familles.dossier": "Propose de réunir la ou les familles choisies (robot ou "
        "indicateur avec ses versions, copies, compilés, SET, modèles, indicateurs utilisés, "
        "DLL, images…) dans un nouveau dossier au nom du robot. Vous voyez la proposition "
        "avant de valider ; la copie est vérifiée et vos originaux ne bougent pas.",
        "familles.corbeille": "Met les fichiers choisis (onglet « Fichiers de la famille » ou "
        "« Fichiers liés ») à la Corbeille du Mac, après une seule confirmation. Les "
        "exemplaires uniques et les fichiers utilisés par un autre outil sont signalés.",
        "doublons.corbeille_groupe": "Met à la Corbeille du Mac les copies en trop de tous les "
        "groupes choisis ; la référence de chaque groupe reste. Chaque copie est revérifiée.",
        "doublons.corbeille_fichier": "Met à la Corbeille du Mac les fichiers choisis dans la "
        "liste du bas, après une seule confirmation. Les références sont protégées.",
        "doublons.octets": "Compare octet par octet tous les fichiers des groupes choisis.",
        "doublons.reference": "Garde le fichier choisi comme exemplaire de référence de son "
        "groupe : c'est lui qui reste en place.",
        "sets.accepter": "Confirme que les associations choisies sont justes. Rien n'est "
        "jamais validé sans vous.",
        "sets.rejeter": "Indique que les associations choisies sont fausses.",
        "sets.annuler": "Efface votre décision sur les associations choisies.",
        "quarantaine.corbeille": "Étape 4 : vous validez la suppression des originaux en trop "
        "des lots choisis. Ils vont dans la Corbeille du Mac ; une copie identique est "
        "conservée.",
        "quarantaine.remettre": "Remet les fichiers choisis à leur emplacement d'origine "
        "(s'ils sont encore dans la Corbeille), sans rien écraser.",
    }
)
WIDGET_TIPS.update(
    {
        ("familles", "tool_type"): "N'affiche que les familles d'un type : robots, "
        "indicateurs, scripts, bibliothèques…",
        ("familles", "deps"): "Ce dont les outils de la famille ont besoin (indicateurs appelés "
        "par iCustom, bibliothèques importées) et qui les utilise.",
        ("familles", "families"): "Chaque ligne est un robot, un indicateur ou un script avec "
        "tout ce qui va avec. Cmd+clic ou Maj+clic pour en choisir plusieurs.",
        ("doublons", "groups"): "Groupes de fichiers identiques octet pour octet. Cmd+clic ou "
        "Maj+clic pour en choisir plusieurs.",
        ("sets", "sets"): "Tous vos SET. Cliquez pour voir ses paramètres et les outils "
        "proposés ; Cmd+clic ou Maj+clic pour en choisir plusieurs.",
    }
)

ACTION_TIPS.update(
    {
        "sources_mq.isoler": "Copie seulement les sources que vous avez cliquées dans la liste "
        "(une, deux, trois ou plus) dans un nouveau dossier, chacune avec ses SET, ses fichiers "
        "liés et les indicateurs ou bibliothèques qu'elle utilise. Vous voyez la proposition "
        "avant de valider.",
        "sources_mq.isoler_tout": "Copie toutes les sources MQ4/MQ5 de la liste, chacune avec ce "
        "qui va avec. Vous voyez la proposition avant de valider.",
        "sources_mq.actualiser": "Recharge la liste des sources MQ4/MQ5.",
    }
)
_CLIC = (
    "Un clic sur une ligne l'ajoute à la sélection, un second clic la retire : choisissez-en "
    "une, deux, trois ou plus. "
)
ACTION_TIPS["sources_mq.tout_sources"] = _TOUT
for _key in [k for k in ACTION_TIPS if ".tout_" in k]:
    ACTION_TIPS[_key] = _CLIC + "Ce bouton les sélectionne toutes."
WIDGET_TIPS.update(
    {
        ("sources_mq", "search"): "Tapez une partie du nom ou du dossier, puis Entrée.",
        ("sources_mq", "platform"): "N'afficher que les sources MQ4 ou MQ5.",
        ("sources_mq", "tool_type"): "N'afficher qu'un type : robots, indicateurs, scripts…",
        ("sources_mq", "sources"): _CLIC + "Colonnes : SET associés, fichiers liés (images, "
        "sons, modèles, DLL…) et indicateurs ou bibliothèques que la source utilise.",
        ("familles", "families"): _CLIC + "Chaque ligne est un robot, un indicateur ou un "
        "script avec tout ce qui va avec.",
        ("doublons", "groups"): _CLIC + "Groupes de fichiers identiques octet pour octet.",
        ("sets", "sets"): _CLIC + "Le détail (paramètres, outils proposés) montre le premier SET "
        "choisi.",
        ("sets", "assoc"): _CLIC + "Puis Accepter ou Rejeter : la décision s'applique à toutes "
        "les associations choisies.",
    }
)
