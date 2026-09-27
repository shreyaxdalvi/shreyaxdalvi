#!/usr/bin/env python3
"""
Generate an animated SVG ASCII portrait from a source photo.

Pipeline: rembg cutout -> bilateral filter -> CLAHE -> darkening curve
-> ramp mapping -> per-row typing animation (SMIL clipPath wipe).

Usage:
    python3 generate_portrait.py <source_image> <output_svg> [--cols 90] [--font woff2_base64_path]
"""
import sys
import argparse
import base64
import numpy as np
from PIL import Image
import cv2

RAMP = " .`:-=+*cs#%@"  # 13 levels, light -> dark
CHAR_W = 7.74           # em advance baked into the grid (0.600em @ font-size 12.9)
FONT_SIZE = 12.9
LINE_H = CHAR_W * 2 * 0.48 / 0.6  # derived so rows*char cell reads square-ish


def remove_background_to_white(img: Image.Image) -> Image.Image:
    """Cut the subject out and composite onto pure white so the background
    maps to the blank end of the ramp instead of filling with '@'."""
    from rembg import remove, new_session
    # u2net_human_seg keeps hair detail far better than plain u2net, which
    # tends to shave dark hair away against a dark/cluttered background
    session = new_session("u2net_human_seg")
    cutout = remove(img, session=session)  # RGBA, subject only
    bg = Image.new("RGBA", cutout.size, (255, 255, 255, 255))
    bg.paste(cutout, (0, 0), cutout)
    return bg.convert("RGB")


def to_ascii_grid(img: Image.Image, cols: int):
    w, h = img.size
    rows = max(1, round(cols * (h / w) * 0.48))
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

    # bilateral filter: smooth skin, keep edges
    gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    # CLAHE: local contrast so a flatly-lit face doesn't collapse to one tone
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # resize down to the character grid
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)

    # darkening curve (v/255)^1.7 -- keeps glasses/brows/lips from washing out
    curved = np.power(small.astype(np.float64) / 255.0, 1.7) * 255.0
    curved = curved.astype(np.uint8)

    return curved, cols, rows


def pixel_to_char(v: int) -> str:
    # v: 0 (dark) .. 255 (light). Ramp is light->dark, so invert index.
    idx = int((255 - v) / 255 * (len(RAMP) - 1))
    idx = max(0, min(len(RAMP) - 1, idx))
    return RAMP[idx]


def grid_to_rows(grid: np.ndarray):
    rows_text = []
    for r in range(grid.shape[0]):
        line = "".join(pixel_to_char(v) for v in grid[r])
        # strip pure trailing background so wipe width is meaningful,
        # but keep leading spaces (they clear background to nothing)
        rows_text.append(line.rstrip())
    return rows_text


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_svg(rows_text, cols, display_px=460, font_b64=None) -> str:
    n_rows = len(rows_text)
    view_w = cols * CHAR_W
    view_h = n_rows * (CHAR_W * 2)  # roughly square-ish cells per the 0.48 ratio
    display_h = round(display_px * (view_h / view_w))

    font_face = ""
    if font_b64:
        font_face = f"""
    @font-face {{
      font-family: 'RampMono';
      src: url(data:font/woff2;base64,{font_b64}) format('woff2');
    }}"""

    style = f"""<style>{font_face}
    .row {{ font-family: 'RampMono', 'JetBrains Mono', 'Liberation Mono', 'DejaVu Sans Mono', 'Noto Sans Mono', monospace;
             font-size: {FONT_SIZE}px; fill: #cfcfcf; white-space: pre; }}
    .cursor {{ fill: #7dd3fc; }}
  </style>"""

    parts = []
    parts.append(
        f'<svg viewBox="0 0 {view_w:.2f} {view_h:.2f}" width="{display_px}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="ASCII portrait, typed line by line">'
    )
    parts.append(style)
    parts.append(f'<rect width="100%" height="100%" fill="#0d1117"/>')

    for i, line in enumerate(rows_text):
        if not line.strip():
            continue
        y = (i + 0.85) * (CHAR_W * 2)
        row_w = len(line) * CHAR_W + CHAR_W * 2
        clip_id = f"clip{i}"
        begin = round(i * 0.09, 2)
        dur = 0.5

        parts.append(f'<clipPath id="{clip_id}">')
        parts.append(
            f'  <rect x="0" y="{y - CHAR_W * 1.4:.2f}" width="0" height="{CHAR_W * 2:.2f}">'
        )
        parts.append(
            f'    <animate attributeName="width" from="0" to="{row_w:.2f}" '
            f'begin="{begin}s" dur="{dur}s" fill="freeze" calcMode="linear"/>'
        )
        parts.append("  </rect>")
        parts.append("</clipPath>")

        parts.append(f'<g clip-path="url(#{clip_id})">')
        parts.append(f'  <text class="row" x="0" y="{y:.2f}">{esc(line)}</text>')
        # cursor block riding the wipe edge
        cursor_x_expr_id = f"cur{i}"
        parts.append(
            f'  <rect class="cursor" y="{y - CHAR_W * 1.1:.2f}" width="{CHAR_W*0.55:.2f}" '
            f'height="{CHAR_W*1.3:.2f}" opacity="0">'
        )
        parts.append(
            f'    <animate attributeName="x" from="0" to="{row_w - CHAR_W:.2f}" '
            f'begin="{begin}s" dur="{dur}s" fill="freeze" calcMode="linear"/>'
        )
        parts.append(
            f'    <set attributeName="opacity" to="1" begin="{begin}s" '
            f'dur="{dur}s" fill="freeze"/>'
        )
        parts.append(
            f'    <set attributeName="opacity" to="0" begin="{begin + dur}s" fill="freeze"/>'
        )
        parts.append("  </rect>")
        parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--cols", type=int, default=90)
    ap.add_argument("--font", default=None, help="path to a woff2 file to embed")
    args = ap.parse_args()

    img = Image.open(args.source).convert("RGB")
    img = remove_background_to_white(img)
    grid, cols, rows = to_ascii_grid(img, args.cols)
    rows_text = grid_to_rows(grid)

    font_b64 = None
    if args.font:
        with open(args.font, "rb") as f:
            font_b64 = base64.b64encode(f.read()).decode("ascii")

    svg = build_svg(rows_text, cols, font_b64=font_b64)
    with open(args.output, "w") as f:
        f.write(svg)

    print(f"grid: {cols}x{rows} rows, wrote {args.output}")


if __name__ == "__main__":
    main()
