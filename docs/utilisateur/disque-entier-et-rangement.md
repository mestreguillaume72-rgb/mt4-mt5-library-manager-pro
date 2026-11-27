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

## Robot ou indicateur ? L'application le dit

L'écran **Sources MQ4/MQ5** affiche pour chaque fichier « C'est un… » (Robot, Indicateur,
Script…) et « Reconnu par » (ce qui a été lu dans le code). Le type est trouvé en lisant le
code, même si le fichier est rangé n'importe où. S'il est rangé dans le dossier d'un autre
type (un indicateur dans « Experts »), c'est écrit « peut-être mal rangé ».

Cases **« Robots MQ4 / MQ5 »** et **« Indicateurs MQ4 / MQ5 »** : décochez l'une pour ne
voir que l'autre, vérifiez, puis créez les dossiers si besoin.

L'écran **Archives** dit aussi ce que contient chaque archive (« 2 robots, 3 indicateurs »)
et le type de chaque fichier, sans rien extraire.

## Robots isolés, indicateurs isolés

Deux écrans à part (menu **Actions**), séparés de l'écran « Sources MQ4/MQ5 » :
**Robots isolés** et **Indicateurs isolés**. Chaque robot ou indicateur (MQ4, MQ5, EX4, EX5)
vient avec tout ce qui va avec : versions, compilés, SET, indicateurs utilisés, DLL, modèles,
images.

1. Cliquez sur les robots (ou indicateurs) voulus, ou « Tout sélectionner ».
2. Facultatif : **« Mettre dans un groupe… »** et tapez un nom (par exemple « Or » ou
   « Scalpers ») ; recommencez pour faire d'autres groupes. Chaque groupe devient un
   dossier. « Retirer du groupe » remet un outil à la racine.
3. Choisissez le rangement : **un dossier par robot** (avec tout dedans) ou **un seul grand
   dossier** (tous les fichiers ensemble).
4. « Isoler les robots choisis… » (ou « Isoler tous les robots… »), choisissez où créer le
   dossier, regardez l'aperçu et validez.

Chaque robot vient avec **son dossier entier** (sous-dossiers, SET, notices, images),
même s'il n'y a que le fichier EX4/EX5 : pour `Gold Pack/MQL4/Experts/Gold.ex4`, c'est tout
le dossier `Gold Pack` qui est copié. **Aucun doublon** : un fichier identique à un autre
n'est copié qu'une fois.

Résultat : un nouveau dossier « Robots isolés <date> » (ou « Indicateurs isolés <date> »),
par exemple `Or/Gold Robot/…`, `Scalpers/…`, `Autre robot/…`. C'est une **copie vérifiée** :
vos fichiers d'origine ne bougent pas.

## Supprimer, recommencer à zéro (1.7.0)

- **Mettre à la Corbeille** : dans l'Explorateur, les SET, Sources MQ4/MQ5, Robots isolés,
  Indicateurs isolés, Doublons, Familles, Archives, Fichiers à risque. Cliquez sur les
  lignes voulues, puis le bouton. Si un fichier est le **seul exemplaire** de son contenu,
  l'application le dit et vous demande si vous le supprimez aussi. Tout reste récupérable
  avec « Remettre en place » (écran Quarantaine, onglet Corbeille) tant que la Corbeille du Mac
  n'est pas vidée.
- **Recommencer l'analyse à zéro** (écran Analyse) : efface les résultats de l'analyse
  précédente pour repartir de rien. Rien n'est touché sur le disque.
- Sous chaque liste : le **nombre d'éléments** et le nombre sélectionné.
