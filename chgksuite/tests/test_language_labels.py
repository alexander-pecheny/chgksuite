import os
from pathlib import Path

import pytest
import toml

from chgksuite.cli import HANDOUT_LANGS
from chgksuite.common import DefaultNamespace
from chgksuite.parser import ChgkParser, chgk_parse, load_regexes

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "chgksuite", "resources")
FIELDS = ("answer", "zachet", "nezachet", "comment", "source", "author")


@pytest.mark.parametrize("lang", HANDOUT_LANGS)
def test_markers_read_own_labels(lang):
    regexes = load_regexes(os.path.join(RESOURCES, f"regexes_{lang}.json"))
    labels = toml.load(os.path.join(RESOURCES, f"labels_{lang}.toml"))
    for field in FIELDS:
        label = labels["question_labels"][field] + ":"
        assert regexes[field].search(label), f"{lang} {field}: {label}"


@pytest.mark.parametrize("lang", HANDOUT_LANGS)
def test_parser_reads_russian_labels(lang):
    args = DefaultNamespace(
        language=lang,
        regexes=os.path.join(RESOURCES, f"regexes_{lang}.json"),
        labels_file=os.path.join(RESOURCES, f"labels_{lang}.toml"),
    )
    regexes = ChgkParser(args=args).regexes
    russian = toml.load(os.path.join(RESOURCES, "labels_ru.toml"))
    for field in FIELDS:
        label = russian["question_labels"][field] + ":"
        assert regexes[field].search(label), f"{lang} {field}: {label}"


TRANSLATIONS = Path(__file__).parent / "translations"
QUESTIONS_PER_STAGE = 36
# The source repeats question 12's answer under the Russian label «Ответ».
EXTRA_QUESTIONS = {"2023-2024_I.ua": 1}


def _parse(text, lang):
    args = DefaultNamespace(
        language=lang,
        regexes=os.path.join(RESOURCES, f"regexes_{lang}.json"),
        labels_file=os.path.join(RESOURCES, f"labels_{lang}.toml"),
    )
    return chgk_parse(text, args=args)


@pytest.mark.parametrize(
    "path", sorted(TRANSLATIONS.glob("*.txt")), ids=lambda p: p.stem
)
def test_translation_has_every_question(path):
    lang = path.stem.rsplit(".", 1)[1]
    parsed = _parse(path.read_text(encoding="utf-8"), lang)
    questions = [x[1] for x in parsed if x[0] == "Question"]
    assert len(questions) == QUESTIONS_PER_STAGE + EXTRA_QUESTIONS.get(path.stem, 0)
    assert all("answer" in q for q in questions)


def test_package_in_another_language_parses_as_russian_without_crash():
    text = (TRANSLATIONS / "2024-2025_I.ua.txt").read_text(encoding="utf-8")
    assert "Question" not in [x[0] for x in _parse(text, "ru")]
