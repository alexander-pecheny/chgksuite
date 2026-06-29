"""Offline tests for the xy board integration (crypto, url parsing, config)."""

import os

import pytest

from chgksuite import board_config, xy_crypto

# A known-answer vector produced by xy's own crypto.js (web/assets/static/
# crypto.js): proves the Python port is wire-compatible with the browser.
XY_VECTOR = {
    "passphrase": "корова-лошадь-42",
    "keymeta": {
        "kdf_salt": "wnjxddpzIKFRzdZR3mJXyw==",
        "kdf_params": '{"kdf":"scrypt","N":32768,"r":8,"p":1,"dkLen":32}',
        "wrapped_key": "eHkxAXF8DWEpjHUmpozvVpO0x+0VREgIpWXR01OG70J4pT+lLAyYWF7Ekog8igYIfpM/Q3Pzax64OFlnLlmtsA==",
        "verify_token": "eHkxAW462BB4eSXjzIdWQfdZibKczGRHnHzMwvGOC3wgGNkznx0ayJ0DZy8=",
    },
    "plaintext": "Вопрос 1.\n! Зеркало\nОтвет: отражение",
    "ciphertext_b64": "eHkxARC90/TRwFKhaG1thzeBm3lHNkhXeS45rgg7peYokgyrB4RCEOl8rhQjDKF3ZLbRsbLUDAJEQbDJP8BBM4gj8rdBHCMmM8WUMCWIglRTHKxMrJ6P6w+h64M8yok=",
}


def test_decrypts_xy_browser_vector():
    dk = xy_crypto.derive_dk(XY_VECTOR["passphrase"], XY_VECTOR["keymeta"])
    assert len(dk) == 32
    assert xy_crypto.decrypt_field(dk, XY_VECTOR["ciphertext_b64"]) == XY_VECTOR["plaintext"]


def test_field_round_trip():
    dk = xy_crypto.derive_dk(XY_VECTOR["passphrase"], XY_VECTOR["keymeta"])
    for text in ["", "просто текст", "много\nстрок\nи юникод ✓"]:
        assert xy_crypto.decrypt_field(dk, xy_crypto.encrypt_field(dk, text)) == text


def test_wrong_passphrase_rejected():
    with pytest.raises(xy_crypto.WrongPassphrase):
        xy_crypto.derive_dk("не тот пароль", XY_VECTOR["keymeta"])


@pytest.mark.parametrize(
    "url,service,board_id,host",
    [
        ("https://trello.com/b/3CRjyqFW/blah-blah", "trello", "3CRjyqFW", "trello.com"),
        ("https://xy.pecheny.me/board/2", "xy", "2", "xy.pecheny.me"),
        ("https://xy.example.org/board/17", "xy", "17", "xy.example.org"),
        ("3CRjyqFW", "trello", "3CRjyqFW", "trello.com"),  # bare legacy id
    ],
)
def test_parse_board_url(url, service, board_id, host):
    meta = board_config.parse_board_url(url)
    assert meta["service"] == service
    assert meta["board_id"] == board_id
    assert meta["host"] == host


def test_parse_board_url_rejects_garbage():
    with pytest.raises(ValueError):
        board_config.parse_board_url("https://xy.pecheny.me/not-a-board")


def test_service_host():
    assert board_config.service_host("https://trello.com") == "trello.com"
    assert board_config.service_host("https://xy.pecheny.me") == "xy.pecheny.me"
    assert board_config.service_host("xy.pecheny.me") == "xy.pecheny.me"


def test_token_store_and_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(board_config, "get_chgksuite_dir", lambda: str(tmp_path))
    # a legacy .trello_token left by an old version
    (tmp_path / ".trello_token").write_text("legacy-trello-token\n", "utf8")

    # first access migrates it and removes the legacy file
    assert board_config.get_token_for_host("trello.com") == "legacy-trello-token"
    assert not os.path.isfile(tmp_path / ".trello_token")
    assert os.path.isfile(tmp_path / ".board_tokens.toml")

    # new xy token coexists; trello entry is untouched
    board_config.set_token_for_host("xy.pecheny.me", "xy-token-123")
    assert board_config.get_token_for_host("xy.pecheny.me") == "xy-token-123"
    assert board_config.get_token_for_host("trello.com") == "legacy-trello-token"

    # overwrite is in-place, not duplicated
    board_config.set_token_for_host("xy.pecheny.me", "xy-token-456")
    tokens = board_config.load_board_tokens()
    assert sum(1 for t in tokens if t["host"] == "xy.pecheny.me") == 1
    assert board_config.get_token_for_host("xy.pecheny.me") == "xy-token-456"


def test_board_metadata_round_trip(tmp_path):
    folder = str(tmp_path)
    assert board_config.read_board_metadata(folder) is None
    # xy: passphrase persisted
    board_config.write_board_metadata(folder, "https://xy.pecheny.me/board/2", "пароль доски")
    meta = board_config.read_board_metadata(folder)
    assert meta["board_url"] == "https://xy.pecheny.me/board/2"
    assert meta["passphrase"] == "пароль доски"
    # trello: no passphrase key
    board_config.write_board_metadata(folder, "https://trello.com/b/3CRjyqFW")
    assert "passphrase" not in board_config.read_board_metadata(folder)


def test_legacy_board_id_migration(tmp_path):
    folder = str(tmp_path)
    legacy = tmp_path / ".board_id"
    legacy.write_text("3CRjyqFW\n", "utf8")

    board_config.migrate_legacy_board_id(folder)

    assert not legacy.exists()
    meta = board_config.read_board_metadata(folder)
    assert meta["board_url"] == "https://trello.com/b/3CRjyqFW"
    assert board_config.parse_board_url(meta["board_url"])["board_id"] == "3CRjyqFW"


def test_legacy_board_id_migration_keeps_existing_metadata(tmp_path):
    folder = str(tmp_path)
    board_config.write_board_metadata(folder, "https://xy.pecheny.me/board/2", "пароль")
    (tmp_path / ".board_id").write_text("3CRjyqFW", "utf8")

    board_config.migrate_legacy_board_id(folder)

    # stale .board_id is dropped; existing metadata is untouched
    assert not (tmp_path / ".board_id").exists()
    assert board_config.read_board_metadata(folder)["board_url"] == "https://xy.pecheny.me/board/2"
