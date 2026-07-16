import os
import shlex
import shutil
import subprocess
import sys

from chgksuite.common import replace_escaped
from chgksuite.composer.composer_common import (
    BaseExporter,
    backtick_replace,
    parseimg,
)

# Page setup, transcribed from template.docx (twips → mm/pt), so the PDF lays
# out like the docx export.
MARGIN_V = "25.4mm"  # w:top / w:bottom = 1440tw
MARGIN_H = "19.05mm"  # w:left / w:right = 1080tw
BODY_PT = 12.0  # Normal: sz 24 half-points
H1_PT = 16.0  # Heading1: sz 32
H2_PT = 14.0  # Heading2: sz 28
HEADING_ABOVE = 12.0  # Heading{1,2} w:spacing w:before=240tw
HEADING_BELOW = 3.0  # …w:after=60tw
QUESTION_ABOVE = 18.0  # question paragraph w:before=360tw
ANSWER_ABOVE = 6.0  # answer paragraph w:before=120tw
SRC_PT = 10.0  # source/author runs: 2pt below body
# the shrunk block starts one BODY line below: 2pt × Noto Sans's 1.362em line
# box (asc 1.069 + desc 0.293)
SRC_GAP_PT = 2.72
LINK_COLOR = "#0000ff"  # Hyperlink character style
TAB_WIDTH = "36pt"  # Word's default tab stop (0.5in)
FONT_FAMILY = "Noto Sans"

# separates the block-chunks of a paragraph interrupted by a page break; can't
# collide with a real expression: those are all function calls
PB_MARKER = "\x00pagebreak\x00"


def typst_string(s):
    """Render a Python string as a typst string literal. Every piece of
    editorial text reaches typst through this, which is why the exporter can
    stay in code mode and never has to escape typst *markup*."""
    out = ['"']
    for c in s:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append("\\u{{{:x}}}".format(ord(c)))
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def pt(v):
    return "{:g}pt".format(round(v, 2))


def mm(v):
    return "{:g}mm".format(round(v, 2))


def wrap_text(s, params):
    if not params:
        return "text(" + typst_string(s) + ")"
    return "text(" + params + ", " + typst_string(s) + ")"


def sc_expr(s, params):
    """Synthesize small caps: lowercase letters are uppercased and set smaller,
    the rest is left alone. It has to be done by hand because Noto Sans carries
    no `smcp` feature — typst's smallcaps() would leave the text as-is."""
    scale = 0.8  # of the surrounding size, as Word renders small caps
    parts = []
    cur = []
    cur_lower = False

    def flush():
        if not cur:
            return
        if cur_lower:
            p = params + ", " if params else ""
            p += "size: {:g}em".format(scale)
            parts.append(wrap_text("".join(cur).upper(), p))
        else:
            parts.append(wrap_text("".join(cur), params))
        del cur[:]

    for c in s:
        lower = c.islower()
        if cur and lower != cur_lower:
            flush()
        cur_lower = lower
        cur.append(c)
    flush()
    return " + ".join(parts)


def text_expr(text, params, small_caps):
    """Build the content for one run's text: the literal, with line breaks and
    tabs lifted out into their own expressions."""
    parts = []

    def emit(s):
        if not s:
            return
        if small_caps:
            parts.append(sc_expr(s, params))
        else:
            parts.append(wrap_text(s, params))

    cur = []
    for c in text:
        if c in ("\n", "\r"):
            emit("".join(cur))
            cur = []
            parts.append("linebreak()")
        elif c == "\t":
            emit("".join(cur))
            cur = []
            parts.append("h(" + TAB_WIDTH + ")")
        else:
            cur.append(c)
    emit("".join(cur))
    if not parts:
        return ""
    return " + ".join(parts)


def styled(text, kind):
    """Turn one run of text into a content expression, applying the 4s inline
    kind (bold/italic/underline/strike/sc, and their combinations)."""
    if not text:
        return ""
    params = []
    if "bold" in kind:
        params.append('weight: "bold"')
    if "italic" in kind:
        params.append('style: "italic"')
    inner = text_expr(text, ", ".join(params), kind == "sc")
    if "underline" in kind:
        inner = "underline(" + inner + ")"
    if kind == "strike":
        inner = "strike(" + inner + ")"
    return inner


def empty_line():
    """The empty paragraph docx emits after a meta block: one blank line of
    body text (a bare block would collapse to nothing)."""
    return "#block(above: 0pt, below: 0pt, text({}))\n".format(typst_string(" "))


class Para:
    """One Word paragraph: a list of typst content expressions plus the
    paragraph properties that came off the docx (spacing, keep-together, the
    heading font). Renders to one #block(…) — or several, since typst refuses
    a pagebreak inside a container, so a (PAGEBREAK) mid-paragraph closes the
    block, breaks the page, and opens the next one."""

    def __init__(
        self,
        above=0.0,
        below=0.0,
        keep_lines=False,
        sticky=False,
        page_break=False,
        size=0.0,
        bold=False,
        italic=False,
        run_size=0.0,
    ):
        self.above = above
        self.below = below
        self.keep_lines = keep_lines
        self.sticky = sticky
        self.page_break = page_break
        self.size = size
        self.bold = bold
        self.italic = italic
        self.run_size = run_size
        self.exprs = []

    def add(self, expr):
        if expr:
            self.exprs.append(expr)

    def sized(self, expr):
        if not expr or not self.run_size:
            return expr
        return "text(size: " + pt(self.run_size) + ", " + expr + ")"

    def add_styled(self, text, kind=""):
        self.add(self.sized(styled(text, kind)))

    def add_break(self):
        self.add("linebreak()")

    def add_page_break(self):
        self.exprs.append(PB_MARKER)

    def add_link(self, url):
        self.add(
            self.sized(
                "link({}, underline(text(fill: rgb({}), {})))".format(
                    typst_string(url), typst_string(LINK_COLOR), typst_string(url)
                )
            )
        )

    def text_params(self):
        params = []
        if self.size and self.size != BODY_PT:
            params.append("size: " + pt(self.size))
        if self.bold:
            params.append('weight: "bold"')
        if self.italic:
            params.append('style: "italic"')
        return ", ".join(params)

    def chunks(self):
        chunks = [[]]
        for e in self.exprs:
            if e == PB_MARKER:
                chunks.append([])
            else:
                chunks[-1].append(e)
        return chunks

    def typ(self):
        out = []
        if self.page_break:
            out.append("#pagebreak(weak: true)\n")
        for i, chunk in enumerate(self.chunks()):
            if i > 0:
                out.append("#pagebreak(weak: true)\n")
            above = self.above if i == 0 else 0.0
            body = " + ".join(chunk) or "[]"
            params = self.text_params()
            if params:
                body = "text({}, {})".format(params, body)
            out.append(
                "#block(above: {}, below: {}, breakable: {}, sticky: {}, {})\n".format(
                    pt(above),
                    pt(self.below),
                    "false" if self.keep_lines else "true",
                    "true" if self.sticky else "false",
                    body,
                )
            )
        return "".join(out)


class TypstExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qcount = 0

    # Word's paragraph-level "keep" flags map onto typst blocks
    # (keepLines → breakable: false, keepNext → sticky: true), so a question
    # never straddles a page break, as in the docx export.
    #
    # top-edge/bottom-edge and leading are load-bearing, not taste. By default
    # typst measures a line box from cap-height to baseline, so a block's height
    # leaves out its descenders — fine when blocks are separated by par.spacing,
    # ruinous here, because Word's paragraphs are flush and consecutive blocks
    # would overlap by a descender. Measuring the full ascender→descender line
    # box makes flush blocks sit flush; dropping leading to 0 keeps the line
    # advance where typst's default had it, i.e. Word's single spacing.
    def preamble(self):
        lang = (self.args.language or "ru")[:2]
        return (
            '#set page(paper: "a4", margin: (top: {v}, bottom: {v}, left: {h}, '
            "right: {h}), footer: context align(center, text(size: {body}, "
            "counter(page).display())))\n"
            "#set text(font: {font}, size: {body}, lang: {lang}, hyphenate: false, "
            'top-edge: "ascender", bottom-edge: "descender")\n'
            "#set par(spacing: 0pt, leading: 0pt, justify: false)\n"
        ).format(
            v=MARGIN_V,
            h=MARGIN_H,
            body=pt(BODY_PT),
            font=typst_string(FONT_FAMILY),
            lang=typst_string(lang),
        )

    def generate(self):
        out = [self.preamble()]
        first_section = True  # only sections after the first get a page break
        heading_pb = False  # sticky page_break_before_heading
        first = True  # nothing emitted yet
        prev_type = None

        for element in self.structure:
            etype = element[0]
            if etype == "meta":
                p = Para(above=QUESTION_ABOVE if prev_type == "Question" else 0.0)
                self.add_value(p, element[1], True)
                out.append(p.typ())
                out.append(empty_line())
            elif etype in ("heading", "ljheading", "section", "editor", "date"):
                p = Para(above=HEADING_ABOVE, below=HEADING_BELOW, sticky=True)
                if etype == "heading":
                    p.size, p.bold = H1_PT, True
                    if not first:
                        heading_pb = True
                    p.page_break = heading_pb
                elif etype == "section":
                    p.size, p.bold, p.italic = H2_PT, True, True
                    p.page_break = not first_section
                    first_section = False
                self.add_value(p, element[1], True)
                p.add_break()
                out.append(p.typ())
            elif etype == "Question":
                out.append(self.render_question(element[1]))
            else:
                continue
            first = False
            prev_type = etype
        return "".join(out)

    def render_question(self, q):
        if "number" not in q:
            self.qcount += 1
        if "setcounter" in q:
            self.qcount = int(q["setcounter"])
        number = q.get("number", self.qcount)
        out = []

        p1 = Para(above=QUESTION_ABOVE, keep_lines=True)
        p1.add_styled(self.get_label(q, "question", number) + ". ", "bold")
        if "handout" in q:
            p1.add_styled("\n[" + self.get_label(q, "handout") + ": ")
            self.add_value(p1, q["handout"], False)
            p1.add_styled("\n]")
        p1.add_break()
        self.add_value(p1, q["question"], True)
        out.append(p1.typ())

        p2 = Para(above=ANSWER_ABOVE, keep_lines=True)
        p2.add_styled(self.get_label(q, "answer") + ": ", "bold")
        self.add_value(p2, q["answer"], True)

        src = None
        for field in ("zachet", "nezachet", "comment", "source", "author"):
            if field not in q:
                continue
            nbsp = field != "source"
            if field in ("source", "author"):
                if src is None:
                    src = Para(keep_lines=True, run_size=SRC_PT, above=SRC_GAP_PT)
                else:
                    src.add_break()
                src.add_styled(self.get_label(q, field) + ": ", "bold")
                self.add_value(src, q[field], nbsp)
                continue
            p2.add_break()
            p2.add_styled(self.get_label(q, field) + ": ", "bold")
            self.add_value(p2, q[field], nbsp)
        out.append(p2.typ())
        if src is not None:
            out.append(src.typ())
        return "".join(out)

    def add_value(self, p, v, nbsp):
        """Render a field value (string or list): the [preamble, [items…]] form
        renders the preamble then a numbered list; a flat list just the
        numbered items."""
        if isinstance(v, str):
            self.add_runs(p, v, nbsp)
        elif isinstance(v, list):
            if len(v) > 1 and isinstance(v[1], list):
                self.add_runs(p, str(v[0]), nbsp)
                for i, item in enumerate(v[1], 1):
                    p.add_styled("\n{}. ".format(i))
                    self.add_runs(p, str(item), nbsp)
            else:
                for i, item in enumerate(v, 1):
                    p.add_styled("\n{}. ".format(i))
                    self.add_runs(p, str(item), nbsp)

    def add_runs(self, p, text, nbsp):
        """Tokenize inline 4s markup and append one content expression per
        token."""
        text = replace_escaped(text)
        text = backtick_replace(text)
        for kind, content in self.parse_4s_elem(text):
            if kind == "linebreak":
                p.add_break()
            elif kind == "pagebreak":
                p.add_page_break()
            elif kind == "img":
                self.add_image(p, content)
            elif kind == "screen":
                p.add_styled(content["for_print"])
            elif kind == "hyperlink":
                p.add_link(content)
            else:
                if nbsp:
                    content = self._replace_no_break(content)
                p.add_styled(content, kind)

    def add_image(self, p, arg):
        """Resolve an (img …) directive and append the picture at the size the
        docx export would give it. With --ignore_missing_images a missing file
        degrades to a bold placeholder instead of failing the export."""
        try:
            parsed = parseimg(
                arg,
                dimensions="inches",
                tmp_dir=self.dir_kwargs.get("tmp_dir"),
                targetdir=self.dir_kwargs.get("targetdir"),
            )
        except Exception as e:
            if getattr(self.args, "ignore_missing_images", False):
                filename = shlex.split(arg)[-1]
                sys.stderr.write(f"Exception: {type(e)} {e}\n")
                sys.stderr.write(f"MISSING IMAGE: {filename}\n")
                p.add_break()
                p.add_styled(f"MISSING IMAGE {filename}", "bold")
                p.add_break()
                return
            raise
        imgfile = os.path.abspath(parsed["imgfile"]).replace("\\", "/")
        if parsed["inline"]:
            expr = "box(image({}, height: {}))".format(
                typst_string(imgfile), mm(25.4 / 6)
            )
            p.add(expr)
            return
        expr = "box(image({}, width: {}, height: {}))".format(
            typst_string(imgfile),
            mm(parsed["width"] * 25.4),
            mm(parsed["height"] * 25.4),
        )
        p.add_break()
        p.add(expr)
        p.add_break()

    def export(self, outfilename):
        from chgksuite.handouter.installer import get_bundled_fonts_dir
        from chgksuite.handouter.runner import ensure_typst_path

        self.qcount = 0
        typ = self.generate()
        with open(outfilename, "w", encoding="utf-8") as f:
            f.write(typ)

        typst_path = ensure_typst_path(self.args)
        pdf_filename = os.path.splitext(outfilename)[0] + ".pdf"
        proc = subprocess.run(
            [
                typst_path,
                "compile",
                "--root",
                os.path.abspath(os.sep),
                "--font-path",
                get_bundled_fonts_dir(),
                outfilename,
                pdf_filename,
            ],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise Exception(
                "typst compile failed: {}".format(
                    proc.stderr.decode("utf8", errors="replace")
                )
            )
        targetdir = self.dir_kwargs["targetdir"]
        shutil.copy(pdf_filename, targetdir)
        if getattr(self.args, "rawtypst", False):
            shutil.copy(outfilename, targetdir)
        self.logger.info(
            "Output: {}".format(
                os.path.join(targetdir, os.path.basename(pdf_filename))
            )
        )
