#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import os
import re
import subprocess
import sys

from chgksuite.common import (
    get_chgksuite_dir,
    get_lastdir,
    log_wrap,
    read_text_file,
    set_lastdir,
)


def _gh(*args, input_data=None):
    """Run a gh CLI command and return stdout. Raises on failure."""
    cmd = ["gh"] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True, input=input_data
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _get_repo(args):
    """Get the repo identifier (owner/name) from args or .board_id file."""
    if hasattr(args, "board_id") and args.board_id:
        repo = args.board_id
    else:
        board_id_path = os.path.join(args.folder, ".board_id")
        if os.path.isfile(board_id_path):
            with open(board_id_path, "r", encoding="utf-8") as f:
                repo = f.read().rstrip()
        else:
            repo = _ask_repo(path=args.folder)
    # Normalize: extract owner/repo from full URL if needed
    m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)", repo)
    if m:
        repo = m.group(1)
    return repo


def _ask_repo(path=None):
    print("To communicate with your GitHub repo we need its identifier.")
    print("Your repo looks like this:")
    print()
    print("https://github.com/owner/repo")
    print("                    owner/repo")
    print()
    repo = input(
        "Please paste your repo (owner/repo or full URL): "
    ).rstrip()
    m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)", repo)
    if m:
        repo = m.group(1)
    if path:
        with open(os.path.join(path, ".board_id"), "w", encoding="utf-8") as f:
            f.write(repo)
    return repo


def _get_project_number(repo):
    """Find the first project linked to the repo, if any. Returns number or None."""
    owner = repo.split("/")[0]
    try:
        out = _gh(
            "project", "list", "--owner", owner, "--format", "json",
            "--limit", "100",
        )
        projects = json.loads(out)
        if projects.get("projects"):
            return projects["projects"][0]["number"]
    except (json.JSONDecodeError, SystemExit):
        pass
    return None


def _get_project_status_field(owner, project_number):
    """Get the Status field ID and option mappings for a project."""
    out = _gh(
        "project", "field-list", str(project_number),
        "--owner", owner, "--format", "json",
    )
    fields = json.loads(out)
    for field in fields.get("fields", []):
        if field.get("name") == "Status":
            options = {
                opt["name"]: opt["id"]
                for opt in field.get("options", [])
            }
            return field["id"], options
    return None, {}


def upload_file(filepath, repo, list_name=None, author=False, project_number=None):
    owner = repo.split("/")[0]
    status_field_id = None
    status_option_id = None

    if list_name and project_number:
        status_field_id, status_options = _get_project_status_field(
            owner, project_number
        )
        if status_field_id and list_name in status_options:
            status_option_id = status_options[list_name]
        elif status_field_id:
            print(
                f"Warning: Status option '{list_name}' not found in project. "
                f"Available: {list(status_options.keys())}"
            )

    content = read_text_file(filepath)
    cards = re.split(r"(\r?\n){2,}", content)
    cards = [x for x in cards if x != "" and x != "\n" and x != "\r\n"]
    for card in cards:
        caption = "вопрос"
        if re.search("\n! (.+?)\r?\n", card):
            caption = re.search("\n! (.+?)\\.?\r?\n", card).group(1)
            if author and re.search("\n@ (.+?)\\.?\r?\n", card):
                caption += " {}".format(re.search("\n@ (.+?)\r?\n", card).group(1))

        url = _gh(
            "issue", "create",
            "--repo", repo,
            "--title", caption,
            "--body", card,
        )
        print("Successfully created {}  {}".format(log_wrap(caption), url))

        if project_number and status_option_id:
            _gh(
                "project", "item-add", str(project_number),
                "--owner", owner,
                "--url", url,
            )
            # Moving to a specific status column would require GraphQL;
            # for now items land in the default column.


def gui_github_upload(args):
    get_lastdir()

    repo = _get_repo(args)
    project_number = _get_project_number(repo)

    if isinstance(args.filename, (list, tuple)):
        if len(args.filename) == 1 and os.path.isdir(args.filename[0]):
            for filename in os.listdir(args.filename[0]):
                if filename.endswith(".4s"):
                    filepath = os.path.join(args.filename[0], filename)
                    upload_file(
                        filepath, repo,
                        list_name=args.list_name,
                        author=args.author,
                        project_number=project_number,
                    )
            set_lastdir(args.filename[0])
        else:
            for filename in args.filename:
                upload_file(
                    filename, repo,
                    list_name=args.list_name,
                    author=args.author,
                    project_number=project_number,
                )
                set_lastdir(filename)
    elif isinstance(args.filename, str):
        if os.path.isdir(args.filename):
            for filename in os.listdir(args.filename):
                if filename.endswith(".4s"):
                    filepath = os.path.join(args.filename, filename)
                    upload_file(
                        filepath, repo,
                        list_name=args.list_name,
                        author=args.author,
                        project_number=project_number,
                    )
                    set_lastdir(filepath)
        elif os.path.isfile(args.filename):
            upload_file(
                args.filename, repo,
                list_name=args.list_name,
                author=args.author,
                project_number=project_number,
            )
            set_lastdir(args.filename)


def gui_github_download(args):
    from collections import defaultdict

    ld = get_lastdir()

    repo = _get_repo(args)
    ld = args.folder
    set_lastdir(ld)
    os.chdir(args.folder)

    # Fetch all open issues from the repo
    out = _gh(
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "--limit", "10000",
        "--json", "title,body,labels,projectItems",
    )
    issues = json.loads(out)

    if not issues:
        print("No open issues found.")
        return

    # Group issues by project status (column) or by label
    _lists = defaultdict(list)
    _label_lists = defaultdict(list)

    for issue in issues:
        title = issue.get("title", "")
        body = issue.get("body", "")
        labels = [l["name"] for l in issue.get("labels", [])]

        # Determine which "list" (status column) this issue belongs to
        list_name = "default"
        for pi in issue.get("projectItems", []):
            status = pi.get("status", {})
            if isinstance(status, dict):
                list_name = status.get("name", list_name)
            elif isinstance(status, str) and status:
                list_name = status

        if args.lists:
            good_lists = [x.strip() for x in args.lists.split(",")]
            if list_name not in good_lists:
                continue

        card_text = body.strip() if body else ""
        if args.si and title:
            entry = title + "\n\n" + card_text
        else:
            entry = card_text

        _lists[list_name].append(entry)

        if args.labels:
            for label in labels:
                _label_lists[label].append(entry)

    if args.singlefile:
        filename = "singlefile.4s"
        print("outputting {}".format(filename))
        with open(filename, "w", encoding="utf-8") as f:
            for list_name in _lists:
                for item in _lists[list_name]:
                    f.write("\n" + item + "\n")
    else:
        for list_name in _lists:
            safe_name = list_name.replace("/", "_")
            filename = "{}.4s".format(safe_name)
            print("outputting {}".format(filename))
            with open(filename, "w", encoding="utf-8") as f:
                for item in _lists[list_name]:
                    f.write("\n" + item + "\n")

    if args.labels:
        for label in _label_lists:
            safe_name = label.replace("/", "_")
            filename = "{}.4s".format(safe_name)
            print("outputting {} (label)".format(filename))
            with open(filename, "w", encoding="utf-8") as f:
                for item in _label_lists[label]:
                    f.write("\n" + item + "\n")


def get_token(tokenpath, args):
    print("GitHub authentication uses the gh CLI tool.")
    print("Run 'gh auth login' to authenticate if you haven't already.")
    print()
    # Check if gh is already authenticated
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    if result.returncode == 0:
        print("Already authenticated:")
        print(result.stdout or result.stderr)
        with open(tokenpath, "w", encoding="utf-8") as f:
            f.write("gh-cli-auth")
        return "gh-cli-auth"
    else:
        print("Not authenticated. Running 'gh auth login'...")
        os.execvp("gh", ["gh", "auth", "login"])


def gui_github(args):
    csdir = get_chgksuite_dir()
    tokenpath = os.path.join(csdir, ".github_token")

    if args.boardsubcommand == "token":
        get_token(tokenpath, args)
        return

    # Verify gh is authenticated
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("GitHub CLI (gh) is not authenticated.")
        print("Please run 'gh auth login' first, or 'chgksuite boards token --provider github'.")
        sys.exit(1)

    if args.boardsubcommand == "download":
        gui_github_download(args)
    elif args.boardsubcommand == "upload":
        gui_github_upload(args)
