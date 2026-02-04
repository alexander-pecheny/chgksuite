#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for handouter layout detection algorithm."""

import pytest
from unittest.mock import Mock

from chgksuite.handouter.runner import HandoutGenerator
from chgksuite.handouter.tex_internals import EDGE_SOLID, EDGE_NONE
from chgksuite.handouter.utils import parse_handouts, wrap_val


@pytest.fixture
def generator():
    """Create a HandoutGenerator with minimal mock args."""
    args = Mock()
    args.language = "ru"
    args.paperwidth = 210
    args.paperheight = 297
    args.margin_left = 5
    args.margin_right = 5
    args.margin_top = 5
    args.margin_bottom = 5
    args.tikz_mm = 1
    args.font = None
    args.font_size = 12
    args.boxwidth = None
    args.boxwidthinner = None
    args.debug = False
    return HandoutGenerator(args)


class TestGetCutDirection:
    """Tests for the get_cut_direction method."""

    def test_single_team_1x3(self, generator):
        """1 column × 3 rows with 3 handouts/team = 1 team rectangle."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=1, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 1
        assert team_rows == 3

    def test_single_team_3x1(self, generator):
        """3 columns × 1 row with 3 handouts/team = 1 team rectangle."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=1, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_prefers_horizontal(self, generator):
        """3×3 grid can be grouped as 3×1 or 1×3, should prefer horizontal (3×1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3
        )
        # Horizontal grouping: 3 columns × 1 row per team
        assert team_cols == 3
        assert team_rows == 1

    def test_2x6_vertical_grouping(self, generator):
        """2 columns × 6 rows with 3 handouts/team = 4 teams of 1×3."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3
        )
        # Only valid option: 1 column × 3 rows per team
        assert team_cols == 1
        assert team_rows == 3

    def test_6x3_prefers_horizontal(self, generator):
        """6×3 grid can be 3×1 or 1×3, should prefer horizontal (3×1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_4x3_vertical_only(self, generator):
        """4 columns × 3 rows with 3 handouts/team = vertical grouping only."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=4, num_rows=3, handouts_per_team=3
        )
        # 4 columns can't be divided by 3, so only 1×3 works
        assert team_cols == 1
        assert team_rows == 3

    def test_2x3_vertical_grouping(self, generator):
        """2 columns × 3 rows with 3 handouts/team = 2 teams of 1×3."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 1
        assert team_rows == 3

    def test_invalid_not_divisible(self, generator):
        """Total handouts not divisible by handouts_per_team returns None."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=2, handouts_per_team=3
        )
        # 4 total handouts, can't divide by 3
        assert team_cols is None
        assert team_rows is None

    def test_invalid_no_valid_layout(self, generator):
        """Grid dimensions don't allow valid team rectangles."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=5, num_rows=5, handouts_per_team=3
        )
        # 25 total, not divisible by 3
        assert team_cols is None
        assert team_rows is None

    def test_handouts_per_team_1(self, generator):
        """Each cell is its own team (handouts_per_team=1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=1
        )
        assert team_cols == 1
        assert team_rows == 1

    def test_handouts_per_team_equals_total(self, generator):
        """All cells form one team."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=9
        )
        assert team_cols == 3
        assert team_rows == 3

    def test_4x6_with_6_per_team(self, generator):
        """4×6 grid with 6 handouts/team can be 2×3 or 3×2, prefers 3×2."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=4, num_rows=6, handouts_per_team=6
        )
        # 4%2=0, 6%3=0 -> (2, 3)
        # 4%3≠0 -> (3, 2) invalid
        # Only option is (2, 3)
        assert team_cols == 2
        assert team_rows == 3

    def test_6x4_with_6_per_team_prefers_horizontal(self, generator):
        """6×4 grid with 6 handouts/team, picks most horizontal option."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=4, handouts_per_team=6
        )
        # Valid options: (6, 1) and (3, 2)
        # (6, 1): 6%6=0, 4%1=0 valid
        # (3, 2): 6%3=0, 4%2=0 valid
        # (2, 3): 6%2=0, 4%3≠0 invalid
        # Prefer smallest team_rows -> (6, 1)
        assert team_cols == 6
        assert team_rows == 1

    def test_6x6_with_6_per_team(self, generator):
        """6×6 grid with 6 handouts/team, multiple options, prefers horizontal."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6
        )
        # Valid options: (6, 1), (3, 2), (2, 3), (1, 6)
        # Sorted by team_rows: [(6, 1), (3, 2), (2, 3), (1, 6)]
        # Pick (6, 1) - most horizontal
        assert team_cols == 6
        assert team_rows == 1


class TestGroupingPreference:
    """Tests for the grouping preference option."""

    def test_3x3_default_horizontal(self, generator):
        """3×3 grid defaults to horizontal grouping."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_explicit_horizontal(self, generator):
        """3×3 grid with explicit horizontal grouping."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3, grouping="horizontal"
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_vertical_grouping(self, generator):
        """3×3 grid with vertical grouping preference."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3, grouping="vertical"
        )
        # Vertical: prefer smaller team_cols -> 1×3 teams
        assert team_cols == 1
        assert team_rows == 3

    def test_6x6_default_horizontal(self, generator):
        """6×6 grid with 6 handouts/team defaults to horizontal."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6
        )
        # Options: (6,1), (3,2), (2,3), (1,6)
        # Horizontal prefers smallest team_rows -> (6, 1)
        assert team_cols == 6
        assert team_rows == 1

    def test_6x6_vertical_grouping(self, generator):
        """6×6 grid with 6 handouts/team and vertical preference."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6, grouping="vertical"
        )
        # Options: (6,1), (3,2), (2,3), (1,6)
        # Vertical prefers smallest team_cols -> (1, 6)
        assert team_cols == 1
        assert team_rows == 6

    def test_grouping_only_one_option(self, generator):
        """When only one layout is valid, grouping preference doesn't matter."""
        # 2×6 with 3 handouts/team: only (1, 3) is valid
        team_cols_h, team_rows_h = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3, grouping="horizontal"
        )
        team_cols_v, team_rows_v = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3, grouping="vertical"
        )
        assert team_cols_h == team_cols_v == 1
        assert team_rows_h == team_rows_v == 3


class TestEdgeBoundaries:
    """Tests for boundary detection in get_edge_styles."""

    def test_single_team_all_solid_outer(self, generator):
        """Single team rectangle has solid outer edges."""
        # 1×3 grid, 1 team
        edges, _ = generator.get_edge_styles(
            row_idx=0, col_idx=0, num_rows=3, columns=1, team_cols=1, team_rows=3
        )
        assert edges["top"] == EDGE_SOLID
        assert edges["left"] == EDGE_SOLID
        assert edges["right"] == EDGE_SOLID

    def test_vertical_team_boundary(self, generator):
        """Test vertical boundary between teams in 2×3 grid (1×3 teams)."""
        # Cell at (0, 0) - right edge should be at team boundary
        edges, _ = generator.get_edge_styles(
            row_idx=0, col_idx=0, num_rows=3, columns=2, team_cols=1, team_rows=3
        )
        # Right edge is at team boundary (col 0 is right edge of team 0)
        assert edges["right"] == EDGE_SOLID

    def test_horizontal_team_boundary(self, generator):
        """Test horizontal boundary between teams in 3×3 grid (3×1 teams)."""
        # Cell at (0, 0) - bottom edge should be at team boundary
        edges, _ = generator.get_edge_styles(
            row_idx=0, col_idx=0, num_rows=3, columns=3, team_cols=3, team_rows=1
        )
        # Bottom edge is at team boundary (row 0 is bottom of team 0)
        assert edges["bottom"] == EDGE_SOLID

    def test_internal_dashed_edges(self, generator):
        """Internal edges within team should be dashed or none."""
        # Cell at (1, 1) in 3×3 grid with 3×1 teams
        # This cell is in middle of row, internal to team
        edges, _ = generator.get_edge_styles(
            row_idx=0, col_idx=1, num_rows=3, columns=3, team_cols=3, team_rows=1
        )
        # Left edge is internal, should be NONE (to avoid double lines)
        assert edges["left"] == EDGE_NONE


class TestGroupingParsing:
    """Tests for parsing the grouping option from txt files."""

    def test_parse_grouping_horizontal(self):
        """Parse horizontal grouping option."""
        contents = """for_question: 1
columns: 3
rows: 3
grouping: horizontal
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "horizontal"

    def test_parse_grouping_vertical(self):
        """Parse vertical grouping option."""
        contents = """for_question: 1
columns: 3
rows: 3
grouping: vertical
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "vertical"

    def test_parse_grouping_case_insensitive(self):
        """Grouping option should be case insensitive."""
        contents = """columns: 3
grouping: VERTICAL
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "vertical"

    def test_parse_no_grouping_defaults_none(self):
        """When grouping is not specified, it should not be in the dict."""
        contents = """columns: 3
rows: 3
test"""
        result = parse_handouts(contents)
        assert "grouping" not in result[0]

    def test_wrap_val_grouping_invalid(self):
        """Invalid grouping value should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid grouping value"):
            wrap_val("grouping", "diagonal")
