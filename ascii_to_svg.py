from pathlib import Path
import html

ASCII_FILE = Path("ascii.txt")
OUT_FILE = Path("ascii_block.svg")

ascii_text = ASCII_FILE.read_text(encoding="utf-8").splitlines()

x = 50
y = 80
line_height = 14

lines = [
    '<g id="ascii_art">',
    f'  <text x="{x}" y="{y}" font-family="monospace" font-size="12" fill="#ffffff" xml:space="preserve">'
]

for i, line in enumerate(ascii_text):
    escaped = html.escape(line)
    if i == 0:
        lines.append(f'    <tspan x="{x}" dy="0">{escaped}</tspan>')
    else:
        lines.append(f'    <tspan x="{x}" dy="{line_height}">{escaped}</tspan>')

lines += [
    "  </text>",
    "</g>",
]

OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {OUT_FILE}")