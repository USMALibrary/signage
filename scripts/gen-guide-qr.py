#!/usr/bin/env python3
"""
Generate an inline-SVG QR code for a LibGuide signage page.

Single-<path> SVG with a 1x1-per-module coordinate system so pages can scale it
to any size with no runtime QR library. No xmlns attribute on purpose: inline SVG
in HTML does not need it, and Rise Vision's HTML Embed rejects any "http://"
string in pasted markup.

Usage:  python3 scripts/gen-guide-qr.py <guide-url> <output.svg>
   e.g. python3 scripts/gen-guide-qr.py https://guides.library.westpoint.edu/OperationOVERLORD hi302-overlord-qr.svg

Requires: segno  (pip install --user segno)
"""

import sys
import segno

BORDER = 2  # quiet-zone modules; pages add a white padded plate behind the code


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    url, out = sys.argv[1], sys.argv[2]
    qr = segno.make(url, error="m")
    matrix = list(qr.matrix)
    size = len(matrix) + BORDER * 2
    path = "".join(
        f"M{c + BORDER} {r + BORDER}h1v1h-1z"
        for r, row in enumerate(matrix)
        for c, dark in enumerate(row)
        if dark
    )
    label = url.replace("https://", "")
    svg = (
        f'<svg viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code linking to {label}">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/></svg>'
    )
    with open(out, "w") as f:
        f.write(svg)
    print(f"wrote {out} ({len(matrix)}x{len(matrix)} modules)")


if __name__ == "__main__":
    main()
