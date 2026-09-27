#!/usr/bin/env python3
"""
Section headings as SVG -- the only way to put JetBrains Mono on a heading,
since GitHub strips <style> blocks and font tags from README markdown.
Lowercase label + a hairline rule running to the right edge, per the guide.

Each heading gets its own font subset covering only the letters it actually
uses (~1.4 KB each) rather than a full basic-latin subset, to keep the
page's total embedded-font weight down.
"""
import sys
import subprocess
import tempfile
import base64
import argparse
import os

FONT_SIZE = 15
FG = "#e6edf3"
RULE = "#30363d"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def subset_font_for_text(ttf_path: str, text: str) -> bytes:
    chars = "".join(sorted(set(text)))
    with tempfile.NamedTemporaryFile(suffix=".woff2", delete=False) as tmp:
        out_path = tmp.name
    subprocess.run(
        [
            sys.executable, "-m", "fontTools.subset", ttf_path,
            f"--text={chars}",
            "--flavor=woff2", "--layout-features=", "--no-hinting",
            f"--output-file={out_path}",
        ],
        check=True, capture_output=True,
    )
    with open(out_path, "rb") as f:
        data = f.read()
    os.unlink(out_path)
    return data


def build_heading_svg(label: str, font_b64: str, width: int = 900) -> str:
    height = 34
    text_w = len(label) * FONT_SIZE * 0.6  # monospace advance estimate
    rule_x = text_w + 24
    return f"""<svg viewBox="0 0 {width} {height}" width="100%" height="{height}"
     xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(label)} section heading">
  <style>
    @font-face {{
      font-family: 'HeadMono';
      src: url(data:font/woff2;base64,{font_b64}) format('woff2');
    }}
    text {{ font-family: 'HeadMono','Liberation Mono',monospace; font-size: {FONT_SIZE}px; fill: {FG}; }}
  </style>
  <text x="0" y="22">{esc(label)}</text>
  <line x1="{rule_x:.0f}" y1="17" x2="{width}" y2="17" stroke="{RULE}" stroke-width="1"/>
</svg>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("output")
    ap.add_argument("--ttf", required=True, help="source TTF to subset per-heading")
    ap.add_argument("--width", type=int, default=900)
    args = ap.parse_args()
    font_bytes = subset_font_for_text(args.ttf, args.label)
    font_b64 = base64.b64encode(font_bytes).decode("ascii")
    svg = build_heading_svg(args.label, font_b64, args.width)
    with open(args.output, "w") as f:
        f.write(svg)
    print(f"wrote {args.output} (font subset {len(font_bytes)} bytes)")


if __name__ == "__main__":
    main()

