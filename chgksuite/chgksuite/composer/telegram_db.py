"""The Telegram export's record, ~/.chgksuite/telegram.db.

The same file is written by the Go chgksuite, so the schema below is a
contract between the two tools: change it in both or in neither. The
``messages`` and ``bot_status`` tables are the sidecar bot's inbox; ``exports``
and ``posts`` are what each export sent, kept so the posts can be found and
edited later. See docs/telegram-db.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from chgksuite.common import get_chgksuite_dir

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (raw_data TEXT, chat_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS bot_status (raw_data TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS exports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool TEXT NOT NULL,
  tool_version TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  tgaccount TEXT NOT NULL,
  bot_id INTEGER,
  channel_id TEXT NOT NULL,
  chat_id TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  export_id INTEGER NOT NULL REFERENCES exports(id),
  chat_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  link TEXT,
  question_number TEXT,
  role TEXT NOT NULL,
  content_type TEXT NOT NULL,
  reply_to_message_id INTEGER,
  text TEXT,
  parse_mode TEXT,
  entities TEXT,
  sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_export ON posts(export_id);
CREATE INDEX IF NOT EXISTS messages_created ON messages(created_at);
"""

# The inbox is only read while its export runs; older rows are dropped.
INBOX_RETENTION = timedelta(days=7)

# parse_mode of a sendRichMessage post, whose text is the rich HTML as sent.
RICH_PARSE_MODE = "rich_html"
HTML_PARSE_MODE = "HTML"

# posts.role: what a message is. A message holding several parts is named after
# its main part.
ROLE_HEADING = "heading"
ROLE_NAVIGATION = "navigation"
ROLE_QUESTION = "question"
ROLE_ANSWER = "answer"
ROLE_COMMENT = "comment"
ROLE_HANDOUT = "handout"
ROLE_POLL = "poll"
ROLE_OTHER = "other"
ROLES = (
    ROLE_HEADING,
    ROLE_NAVIGATION,
    ROLE_QUESTION,
    ROLE_ANSWER,
    ROLE_COMMENT,
    ROLE_HANDOUT,
    ROLE_POLL,
    ROLE_OTHER,
)

# posts.content_type
CONTENT_TEXT = "text"
CONTENT_PHOTO = "photo"
CONTENT_POLL = "poll"


@dataclass(frozen=True)
class PostKind:
    """What a message about to be sent is, for its row in ``posts``."""

    role: str = ROLE_OTHER
    question_number: object = None

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"unknown post role {self.role!r}")


@dataclass(frozen=True)
class SentPost:
    """A message Telegram accepted, as its row in ``posts`` records it."""

    chat_id: object
    message_id: int
    content_type: str
    kind: PostKind
    text: str = None
    parse_mode: str = None
    reply_to_message_id: int = None
    link: str = None


def telegram_db_path():
    return os.path.join(get_chgksuite_dir(), "telegram.db")


def utc_now():
    return utc_iso(datetime.now(timezone.utc))


def utc_ago(delta):
    return utc_iso(datetime.now(timezone.utc) - delta)


def utc_iso(moment):
    """Timestamps are UTC with a fixed width, so they compare as strings."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def connect(path=None):
    conn = sqlite3.connect(path or telegram_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    return conn


def prune_inbox(conn):
    threshold = utc_ago(INBOX_RETENTION)
    conn.execute("DELETE FROM messages WHERE created_at < ?", (threshold,))
    conn.execute("DELETE FROM bot_status WHERE created_at < ?", (threshold,))
    conn.commit()


def sources_digest(paths):
    """The path and sha256 of what was exported; merged files are joined."""
    sha = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 16), b""):
                sha.update(block)
    return "\n".join(os.path.abspath(p) for p in paths), sha.hexdigest()


class ExportRecord:
    """One run's rows in ``exports`` and ``posts``, each written as it happens."""

    def __init__(self, conn, export_id):
        self.conn = conn
        self.export_id = export_id

    @classmethod
    def start(
        cls,
        conn,
        *,
        tool,
        tool_version,
        source_path,
        source_sha256,
        tgaccount,
        bot_id,
        channel_id,
        chat_id,
    ):
        cur = conn.execute(
            """INSERT INTO exports (tool, tool_version, source_path, source_sha256,
                 tgaccount, bot_id, channel_id, chat_id, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tool,
                tool_version,
                source_path,
                source_sha256,
                tgaccount,
                bot_id,
                str(channel_id),
                None if chat_id is None else str(chat_id),
                utc_now(),
            ),
        )
        conn.commit()
        return cls(conn, cur.lastrowid)

    def add_post(self, post, entities=None):
        question_number = post.kind.question_number
        cur = self.conn.execute(
            """INSERT INTO posts (export_id, chat_id, message_id, link,
                 question_number, role, content_type, reply_to_message_id, text,
                 parse_mode, entities, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.export_id,
                str(post.chat_id),
                post.message_id,
                post.link,
                None if question_number is None else str(question_number),
                post.kind.role,
                post.content_type,
                post.reply_to_message_id,
                post.text,
                post.parse_mode,
                None if entities is None else json.dumps(entities, ensure_ascii=False),
                utc_now(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_post_text(self, post_id, text):
        """A photo is sent with a stub caption and then edited to its text."""
        self.conn.execute("UPDATE posts SET text = ? WHERE id = ?", (text, post_id))
        self.conn.commit()

    def finish(self):
        self.conn.execute(
            "UPDATE exports SET finished_at = ? WHERE id = ?",
            (utc_now(), self.export_id),
        )
        self.conn.commit()
