from types import SimpleNamespace

from PIL import Image

from chgksuite.handouter.gen import generate_handouts


def test_4s2hndt_reads_a_handout_without_the_bracket(tmp_path):
    """A parsed .docx puts «Раздаточный материал.» on a line of its own with the
    picture or the text under it: the picture is the handout, and a text keeps
    everything but the label line for the author to cut down."""
    Image.new("RGB", (2, 2)).save(tmp_path / "pic.png")
    (tmp_path / "pack.4s").write_text(
        "? Раздаточный материал.\n(img pic.png)\nЧто изображено?\n! А\n\n"
        "? Раздаточный материал\nThere is ******* of ******.\nВосстановите слова.\n! Б\n\n"
        "? Без картинки.\n! В\n",
        encoding="utf8",
    )
    args = SimpleNamespace(
        filename=str(tmp_path / "pack.4s"),
        language="ru",
        separate=False,
        list_handouts=False,
    )
    generate_handouts(args)
    assert (tmp_path / "pack.hndt").read_text(encoding="utf8") == (
        f"for_question: 1\ncolumns: 3\n\nimage: {tmp_path / 'pic.png'}\n---\n"
        "for_question: 2\ncolumns: 3\n\nThere is ******* of ******.\nВосстановите слова."
    )
