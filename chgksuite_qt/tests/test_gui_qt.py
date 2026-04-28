from chgksuite_qt.gui import get_radiobutton_default


def test_radiobutton_default_uses_explicit_default():
    kwargs = {"choices": ["a", "b"], "default": "b"}

    assert get_radiobutton_default(kwargs) == "b"


def test_radiobutton_default_falls_back_when_missing():
    kwargs = {"choices": ["a", "b"]}

    assert get_radiobutton_default(kwargs) == "a"


def test_radiobutton_default_falls_back_when_none():
    kwargs = {"choices": ["a", "b"], "default": None}

    assert get_radiobutton_default(kwargs) == "a"
