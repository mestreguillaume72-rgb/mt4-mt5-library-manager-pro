# PLAN DE TESTS — MT4 MT5 Library Manager PRO

> Statut : **PROPOSITION — en attente de validation.**
> Principe : une fonctionnalité n'existe que si elle est testée, journalisée, documentée et satisfait ses critères d'acceptation. Aucun résultat n'est déclaré « testé » sans exécution réelle en CI.

---

## 1. Pyramide et outillage

| Niveau | Outil | Où | Quand |
|---|---|---|---|
| Unitaires | Swift Testing (`@Test`) / XCTest | `Packages/LibraryManagerKit/Tests` | Chaque commit (CI Linux + macOS) |
| Propriétés / fuzz | Générateurs maison (graine fixe + graine aléatoire journalisée) | idem | Chaque PR (court) / nightly (long) |
| Intégration système de fichiers | Dossiers temporaires réels (`FileManager.temporaryDirectory`) | idem | Chaque PR |
| Golden (fichiers MQL réels) | Corpus `Fixtures/golden` + résultats attendus JSON | idem | Chaque PR |
| Performance | `XCTMetric` / chronométrage + `OSSignposter`, seuils en échec | `PerformanceTests` | 50k chaque PR (macOS) ; 100k nightly |
| UI | XCUITest | `App/UITests` | Chaque PR (macOS) |
| Statique / sécurité | Script CI : APIs interdites, graphe de dépendances, entitlements, SwiftLint | `.github/workflows` | Chaque commit |
| Manuel exploratoire | Checklist documentée | `docs/tests/manuel.md` | Avant chaque version |

Chaque test est **déterministe** : horloge, UUID et graine aléatoire injectés (`LMCore.Clock`, `UUIDProvider`). Les tests ne touchent jamais `~/` réel ; seulement des dossiers temporaires créés et détruits par le test.

---

## 2. Corpus synthétique (`LMTestSupport.CorpusGenerator`)

Utilisé **uniquement** en test (jamais lié à l'app, vérifié en CI — D-011).

| Paramètre | Valeurs |
|---|---|
| Taille | 1k (unitaire), 10k, **50k**, **100k** |
| Arborescence | `MQL4/` et `MQL5/` avec `Experts, Indicators, Scripts, Include, Libraries, Presets, Files, Services, Images`, profondeur 1–8 |
| Types | `.mq4 .mq5 .mqh` (sources générées syntaxiquement plausibles avec `#property`, `#include`, `input`, `OnTick`/`OnCalculate`/`OnStart`), `.ex4 .ex5 .dll` (octets aléatoires — **jamais de vrais binaires**), `.set .tpl .csv .ini`, extensions inconnues |
| Encodages | UTF-8, UTF-8 BOM, UTF-16 LE BOM, UTF-16 BE BOM, CP1252, fichiers invalides |
| Doublons injectés (vérité terrain connue) | 5 % exacts ; 2 % équivalents normalisés (CRLF/LF, commentaires, espaces, encodage) ; 3 % similaires à taux de mutation contrôlé (5–40 % des tokens) ; 2 % familles de versions (`#property version` 1.00→1.0n) |
| Pièges | Mêmes tailles contenus différents ; même préfixe 64 Kio + même taille ; même tête et queue, milieu différent ; fichiers vides ; 1 octet ; > 100 Mo (un seul, nightly) |
| Pathologies FS | Symlinks (valides, cassés, boucle), noms NFD vs NFC, casse différente, espaces/emoji/`:`, chemins longs, fichiers sans permission de lecture, dossiers non lisibles |

Le générateur produit un **manifeste de vérité terrain** (JSON) ; les tests comparent les résultats de l'app à ce manifeste (précision, rappel, nombre exact).

---

## 3. Tests par module

### 3.1 LMFileSystem
- Énumère exactement les fichiers du manifeste (compte, chemins, tailles).
- Ne suit pas les symlinks ; détecte la boucle ; enregistre le lien comme tel.
- Fichier illisible → erreur comptée, scan continue.
- Fichier dataless (simulé via protocole injectable ; test réel macOS manuel) → non lu.
- Annulation à 10 %, 50 %, 99 % → aucun état incohérent, session `cancelled`.
- **Invariant lecture seule** (voir § 5).

### 3.2 LMHashing
- SHA-256 conforme aux vecteurs NIST et à `shasum -a 256` sur 1 000 fichiers.
- Fichier vide, 1 octet, multiple exact de la taille de bloc, > 4 Gio (nightly, fichier creux).
- Pré-hash tête+queue : fichiers < 128 Kio traités correctement (chevauchement).
- Parallélisme borné respecté ; annulation propre.

### 3.3 LMIndexStore
- Chaque migration testée depuis chaque version précédente (base de chaque version archivée en fixture).
- Insertions par lots : 100k lignes dans le budget ; atomicité (crash simulé au milieu d'un lot → rien de partiel).
- Requêtes paginées : ordre stable, pas de doublon entre pages.
- FTS5 : recherche par nom, chemin, `#property description`, accents.

### 3.4 LMMQLAnalysis
- Golden : pour chaque fixture, JSON attendu (`encoding`, `program_type`, `#property`, includes, imports, inputs) → égalité stricte.
- Commentaires `//` et `/* */` imbriqués dans chaînes, chaînes contenant `#property`, lignes continuées, macros.
- `#import "xxx.dll"` détecté et signalé — **jamais chargé** (test : aucun `dlopen` dans le binaire).
- Fuzz : 10 000 entrées aléatoires / tronquées / binaires renommés → aucun crash, aucun blocage > 1 s par fichier.
- Refus explicite d'analyser `.ex4 .ex5 .dll` (D-007).

### 3.5 LMDuplicates
- **Exacts** : rappel = précision = 1,0 sur le manifeste ; 0 faux positif sur les pièges (même taille, même tête/queue).
- **Équivalents normalisés** : détectés pour CRLF/LF, BOM, encodage, commentaires, espaces ; **jamais** classés comme exacts.
- **Similaires** : précision ≥ 0,95, rappel ≥ 0,90 au seuil 0,80 (à confirmer Q-11) ; le score affiché = Jaccard exact recalculé.
- **Versions** : familles reconstruites conformes au manifeste ; ordre selon `#property version` ; « ordre supposé » quand absent.
- Les classes sont disjointes dans l'affichage : un test vérifie qu'aucune paire « similaire » n'est étiquetée « doublon ».
- Stabilité : deux exécutions → résultats identiques.

### 3.6 LMQuarantine
- Impossible d'appeler `quarantine(...)` sans `UserConfirmation` (test de compilation/visibilité + test runtime).
- Aller-retour quarantaine → restauration : contenu (SHA-256), taille, mode, mtime, xattrs identiques ; 1 000 répétitions.
- **Injection de fautes** après chaque étape (planned / moved / avant vérification / pendant restauration) → au redémarrage, réconciliation proposée, aucune perte, aucun fichier dupliqué.
- Conflit à la restauration (chemin occupé) → refus + proposition de nom suffixé ; rien d'écrasé.
- Volume différent / racine non inscriptible → refus explicite, rien déplacé.
- Disque plein simulé → échec propre, état cohérent.
- Chaque opération produit des `audit_event` avec l'identifiant de confirmation.

### 3.7 LMReports
- Export CSV/JSON ré-importé et comparé à l'index ; échappement (virgules, guillemets, sauts de ligne, Unicode).
- Export d'une bibliothèque vide → fichier valide vide (en-têtes), pas de données d'exemple.

### 3.8 App (XCUITest)
- **Inventaire automatique des contrôles** : un test parcourt chaque vue et vérifie que chaque bouton/menu identifié (`accessibilityIdentifier` obligatoire) est couvert par au moins un scénario. Un contrôle sans test fait échouer la CI.
- Scénarios : ajouter racine → scanner → filtrer → inspecter → voir doublons → mettre en quarantaine (annuler puis confirmer) → restaurer → exporter → consulter journal.
- États vides (aucune racine, aucun doublon) : message réel, pas de données factices.
- Clavier seul, VoiceOver (audit `performAccessibilityAudit()`), mode sombre.

---

## 4. Tests de performance

| Scénario | Corpus | Seuil d'échec (proposé, Q-08) | Fréquence |
|---|---|---|---|
| Inventaire initial | 50k | > 15 s | Chaque PR (macOS) |
| Inventaire initial | 100k | > 30 s | Nightly |
| Re-scan inchangé | 50k / 100k | > 5 s / > 10 s | PR / nightly |
| Doublons exacts (hash inclus) | 50k / 100k | débit < 70 % du débit séquentiel mesuré | PR / nightly |
| Similarité | 50k sources | > 120 s | Nightly |
| Mémoire pic | 50k / 100k | > 400 Mo / > 700 Mo | PR / nightly |
| Filtre table | 100k | > 300 ms | Nightly (UI) |
| Thread principal bloqué | 100k | toute frame > 100 ms | Nightly (UI) |

Les résultats sont archivés (artefact CI JSON) pour suivre les régressions ; régression > 15 % vs moyenne des 5 derniers runs = alerte.

---

## 5. Test d'invariant « lecture seule » (critique)

1. Générer le corpus (50k PR / 100k nightly).
2. Instantané **avant** : pour chaque entrée, chemin brut, type, taille, SHA-256, `mtime`, `ctime`, mode, propriétaire, liste et valeurs des xattrs ; liste des entrées de chaque dossier.
3. Exécuter : scan + hash + analyse MQL + doublons + similarité + exports.
4. Instantané **après** et comparaison stricte → **zéro différence** exigée (hors `atime`, contrôlé séparément et documenté).
5. Vérifier qu'aucun fichier n'a été créé dans l'arborescence (pas de `.DS_Store`, pas de fichiers temporaires).
6. Seule exception testée séparément : les déplacements de quarantaine **confirmés**, dont l'effet doit être exactement celui du plan affiché.

---

## 6. Tests statiques de sécurité (CI)

- Recherche des symboles interdits dans les sources hors modules autorisés : `Process`, `NSTask`, `posix_spawn`, `dlopen`, `NSWorkspace.shared.open`, `QLPreview`, `NSAppleScript`, `setxattr`, `chmod`, `utimes`, `removeItem`, `moveItem`.
- `nm`/`otool` sur le binaire Release : absence de `dlopen`, `posix_spawn`, `execve`.
- Entitlements : sandbox ON, réseau OFF, `disable-library-validation` absent.
- Graphe de dépendances : `LMTestSupport` non lié à l'app.

---

## 7. Logs : ce qui est testé

- Chaque cas d'usage émet `début`, `fin` (avec durée et compteurs) ou `échec` (erreur typée) — vérifié via un `LogSink` de test.
- Chemins de fichiers jamais en clair dans les logs système (`.private`) ; présents dans le journal d'audit local (nécessaire à la traçabilité).
- Chaque action de quarantaine/restauration → exactement un `audit_event` par fichier + un par lot.

---

## 8. Critères d'acceptation transverses (Definition of Done)

Une étape/phase est terminée si et seulement si :
1. Tous les tests de la phase passent en CI macOS (et Linux pour le cœur), y compris performance au palier prévu.
2. Couverture ≥ 85 % sur les modules du cœur modifiés, 100 % des branches de `LMQuarantine`.
3. Invariant lecture seule vert.
4. Logs et événements d'audit présents et testés.
5. Documentation mise à jour (`ARCHITECTURE.md`, `DECISIONS.md` si décision, `docs/`, `CHANGELOG.md`).
6. Aucun contrôle d'UI sans action réelle ni test ; aucune donnée fictive dans l'app.
7. Exigences du PDF correspondantes marquées couvertes dans `docs/TRACABILITE.md`.

---

## 9. Pipelines CI proposés

| Workflow | Déclencheur | Contenu |
|---|---|---|
| `ci-linux.yml` | push/PR | `swift build`, `swift test` (cœur), lint, analyse statique |
| `ci-macos.yml` | push/PR | build app, tests unitaires + intégration + golden, perf 50k, XCUITest, invariant lecture seule 50k, vérification entitlements |
| `perf-nightly.yml` | nuit | 100k complet, similarité 50k, fuzz long, archivage des métriques |
