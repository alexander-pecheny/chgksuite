#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Parser for СИ (Своя Игра) format documents.
Reuses DOCX extraction from parser.py, applies SI-specific text parsing.

SI structure: Пакет → Бой → Тема → Вопрос
Questions numbered 10-50 per theme (default step 10).
"""

import os
import re
import sys

import chgksuite.typotools as typotools
from chgksuite.common import (
    QUESTION_LABELS,
    DefaultNamespace,
    DummyLogger,
    compose_4s,
    init_logger,
    set_lastdir,
    load_settings,
)
from chgksuite.composer.composer_common import make_filename, game_to_ext
from chgksuite.typotools import remove_excessive_whitespace as rew

SEP = "\n"

# SI-specific regexes
RE_THEME = re.compile(r"^Тема\s+(\d+)\.\s*(.*)", re.IGNORECASE)
RE_THEME_COMMENT = re.compile(r"^Комментарий к теме[\.:]", re.IGNORECASE)
RE_BATTLE = re.compile(r"^(?:БОЙ|Бой)\s+([IVXLCDM\d]+)", re.IGNORECASE)
RE_BATTLE_NUMBERED = re.compile(r"^(\d+)\.\s+([А-ЯЁA-Z\s\-–—]+)$")
RE_SI_QUESTION_NUM = re.compile(r"^(\d+)\.\s+")
RE_SI_QUESTION_NUM_ONLY = re.compile(r"^(\d+)\.?$")
SI_QUESTION_NUMBERS = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}

# Standard field regexes (reused from ChgkParser)
RE_ANSWER = re.compile(r"О[Тт][Вв][Ее][Тт][Ыы]?\s?[№N]?(\d+)?\s?[\\.:]")
RE_ZACHET = re.compile(r"З[Аа][Чч][ЕеЁё][Тт]\s?[\\.:]")
RE_NEZACHET = re.compile(r"Н[Ее][Зз][Аа][Чч][ЕеЁё][Тт]\s?[\\.:]")
RE_COMMENT = re.compile(
    r"К[Оо][Мм][Мм]?([Ее][Нн][Тт]([Аа][Рр][Ии][ИиЙй]|\.)|\.)\s?[№N]?(\d+)?\s?[\\.:]"
)
RE_AUTHOR = re.compile(r"А[Вв][Тт][Оо][Рр](\(?[Ыы]?\)?|[Кк][АаИи])?\s?[\\.:]")
RE_SOURCE = re.compile(r"И[Сс][Тт][Оо][Чч][Нн][Ии][Кк]\(?[Ии]?\)?\s?[\\.:]")
RE_EDITOR = re.compile(
    r"[Рр][Ее][Дд][Аа][Кк][Тт][Оо][Рр]([Ыы]|[Сс][Кк][Аа][Яя]\s[Гг][Рр][Уу][Пп][Пп][Аа])?(\s?[\\.:]|\s[\-–—]+\s)"
)
RE_YOUR_THEMES = re.compile(r"^Ваши\s+темы\s*:", re.IGNORECASE)

# Style-based heading markers (injected by si_parse_docx from DOCX heading styles)
RE_STYLE_HEADING = re.compile(r"^\$\$H(\d)\$\$\s*(.*)")
RE_ROUND_NAME = re.compile(r"(открытый|полуоткрытый|закрытый)\s+раунд", re.IGNORECASE)


def si_parse_text(text, args=None, logger=None):
    """
    Parse plain text extracted from SI DOCX into a structure with
    battle/theme/question elements.
    """
    args = args or DefaultNamespace()
    logger = logger or init_logger("si_parser")

    lines = text.split("\n")
    structure = []
    current_field = None
    current_content = ""
    heading_found = False
    in_theme_list = False  # skip "Ваши темы:" blocks

    # Typography settings
    if ("«" in text or "»" in text) and args.typography_quotes == "smart":
        typography_quotes = "smart_disable"
    else:
        typography_quotes = getattr(args, "typography_quotes", "on") or "on"
    if "\u0301" in text and args.typography_accents == "smart":
        typography_accents = "smart_disable"
    else:
        typography_accents = getattr(args, "typography_accents", "on") or "on"

    def flush():
        nonlocal current_field, current_content
        if current_field and current_content.strip():
            content = rew(current_content)
            content = typotools.recursive_typography(
                content,
                accents=typography_accents,
                dashes=getattr(args, "typography_dashes", "on"),
                quotes=typography_quotes,
                wsp=getattr(args, "typography_whitespace", "on"),
                percent=getattr(args, "typography_percent", "on"),
            )
            structure.append([current_field, content])
        current_field = None
        current_content = ""

    def apply_typo(s):
        return typotools.recursive_typography(
            s,
            accents=typography_accents,
            dashes=getattr(args, "typography_dashes", "on"),
            quotes=typography_quotes,
            wsp=getattr(args, "typography_whitespace", "on"),
            percent=getattr(args, "typography_percent", "on"),
        )

    after_theme = False  # track if we just saw a theme header

    for line in lines:
        stripped = rew(line)

        # Skip empty lines (they act as separators)
        if not stripped:
            after_theme = False
            continue

        # Check for style-based heading markers (from DOCX heading styles)
        m_style = RE_STYLE_HEADING.search(stripped)
        if m_style:
            level = int(m_style.group(1))
            heading_text = rew(m_style.group(2))
            if not heading_text:
                continue  # skip empty headings
            flush()
            in_theme_list = False
            if RE_ROUND_NAME.search(heading_text):
                structure.append(["round", apply_typo(heading_text)])
            elif level == 1:
                structure.append(["battle", apply_typo(heading_text)])
            elif level == 2:
                if re.match(r"тем[ыа]\s*:?$", heading_text, re.IGNORECASE):
                    in_theme_list = True
                structure.append(["meta", apply_typo(heading_text)])
            elif level == 3:
                # Strip leading "N. " from theme name
                theme_text = re.sub(r"^\d+\.\s*", "", heading_text)
                structure.append(["theme", apply_typo(theme_text)])
                after_theme = True
            continue

        # Check for "Ваши темы:" block - preserve as meta
        if RE_YOUR_THEMES.search(stripped):
            flush()
            in_theme_list = True
            structure.append(["meta", apply_typo(stripped)])
            continue

        # Check for theme header BEFORE theme list skip (theme terminates the list)
        m_theme = RE_THEME.search(stripped)
        if m_theme:
            in_theme_list = False
            flush()
            theme_name = apply_typo(m_theme.group(2).strip())
            structure.append(["theme", theme_name])
            after_theme = True
            continue

        if in_theme_list:
            # Theme list items - append to the last meta element (the "Ваши темы:" line)
            if structure and structure[-1][0] == "meta":
                structure[-1][1] += SEP + apply_typo(stripped)
            else:
                structure.append(["meta", apply_typo(stripped)])
            continue

        # Check for theme comment (before regular comment check)
        if RE_THEME_COMMENT.search(stripped):
            flush()
            current_field = "comment"
            current_content = RE_THEME_COMMENT.sub("", stripped)
            continue

        # Check for battle header: "БОЙ I" or "БОЙ 1"
        m = RE_BATTLE.search(stripped)
        if m:
            flush()
            structure.append(["battle", apply_typo(stripped)])
            continue

        # Check for numbered battle header like "1. ПИСЬМЕННЫЙ ОТБОР"
        # (uppercase section names that are not themes)
        m = RE_BATTLE_NUMBERED.search(stripped)
        if m and not RE_THEME.search(stripped):
            flush()
            structure.append(["battle", apply_typo(stripped)])
            continue

        # Check for editor line
        m = RE_EDITOR.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_EDITOR.sub("", stripped, 1).strip()
            if not heading_found and not structure:
                # This might be at the top, treat as meta
                structure.append(["editor", apply_typo(content)])
            else:
                structure.append(["editor", apply_typo(content)])
            continue

        # Check for author line
        m = RE_AUTHOR.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_AUTHOR.sub("", stripped, 1).strip()
            if after_theme:
                # Theme-level author — keep as standalone author element
                structure.append(["author", apply_typo(content)])
            else:
                current_field = "author"
                current_content = content
            continue

        # Check for answer
        m = RE_ANSWER.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_ANSWER.sub("", stripped, 1).strip()
            current_field = "answer"
            current_content = content
            continue

        # Check for зачёт
        m = RE_ZACHET.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_ZACHET.sub("", stripped, 1).strip()
            current_field = "zachet"
            current_content = content
            continue

        # Check for незачёт
        m = RE_NEZACHET.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_NEZACHET.sub("", stripped, 1).strip()
            current_field = "nezachet"
            current_content = content
            continue

        # Check for comment
        m = RE_COMMENT.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_COMMENT.sub("", stripped, 1).strip()
            current_field = "comment"
            current_content = content
            continue

        # Check for source
        m = RE_SOURCE.search(stripped)
        if m and m.start() == 0:
            flush()
            content = RE_SOURCE.sub("", stripped, 1).strip()
            current_field = "source"
            current_content = content
            continue

        # Check for SI question number: "10." / "20." etc. at start of line
        m = RE_SI_QUESTION_NUM.search(stripped)
        if m:
            num = int(m.group(1))
            if num in SI_QUESTION_NUMBERS:
                flush()
                structure.append(["number", str(num)])
                question_text = stripped[m.end() :].strip()
                if question_text:
                    current_field = "question"
                    current_content = question_text
                continue

        # Check for standalone number line: just "10" or "10."
        m = RE_SI_QUESTION_NUM_ONLY.search(stripped)
        if m:
            num = int(m.group(1))
            if num in SI_QUESTION_NUMBERS:
                flush()
                structure.append(["number", str(num)])
                continue

        # If nothing matched, it's either a continuation or heading/meta
        if current_field:
            # Continuation of current field
            current_content += SEP + stripped
        elif not heading_found:
            # First unmatched text is probably the heading
            heading_found = True
            structure.append(["heading", apply_typo(stripped)])
        else:
            # Meta information
            structure.append(["meta", apply_typo(stripped)])

    flush()

    # Now pack into question structures
    final_structure = []
    current_question = {}

    for element in structure:
        etype = element[0]

        if etype in (
            "battle",
            "round",
            "section",
            "theme",
            "heading",
            "editor",
            "date",
            "meta",
        ):
            # Flush current question if any
            if "question" in current_question:
                final_structure.append(["Question", current_question])
                current_question = {}
            final_structure.append(element)
        elif etype == "number":
            # Flush current question if any
            if "question" in current_question:
                final_structure.append(["Question", current_question])
                current_question = {}
            current_question["number"] = element[1]
        elif etype in QUESTION_LABELS:
            # If no question is being built yet, keep as standalone element
            if not current_question and etype not in ("question", "number"):
                final_structure.append(element)
            elif etype in current_question:
                # Merge
                if isinstance(current_question[etype], str) and isinstance(
                    element[1], str
                ):
                    current_question[etype] += SEP + element[1]
                else:
                    current_question[etype] = element[1]
            else:
                current_question[etype] = element[1]
        else:
            if "question" in current_question:
                final_structure.append(["Question", current_question])
                current_question = {}
            final_structure.append(element)

    # Flush last question
    if "question" in current_question:
        final_structure.append(["Question", current_question])

    # Handle source as list if multi-line
    re_leading_num = re.compile(r"^\d+\.\s*")
    for element in final_structure:
        if element[0] == "Question":
            q = element[1]
            if "source" in q and isinstance(q["source"], str):
                source_lines = [s.strip() for s in q["source"].split(SEP) if s.strip()]
                if len(source_lines) > 1:
                    # Strip leading "N." numbering — the list format adds its own
                    q["source"] = [re_leading_num.sub("", s) for s in source_lines]

    return final_structure


def si_parse_docx(docxfile, args=None, logger=None):
    """
    Parse an SI DOCX file by reusing chgk_parse_docx's HTML extraction,
    then applying SI-specific text parsing.

    We call the extraction part of chgk_parse_docx indirectly by using
    mammoth for HTML conversion, then parse the text ourselves.
    """
    import base64
    import urllib

    import bs4
    import mammoth
    from bs4 import BeautifulSoup
    from parse import parse as parse_fmt

    from chgksuite._html2md import html2md
    from chgksuite.parser import generate_imgname, ensure_line_breaks

    logger = logger or DummyLogger()
    args = args or DefaultNamespace()

    target_dir = os.path.dirname(os.path.abspath(docxfile))
    if not getattr(args, "no_image_prefix", False):
        bn_for_img = (
            os.path.splitext(os.path.basename(docxfile))[0].replace(" ", "_") + "_"
        )
    else:
        bn_for_img = ""

    # Extract HTML from DOCX using mammoth (same as chgk_parse_docx)
    with open(docxfile, "rb") as docx_file:
        html = mammoth.convert_to_html(docx_file).value

    input_docx = (
        html.replace("</strong><strong>", "")
        .replace("</em><em>", "")
        .replace("_", "$$$UNDERSCORE$$$")
    )
    bsoup = BeautifulSoup(input_docx, "html.parser")

    for tag in bsoup.find_all("style"):
        tag.extract()
    for br in bsoup.find_all("br"):
        br.replace_with("\n")
    imgpaths = []
    for tag in bsoup.find_all("img"):
        imgparse = parse_fmt("data:image/{ext};base64,{b64}", tag["src"])
        if imgparse:
            imgname = generate_imgname(target_dir, imgparse["ext"], prefix=bn_for_img)
            with open(os.path.join(target_dir, imgname), "wb") as f:
                f.write(base64.b64decode(imgparse["b64"]))
            imgpath = os.path.basename(imgname)
        else:
            imgpath = "BROKEN_IMAGE"
        tag.insert_before(f"IMGPATH({len(imgpaths)})")
        imgpath_formatted = "(img {})".format(imgpath)
        imgpaths.append(imgpath_formatted)
        tag.extract()
    for tag in bsoup.find_all("p"):
        ensure_line_breaks(tag)
    for tag in bsoup.find_all("b"):
        if getattr(args, "preserve_formatting", False):
            tag.insert(0, "__")
            tag.append("__")
        tag.unwrap()
    for tag in bsoup.find_all("strong"):
        if getattr(args, "preserve_formatting", False):
            tag.insert(0, "__")
            tag.append("__")
        tag.unwrap()
    for tag in bsoup.find_all("i"):
        if getattr(args, "preserve_formatting", False):
            tag.insert(0, "_")
            tag.append("_")
        tag.unwrap()
    for tag in bsoup.find_all("em"):
        if getattr(args, "preserve_formatting", False):
            tag.insert(0, "_")
            tag.append("_")
        tag.unwrap()
    if getattr(args, "fix_spans", False):
        for tag in bsoup.find_all("span"):
            tag.unwrap()
    heading_markers = {"h1": "$$H1$$ ", "h2": "$$H2$$ ", "h3": "$$H3$$ "}
    for h in ["h1", "h2", "h3", "h4"]:
        for tag in bsoup.find_all(h):
            marker = heading_markers.get(h)
            if marker:
                tag.insert(0, marker)
            ensure_line_breaks(tag)
    for tag in bsoup.find_all("table"):
        try:
            table = html2md(str(tag))
            tag.insert_before(table)
        except (TypeError, ValueError):
            logger.error(f"couldn't parse html table: {str(tag)}")
        tag.extract()
    for tag in bsoup.find_all("hr"):
        tag.extract()
    # Number ordered list items
    for_ol = {}
    to_append = []
    for tag in bsoup.find_all("li"):
        if tag.parent and tag.parent.name == "ol":
            if not for_ol.get(tag.parent):
                for_ol[tag.parent] = 1
            else:
                for_ol[tag.parent] += 1
            to_append.append((tag, f"{for_ol[tag.parent]}. "))
    for tag, prefix in to_append:
        tag.insert(0, prefix)
        ensure_line_breaks(tag)
    # Unwrap links
    links = getattr(args, "links", "unwrap")
    if links == "unwrap":
        for tag in bsoup.find_all("a"):
            if tag.get_text().startswith("http"):
                tag.unwrap()
            elif (
                tag.get("href")
                and tag["href"].startswith("http")
                and tag.get_text().strip() not in tag["href"]
                and (
                    urllib.parse.unquote(tag.get_text().strip())
                    not in urllib.parse.unquote(tag["href"])
                )
            ):
                tag.string = f"{tag.get_text()} ({tag['href']})"
                tag.unwrap()

    # Unwrap remaining tags
    found = True
    while found:
        found = False
        for tag in bsoup:
            if isinstance(tag, bs4.element.Tag):
                tag.unwrap()
                found = True
    txt = str(bsoup)

    txt = (
        txt.replace("\\-", "")
        .replace("\\.", ".")
        .replace("( ", "(")
        .replace("[ ", "[")
        .replace(" )", ")")
        .replace(" ]", "]")
        .replace(" :", ":")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("$$$UNDERSCORE$$$", "\\_")
    )
    txt = re.sub(r"_ *_", "", txt)
    for i, elem in enumerate(imgpaths):
        txt = txt.replace(f"IMGPATH({i})", elem)

    if getattr(args, "debug", False):
        with open(
            os.path.join(target_dir, "si_debug.txt"), "w", encoding="utf-8"
        ) as dbg:
            dbg.write(txt)

    return si_parse_text(txt, args=args, logger=logger)


def si_parse_wrapper(path, args, logger=None):
    """Parse an SI file (DOCX or TXT) and write 4s output."""
    abspath = os.path.abspath(path)
    target_dir = os.path.dirname(abspath)
    logger = logger or init_logger("si_parser")

    # SI questions are numbered by point value (10, 20, ...); always preserve them
    if (
        not getattr(args, "numbers_handling", None)
        or args.numbers_handling == "default"
    ):
        args.numbers_handling = "all"

    if os.path.splitext(abspath)[1] == ".docx":
        final_structure = si_parse_docx(abspath, args=args, logger=logger)
    elif os.path.splitext(abspath)[1] == ".txt":
        from chgksuite.common import read_text_file

        text = read_text_file(abspath)
        final_structure = si_parse_text(text, args=args, logger=logger)
    else:
        sys.stderr.write("Error: unsupported file format.\n")
        sys.exit()

    outfilename = os.path.join(target_dir, make_filename(abspath, game_to_ext("si"), args))
    logger.info("Output: {}".format(os.path.abspath(outfilename)))
    with open(outfilename, "w", encoding="utf-8") as output_file:
        output_file.write(compose_4s(final_structure, args=args))
    return outfilename


def gui_parse_si(args):
    """CLI entry point for parse_si command."""
    import shlex
    import subprocess

    logger = init_logger("si_parser", debug=getattr(args, "debug", False))

    if args.filename:
        ld = os.path.dirname(os.path.abspath(args.filename))
        set_lastdir(ld)
    else:
        print("No file specified.")
        sys.exit(0)

    outfilename = si_parse_wrapper(args.filename, args, logger=logger)
    if outfilename and not args.console_mode:
        print(
            "Please review the resulting file {}:".format(
                make_filename(args.filename, "si.4s", args)
            )
        )
        texteditor = (
            load_settings().get("editor")
            or {"darwin": "open -t", "linux": "xdg-open", "win32": "notepad"}[
                sys.platform
            ]
        )
        subprocess.call(shlex.split('{} "{}"'.format(texteditor, outfilename)))
