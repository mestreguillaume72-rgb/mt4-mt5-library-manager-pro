# Construire l'application sur votre Mac, sans GitHub

Tout ce qu'il faut est dans le dossier des **sources**
(`MT4-MT5-Library-Manager-PRO-<version>-sources.zip`, joint à chaque version et envoyé avec
la sauvegarde). Gardez-le sur votre Mac ou un disque externe.

## En 3 gestes
1. Double-cliquez sur le zip des sources : un dossier apparaît.
2. Dans ce dossier, **clic droit sur `Construire-sur-ce-Mac.command` → Ouvrir → Ouvrir**
   (les fois suivantes, un double-clic suffit).
3. Attendez « ✅ Terminé » (5 à 15 minutes la première fois), puis répondez **o** pour
   installer l'application dans Applications.

## Ce que fait le script
- vérifie que le Mac a macOS 12 Monterey ou plus récent ;
- installe l'outil **uv** dans votre dossier personnel (sans mot de passe administrateur) ;
  uv télécharge Python et les **versions exactes** des bibliothèques du projet (`uv.lock`) :
  une connexion Internet est nécessaire la première fois ;
- construit l'application **pour ce Mac** (Intel ou Apple Silicon), la teste
  (auto-diagnostic) et crée `dist/MT4-MT5-Library-Manager-PRO-<version>-macOS-ce-Mac.dmg` ;
- propose de l'installer (une ancienne version de l'application est remplacée ; vos
  données et réglages sont conservés).

Il ne touche jamais à vos fichiers MetaTrader. Tout est noté dans `construction-locale.log`,
à côté du script : en cas de problème, envoyez ce fichier.

## Options
- Lancer aussi tous les tests : dans le Terminal, `MTLM_TESTS=1 ./Construire-sur-ce-Mac.command`.
- Ne pas installer : `MTLM_NO_INSTALL=1 ./Construire-sur-ce-Mac.command`.

## Vérifié
Le script est lancé automatiquement, à chaque publication, sur un Mac Intel neuf de GitHub,
depuis un dossier de sources sans git et sans uv préinstallé (tâche « Construction locale »).
