#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import os
import argparse
import inspect
import json

ALLOWED_IMAGES = ["long_handout.png", "test.jpg"]

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)

with open(os.path.join(currentdir, "settings.json")) as f:
    settings = json.loads(f.read())

from chgksuite.parser import (  # noqa: E402
    chgk_parse_txt,
    chgk_parse_docx,
    compose_4s,
    si_parse_docx,
    si_parse_text,
)
from chgksuite.common import read_text_file  # noqa: E402


from chgksuite_test import DefaultArgs  # noqa: E402


def workaround_chgk_parse(filename, game=None, **kwargs):
    args = DefaultArgs(**kwargs)
    if game == "si":
        if not getattr(args, "numbers_handling", None) or args.numbers_handling == "default":
            args.numbers_handling = "all"
        if filename.endswith(".docx"):
            return si_parse_docx(filename, args=args)
        if filename.endswith(".txt"):
            return si_parse_text(read_text_file(filename), args=args)
        return None
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename, args=args)
    if filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=args)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsing_engine", default="mammoth")
    parser.add_argument("file", nargs="?", help="Single file to canonize (optional)")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        files = os.listdir(currentdir)

    for filename in files:
        if filename.endswith((".docx", ".txt")):
            print("Canonizing {}...".format(filename))
            file_settings = settings.get(filename, {})
            function_args = file_settings.get("function_args") or {}
            game = file_settings.get("game")
            parsed = workaround_chgk_parse(
                os.path.join(currentdir, filename),
                game=game,
                parsing_engine=args.parsing_engine,
                **function_args,
            )
            for filename1 in os.listdir(currentdir):
                if (
                    filename1.endswith((".jpg", ".jpeg", ".png", ".gif"))
                    and not filename1.startswith("ALLOWED")
                    and filename1 not in ALLOWED_IMAGES
                ):
                    os.remove(os.path.join(currentdir, filename1))
            compose_args = DefaultArgs()
            if game:
                compose_args.game = game
            if game == "si":
                compose_args.numbers_handling = "all"
            with open(
                os.path.join(currentdir, filename) + ".canon", "w", encoding="utf-8"
            ) as f:
                f.write(compose_4s(parsed, args=compose_args))


if __name__ == "__main__":
    main()
