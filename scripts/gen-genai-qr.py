#!/usr/bin/env python3
"""
Generate the QR code used by genai-guide.html / genai-guide-portrait.html.

Encodes https://guides.library.westpoint.edu/GenAI as a single-<path> SVG with a
1x1-per-module coordinate system, so the signage pages can scale it to any size
with no runtime QR library. Run this once and commit the output; the same markup
is also pasted inline into both HTML pages.

Usage:  python3 scripts/gen-genai-qr.py
Output: genai-guide-qr.svg   (repo root)

Requires: segno  (pip install --user segno)
"""

import segno

URL = "https://guides.library.westpoint.edu/GenAI"
OUT = "genai-guide-qr.svg"
BORDER = 2  # quiet-zone modules on every side (QR spec minimum is 4; 2 is fine
            # here because the pages set a white padded plate behind the code)


def main():
    qr = segno.make(URL, error="m")
    matrix = list(qr.matrix)
    n = len(matrix)
    size = n + BORDER * 2

    # One path, one "M h1v1h-1z" sub-path per dark module. Compact and crisp.
    parts = []
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                parts.append(f"M{c + BORDER} {r + BORDER}h1v1h-1z")
    path = "".join(parts)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code linking to guides.library.westpoint.edu/GenAI">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/>'
        f'</svg>\n'
    )

    with open(OUT, "w") as f:
        f.write(svg)
    print(f"wrote {OUT}  ({size}x{size} module grid, {len(parts)} dark modules)")


if __name__ == "__main__":
    main()
