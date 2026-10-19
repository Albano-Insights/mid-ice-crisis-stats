"""The timestamp-only write skip must not freeze meta.json.

_save_json skips a write whose only change is a generated_at timestamp, which keeps ~50 derived
files from churning on every build. meta.json holds nothing but that timestamp, so the comparison
is `{} == {}` forever and the file was written once and never again -- while docs/app.js reads it
for the site's "Updated ..." stamp. The page therefore advertised a build date weeks older than
the data beneath it.

Run: python -m pytest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site_data as b  # noqa: E402


def test_timestamp_only_change_is_skipped(tmp_path):
    """The optimisation itself still holds for a normal derived file."""
    path = tmp_path / "players_index.json"
    b._save_json(path, {"generated_at": "2026-10-05T05:20+00:00", "players": [1, 2]})
    b._save_json(path, {"generated_at": "2026-10-19T13:26+00:00", "players": [1, 2]})
    assert json.loads(path.read_text())["generated_at"] == "2026-10-05T05:20+00:00"


def test_real_change_is_written(tmp_path):
    path = tmp_path / "players_index.json"
    b._save_json(path, {"generated_at": "2026-10-05T05:20+00:00", "players": [1, 2]})
    b._save_json(path, {"generated_at": "2026-10-19T13:26+00:00", "players": [1, 2, 3]})
    written = json.loads(path.read_text())
    assert written["players"] == [1, 2, 3]
    assert written["generated_at"] == "2026-10-19T13:26+00:00"


def test_meta_json_always_rewrites(tmp_path):
    """always=True: a file that is only a timestamp must still advance."""
    path = tmp_path / "meta.json"
    b._save_json(path, {"generated_at": "2026-10-05T05:20+00:00"}, always=True)
    b._save_json(path, {"generated_at": "2026-10-19T13:26+00:00"}, always=True)
    assert json.loads(path.read_text())["generated_at"] == "2026-10-19T13:26+00:00"


def test_meta_json_would_freeze_without_always(tmp_path):
    """Guards the reason always=True exists, so removing it fails here and not on the live site."""
    path = tmp_path / "meta.json"
    b._save_json(path, {"generated_at": "2026-10-05T05:20+00:00"})
    b._save_json(path, {"generated_at": "2026-10-19T13:26+00:00"})
    assert json.loads(path.read_text())["generated_at"] == "2026-10-05T05:20+00:00"


def test_build_stamps_meta_with_always():
    """The call site must pass always=True -- the test above only proves the mechanism."""
    src = (ROOT / "scripts" / "build_site_data.py").read_text(encoding="utf-8")
    i = src.index('DERIVED / "meta.json"')
    assert "always=True" in src[i:i + 200]
