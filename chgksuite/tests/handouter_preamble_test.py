"""The ///preamble block and /// comments in a .hndt file."""

from types import SimpleNamespace

import pytest

from chgksuite.handouter.utils import apply_preamble, parse_handouts, preamble_ignore

SOURCE = """///preamble
/// house style for the whole pack
font_size: 16
question_label: inside
---
for_question: 1
columns: 3

Первая раздатка
/// a note to the editor
---
for_question: 2
columns: 2
font_size: 12
question_label: above

Вторая
---
---
for_question: 3
columns: 1

Третья"""


def test_a_file_without_comments_is_left_alone():
    plain = "for_question: 1\ncolumns: 3\n\nтекст //не комментарий"
    assert apply_preamble(plain) == plain


def test_the_preamble_fills_what_a_handout_does_not_set():
    blocks = parse_handouts(SOURCE)
    assert [b.get("font_size") for b in blocks] == [16, 12, None, 16]
    assert [b.get("question_label") for b in blocks] == [
        "inside",
        "above",
        None,
        "inside",
    ]


def test_comments_are_dropped_and_page_breaks_stay_empty():
    blocks = parse_handouts(SOURCE)
    assert blocks[0]["text"] == "Первая раздатка"
    assert blocks[2] == {}


def test_an_explicit_flag_beats_the_preamble():
    ignore = preamble_ignore(SimpleNamespace(font=None, font_size=20))
    assert parse_handouts(SOURCE, ignore)[0].get("font_size") is None
    assert parse_handouts(SOURCE, ignore)[0].get("question_label") == "inside"


@pytest.mark.parametrize(
    "line", ["columns: 3", "for_question: 1", "image: a.png", "просто текст"]
)
def test_the_preamble_takes_only_settings_that_can_be_shared(line):
    with pytest.raises(ValueError):
        apply_preamble(
            f"///preamble\n{line}\n---\nfor_question: 1\ncolumns: 3\n\nтекст"
        )


def test_a_preamble_is_only_the_first_block():
    blocks = parse_handouts(
        "for_question: 1\ncolumns: 3\n\nтекст\n---\n///preamble\nfont_size: 16"
    )
    assert blocks[0].get("font_size") is None
    assert "font_size" in blocks[1]
