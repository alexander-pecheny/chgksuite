HEADER = r"""
\documentclass{minimal}
\usepackage[paperwidth=<PAPERWIDTH>mm,paperheight=<PAPERHEIGHT>mm,top=<MARGIN_TOP>mm,bottom=<MARGIN_BOTTOM>mm,left=<MARGIN_LEFT>mm,right=<MARGIN_RIGHT>mm]{geometry}
\frenchspacing
\usepackage{fontspec}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{calc}
\usepackage[document]{ragged2e}
\setmainfont{Arial}
\newlength{\boxwidth}
\newlength{\boxwidthinner}
\begin{document}
\fontsize{14pt}{16pt}\selectfont
\setlength\parindent{0pt}
\tikzstyle{box}=[rectangle, inner sep=<TIKZ_MM>mm]
\newcommand{\hstrut}{\vphantom{Ayg}}
\raggedright
\raggedbottom
""".strip()

GREYTEXT = r"""{\fontsize{9pt}{11pt}\selectfont \textcolor{gray}{<GREYTEXT>}}"""

TIKZBOX_START = r"""{<CENTERING>
"""

TIKZBOX_INNER = r"""
\begin{tikzpicture}
\node[box, minimum width=\boxwidth<INNER_SEP_OVERRIDE><TEXTWIDTH><ALIGN>] (b) {<FONTSIZE>\hstrut <CONTENTS>\par};
\useasboundingbox (b.south west) rectangle (b.north east);
\draw[<TOP>] ([xshift=<TOP_EXT_L>]b.north west) -- ([xshift=<TOP_EXT_R>]b.north east);
\draw[<BOTTOM>] ([xshift=<BOTTOM_EXT_L>]b.south west) -- ([xshift=<BOTTOM_EXT_R>]b.south east);
\draw[<LEFT>] ([yshift=<LEFT_EXT_T>]b.north west) -- ([yshift=<LEFT_EXT_B>]b.south west);
\draw[<RIGHT>] ([yshift=<RIGHT_EXT_T>]b.north east) -- ([yshift=<RIGHT_EXT_B>]b.south east);
\end{tikzpicture}
""".strip()

# Line styles for box edges
EDGE_SOLID = "line width=0.8pt"
EDGE_DASHED = "dashed"
EDGE_NONE = "draw=none"  # Don't draw this edge (to avoid double dashed lines)

TIKZBOX_END = "\n}"

IMG = r"""\includegraphics<IMGWIDTH>{<IMGPATH>}"""

IMGWIDTH = r"[width=<QWIDTH>\textwidth]"
