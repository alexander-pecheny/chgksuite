import os

import pytest

from chgksuite.common import DefaultArgs, compose_4s, escape_markers
from chgksuite.composer.chgksuite_parser import parse_4s
from chgksuite.composer.docx import DocxExporter
from chgksuite.composer.markdown import MarkdownExporter
from chgksuite.composer.typst import TypstExporter

from .chgksuite_test import _make_rich_telegram_exporter

RESOURCES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "chgksuite",
    "resources",
)

QUESTION = {
    "question": "Вопрос.",
    "answer": "Ответ.",
    "zachet": "Зачёт.",
    "comment": "Комментарий.",
    "source": "Источник.",
    "author": "Автор.",
}


def _question(text):
    return next(e[1] for e in parse_4s(text) if e[0] == "Question")


def test_escaped_handout_lines_stay_in_one_handout():
    q = _question(
        "№ 1\n> Раздатка:\n\\> первая строка\n\\> вторая строка\n? Вопрос\n! Ответ"
    )
    assert q["handout"] == "Раздатка:\n> первая строка\n> вторая строка"


@pytest.mark.parametrize(
    "line,text",
    [
        ("\\? не вопрос", "? не вопрос"),
        ("\\!= не незачёт", "!= не незачёт"),
        ("\\## не тур", "## не тур"),
        ("\\\\> два слеша", "\\> два слеша"),
        ("  \\> с отступом", "  > с отступом"),
        ("\\x не маркер", "\\x не маркер"),
        ("\\>> не маркер", "\\>> не маркер"),
    ],
)
def test_escape_removes_one_backslash_only_before_a_marker(line, text):
    q = _question(f"? Вопрос\n{line}\n! Ответ")
    assert q["question"] == f"Вопрос\n{text}"


def test_escape_markers_skips_the_first_line():
    assert escape_markers("> a\n> b\n\\? c\nd") == "> a\n\\> b\n\\\\? c\nd"


def test_compose_escapes_marker_lines_so_parse_round_trips():
    structure = parse_4s(
        "? Вопрос\n\\> строка раздатки\n! Ответ\n/ Комментарий:\n- пункт\n\\? в пункте\n- второй"
    )
    composed = compose_4s(structure, args=DefaultArgs())
    assert "\n\\> строка раздатки\n" in composed
    assert "\n\\? в пункте\n" in composed
    assert parse_4s(composed) == structure


def _docx_text(tmp_path, comment_first):
    from docx import Document

    args = DefaultArgs(
        docx_template=os.path.join(RESOURCES, "template.docx"),
        game="chgk",
        regexes_file=os.path.join(RESOURCES, "regexes_ru.json"),
        optimize_size="off",
        spoilers="off",
        screen_mode="off",
        comment_first=comment_first,
    )
    out = tmp_path / f"out{int(comment_first)}.docx"
    DocxExporter(
        [["Question", dict(QUESTION)]],
        args,
        {"tmp_dir": str(tmp_path), "targetdir": str(tmp_path)},
    ).export(out)
    return [p.text for p in Document(out).paragraphs if p.text]


def test_docx_comment_first(tmp_path):
    default = _docx_text(tmp_path, False)
    assert default[1].startswith("Ответ: Ответ.\nЗачёт: Зачёт.\nКомментарий:")
    first = _docx_text(tmp_path, True)
    assert first[1].startswith("Комментарий: Комментарий.\nОтвет: Ответ.\nЗачёт:")
    assert first[2] == default[2]


def test_typst_comment_first():
    def render(comment_first):
        args = DefaultArgs(
            regexes_file=os.path.join(RESOURCES, "regexes_ru.json"),
            comment_first=comment_first,
        )
        return TypstExporter([], args, {}).render_question(dict(QUESTION))

    default, first = render(False), render(True)
    assert default.index("Ответ") < default.index("Комментарий")
    assert first.index("Комментарий") < first.index("Ответ") < first.index("Зачёт")
    assert first.index("Зачёт") < first.index("Источник")


def test_markdown_comment_first_moves_the_spoiler_start():
    args = DefaultArgs(
        regexes_file=os.path.join(RESOURCES, "regexes_ru.json"),
        filetype="redditmd",
        comment_first=True,
    )
    res = MarkdownExporter([], args, {}).markdown_format_question(dict(QUESTION))
    lines = res.split("\n")
    assert lines[1] == "__Комментарий:__ >!Комментарий.  "
    assert lines[2] == "__Ответ:__ Ответ.  "


def test_telegram_comment_first():
    exporter = _make_rich_telegram_exporter()
    exporter.args.comment_first = True
    parts = exporter._format_question_parts(dict(QUESTION), number=1)
    assert parts["comm"] == ""
    assert parts["a"].index("Комментарий") < parts["a"].index("Ответ")
