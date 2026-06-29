"""Board-service plumbing shared by the ``board`` (formerly ``trello``) command.

Generalises chgksuite's Trello integration to also speak to xy boards
(https://xy.pecheny.me, an end-to-end-encrypted Trello-style editor whose API is
Trello-compatible). It covers:

- detecting the service (Trello vs xy) from a board URL;
- the per-host token store ``~/.chgksuite/.board_tokens.toml`` (a list of
  ``{host, token}``), with a one-time migration of the legacy ``.trello_token``;
- per-folder ``board_metadata.toml`` (``board_url`` + board ``passphrase`` for
  xy), which supersedes the legacy bare-id ``.board_id`` file.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import toml

from chgksuite.common import get_chgksuite_dir

TRELLO_HOST = "trello.com"


def _is_trello_host(host):
    host = (host or "").lower()
    return host == TRELLO_HOST or host == "www.trello.com" or host.endswith(".trello.com")


def parse_board_url(url):
    """Parse a board URL into a service descriptor.

    Returns a dict ``{service, host, board_id, base_url}`` where ``service`` is
    ``"trello"`` or ``"xy"``. Accepts:
      - ``https://trello.com/b/3CRjyqFW/blah``  → trello, board_id 3CRjyqFW
      - ``https://xy.pecheny.me/board/2``       → xy, board_id 2
      - a bare Trello board id (legacy ``.board_id`` contents)
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("empty board url")
    # bare trello board id (no scheme, no host, no path)
    if "/" not in url and "." not in url and "://" not in url:
        return {
            "service": "trello",
            "host": TRELLO_HOST,
            "board_id": url,
            "base_url": "https://trello.com",
        }
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.netloc.lower()
    if _is_trello_host(host):
        m = re.search(r"/b/([^/]+)", parsed.path)
        return {
            "service": "trello",
            "host": TRELLO_HOST,
            "board_id": m.group(1) if m else url,
            "base_url": "https://trello.com",
        }
    m = re.search(r"/board/([^/?#]+)", parsed.path)
    if not m:
        raise ValueError(f"cannot determine board id from url: {url}")
    return {
        "service": "xy",
        "host": host,
        "board_id": m.group(1),
        "base_url": f"{parsed.scheme}://{parsed.netloc}",
    }


def service_host(service_url):
    """Return the canonical token-store host for a board *service* URL.

    Trello collapses to ``trello.com``; xy keeps its own host so several xy
    deployments (xy.pecheny.me, xy.example.org, …) can each hold a token.
    """
    parsed = urlparse(service_url if "://" in service_url else "https://" + service_url)
    host = parsed.netloc.lower()
    if _is_trello_host(host) or not host:
        return TRELLO_HOST
    return host


# ---- token store: ~/.chgksuite/.board_tokens.toml ----


def _tokens_path():
    return os.path.join(get_chgksuite_dir(), ".board_tokens.toml")


def _legacy_trello_token_path():
    return os.path.join(get_chgksuite_dir(), ".trello_token")


def _read_tokens_file():
    path = _tokens_path()
    if not os.path.isfile(path):
        return []
    data = toml.loads(Path(path).read_text("utf8"))
    tokens = data.get("tokens") or []
    return [t for t in tokens if isinstance(t, dict) and t.get("host")]


def _write_tokens_file(tokens):
    Path(_tokens_path()).write_text(toml.dumps({"tokens": tokens}), "utf8")


def migrate_legacy_trello_token():
    """One-time: fold a legacy ``.trello_token`` into ``.board_tokens.toml``.

    Runs on first use of the new version. Adds a ``trello.com`` entry (unless one
    already exists) and deletes ``.trello_token``.
    """
    legacy = _legacy_trello_token_path()
    if not os.path.isfile(legacy):
        return
    token = Path(legacy).read_text("utf8").strip()
    tokens = _read_tokens_file()
    if token and not any(t.get("host") == TRELLO_HOST for t in tokens):
        tokens.append({"host": TRELLO_HOST, "token": token})
        _write_tokens_file(tokens)
    os.remove(legacy)


def load_board_tokens():
    migrate_legacy_trello_token()
    return _read_tokens_file()


def get_token_for_host(host):
    for t in load_board_tokens():
        if t.get("host") == host:
            return t.get("token")
    return None


def set_token_for_host(host, token):
    tokens = load_board_tokens()
    for t in tokens:
        if t.get("host") == host:
            t["token"] = token
            break
    else:
        tokens.append({"host": host, "token": token})
    _write_tokens_file(tokens)


# ---- per-folder board metadata: <folder>/board_metadata.toml ----
# A visible, service-agnostic file holding the board_url (and, for xy, the
# passphrase). Supersedes the legacy bare-id `.board_id` file.


def board_metadata_path(folder):
    return os.path.join(folder, "board_metadata.toml")


def read_board_metadata(folder):
    path = board_metadata_path(folder)
    if not os.path.isfile(path):
        return None
    return toml.loads(Path(path).read_text("utf8"))


def write_board_metadata(folder, board_url, passphrase=None):
    data = {"board_url": board_url}
    if passphrase is not None:
        data["passphrase"] = passphrase
    Path(board_metadata_path(folder)).write_text(toml.dumps(data), "utf8")


def migrate_legacy_board_id(folder):
    """One-time: fold a legacy ``.board_id`` (bare Trello id) into
    ``board_metadata.toml``, then delete it.

    Runs on the first ``board`` command with this folder as target.
    """
    legacy = os.path.join(folder, ".board_id")
    if not os.path.isfile(legacy):
        return
    if not os.path.isfile(board_metadata_path(folder)):
        board_id = Path(legacy).read_text("utf8").strip()
        if board_id:
            write_board_metadata(folder, f"https://trello.com/b/{board_id}")
    os.remove(legacy)
