# Installer MT4 MT5 Library Manager PRO sur votre Mac

## Le plus simple : le dossier d'installation
Dans **Releases**, téléchargez `MT4-MT5-Library-Manager-PRO-<version>-Installation-macOS.zip`,
ouvrez-le, puis faites **clic droit → Ouvrir** sur **`Installer.command`**. L'application est
**universelle** (la même pour les Mac Intel et Apple Silicon, macOS 12 ou plus récent).
L'installateur vérifie l'empreinte du fichier, le processeur et la version de macOS, installe
l'application dans **Applications** (une ancienne version de cette application est remplacée,
vos données et réglages sont conservés), l'autorise et l'ouvre. Il ne touche à rien d'autre.

La première fois, macOS peut bloquer `Installer.command` : **Réglages Système →
Confidentialité et sécurité → Ouvrir quand même** (ou clic droit → **Ouvrir** sur un macOS plus
ancien). Le **Guide d'installation.pdf** inclus explique tout avec une capture.

Ce script est testé à chaque construction sur de vrais Mac (Apple Silicon et Intel) :
première installation, mise à jour, refus de toucher un élément étranger du même nom, refus
d'un fichier abîmé, d'un macOS trop ancien et d'une image sans le code du processeur.

La méthode manuelle ci-dessous reste possible.

## 1. Télécharger
Sur GitHub (dépôt privé), onglet **Releases** : téléchargez le fichier
`MT4-MT5-Library-Manager-PRO-<version>-macOS.dmg` (universel : Intel et Apple Silicon).
Les versions 1.2.1 et antérieures avaient deux DMG ; un DMG « Apple-Silicon » ouvert sur un Mac
Intel donne « n'est pas prise en charge sur ce Mac ».

Le fichier `.sha256` à côté permet de vérifier l'intégrité (facultatif) :
`shasum -a 256 NomDuFichier.dmg` doit afficher la même valeur.

## 2. Installer
1. Double-cliquez sur le fichier `.dmg`.
2. Glissez **MT4 MT5 Library Manager PRO** sur le dossier **Applications**.
3. Éjectez le disque « MT4 MT5 Library Manager PRO ».

## 3. Premier lancement
L'application n'est pas encore signée par un compte développeur Apple (question Q-03). macOS
affiche donc « impossible de vérifier le développeur ». Pour l'ouvrir la première fois :
1. Dans **Applications**, faites un **clic droit** (ou Ctrl + clic) sur l'application → **Ouvrir**.
2. Confirmez **Ouvrir**.
Si macOS refuse encore : **Réglages Système → Confidentialité et sécurité**, en bas : « Ouvrir
quand même ». Les lancements suivants se font normalement.

## 4. Utilisation
Suivez l'écran **Aide** de l'application : ajoutez votre dossier MetaTrader dans **Sources**,
lancez **Tout analyser**. Vos fichiers d'origine ne sont jamais modifiés.

## 5. Où sont mes données ?
- Base et sauvegardes : `~/Library/Application Support/MT4MT5LibraryManagerPro/`
- Journaux techniques : `~/Library/Logs/MT4MT5LibraryManagerPro/`

## 6. Sauvegarde et restauration de la base
- Écran **Rapports et journal** → **Sauvegarder la base** (sauvegarde vérifiée).
- Une sauvegarde est aussi faite automatiquement avant chaque mise à jour du schéma.
- Restauration (outil en ligne de commande inclus dans le dépôt) :
  `mtlm restaurer FICHIER.sqlite --confirmer` (la base actuelle est d'abord sauvegardée).

## 7. Mise à jour
Téléchargez le nouveau `.dmg` et remplacez l'application dans **Applications**. Vos données
(base, sauvegardes, journaux) sont conservées et la base est mise à niveau automatiquement
(après une sauvegarde).

## 8. Désinstallation
1. Mettez l'application à la corbeille depuis **Applications**.
2. (Facultatif) Supprimez vos données d'analyse : les deux dossiers du § 5. **Cela ne touche
   pas vos fichiers MetaTrader**, ni vos copies de quarantaine ou bibliothèques organisées,
   qui sont dans les dossiers que vous avez choisis.
