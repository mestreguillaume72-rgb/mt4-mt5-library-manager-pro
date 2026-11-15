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

Résultat : un nouveau dossier « Robots isolés <date> » (ou « Indicateurs isolés <date> »),
par exemple `Or/Gold Robot/…`, `Scalpers/…`, `Autre robot/…`. C'est une **copie vérifiée** :
vos fichiers d'origine ne bougent pas.
