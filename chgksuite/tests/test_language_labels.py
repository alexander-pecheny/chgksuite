import os

import pytest
import toml

from chgksuite.cli import HANDOUT_LANGS
from chgksuite.common import DefaultNamespace
from chgksuite.parser import ChgkParser, load_regexes

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
