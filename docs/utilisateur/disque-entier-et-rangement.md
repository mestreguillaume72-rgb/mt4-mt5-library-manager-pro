# Analyser un disque entier, ranger robots et indicateurs (1.6.0)

## Analyse d'un disque entier

Sur un disque entier, la plupart des fichiers n'ont rien à voir avec MetaTrader (vidéos,
photos, images disque…). Depuis 1.6.0, l'étape « Empreintes » **lit en entier seulement** :

- les fichiers MetaTrader : `.mq4`, `.mq5`, `.mqh`, `.ex4`, `.ex5`, `.set`, `.tpl` (modèles
  de graphique), `.chr`, `.dll`, `.ini`… ;
- les archives (ZIP, RAR, 7z, TAR, GZ…), dont chaque fichier contenu est lu ;
- les autres fichiers (images, sons, documents…) **rangés dans un dossier de robot** ou
  jusqu'à 2 niveaux en dessous (par exemple `MonRobot/Images/logo.png`).

Les autres fichiers sont **seulement listés** (nom, taille, date) : ils ne sont ni lus en
entier, ni comparés. Pour tout lire quand même : Paramètres → « Lire en entier tous les
fichiers du disque » = 1 (cela peut prendre des heures sur un grand disque).

Pendant le calcul, la progression indique les Go lus, la vitesse et le **temps restant
estimé**. Sur un disque dur classique, régler « Calculs d'empreintes en parallèle » à 1 ou 2
est souvent plus rapide.

## Ranger robots et indicateurs dans des dossiers séparés

Écran **Sources MQ4/MQ5** :

1. « Choisir tous les robots » et/ou « Choisir tous les indicateurs » (MQ4 et MQ5), ou un
   clic sur chaque ligne voulue ;
2. laissez cochée la case « Ranger dans des dossiers Robots / Indicateurs » ;
3. « Isoler les sources choisies… », choisissez le dossier de destination, cochez les
   fichiers proposés qui vont avec, puis validez.

Résultat : `Robots/MQ4/<nom>/`, `Robots/MQ5/<nom>/`, `Indicateurs/MQ4/<nom>/`,
`Indicateurs/MQ5/<nom>/` (et `Scripts/…`), chaque outil avec tout ce qui va avec. C'est une
**copie vérifiée** : vos fichiers d'origine ne bougent pas.
