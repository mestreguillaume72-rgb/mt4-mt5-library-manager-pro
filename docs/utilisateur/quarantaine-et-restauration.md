# Quarantaine et restauration — mode d'emploi

> Principe (décision du propriétaire) : la quarantaine est une **copie vérifiée**.
> **Vos fichiers d'origine ne sont jamais modifiés, déplacés ni supprimés.**

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

## Suivi
`mtlm quarantaine lots`, `mtlm quarantaine lot LOT`, et le journal d'audit
(`mtlm audit exporter fichier.jsonl`).
