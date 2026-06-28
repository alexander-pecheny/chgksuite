"""Typst markup fragments used to render handout grids.

This replaces the previous TeX/TikZ backend (``tex_internals``). The visual
contract is identical: a grid of identical handout cells whose four edges are
drawn independently as solid (team boundary / outer), dashed (internal
separator) or omitted, with the solid lines extended into the inter-cell gaps
so they meet across cuts.
"""

# Document preamble: page geometry, default font and the ``hcell`` helper that
# draws a single handout box with four independently styled edges.
#
# Placeholders (``<...>``) are filled in by HandoutGenerator.get_header().
HEADER = r"""
#set page(
  width: <PAPERWIDTH>mm,
  height: <PAPERHEIGHT>mm,
  margin: (
    top: <MARGIN_TOP>mm,
    bottom: <MARGIN_BOTTOM>mm,
    left: <MARGIN_LEFT>mm,
    right: <MARGIN_RIGHT>mm,
  ),
)
#set text(font: "<FONT>", size: <FONTSIZE>pt)
#set par(justify: false, leading: 0.5em)

#let _edge_stroke(kind) = {
  if kind == "solid" { (paint: black, thickness: 0.8pt) }
  else if kind == "dashed" { (paint: black, thickness: 0.4pt, dash: "dashed") }
  else { none }
}

// A single handout cell. `width`/`inset` are lengths; `halign` is an alignment;
// `body` is content. The four `e_*` are "solid"/"dashed"/"none". The remaining
// arguments are gap-closing extensions (lengths), already converted to Typst's
// y-down coordinate system by the caller.
//
// The cell height is measured up front so the vertical edges get a concrete
// length: a placed line's `100%` would otherwise resolve against the page
// region (full height) rather than the cell when laid out inside a grid.
#let hcell(
  width, inset, halign, body,
  e_top, e_bottom, e_left, e_right,
  top_l, top_r, bottom_l, bottom_r,
  left_t, left_b, right_t, right_b,
  top_y, bottom_y,
) = context {
  let inner = width - 2 * inset
  let h = measure(box(width: inner, body)).height + 2 * inset
  box(width: width, height: h, inset: inset, {
    if e_top != "none" {
      place(top + left, line(
        start: (top_l, top_y),
        end: (width + top_r, top_y),
        stroke: _edge_stroke(e_top),
      ))
    }
    if e_bottom != "none" {
      place(top + left, line(
        start: (bottom_l, h + bottom_y),
        end: (width + bottom_r, h + bottom_y),
        stroke: _edge_stroke(e_bottom),
      ))
    }
    if e_left != "none" {
      place(top + left, line(
        start: (0pt, left_t),
        end: (0pt, h + left_b),
        stroke: _edge_stroke(e_left),
      ))
    }
    if e_right != "none" {
      place(top + left, line(
        start: (width, right_t),
        end: (width, h + right_b),
        stroke: _edge_stroke(e_right),
      ))
    }
    align(halign, body)
  })
}
""".strip()

# A small grey caption above a handout grid (e.g. "Handout for question 5").
GREYTEXT = r"""#text(fill: gray, size: 9pt)[<GREYTEXT>]"""

# Image inside a cell, scaled relative to the cell's inner content width.
IMG = r"""#image("<IMGPATH>", width: <IMGWIDTH>)"""

IMGWIDTH = r"""<QWIDTH>"""

# Line styles for box edges. Values double as the literal tokens passed to the
# Typst `hcell` helper, so they must stay in sync with `_edge_stroke` above.
EDGE_SOLID = "solid"
EDGE_DASHED = "dashed"
EDGE_NONE = "none"
