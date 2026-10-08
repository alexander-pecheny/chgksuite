import json
from datetime import timedelta
from pathlib import Path


import chgksuite.composer.telegram as telegram_module
import chgksuite.composer.telegram_db as telegram_db_module
from chgksuite.common import DefaultArgs
from chgksuite.composer.telegram import TelegramExporter
from chgksuite.composer.telegram_db import (
    ROLE_COMMENT,
    ROLE_POLL,
    PostKind,
    connect,
    prune_inbox,
    utc_ago,
    utc_now,
)

CHANNEL = "-1001111"
CHAT = "-1002222"

NO_STATS = "? Вопрос один\n! Ответ\n/ Комментарий\n"


class FakeTelegram:
    """Answers the Bot API calls the exporter makes, numbering the messages."""

    def __init__(self):
        self.calls = []
        self.next_id = 100

    def __call__(self, method, data=None, files=None):
        self.calls.append(method)
        if method == "editMessageCaption":
            return True
        self.next_id += 1
        return {"message_id": self.next_id}


def _exporter(tmp_path, monkeypatch, structure=None, **args):
    """A real exporter whose Telegram side is faked: no bot, no network."""
    monkeypatch.setattr(telegram_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(telegram_module, "get_chgksuite_dir", lambda: str(tmp_path))
    monkeypatch.setattr(telegram_db_module, "get_chgksuite_dir", lambda: str(tmp_path))

    def init_telegram(self):
        self.init_db()
        self.bot_id = 42

    monkeypatch.setattr(TelegramExporter, "init_telegram", init_telegram)
    args.setdefault("regexes_file", DefaultArgs.regexes)
    exporter = TelegramExporter(structure or [], DefaultArgs(**args), {})
    exporter.channel_id = CHANNEL
    exporter.chat_id = CHAT
    exporter.send_api_request = FakeTelegram()
    exporter.get_discussion_message = lambda channel, message_id: message_id + 5000
    return exporter


def _start(exporter, source):
    exporter.dir_kwargs = {"source_paths": [str(source)]}
    exporter._start_record()


def _posts(exporter):
    return [
        dict(row) for row in exporter.db_conn.execute("SELECT * FROM posts ORDER BY id")
    ]


def test_connect_creates_the_shared_schema(tmp_path):
    path = str(tmp_path / "telegram.db")
    connect(path).close()
    conn = connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"messages", "bot_status", "exports", "posts"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_prune_inbox_drops_only_old_rows(tmp_path):
    conn = connect(str(tmp_path / "telegram.db"))
    old, new = utc_ago(timedelta(days=8)), utc_now()
    for created_at in (old, new):
        conn.execute("INSERT INTO messages VALUES (?, ?, ?)", ("{}", CHAT, created_at))
        conn.execute("INSERT INTO bot_status VALUES (?, ?)", ("{}", created_at))
    prune_inbox(conn)
    assert [r[0] for r in conn.execute("SELECT created_at FROM messages")] == [new]
    assert [r[0] for r in conn.execute("SELECT created_at FROM bot_status")] == [new]


def test_export_records_every_post(tmp_path, monkeypatch):
    source = tmp_path / "pack.4s"
    source.write_text(NO_STATS, encoding="utf8")
    exporter = _exporter(tmp_path, monkeypatch, tgaccount="club")
    _start(exporter, source)

    exporter.tg_process_element(["heading", "Кубок"])
    exporter.tg_process_element(
        ["Question", {"number": 7, "question": "Текст", "answer": "Ответ"}]
    )
    exporter._post_poll(
        CHAT,
        {"text": "Вопрос {NUMBER}", "variants": ["a", "b"]},
        {"NUMBER": 7},
        kind=PostKind(ROLE_POLL, 7),
    )
    exporter._post(
        CHAT,
        "подпись",
        str(source),
        reply_to_message_id=9,
        kind=PostKind(ROLE_COMMENT),
    )
    exporter.record.finish()

    export = dict(exporter.db_conn.execute("SELECT * FROM exports").fetchone())
    assert export["tool"] == "chgksuite"
    assert export["tgaccount"] == "club"
    assert export["bot_id"] == 42
    assert export["channel_id"] == CHANNEL
    assert export["chat_id"] == CHAT
    assert export["source_path"] == str(source)
    assert len(export["source_sha256"]) == 64
    assert export["finished_at"] is not None

    posts = _posts(exporter)
    assert [(p["role"], p["content_type"], p["question_number"]) for p in posts] == [
        ("heading", "text", None),
        ("question", "text", "7"),
        ("poll", "poll", "7"),
        ("comment", "photo", None),
    ]
    heading, question, poll, photo = posts
    assert heading["chat_id"] == CHANNEL
    assert heading["parse_mode"] == "rich_html"
    assert heading["text"] == "<h3>Кубок</h3>"
    assert question["link"] == f"https://t.me/c/1111/{question['message_id']}"
    assert "Ответ" in question["text"]
    assert poll["text"] == "Вопрос 7"
    # The photo goes out with a stub caption; the row keeps the edited text.
    assert photo["text"] == "подпись"
    assert photo["reply_to_message_id"] == 9
    assert photo["entities"] is None


def test_a_crashed_export_keeps_its_posts(tmp_path, monkeypatch):
    source = tmp_path / "pack.4s"
    source.write_text(NO_STATS, encoding="utf8")
    exporter = _exporter(tmp_path, monkeypatch)
    _start(exporter, source)
    exporter._post(CHANNEL, "первый", None)

    export = exporter.db_conn.execute(
        "SELECT tgaccount, finished_at FROM exports"
    ).fetchone()
    assert tuple(export) == ("", None)
    assert len(_posts(exporter)) == 1


def test_dry_run_records_nothing(tmp_path, monkeypatch):
    exporter = _exporter(tmp_path, monkeypatch, dry_run=True)
    exporter.tg_process_element(
        ["Question", {"number": 1, "question": "Текст", "answer": "Ответ"}]
    )
    assert exporter.db_conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert _posts(exporter) == []
    assert exporter.send_api_request.calls == []


def test_inbox_queries_ignore_earlier_runs(tmp_path, monkeypatch):
    """A forward left by an earlier run must not answer this run's prompt."""
    exporter = _exporter(tmp_path, monkeypatch)
    exporter.control_chat_id = 77
    exporter.created_at = None
    exporter.run_started_at = utc_now()

    def forward(created_at, channel):
        update = {
            "message": {
                "chat": {"id": 77, "type": "private"},
                "forward_from_chat": {"id": channel, "type": "channel"},
            }
        }
        exporter.db_conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?)",
            (json.dumps(update), "77", created_at),
        )
        exporter.db_conn.commit()

    forward(utc_ago(timedelta(seconds=30)), -1009999)
    assert exporter.wait_for_forwarded_message(entity_type="channel") is None

    forward(utc_now(), -1008888)
    assert exporter.wait_for_forwarded_message(entity_type="channel") == 8888


IMAGE = Path(__file__).parent / "test.jpg"


def _plain_question_roles(tmp_path, monkeypatch, question):
    """The (role, content_type, question_number) of each post of one question."""
    source = tmp_path / "pack.4s"
    source.write_text(NO_STATS, encoding="utf8")
    exporter = _exporter(tmp_path, monkeypatch)
    exporter.rich_mode = False
    _start(exporter, source)
    exporter.tg_process_element(["Question", dict(question, number=4)])
    return [
        (p["role"], p["content_type"], p["question_number"]) for p in _posts(exporter)
    ]


def test_a_reply_under_a_custom_label_is_a_comment(tmp_path, monkeypatch):
    question = {
        "question": "Текст",
        "answer": "Ответ",
        "comment": "к" * 3000,
        "source": "и" * 1500,
        "overrides": {"source": "Литература", "answer": "Решение"},
    }
    assert _plain_question_roles(tmp_path, monkeypatch, question) == [
        ("question", "text", "4"),
        ("comment", "text", "4"),
    ]


def test_an_author_only_reply_is_a_comment(tmp_path, monkeypatch):
    question = {
        "question": "Текст",
        "answer": "Ответ",
        "comment": "к" * 3900,
        "author": "Автор Авторов, " * 20,
    }
    assert _plain_question_roles(tmp_path, monkeypatch, question) == [
        ("question", "text", "4"),
        ("comment", "text", "4"),
    ]


def test_a_photo_only_reply_is_a_comment(tmp_path, monkeypatch):
    question = {"question": "Текст", "answer": f"Ответ (img {IMAGE})"}
    assert _plain_question_roles(tmp_path, monkeypatch, question) == [
        ("question", "text", "4"),
        ("comment", "photo", "4"),
    ]


def test_si_buffer_with_one_question_keeps_its_number(tmp_path, monkeypatch):
    source = tmp_path / "pack.4s"
    source.write_text(NO_STATS, encoding="utf8")
    exporter = _exporter(tmp_path, monkeypatch, game="si")
    _start(exporter, source)

    exporter.tg_process_element(["Question", {"number": 30, "question": "Т", "answer": "О"}])
    exporter._flush_buffer()
    for number in (10, 20):
        exporter.tg_process_element(
            ["Question", {"number": number, "question": "Т", "answer": "О"}]
        )
    exporter._flush_buffer()

    assert [(p["role"], p["question_number"]) for p in _posts(exporter)] == [
        ("question", "30"),
        ("question", None),
    ]
