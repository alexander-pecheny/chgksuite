"""Simple HTML table to Markdown converter.

Replaces dashtable.html2md with a minimal implementation that avoids
deprecated BeautifulSoup methods.
"""

from bs4 import BeautifulSoup


def html2md(html_string: str) -> str:
    """Convert an HTML table to a Markdown table string.

    Parameters
    ----------
    html_string : str
        HTML string containing a table

    Returns
    -------
    str
        The table formatted as Markdown
    """
    soup = BeautifulSoup(html_string, "html.parser")
    table = soup.find("table")

    if not table:
        return ""

    rows = table.find_all("tr")
    if not rows:
        return ""

    # Extract all rows as lists of cell texts
    data = []
    for row in rows:
        # Check for header cells first, then data cells
        cells = row.find_all("th")
        if not cells:
            cells = row.find_all("td")

        row_data = []
        for cell in cells:
            # Get text, normalize whitespace
            text = " ".join(cell.get_text().split())
            row_data.append(text)
        if row_data:
            data.append(row_data)

    if not data:
        return ""

    # Normalize row lengths (pad shorter rows)
    max_cols = max(len(row) for row in data)
    for row in data:
        while len(row) < max_cols:
            row.append("")

    # Calculate column widths (minimum 3 for markdown separator)
    # Add 2 for space cushions on each side
    widths = []
    for col in range(max_cols):
        width = max(len(row[col]) for row in data)
        widths.append(max(width + 2, 3))

    # Build markdown table
    lines = []

    # Header row (centered, with padding)
    header = "|" + "|".join(_center(cell, widths[i]) for i, cell in enumerate(data[0])) + "|"
    lines.append(header)

    # Separator row (no spaces to avoid typotools converting --- to em-dash)
    separator = "|" + "|".join("-" * w for w in widths) + "|"
    lines.append(separator)

    # Data rows (centered, with padding)
    for row in data[1:]:
        line = "|" + "|".join(_center(cell, widths[i]) for i, cell in enumerate(row)) + "|"
        lines.append(line)

    return "\n".join(lines)


def _center(text: str, width: int) -> str:
    """Center text within width, with space padding."""
    text = text.strip()
    padding = width - len(text)
    left = padding // 2
    right = padding - left
    return " " * left + text + " " * right
