# Release chgksuite projects

Follow these steps carefully, pausing for user input where indicated.

## Step 1: Determine what needs releasing

Find the latest git tag:

```
git describe --tags --abbrev=0
```

If there are no tags yet, use the initial commit as the baseline.

Then check which projects have changes since that tag:

```
git log <latest-tag>..HEAD --oneline -- chgksuite/
git log <latest-tag>..HEAD --oneline -- chgksuite_qt/
git log <latest-tag>..HEAD --oneline -- chgksuite_tk/
```

Report which projects have changes and need releasing. If none have changes, stop and tell the user.

## Step 2: Show change summary and versions

For each project with changes, show:

1. The commit log since the last tag (from step 1)
2. A draft of release notes: read the diffs and commit messages, then write a human-readable summary in the style of HISTORY.md entries -- concise bullet points describing user-facing changes, not raw commit titles
3. The current version from `version.py`:
   - Core: `chgksuite/chgksuite/version.py`
   - Qt: `chgksuite_qt/chgksuite_qt/version.py`
   - Tk: `chgksuite_tk/chgksuite_tk/version.py`
4. The latest PyPI version for each project being released:
   ```
   curl -s "https://pypi.org/pypi/chgksuite/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
   curl -s "https://pypi.org/pypi/chgksuite-qt/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
   curl -s "https://pypi.org/pypi/chgksuite-tk/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
   ```

Present all of this to the user and proceed to step 3.

## Step 3: User provides release notes and version bumps

Ask the user (using AskUserQuestion or just prompting them):

- What text to add to HISTORY.md (release notes are only for chgksuite core). Offer the draft from step 2 as a starting point.
- Which version number(s) to use for each project being released (patch / minor / major bump, or an explicit version).

Wait for the user to provide this information before continuing.

## Step 4: Update files, commit, publish

1. Update `__version__` in the `version.py` file for each project being released
2. Insert the release notes into `HISTORY.md` at the monorepo root, right after the `# What's new` header line. The format should be:

   ```
   ## version (YYYY-MM-DD)

   - bullet point
   - bullet point
   ```

   Insert this block (with a blank line before and after) between the `# What's new` header and the first existing `## v...` entry.

3. Commit all the changed files with a message like: `Release chgksuite v{version}, chgksuite-qt v{version}, ...` (list only the projects being released). Do NOT push yet.

4. For each project being released, build and publish to PyPI:
   ```
   cd <project-dir> && rm -rf dist && uv build && uv publish
   ```
   Run each project sequentially. If any publish fails, stop and report to the user.

## Step 5: Git tags and GitLab release

1. Push the commit:
   ```
   git push
   ```

2. Create git tags. Tag naming conventions:
   - Core (`chgksuite`): `v{version}` (e.g. `v0.29.0`)
   - Qt (`chgksuite_qt`): `qt-v{version}` (e.g. `qt-v0.0.8`)
   - Tk (`chgksuite_tk`): `tk-v{version}` (e.g. `tk-v0.0.6`)

   The **core tag must be annotated** with the release notes (this is how release notes propagate to GitHub via the CI workflow):
   ```
   git tag -a v{version} -m "<release notes>"
   ```

   Qt and Tk tags can be lightweight:
   ```
   git tag qt-v{version}
   git tag tk-v{version}
   ```

   Push all tags:
   ```
   git push origin v{version} qt-v{version} tk-v{version}
   ```

3. Create a GitLab release **only for chgksuite core** using the release notes:
   ```
   glab release create v{version} --notes "<release notes>"
   ```

## Step 6: Telegram announcement

Print the release notes formatted for Telegram: take the HISTORY.md entry and replace `-` list markers with `*`. Output this as a code block so the user can copy it.
