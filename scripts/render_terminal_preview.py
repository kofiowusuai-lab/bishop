"""Render captured ANSI terminal output for visual QA (dev-only Pillow dependency).

Usage: python scripts/render_terminal_preview.py capture.ansi preview.png
Preserves cell positions; supports SGR truecolor and indexed foreground colors.
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

SGR = re.compile(r"\x1b\[([0-9;]*)m")
PALETTE = ["#111111", "#cc5555", "#67ad63", "#d7b66b", "#6489ba", "#b47db4", "#6daeb0", "#e7e0d1", "#77736b", "#ef7777", "#92ca86", "#f4dca6", "#8eafe0", "#d4a2d4", "#9ad4d4", "#ffffff"]


def indexed(value):
    if value < 16:
        return PALETTE[value]
    if value >= 232:
        return (8 + 10 * (value - 232),) * 3
    value -= 16
    levels = [0, 95, 135, 175, 215, 255]
    return (levels[value // 36], levels[value // 6 % 6], levels[value % 6])


def render(source, target, font_path, font_size=18, columns=None):
    font = ImageFont.truetype(font_path, font_size)
    # Apple Symbols includes braille; Menlo lacks it on some macOS releases.
    symbols_path = Path("/System/Library/Fonts/Apple Symbols.ttf")
    symbols = ImageFont.truetype(str(symbols_path), font_size) if symbols_path.exists() else font
    lines = source.rstrip("\n").split("\n")
    visible = [SGR.sub("", line) for line in lines]
    cell_width = font.getlength("M")
    line_height = round(font_size * 1.4)
    columns = columns or max(map(len, visible), default=1)
    margin = 24
    canvas = Image.new("RGB", (round(columns * cell_width) + margin * 2, len(lines) * line_height + margin * 2), "#0d0e10")
    draw = ImageDraw.Draw(canvas)
    color = "#e7e0d1"
    for row, line in enumerate(lines):
        x = margin
        cursor = 0
        for match in list(SGR.finditer(line)) + [None]:
            end = match.start() if match else len(line)
            for char in line[cursor:end]:
                char_font = symbols if 0x2800 <= ord(char) <= 0x28ff else font
                draw.text((x, margin + row * line_height), char, font=char_font, fill=color)
                x += cell_width * (0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1)
            if match:
                codes = [int(value or 0) for value in match.group(1).split(";")]
                index = 0
                while index < len(codes):
                    code = codes[index]
                    if code in (0, 39):
                        color = "#e7e0d1"
                    elif 30 <= code <= 37:
                        color = PALETTE[code - 30]
                    elif 90 <= code <= 97:
                        color = PALETTE[code - 90 + 8]
                    elif code == 38 and codes[index + 1:index + 2] == [2] and len(codes) >= index + 5:
                        color = tuple(codes[index + 2:index + 5])
                        index += 4
                    elif code == 38 and codes[index + 1:index + 2] == [5] and len(codes) >= index + 3:
                        color = indexed(codes[index + 2])
                        index += 2
                    index += 1
                cursor = match.end()
    metadata = PngInfo()
    metadata.add_text("Title", "Bishop independent agent runtime terminal preview")
    metadata.add_text("Description", "Actual rendered Bishop terminal boot output. Bishop by Kedolabs, https://kedolabs.com.")
    metadata.add_text("Copyright", "Kedolabs; Bishop contributors. See repository license.")
    metadata.add_text("Keywords", "Bishop, Kedolabs, AI agent runtime, terminal interface")
    canvas.save(target, pnginfo=metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", default="/System/Library/Fonts/Menlo.ttc")
    parser.add_argument("--font-size", type=int, default=18)
    parser.add_argument("--columns", type=int)
    args = parser.parse_args()
    render(args.capture.read_text(), args.output, args.font, args.font_size, args.columns)
