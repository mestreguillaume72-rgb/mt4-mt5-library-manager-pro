# Rapport de phase 4 — Formats et archives

> Date : 2026-11-10.

## 1. Livré (F3)

| Élément | Comportement | Fichiers |
|---|---|---|
| Signatures binaires | Format réel identifié sur les 4 096 premiers octets (ZIP, RAR, 7z, GZIP, PE/DLL, Mach-O, ELF, PDF, images, SQLite, texte, texte UTF-16, binaire non identifié) ; **extensions trompeuses** signalées (ex. `.mq4` qui est un exécutable, `.ex4` qui est du texte) | `src/mtlm/formats/signatures.py` |
| Inspection ZIP | **Aucune extraction sur disque** : chaque entrée est décompressée en mémoire, par blocs, vers le calcul SHA-256. Limites comptées sur les octets réellement décompressés : profondeur (2), entrées (10 000), total (2 Gio), par entrée (512 Mio), ratio (100:1). Refus : chemin absolu, lecteur Windows, « .. », lien symbolique ; doublons signalés ; entrées chiffrées non lues ; CRC incorrect détecté | `src/mtlm/formats/archives.py` |
| Autres archives | RAR, 7z, GZIP : identifiés, **non ouverts** (aucun outil externe, aucune dépendance native) | idem |
| Service | Signatures persistées (`file_record.magic`), résultat global (`archive_scan`) et entrées (`archive_entry`, avec empreinte) ; ré-inspection seulement si le contenu ou la version du moteur change | `src/mtlm/app/formats.py`, migration `0003` |
| CLI | `mtlm formats`, `mtlm archive ID` ; `mtlm fichier ID` affiche le format réel et « EXTENSION TROMPEUSE » | `src/mtlm/cli/main.py` |

## 2. Cas de validation (F3)

| Cas imposé | Test |
|---|---|
| Archive saine | `test_archive_saine` |
| Archive corrompue | `test_archive_corrompue`, `test_archive_tronquee`, `test_crc_incorrect` |
| Zip bomb simulée | `test_zip_bomb_simulee` (64 Mio de zéros dans < 1 Mio : arrêt après ~6,5 Mio décompressés en mémoire, au ratio 100:1) |
| Noms traversants | `test_noms_traversants_et_absolus`, `test_noms_dangereux` |
| Doublons d'entrées | `test_doublons_d_entrees` |
| Archive chiffrée | `test_archive_chiffree` |
| Échec propre et journalisé | statut + motif enregistrés (`archive_scan.reason`), journal technique ; `test_signatures_et_archives` |
| Aucune écriture | `test_aucune_ecriture_sur_disque` (instantané avant/après), invariant « sources inchangées » |
| Limites, imbrication | `test_limites_taille_et_nombre`, `test_archive_imbriquee_et_profondeur` |

## 3. Résultats réels

| Environnement | Commande | Résultat |
|---|---|---|
| Linux x86_64, Python 3.13.18 | `uv run pytest -W error::ResourceWarning` | **232 passed, 1 skipped** |
| Linux | `uv run ruff check .`, `mypy` | OK, « no issues found in 60 source files » |
| macOS 15 arm64 / Intel (GitHub, phase 3) | suite complète + invariant 50 000 | voir CI du commit de phase 3 |

## 4. Défauts trouvés et corrigés
- La règle statique « aucune écriture dans les modules d'analyse » confondait `str.replace` avec
  `Path.replace` et `ZipFile.open(info)` (lecture) avec une ouverture en écriture : règle affinée,
  avec auto-tests pour chaque cas.

## 5. Limites
- Seul ZIP est ouvert. RAR/7z/GZIP sont identifiés mais leur contenu n'est pas inspecté.
- Une archive imbriquée n'est ouverte que si elle fait au plus 64 Mio (lue en mémoire).
- Les entrées d'archive participent à la détection des contenus identiques mais ne sont jamais
  mises en quarantaine (une archive n'est jamais modifiée).
