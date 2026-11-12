# Tout conserver, même si le dépôt redevient privé

## Ce qui est conservé où
| Quoi | Où | Si le dépôt redevient privé |
|---|---|---|
| Code, historique, documentation | dépôt GitHub | conservé, visible par vous seul |
| Versions publiées (DMG, dossier d'installation `…-Installation-macOS.zip`) | onglet **Releases** | conservées, téléchargeables par vous |
| Copie chez vous | le dossier d'installation et la **sauvegarde complète** `…-sauvegarde.bundle` qui vous ont été envoyés | indépendants de GitHub |

Le **zip des sources** (`…-sources.zip`) permet aussi de reconstruire l'application
directement sur votre Mac, sans GitHub : voir `construire-sur-mac.md`.

Gardez le dossier d'installation, le zip des sources et la sauvegarde complète (par exemple sur un disque externe
et dans un service de stockage) : avec eux, rien ne dépend de GitHub.

## Restaurer le projet depuis la sauvegarde complète
Le fichier `.bundle` contient tout le code et tout l'historique. Sur un Mac :
`git clone MT4-MT5-Library-Manager-PRO-<version>-sauvegarde.bundle projet`
(puis `git remote add origin <adresse d'un nouveau dépôt>` et `git push -u origin --all`).

## Minutes de construction GitHub
- **Dépôt public** : constructions gratuites et illimitées (Mac compris).
- **Dépôt privé** : quota gratuit mensuel ; les minutes Mac comptent dix fois. C'est pourquoi les
  constructions Mac ne tournent plus à chaque modification, mais seulement pour une
  publication : message contenant `[publier]`, étiquette `v…`, ou bouton **Actions →
  « Application macOS (.app + DMG) » → Run workflow** (publication manuelle).
- Si GitHub refuse de lancer une construction (« spending limit »), le quota du mois est
  épuisé : augmentez la limite de dépenses (Settings → Billing) ou attendez le mois suivant.
