#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Dispatcher for board providers (Trello, GitHub).
"""


def gui_boards(args):
    provider = getattr(args, "provider", "trello")

    if provider == "github":
        from chgksuite.github import gui_github

        gui_github(args)
    else:
        from chgksuite.trello import gui_trello

        gui_trello(args)
