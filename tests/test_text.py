"""humanise() must leave no typographic AI/ATS tells in generated CV/CL text."""

from web.app.services.text import humanise

TELLS = "—–―−“”‘’…• ​﻿"


def test_humanise_strips_every_tell():
    out = humanise(
        "He — she – they; “quoted”, don’t… "
        "• world—class x y​"
    )
    assert not any(ch in out for ch in TELLS), out
    # spaced em/en dash reads as a comma; joined dash becomes a hyphen
    assert humanise("Led strategy — across teams") == "Led strategy, across teams"
    assert humanise("cost–benefit") == "cost-benefit"
    assert humanise("“ok” it’s fine") == '"ok" it\'s fine'
    assert humanise("") == ""
