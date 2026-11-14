from __future__ import annotations

import stat

from quoll.config import store


def test_token_roundtrip_owner_only(tmp_path, monkeypatch) -> None:
    path = tmp_path / "quoll" / "config.toml"
    monkeypatch.setattr(store, "_CONFIG_PATH", path)

    assert store.load_stored_token() == ""
    store.save_token("gh-1")
    store.save_token("gl-1", platform="gitlab")

    assert store.load_stored_token() == "gh-1"
    assert store.load_stored_token("gitlab") == "gl-1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_file_tightened(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[github]\ntoken = "old"\n')
    path.chmod(0o644)
    monkeypatch.setattr(store, "_CONFIG_PATH", path)

    store.save_token("new")

    assert store.load_stored_token() == "new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
