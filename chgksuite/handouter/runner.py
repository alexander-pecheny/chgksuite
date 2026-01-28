#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import time

import toml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from chgksuite.common import get_source_dirs
from chgksuite.handouter.gen import generate_handouts
from chgksuite.handouter.pack import pack_handouts
from chgksuite.handouter.installer import get_tectonic_path, install_tectonic
from chgksuite.handouter.tex_internals import (
    EDGE_DASHED,
    EDGE_NONE,
    EDGE_SOLID,
    GREYTEXT,
    HEADER,
    IMG,
    IMGWIDTH,
    TIKZBOX_END,
    TIKZBOX_INNER,
    TIKZBOX_START,
)
from chgksuite.handouter.utils import parse_handouts, read_file, replace_ext, write_file


class HandoutGenerator:
    def __init__(self, args):
        # Inner spacing (within teams, between dashed lines)
        self.inner_hspace = getattr(args, 'hspace', 1.5)
        self.inner_vspace = getattr(args, 'vspace', 1.5)
        # Outer spacing (between teams, at solid lines) - defaults to inner
        self.outer_hspace = getattr(args, 'outer_hspace', None) or self.inner_hspace
        self.outer_vspace = getattr(args, 'outer_vspace', None) or self.inner_vspace
        self.args = args
        _, resourcedir = get_source_dirs()
        self.labels = toml.loads(
            read_file(os.path.join(resourcedir, f"labels_{args.language}.toml"))
        )
        self.blocks = [self.get_header()]

    def get_header(self):
        header = HEADER
        header = (
            header.replace("<PAPERWIDTH>", str(self.args.paperwidth))
            .replace("<PAPERHEIGHT>", str(self.args.paperheight))
            .replace("<MARGIN_LEFT>", str(self.args.margin_left))
            .replace("<MARGIN_RIGHT>", str(self.args.margin_right))
            .replace("<MARGIN_TOP>", str(self.args.margin_top))
            .replace("<MARGIN_BOTTOM>", str(self.args.margin_bottom))
            .replace("<TIKZ_MM>", str(self.args.tikz_mm))
        )
        if self.args.font:
            header = header.replace("Arial", self.args.font)
        return header

    def parse_input(self, filepath):
        contents = read_file(filepath)
        return parse_handouts(contents)

    def generate_for_question(self, question_num):
        handout_text = self.labels["general"]["handout_for_question"].format(
            question_num
        )
        return GREYTEXT.replace("<GREYTEXT>", handout_text)

    def make_tikzbox(self, block, edges=None, ext=None):
        """
        Create a TikZ box with configurable edge styles and extensions.
        edges is a dict with keys 'top', 'bottom', 'left', 'right'
        values are EDGE_DASHED or EDGE_SOLID
        ext is a dict with edge extensions to close gaps at boundaries
        """
        if edges is None:
            edges = {
                "top": EDGE_DASHED,
                "bottom": EDGE_DASHED,
                "left": EDGE_DASHED,
                "right": EDGE_DASHED,
            }
        if ext is None:
            ext = {
                "top": ("0pt", "0pt"),
                "bottom": ("0pt", "0pt"),
                "left": ("0pt", "0pt"),
                "right": ("0pt", "0pt"),
            }

        if block.get("no_center"):
            align = ""
        else:
            align = ", align=center"
        textwidth = ", text width=\\boxwidthinner"
        fs = block.get("font_size") or self.args.font_size
        fontsize = "\\fontsize{FSpt}{LHpt}\\selectfont ".replace("FS", str(fs)).replace(
            "LH", str(round(fs * 1.2, 1))
        )
        contents = block["contents"]
        if block.get("font_family"):
            contents = "\\fontspec{" + block["font_family"] + "}" + contents
        return (
            TIKZBOX_INNER.replace("<CONTENTS>", contents)
            .replace("<ALIGN>", align)
            .replace("<TEXTWIDTH>", textwidth)
            .replace("<FONTSIZE>", fontsize)
            .replace("<TOP>", edges["top"])
            .replace("<BOTTOM>", edges["bottom"])
            .replace("<LEFT>", edges["left"])
            .replace("<RIGHT>", edges["right"])
            .replace("<TOP_EXT_L>", ext["top"][0])
            .replace("<TOP_EXT_R>", ext["top"][1])
            .replace("<BOTTOM_EXT_L>", ext["bottom"][0])
            .replace("<BOTTOM_EXT_R>", ext["bottom"][1])
            .replace("<LEFT_EXT_T>", ext["left"][0])
            .replace("<LEFT_EXT_B>", ext["left"][1])
            .replace("<RIGHT_EXT_T>", ext["right"][0])
            .replace("<RIGHT_EXT_B>", ext["right"][1])
        )

    def get_page_width(self):
        return self.args.paperwidth - self.args.margin_left - self.args.margin_right - 2

    def get_cut_direction(
        self, columns, num_rows, handouts_per_team, grouping="horizontal"
    ):
        """
        Determine team rectangle dimensions.
        Returns (team_cols, team_rows) where each team is a team_cols × team_rows block.

        Falls back to (None, None) if handouts can't be evenly divided into teams.

        Args:
            grouping: "horizontal" (default) prefers wider teams (smaller team_rows),
                      "vertical" prefers taller teams (smaller team_cols).
        """
        total = columns * num_rows

        # Check if total handouts can be evenly divided
        if total % handouts_per_team != 0:
            return None, None

        num_teams = total // handouts_per_team
        if num_teams < 1:
            return None, None  # Invalid configuration

        # Find all valid team rectangle sizes (team_cols × team_rows = handouts_per_team)
        valid_layouts = []
        for team_rows in range(1, handouts_per_team + 1):
            if handouts_per_team % team_rows == 0:
                team_cols = handouts_per_team // team_rows
                if columns % team_cols == 0 and num_rows % team_rows == 0:
                    valid_layouts.append((team_cols, team_rows))

        if not valid_layouts:
            return None, None

        # Sort based on grouping preference
        if grouping == "vertical":
            # Prefer vertical grouping (smaller team_cols = taller teams)
            valid_layouts.sort(key=lambda x: x[0])
        else:
            # Prefer horizontal grouping (smaller team_rows = wider teams)
            valid_layouts.sort(key=lambda x: x[1])

        return valid_layouts[0]

    def get_edge_styles(
        self, row_idx, col_idx, num_rows, columns, team_cols, team_rows,
        inner_hspace=None, inner_vspace=None
    ):
        # Use provided spacing or fall back to instance defaults
        inner_hspace = inner_hspace if inner_hspace is not None else self.inner_hspace
        inner_vspace = inner_vspace if inner_vspace is not None else self.inner_vspace
        """
        Determine edge styles and extensions for a box at position (row_idx, col_idx).
        Outer edges of team rectangles are solid (thicker), inner edges are dashed.
        Extensions are used to close gaps in ALL solid lines.
        Duplicate dashed edges are skipped to avoid double lines.

        team_cols and team_rows define the dimensions of each team rectangle.
        """
        # Default: all dashed, no extension
        edges = {
            "top": EDGE_DASHED,
            "bottom": EDGE_DASHED,
            "left": EDGE_DASHED,
            "right": EDGE_DASHED,
        }
        ext = {
            "top": ("0pt", "0pt"),
            "bottom": ("0pt", "0pt"),
            "left": ("0pt", "0pt"),
            "right": ("0pt", "0pt"),
        }

        # Helper functions to check if position is at a team boundary
        def is_at_right_team_boundary():
            """Is this box at the right edge of its team (but not at grid edge)?"""
            if not team_cols:
                return False
            return (col_idx + 1) % team_cols == 0 and col_idx < columns - 1

        def is_at_left_team_boundary():
            """Is this box at the left edge of its team (but not at grid edge)?"""
            if not team_cols:
                return False
            return col_idx % team_cols == 0 and col_idx > 0

        def is_at_bottom_team_boundary():
            """Is this box at the bottom edge of its team (but not at grid edge)?"""
            if not team_rows:
                return False
            return (row_idx + 1) % team_rows == 0 and row_idx < num_rows - 1

        def is_at_top_team_boundary():
            """Is this box at the top edge of its team (but not at grid edge)?"""
            if not team_rows:
                return False
            return row_idx % team_rows == 0 and row_idx > 0

        # Determine which edges are solid
        # Only apply solid edges if we have valid team dimensions
        # Otherwise fall back to all-dashed (default)
        if team_cols is not None and team_rows is not None:
            # Outer edges of the entire grid
            if row_idx == 0:
                edges["top"] = EDGE_SOLID
            if row_idx == num_rows - 1:
                edges["bottom"] = EDGE_SOLID
            if col_idx == 0:
                edges["left"] = EDGE_SOLID
            if col_idx == columns - 1:
                edges["right"] = EDGE_SOLID

            # Team boundary edges
            if is_at_right_team_boundary():
                edges["right"] = EDGE_SOLID
            if is_at_left_team_boundary():
                edges["left"] = EDGE_SOLID
            if is_at_bottom_team_boundary():
                edges["bottom"] = EDGE_SOLID
            if is_at_top_team_boundary():
                edges["top"] = EDGE_SOLID

        # Skip duplicate dashed edges (to avoid double lines between adjacent boxes)
        if edges["left"] == EDGE_DASHED and col_idx > 0:
            edges["left"] = EDGE_NONE

        if edges["top"] == EDGE_DASHED and row_idx > 0:
            edges["top"] = EDGE_NONE

        # Calculate extensions for solid edges to close gaps
        # Use inner spacing for gaps within teams, outer spacing for gaps between teams
        # But don't extend into team boundary gaps (those use outer spacing and stay separate)

        def get_h_gap_left():
            """Get horizontal gap to the left (for extending into)"""
            if col_idx == 0:
                return "0pt"
            # Check if left neighbor is in different team
            if is_at_left_team_boundary():
                return "0pt"  # Don't extend into outer gaps
            return f"{inner_hspace / 2}mm"

        def get_h_gap_right():
            """Get horizontal gap to the right (for extending into)"""
            if col_idx >= columns - 1:
                return "0pt"
            # Check if right neighbor is in different team
            if is_at_right_team_boundary():
                return "0pt"  # Don't extend into outer gaps
            return f"{inner_hspace / 2}mm"

        def get_v_gap_top():
            """Get vertical gap above (for extending into)"""
            if row_idx == 0:
                return "0pt"
            # Check if top neighbor is in different team
            if is_at_top_team_boundary():
                return "0pt"  # Don't extend into outer gaps
            return f"{inner_vspace / 2}mm"

        def get_v_gap_bottom():
            """Get vertical gap below (for extending into)"""
            if row_idx >= num_rows - 1:
                return "0pt"
            # Check if bottom neighbor is in different team
            if is_at_bottom_team_boundary():
                return "0pt"  # Don't extend into outer gaps
            return f"{inner_vspace / 2}mm"

        # For horizontal lines (top/bottom): extend into gaps to close corners
        # Only extend where there's actually a gap (clipped at grid edges and team boundaries)
        if edges["top"] == EDGE_SOLID:
            h_gap_left = get_h_gap_left()
            h_gap_right = get_h_gap_right()
            ext_left = "-" + h_gap_left if h_gap_left != "0pt" else "0pt"
            ext["top"] = (ext_left, h_gap_right)

        if edges["bottom"] == EDGE_SOLID:
            h_gap_left = get_h_gap_left()
            h_gap_right = get_h_gap_right()
            ext_left = "-" + h_gap_left if h_gap_left != "0pt" else "0pt"
            ext["bottom"] = (ext_left, h_gap_right)

        # For vertical lines (left/right): NO extensions
        # Vertical extensions cause uneven perceived row heights
        # ext["left"] and ext["right"] stay at default (0pt, 0pt)

        return edges, ext

    def generate_regular_block(self, block_):
        block = block_.copy()
        if not (block.get("image") or block.get("text")):
            return
        columns = block["columns"]
        num_rows = block.get("rows") or 1
        handouts_per_team = block.get("handouts_per_team") or 3
        grouping = block.get("grouping") or "horizontal"

        # Block-level spacing overrides (fall back to instance defaults)
        inner_hspace = block.get("hspace") if block.get("hspace") is not None else self.inner_hspace
        inner_vspace = block.get("vspace") if block.get("vspace") is not None else self.inner_vspace
        outer_hspace = block.get("outer_hspace") if block.get("outer_hspace") is not None else (block.get("hspace") if block.get("hspace") is not None else self.outer_hspace)
        outer_vspace = block.get("outer_vspace") if block.get("outer_vspace") is not None else (block.get("vspace") if block.get("vspace") is not None else self.outer_vspace)

        # Determine team rectangle dimensions
        team_cols, team_rows = self.get_cut_direction(
            columns, num_rows, handouts_per_team, grouping
        )
        if self.args.debug:
            print(
                f"team_cols: {team_cols}, team_rows: {team_rows}, grouping: {grouping}"
            )

        # Calculate total horizontal spacing
        # Inner gaps are within teams, outer gaps are between teams
        if team_cols and team_cols > 0:
            num_teams_h = columns // team_cols
            inner_gaps_h = num_teams_h * (team_cols - 1)  # gaps within all teams
            outer_gaps_h = num_teams_h - 1  # gaps between teams
        else:
            inner_gaps_h = columns - 1
            outer_gaps_h = 0
        total_hspace = inner_gaps_h * inner_hspace + outer_gaps_h * outer_hspace

        boxwidth = self.args.boxwidth or round(
            (self.get_page_width() - total_hspace) / columns,
            3,
        )
        total_width = boxwidth * columns + total_hspace
        if self.args.debug:
            print(
                f"columns: {columns}, boxwidth: {boxwidth}, total width: {total_width}"
            )
        boxwidthinner = self.args.boxwidthinner or (boxwidth - 2 * self.args.tikz_mm)
        header = [
            r"\setlength{\boxwidth}{<Q>mm}%".replace("<Q>", str(boxwidth)),
            r"\setlength{\boxwidthinner}{<Q>mm}%".replace("<Q>", str(boxwidthinner)),
        ]
        contents = []
        if block.get("image"):
            img_qwidth = block.get("resize_image") or 1.0
            imgwidth = IMGWIDTH.replace("<QWIDTH>", str(img_qwidth))
            contents.append(
                IMG.replace("<IMGPATH>", block["image"]).replace("<IMGWIDTH>", imgwidth)
            )
        if block.get("text"):
            contents.append(block["text"])
        block["contents"] = "\\linebreak\n".join(contents)
        if block.get("no_center"):
            block["centering"] = ""
        else:
            block["centering"] = "\\centering"

        # Helper to check if there's a team boundary between two adjacent columns
        def is_team_boundary_h(col_idx):
            """Is there a team boundary between col_idx and col_idx+1?"""
            if not team_cols or col_idx >= columns - 1:
                return False
            return (col_idx + 1) % team_cols == 0

        # Helper to check if there's a team boundary between two adjacent rows
        def is_team_boundary_v(row_idx):
            """Is there a team boundary between row_idx and row_idx+1?"""
            if not team_rows or row_idx >= num_rows - 1:
                return False
            return (row_idx + 1) % team_rows == 0

        rows = []
        for row_idx in range(num_rows):
            row_boxes = []
            for col_idx in range(columns):
                edges, ext = self.get_edge_styles(
                    row_idx, col_idx, num_rows, columns, team_cols, team_rows,
                    inner_hspace, inner_vspace
                )
                row_boxes.append(self.make_tikzbox(block, edges, ext))

            # Join boxes with appropriate horizontal spacing
            # Use outer_hspace at team boundaries, inner_hspace elsewhere
            row_parts = [row_boxes[0]]
            for col_idx in range(1, columns):
                hspace = outer_hspace if is_team_boundary_h(col_idx - 1) else inner_hspace
                if hspace > 0:
                    row_parts.append(f"%\n\\hspace{{{hspace}mm}}%\n")
                else:
                    row_parts.append("%\n")
                row_parts.append(row_boxes[col_idx])

            row = (
                TIKZBOX_START.replace("<CENTERING>", block["centering"])
                + "\\mbox{%\n"
                + "".join(row_parts)
                + "%\n}%"
                + TIKZBOX_END
            )
            rows.append(row)

        # Join rows with appropriate vertical spacing
        # Use outer_vspace at team boundaries, inner_vspace elsewhere
        row_parts = [rows[0]]
        for row_idx in range(1, num_rows):
            vspace = outer_vspace if is_team_boundary_v(row_idx - 1) else inner_vspace
            if vspace > 0:
                row_parts.append(f"\n\n\\vspace{{{vspace}mm}}\n\n")
            else:
                row_parts.append("\n\n")
            row_parts.append(rows[row_idx])

        return "\n".join(header) + "\n" + "".join(row_parts)

    def generate(self):
        for block in self.parse_input(self.args.filename):
            if not block:
                self.blocks.append("\n\\clearpage\n")
                continue
            if self.args.debug:
                print(block)
            if block.get("for_question"):
                self.blocks.append(self.generate_for_question(block["for_question"]))
            if block.get("columns"):
                block = self.generate_regular_block(block)
                if block:
                    self.blocks.append(block)
        self.blocks.append("\\end{document}")
        return "\n\n".join(self.blocks)


def process_file(args, file_dir, bn):
    tex_contents = HandoutGenerator(args).generate()
    tex_path = os.path.join(file_dir, f"{bn}_{args.language}.tex")
    write_file(tex_path, tex_contents)

    tectonic_path = get_tectonic_path()
    if not tectonic_path:
        print("tectonic is not present, installing it...")
        install_tectonic(args)
        tectonic_path = get_tectonic_path()
    if not tectonic_path:
        raise Exception("tectonic couldn't be installed successfully :(")
    if args.debug:
        print(f"tectonic found at `{tectonic_path}`")

    subprocess.run(
        [tectonic_path, os.path.basename(tex_path)], check=True, cwd=file_dir
    )

    output_file = replace_ext(tex_path, "pdf")

    if args.compress:
        print(f"compressing {output_file}")
        size_before = round(os.stat(output_file).st_size / 1024)
        output_file_compressed = output_file[:-4] + ".compressed.pdf"
        subprocess.run(
            [
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.5",
                f"-dPDFSETTINGS=/{args.pdfsettings}",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                f"-sOutputFile={output_file_compressed}",
                output_file,
            ],
            check=True,
        )
        shutil.move(output_file_compressed, output_file)
        size_after = round(os.stat(output_file).st_size / 1024)
        q = round(size_after / size_before, 1)
        print(f"before: {size_before}kb, after: {size_after}kb, compression: {q}")

    print(f"Output file: {output_file}")

    if not args.debug:
        os.remove(tex_path)


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, args, file_dir, bn):
        self.args = args
        self.file_dir = file_dir
        self.bn = bn
        self.last_processed = 0

    def on_modified(self, event):
        if event.src_path == os.path.abspath(self.args.filename):
            # Debounce to avoid processing the same change multiple times
            current_time = time.time()
            if current_time - self.last_processed > 1:
                print(f"File {self.args.filename} changed, regenerating PDF...")
                process_file(self.args, self.file_dir, self.bn)
                self.last_processed = current_time


def run_handouter(args):
    file_dir = os.path.dirname(os.path.abspath(args.filename))
    bn, _ = os.path.splitext(os.path.basename(args.filename))

    process_file(args, file_dir, bn)

    if args.watch:
        print(f"Watching {args.filename} for changes. Press Ctrl+C to stop.")
        event_handler = FileChangeHandler(args, file_dir, bn)
        observer = Observer()
        observer.schedule(event_handler, path=file_dir, recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


def gui_handouter(args):
    if args.handoutssubcommand == "run":
        run_handouter(args)
    elif args.handoutssubcommand == "generate":
        generate_handouts(args)
    elif args.handoutssubcommand == "pack":
        pack_handouts(args)
    elif args.handoutssubcommand == "install":
        install_tectonic(args)
