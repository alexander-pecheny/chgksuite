from chgksuite_tk.gui import get_radiobutton_default


def test_radiobutton_default_uses_explicit_default():
    kwargs = {"choices": ["a", "b"], "default": "b"}

    assert get_radiobutton_default(kwargs) == "b"


def test_radiobutton_default_falls_back_when_missing():
    kwargs = {"choices": ["a", "b"]}

    assert get_radiobutton_default(kwargs) == "a"


def test_radiobutton_default_falls_back_when_none():
    kwargs = {"choices": ["a", "b"], "default": None}

    assert get_radiobutton_default(kwargs) == "a"


def _telegram_wrapper(pack, answer, monkeypatch):
    import argparse

    from chgksuite.cli import ArgparseBuilder

    from chgksuite_tk import gui

    monkeypatch.delenv("CHGKSUITE_BYPASS_STATS_CHECK", raising=False)
    asked = []

    def askyesno(title, message, **kwargs):
        asked.append(kwargs["default"])
        return answer

    monkeypatch.setattr(gui.messagebox, "askyesno", askyesno)
    parser = argparse.ArgumentParser(prog="chgksuite")
    ArgparseBuilder(parser, False).build()
    wrapper = gui.ParserWrapper.__new__(gui.ParserWrapper)
    wrapper.parser = parser
    wrapper.tk = None
    wrapper.cmdline_call = [
        "compose", "telegram", str(pack), "--tgchannel", "c", "--tgchat", "g",
    ]
    wrapper.cmdline_call_display = "Command line call: ..."
    return wrapper, asked


def test_publishing_without_stats_needs_a_yes(tmp_path, monkeypatch):
    pack = tmp_path / "pack.4s"
    pack.write_text("? Вопрос\n! Ответ\n", encoding="utf8")

    wrapper, asked = _telegram_wrapper(pack, False, monkeypatch)
    assert not wrapper.confirm_publishing_without_stats()
    assert asked == ["no"]

    wrapper, asked = _telegram_wrapper(pack, True, monkeypatch)
    assert wrapper.confirm_publishing_without_stats()
    assert wrapper.cmdline_call[-1] == "--allow_no_stats"


def test_a_pack_with_stats_is_not_asked_about(tmp_path, monkeypatch):
    pack = tmp_path / "pack.4s"
    pack.write_text("? Вопрос\n! Ответ\n/ Взятия: 1/2 (50%)\n", encoding="utf8")

    wrapper, asked = _telegram_wrapper(pack, False, monkeypatch)
    assert wrapper.confirm_publishing_without_stats()
    assert asked == []
    assert "--allow_no_stats" not in wrapper.cmdline_call
