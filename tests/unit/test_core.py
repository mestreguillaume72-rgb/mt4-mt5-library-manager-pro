from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from mtlm.core.clock import FixedClock, SystemClock, iso_utc
from mtlm.core.paths import default_paths


def test_iso_utc_millisecondes_et_conversion_fuseau() -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone(timedelta(hours=2)))
    assert iso_utc(moment) == "2026-01-02T01:04:05.678Z"


def test_fixed_clock_exige_un_fuseau() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))


def test_fixed_clock_avance() -> None:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.advance(1.5)
    assert iso_utc(clock.now()) == "2026-01-01T00:00:01.500Z"


def test_system_clock_est_en_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)


def test_chemins_macos(tmp_path: Path) -> None:
    paths = default_paths({}, platform="darwin", home=tmp_path)
    assert paths.data_dir == tmp_path / "Library/Application Support/MT4MT5LibraryManagerPro"
    assert paths.logs_dir == tmp_path / "Library/Logs/MT4MT5LibraryManagerPro"
    assert paths.database.name == "library.sqlite"
    assert paths.backups_dir == paths.data_dir / "backups"


def test_chemins_linux_xdg(tmp_path: Path) -> None:
    paths = default_paths({"XDG_DATA_HOME": str(tmp_path)}, platform="linux", home=tmp_path)
    assert paths.data_dir == tmp_path / "mt4mt5-library-manager-pro"


def test_chemins_linux_defaut(tmp_path: Path) -> None:
    paths = default_paths({}, platform="linux", home=tmp_path)
    assert paths.data_dir == tmp_path / ".local/share/mt4mt5-library-manager-pro"


def test_mtlm_home_prioritaire(tmp_path: Path) -> None:
    paths = default_paths({"MTLM_HOME": str(tmp_path)}, platform="darwin", home=Path("/x"))
    assert paths.data_dir == tmp_path / "data"
    assert paths.logs_dir == tmp_path / "logs"


def test_ensure_cree_uniquement_les_dossiers_de_l_application(tmp_path: Path) -> None:
    paths = default_paths({"MTLM_HOME": str(tmp_path / "h")})
    paths.ensure()
    created = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert created == ["h", "h/data", "h/data/backups", "h/logs"]
