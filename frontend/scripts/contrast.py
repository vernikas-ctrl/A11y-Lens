"""Measure the palette's contrast ratios. Task 7.2.

Run it from `frontend/`:

    python scripts/contrast.py

It reads the colours out of `src/index.css` rather than keeping a second copy
of them, so the numbers it prints are the numbers the app actually renders.
`src/palette.test.ts` runs the same arithmetic and fails if any pair drops
below the threshold, which is what stops the table in the CSS comment from
quietly going stale when somebody adjusts a colour.

The formula is WCAG's own (relative luminance, then
`(lighter + 0.05) / (darker + 0.05)`), not an approximation.

Thresholds, from WCAG 2.1:
  4.5:1  normal text (AA)
  3.0:1  large text and user interface components (AA)
  7.0:1  normal text (AAA) -- not a target here, shown for information
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "src" / "index.css"

AA_TEXT = 4.5
AA_LARGE = 3.0
AAA_TEXT = 7.0

# Which pairs matter, and what each is for. A palette is not "accessible" on
# its own -- only a foreground on a background is, so these are the pairs the
# app is allowed to use.
PAIRS: list[tuple[str, str, str]] = [
    ("ink", "paper", "body text"),
    ("ink", "surface", "body text on cards"),
    ("muted", "paper", "secondary text, captions"),
    ("muted", "surface", "secondary text on cards"),
    ("primary", "paper", "links, focus ring"),
    ("primary", "surface", "links on cards"),
    ("paper", "primary", "button label"),
    ("alert", "paper", "error text"),
    ("alert", "surface", "error text on cards"),
    ("paper", "alert", "badge label"),
]


def read_palette(css: Path) -> dict[str, str]:
    """Pull `--color-NAME: #hex;` out of the @theme block."""
    text = css.read_text(encoding="utf-8")
    found = dict(re.findall(r"--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", text))
    if not found:
        raise SystemExit(f"no --color-* declarations found in {css}")
    return found


def channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(foreground: str, background: str) -> float:
    a, b = luminance(foreground), luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def main() -> int:
    palette = read_palette(CSS)
    print(f"palette from {CSS.name}:")
    for name, value in sorted(palette.items()):
        print(f"  {name:9} {value}")
    print()

    header = f"{'pair':20} {'ratio':>7}  {'AA':>5} {'AA large':>9} {'AAA':>5}   use"
    print(header)
    print("-" * len(header))

    worst = (99.0, "")
    failures = 0
    for fg, bg, use in PAIRS:
        if fg not in palette or bg not in palette:
            print(f"  missing colour in pair {fg} on {bg}")
            failures += 1
            continue
        r = ratio(palette[fg], palette[bg])
        if r < worst[0]:
            worst = (r, f"{fg} on {bg}")
        if r < AA_TEXT:
            failures += 1
        print(
            f"{fg + ' on ' + bg:20} {r:6.2f}:1  "
            f"{'pass' if r >= AA_TEXT else 'FAIL':>5} "
            f"{'pass' if r >= AA_LARGE else 'FAIL':>9} "
            f"{'pass' if r >= AAA_TEXT else '-':>5}   {use}"
        )

    print()
    print(f"worst pair: {worst[1]} at {worst[0]:.2f}:1 (AA needs {AA_TEXT})")
    if failures:
        print(f"{failures} pair(s) below AA for normal text")
        return 1
    print("every pair clears AA for normal text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
