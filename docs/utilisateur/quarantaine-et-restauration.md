# Quarantaine et restauration — mode d'emploi

> Principe (décision du propriétaire) : la quarantaine est une **copie vérifiée**. Ensuite,
> **vous validez** la mise à la **Corbeille du Mac** des originaux en trop (depuis 1.3.0).
> Rien n'est jamais effacé définitivement par l'application.

## Ce qui peut aller en quarantaine
Uniquement les **doublons exacts** : fichiers dont le contenu est identique octet pour octet
(même taille et même empreinte SHA-256) à un autre fichier, appelé **référence**, qui reste
toujours à sa place. Les fichiers « similaires », les « versions différentes » et les SET
« presque identiques » ne sont **jamais** proposés.

## Étapes
1. Préparez une **destination existante, en dehors de vos bibliothèques** (ex. un dossier
   « Quarantaine » sur un disque de sauvegarde). L'application refuse toute destination située
   dans une source, contenant une source, ou absente (disque débranché).
2. **Simulation** — rien n'est copié :
   `mtlm quarantaine simuler /chemin/vers/Quarantaine`
   Un rapport est enregistré et un **jeton de confirmation** est affiché.
3. **Confirmation** — seulement si la simulation vous convient :
   `mtlm quarantaine executer LOT --jeton JETON`
   Si un fichier a changé depuis la simulation, ou si la référence conservée a changé ou a
   disparu, l'opération est **refusée** ; il faut relancer inventaire, empreintes, doublons
   et une nouvelle simulation.
4. Pendant l'exécution, chaque fichier est copié, synchronisé sur disque, **relu** et comparé à
   son empreinte. Au premier problème (disque plein, fichier modifié, destination déjà
   occupée…), tout s'arrête proprement ; relancez la même commande pour reprendre là où elle
   s'est arrêtée.

## Où sont les copies ?
`<destination>/<identifiant du lot>/<nom de la source>/<chemin d'origine>`, avec :
- `manifeste.json` : chaque fichier (source, destination, empreinte, taille, date, état) ;
- `journal.jsonl` : une ligne par copie vérifiée ou échouée.

## Restauration
`mtlm quarantaine restaurer LOT` retire la marque « en quarantaine » : les fichiers
réapparaissent normalement dans l'application. Les copies de quarantaine sont conservées
(il n'existe aucune purge automatique).

Si un original a disparu entre-temps (supprimé en dehors de l'application) :
`mtlm quarantaine restaurer LOT --recopier-originaux-absents` le recopie depuis la quarantaine,
avec vérification. Si un **autre** fichier occupe son chemin, rien n'est écrasé : le fichier
est signalé en « conflit ».

## Valider la suppression (Corbeille du Mac, depuis 1.3.0)
Écran **Quarantaine**, onglet « Lots de quarantaine » : choisissez un lot dont les copies sont
vérifiées, puis **« 4. Valider : originaux du lot à la Corbeille »**. Vous pouvez aussi
supprimer directement :
- écran **Doublons** : « Mettre à la Corbeille les copies en trop du groupe » (la référence
  reste) ou « Mettre le fichier choisi à la Corbeille » (la référence est protégée) ;
- écran **Familles et versions** : « Mettre le fichier choisi à la Corbeille ». S'il s'agit du
  **seul exemplaire** d'une version, l'application vous le dit clairement avant de demander
  confirmation.

Avant chaque fichier, l'application vérifie qu'il n'a pas changé depuis l'analyse et qu'une
**copie identique est conservée** (comparaison octet par octet : référence, autre copie ou
copie de quarantaine). Sinon le fichier n'est pas touché et la raison est affichée.

Onglet **« Corbeille »** : tout ce qui a été mis à la Corbeille, avec la copie conservée.
**« Remettre en place le fichier choisi »** le remet à son emplacement d'origine (jamais
d'écrasement), tant que la Corbeille du Mac n'a pas été vidée. Relancez ensuite l'analyse pour
mettre à jour les doublons.

## Suivi
`mtlm quarantaine lots`, `mtlm quarantaine lot LOT`, et le journal d'audit
(`mtlm audit exporter fichier.jsonl`).
