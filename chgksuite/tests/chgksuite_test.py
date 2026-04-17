#!/usr/bin/env python
#! -*- coding: utf-8 -*-
import contextlib
import inspect
import json
import os
import shutil
import subprocess
import tempfile

import pytest
from chgksuite.common import DefaultArgs
from chgksuite.composer.chgksuite_parser import parse_4s, replace_counters
from chgksuite.composer.composer_common import (
    _parse_4s_elem,
    game_to_ext,
    parseimg,
    remove_accents_standalone,
)
from chgksuite.composer.docx import remove_square_brackets_standalone
from chgksuite.composer.telegram import TelegramExporter
from chgksuite.parser import (
    chgk_parse_docx,
    chgk_parse_txt,
    compose_4s,
)
from chgksuite.typotools import get_quotes_right, cyr_lat_check_word
from PIL import Image

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)

# Encrypted test file support
PASSWORD_FILE = os.path.join(currentdir, "tests_password.txt")


def get_test_password():
    """Read password from file, return None if not found."""
    if os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "r") as f:
            return f.read().strip()
    return None


def decrypt_test_file(filepath: str, password: str) -> bytes:
    """Decrypt a test file using XOR."""
    import hashlib

    key = hashlib.sha256(password.encode()).digest()
    with open(filepath, "rb") as f:
        data = f.read()
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


with open(os.path.join(currentdir, "settings.json")) as f:
    settings = json.loads(f.read())


ljlogin, ljpassword = open(os.path.join(currentdir, "ljcredentials")).read().split("\t")


def workaround_chgk_parse(filename, **kwargs):
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename, args=DefaultArgs(**kwargs))
    elif filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=DefaultArgs(**kwargs))
    return


QUOTE_TEST_CASES = [
    ('«"Альфа" Бета»', "«„Альфа“ Бета»"),
    ("«“Альфа” Бета»", "«„Альфа“ Бета»"),
    ("«„Альфа“ Бета»", "«„Альфа“ Бета»"),
    ("«Альфа», “Бета”", "«Альфа», «Бета»"),
    (
        '"Он сказал: "Привет!". А потом заплакал"',
        "«Он сказал: „Привет!“. А потом заплакал»",
    ),
    (
        "“Он сказал: “Привет!”. А потом заплакал”",
        "«Он сказал: „Привет!“. А потом заплакал»",
    ),
    (
        "Все вопросы тура написаны по одному источнику — книге Натальи Эдуардовны Манусаджян «Применение соматопсихотерапии во время тренировок по „Что? Где? Когда?“ как метода развития креативности мышления».",
        "Все вопросы тура написаны по одному источнику — книге Натальи Эдуардовны Манусаджян «Применение соматопсихотерапии во время тренировок по „Что? Где? Когда?“ как метода развития креативности мышления».",
    ),
]


@pytest.mark.parametrize("a,expected", QUOTE_TEST_CASES)
def test_quotes(a, expected):
    assert get_quotes_right(a) == expected


# Test cases for Latin accented character conversion to Cyrillic
# Format: (input, expected_output)
# The fix ensures uppercase Cyrillic neighbors are recognized correctly
CYR_LAT_ACCENT_TEST_CASES = [
    # Bug case: Latin á (U+00E1) after uppercase Cyrillic should convert
    ("Хáральд", "Ха́ральд"),  # Х is uppercase Cyrillic
    # Latin à (U+00E0) after lowercase Cyrillic - already worked
    ("Ивàново", "Ива́ново"),
    # Latin é (U+00E9) in middle of word - already worked
    ("крылéц", "крыле́ц"),
    # Latin ó (U+00F3) after uppercase Cyrillic
    ("Óльга", "О́льга"),  # О is uppercase Cyrillic
    # Latin ú (U+00FA) mapped to Cyrillic и́
    ("Иúсус", "Ии́сус"),
    # Multiple accented chars in one word
    ("Москвá", "Москва́"),
    # Pure Latin word - should NOT convert (no Cyrillic neighbors)
    ("café", None),  # None means no change
    # Mixed but Latin char surrounded by Latin - should NOT convert
    ("Caféшоп", None),  # é surrounded by Latin 'f' and Cyrillic 'ш', but 'f' blocks it
    # Single char word - should not convert (length check)
    ("á", None),
    # Uppercase Latin accent after uppercase Cyrillic
    ("ХÁРАЛЬД", "ХА́РАЛЬД"),
]


@pytest.mark.parametrize("input_word,expected", CYR_LAT_ACCENT_TEST_CASES)
def test_cyr_lat_accent_conversion(input_word, expected):
    result = cyr_lat_check_word(input_word)
    if expected is None:
        assert result is None, f"Expected no change for '{input_word}', got '{result}'"
    else:
        assert result == expected, (
            f"Expected '{expected}' for '{input_word}', got '{result}'"
        )


with open(os.path.join(parentdir, "chgksuite", "resources", "regexes_ru.json")) as f:
    TEST_REGEXES = json.load(f)


SQUARE_BRACKET_TEST_CASES = [
    ("black [блэк]", "black"),
    ("black [блэк] смотрит [looks]", "black смотрит"),
    (
        "text with [Раздаточный материал: handout] here",
        "text with [Раздаточный материал: handout] here",
    ),  # handout preserved
    ("text \\[escaped\\]", "text [escaped]"),  # escaped brackets restored
    ("simple text", "simple text"),  # no brackets
]


@pytest.mark.parametrize("input_text,expected", SQUARE_BRACKET_TEST_CASES)
def test_remove_square_brackets(input_text, expected):
    assert remove_square_brackets_standalone(input_text, TEST_REGEXES) == expected


ACCENT_TEST_CASES = [
    ("при́вет", "привет"),  # \u0301 accent removed
    ("мо́ре си́нее", "море синее"),  # multiple accents
    (
        "[Раздаточный материал: при́вет]",
        "[Раздаточный материал: при́вет]",
    ),  # accent in handout preserved
    ("simple text", "simple text"),  # no accents
]


@pytest.mark.parametrize("input_text,expected", ACCENT_TEST_CASES)
def test_remove_accents(input_text, expected):
    assert remove_accents_standalone(input_text, TEST_REGEXES) == expected


@contextlib.contextmanager
def make_temp_directory(**kwargs):
    temp_dir = tempfile.mkdtemp(**kwargs)
    yield temp_dir
    shutil.rmtree(os.path.abspath(temp_dir))


def normalize(string):
    return string.replace("\r\n", "\n")


# Regular canon files (always run)
CANON_FILENAMES = [
    fn
    for fn in os.listdir(currentdir)
    if fn.endswith(".canon") and not fn.endswith(".encrypted.canon")
]

# Add encrypted canon files only if password exists
if os.path.exists(PASSWORD_FILE):
    CANON_FILENAMES.extend(
        [fn for fn in os.listdir(currentdir) if fn.endswith(".encrypted.canon")]
    )


@pytest.mark.parametrize("filename", CANON_FILENAMES)
def test_canonical_equality(parsing_engine, filename):
    # Handle encrypted files
    is_encrypted = filename.endswith(".encrypted.canon")
    if is_encrypted:
        password = get_test_password()
        if password is None:
            pytest.skip("No password file found for encrypted test")

    with make_temp_directory(dir=".") as temp_dir:
        if is_encrypted:
            # filename = "file.docx.encrypted.canon" (16 chars for ".encrypted.canon")
            # Decrypt .encrypted.canon -> .canon in temp dir
            canon_content = decrypt_test_file(
                os.path.join(currentdir, filename), password
            )
            decrypted_canon = filename[:-16] + ".canon"  # "file.docx.canon"
            with open(os.path.join(temp_dir, decrypted_canon), "wb") as f:
                f.write(canon_content)

            # Decrypt source file (.docx.encrypted)
            source_encrypted = filename[:-6]  # remove ".canon" -> "file.docx.encrypted"
            source_decrypted = filename[
                :-16
            ]  # remove ".encrypted.canon" -> "file.docx"
            source_content = decrypt_test_file(
                os.path.join(currentdir, source_encrypted), password
            )
            with open(os.path.join(temp_dir, source_decrypted), "wb") as f:
                f.write(source_content)

            to_parse_fn = source_decrypted
            canon_fn = decrypted_canon
        else:
            # Original logic for non-encrypted files
            to_parse_fn = filename[:-6]
            canon_fn = filename
            shutil.copy(os.path.join(currentdir, filename), temp_dir)
            shutil.copy(os.path.join(currentdir, to_parse_fn), temp_dir)

        print("Testing {}...".format(to_parse_fn))
        bn, _ = os.path.splitext(to_parse_fn)
        file_settings = settings.get(to_parse_fn, {})
        game = file_settings.get("game")
        call_args = [
            "python",
            "-m",
            "chgksuite",
            "parse",
            "--parsing_engine",
            parsing_engine,
        ]
        if game:
            call_args.extend(["--game", game])
        call_args.append(os.path.join(temp_dir, to_parse_fn))
        if file_settings.get("cmdline_args"):
            call_args.extend(file_settings["cmdline_args"])
        subprocess.call(call_args, timeout=5)
        out_ext = game_to_ext(game)
        with open(
            os.path.join(temp_dir, bn + "." + out_ext), "r", encoding="utf-8"
        ) as f:
            parsed = f.read()
        with open(os.path.join(temp_dir, canon_fn), "r", encoding="utf-8") as f:
            canonical = f.read()
        assert normalize(canonical) == normalize(parsed)


TO_DOCX_FILENAMES = [
    fn for fn in os.listdir(currentdir) if fn.endswith((".docx", ".txt"))
]
TO_DOCX_FILENAMES.remove("balt09-1.txt")  # TODO: rm this line once dns is fixed


@pytest.mark.parametrize("filename", TO_DOCX_FILENAMES)
def test_docx_composition(filename):
    print("Testing {}...".format(filename))
    with make_temp_directory(dir=".") as temp_dir:
        shutil.copy(os.path.join(currentdir, filename), temp_dir)
        temp_dir_filename = os.path.join(temp_dir, filename)
        parsed = workaround_chgk_parse(temp_dir_filename)
        file4s = os.path.splitext(filename)[0] + ".4s"
        composed_abspath = os.path.join(temp_dir, file4s)
        print(composed_abspath)
        with open(composed_abspath, "w", encoding="utf-8") as f:
            f.write(compose_4s(parsed, args=DefaultArgs()))
        call_args = [
            "python",
            "-m",
            "chgksuite",
            "compose",
            "docx",
            composed_abspath,
        ]
        code = subprocess.call(call_args, timeout=5)
        assert 0 == code


@pytest.mark.tex
def test_tex_composition():
    for filename in os.listdir(currentdir):
        if (
            filename.endswith((".docx", ".txt"))
            and filename == "Kubok_knyagini_Olgi-2015.docx"
        ):
            print("Testing {}...".format(filename))
            with make_temp_directory(dir=".") as temp_dir:
                shutil.copy(os.path.join(currentdir, filename), temp_dir)
                temp_dir_filename = os.path.join(temp_dir, filename)
                parsed = workaround_chgk_parse(temp_dir_filename)
                file4s = os.path.splitext(filename)[0] + ".4s"
                composed_abspath = os.path.join(temp_dir, file4s)
                print(composed_abspath)
                with open(composed_abspath, "w", encoding="utf-8") as f:
                    f.write(compose_4s(parsed, args=DefaultArgs()))
                code = subprocess.call(
                    [
                        "python",
                        "-m",
                        "chgksuite",
                        "compose",
                        "tex",
                        composed_abspath,
                    ]
                )
                assert 0 == code


TEST_INLINE_IMAGE = """\
? какой-то Тест вопроса с (img inline test.jpg) инлайн картинкой.
! какой-то ответ
/ какой-то комментарий
^ какой-то источник
@ какой-то автор"""


def test_inline_image():
    structure = parse_4s(TEST_INLINE_IMAGE)
    question = structure[0][1]["question"]
    question_parsed = _parse_4s_elem(question)
    img = [x for x in question_parsed if x[0] == "img"]
    assert len(img) == 1
    with make_temp_directory(dir=".") as temp_dir:
        shutil.copy(os.path.join(currentdir, "test.jpg"), temp_dir)
        img_parsed = parseimg(img[0][1], tmp_dir=temp_dir)
    assert img_parsed["inline"]
    assert os.path.basename(img_parsed["imgfile"]) == "test.jpg"
    assert compose_4s(structure, DefaultArgs()).strip() == TEST_INLINE_IMAGE.strip()


def test_long_handout():
    cwd = os.getcwd()
    with make_temp_directory(dir=".") as temp_dir:
        shutil.copy(os.path.join(currentdir, "test.jpg"), temp_dir)
        shutil.copy(os.path.join(currentdir, "long_handout.png"), temp_dir)
        os.chdir(temp_dir)
        assert TelegramExporter.prepare_image_for_telegram("test.jpg") == "test.jpg"
        assert (
            TelegramExporter.prepare_image_for_telegram("long_handout.png")
            == "long_handout_telegram.jpg"
        )
        img = Image.open("long_handout_telegram.jpg")
        assert img.size == (1600, 83)
        os.chdir(cwd)


REPLACE_COUNTER_TEST_CASES = [
    ("4SCOUNTER 4SCOUNTER 4SCOUNTER", "1 2 3"),
    ("4SCOUNTER 4SCOUNTER1 4SCOUNTERa", "1 1 1"),
    ("set 4SCOUNTER = 5 4SCOUNTER", " 5"),
    ("set 4SCOUNTERa = 4 4SCOUNTERa", " 4"),
]


@pytest.mark.parametrize("replace_input, replace_output", REPLACE_COUNTER_TEST_CASES)
def test_replace_counters(replace_input, replace_output):
    assert replace_counters(replace_input) == replace_output
