# /// script
# dependencies = ["fonttools"]
# ///
"""Subset the bundled Noto Sans fonts to the codepoints in noto_keep_unicodes.txt.

The keeplist = every character ever used in db.chgk.info packets (2022 dump)
plus full Latin/Latin-Ext-A/Cyrillic(+Supplement)/Greek/combining-diacritics/
General-Punctuation blocks. Hinting is kept for on-screen rendering on Windows.

Source fonts: full Noto Sans LGC from
https://github.com/notofonts/latin-greek-cyrillic/releases

Usage: uv run scripts/subset_noto_fonts.py <dir-with-full-NotoSans-ttfs>
"""

import os
import sys

from fontTools import subset

FACES = ["Regular", "Bold", "Italic", "BoldItalic"]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEEP_FILE = os.path.join(SCRIPT_DIR, "noto_keep_unicodes.txt")
OUT_DIR = os.path.join(
    SCRIPT_DIR, "..", "chgksuite", "chgksuite", "resources", "fonts"
)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source_dir = sys.argv[1]

    with open(KEEP_FILE) as f:
        unicodes = ",".join(line.strip() for line in f if line.strip())

    for face in FACES:
        src = os.path.join(source_dir, f"NotoSans-{face}.ttf")
        out = os.path.join(OUT_DIR, f"NotoSans-{face}.ttf")
        subset.main(
            [
                src,
                f"--unicodes={unicodes}",
                "--layout-features=*",
                "--name-IDs=*",
                "--name-legacy",
                f"--output-file={out}",
            ]
        )
        print(f"{out}: {os.path.getsize(out)} bytes")


if __name__ == "__main__":
    main()
