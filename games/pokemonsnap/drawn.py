"""Drawn assets (no retail pixels): fonts, and hooks for text-bearing textures, faces and pictures.

hooks(spec, rom) -> {key: rgba override, "__bytes__": [(space, off, bytes)]} used by generate.py
taint_ranges()   -> {label: (space, off, nbytes)} extra ranges for the taint report

Text font (window/text.c): 370 glyphs in two sizes (8x8 and 12x12, 4 bits per pixel, even x in the low nibble,
0 = clear, 1..15 = ramp from background to text colour). The character of each glyph is the decomp's
UIText_CharTable; advance widths are UIText_WidthTable (kept code data). Glyphs are typeset with OFL fonts:
Press Start 2P (8x8 Latin), M PLUS Rounded 1c ExtraBold (12x12 and all kana), see fonts/README.md.
"""
import os
import re
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
PRISTINE = "D:/n64work/pokemonsnap/pristine"
# glyph tables (ROM offsets, from the pointer table D_8037EA68 in window .data)
FONT_TABLES = {8: 0x848BC0, 12: 0x84BA04}
NGLYPH = 370


def _c_table(src, name):
    m = re.search(r"\b%s\[[^\]]*\](?:\[[^\]]*\])?\s*=\s*\{(.*?)\n\};" % re.escape(name), src, re.S)
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return body


def char_table():
    src = open(f"{PRISTINE}/src/window/text.c", encoding="utf-8").read()
    body = _c_table(src, "UIText_CharTable")
    toks = re.findall(r"'((?:\\\\|[^'])+)'|(0x[0-9A-Fa-f]+)", body)
    out = []
    for a, b in toks:
        out.append(a.replace("\\\\", "\\") if a else chr(0x301C))  # 0xA1C1 (EUC-JP) = wave dash
    assert len(out) == NGLYPH, len(out)
    body = _c_table(src, "UIText_WidthTable")
    nums = [int(v) for v in re.findall(r"\d+", body)]
    return out, {8: nums[:NGLYPH], 12: nums[NGLYPH:2 * NGLYPH]}


def _font(name, px):
    return ImageFont.truetype(os.path.join(FONTS, name), px)


UNITS = {"mm": "mm", "cm": "cm", "\\m": "m", "Km": "km", "\\g": "g", "Kg": "kg", "\\l": "l", "No": "No"}


def glyph_alpha(ch, cell, adv):
    """alpha (cell x cell) in 0..1, glyph drawn inside the left `adv` columns"""
    SS = 8
    W = H = cell * SS
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    text = UNITS.get(ch, ch)
    if ch == "・" and cell == 12:
        text = "・"
    plain = unicodedata.normalize("NFKC", text) if len(text) == 1 else text
    is_kana = any(0x3000 <= ord(c) <= 0x30FF for c in text) and ch not in ("ー",)
    if cell == 8 and not is_kana and plain.isascii() and len(plain) == 1:
        f = _font("PressStart2P-Regular.ttf", 8 * SS)
        text = plain
    else:
        text = plain if not is_kana else text
        px = (cell + 1) * SS if len(text) == 1 else int(cell * SS * 0.8)
        f = _font("MPLUSRounded1c-ExtraBold.ttf", px)
    box = d.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    aw = max(1, adv) * SS
    asc, desc = f.getmetrics()
    single = len(text) == 1
    if tw > aw or th > H or not single:
        # squeeze to the advance width (horizontal only for single characters, keeping the line height)
        full = Image.new("L", (tw + 2, (asc + desc) + 2), 0)
        ImageDraw.Draw(full).text((-box[0] + 1, 1), text, font=f, fill=255)
        if not single:
            full = full.crop((0, box[1], full.width, box[3] + 2))
        sx = min(1.0, aw / max(1, full.width))
        sy = min(1.0, H / max(1, full.height)) if single else min(1.0, H * 0.75 / max(1, full.height))
        full = full.resize((max(1, int(full.width * sx)), max(1, int(full.height * sy))), Image.LANCZOS)
        x0 = (aw - full.width) // 2
        y0 = (H - full.height) // 2 + (SS // 2 if single else SS)
        im.paste(full, (max(0, x0), max(0, y0)))
    else:
        if cell == 8 and f.path.endswith("PressStart2P-Regular.ttf"):
            x0, y0 = (aw - tw) // 2 - box[0], 0
        else:
            x0 = (aw - tw) // 2 - box[0]
            y0 = (H - (asc + desc)) // 2 + SS // 2
        d.text((x0, y0), text, font=f, fill=255)
    a = np.asarray(im.resize((cell, cell), Image.BOX), np.float32) / 255.0
    return a


def font_bytes(cell, chars, widths):
    out = bytearray()
    for i, ch in enumerate(chars):
        if ch == "・" and i != 83:
            a = np.zeros((cell, cell), np.float32)  # unused slots (the table fills them with '・')
        else:
            a = glyph_alpha(ch, cell, widths[i])
        # sharpen the ramp so small text stays crisp: 1-bit core + a soft edge
        lv = np.clip(np.round(np.clip((a - 0.12) / 0.6, 0, 1) * 15), 0, 15).astype(np.uint8)
        for row in lv:
            for x in range(0, cell, 2):
                out.append((row[x] & 0xF) | ((row[x + 1] & 0xF) << 4))
    return bytes(out)


def font_patches():
    chars, widths = char_table()
    return [("rom", FONT_TABLES[c], font_bytes(c, chars, widths[c])) for c in (8, 12)]


def taint_ranges():
    return {f"font{c}": ("rom", FONT_TABLES[c], NGLYPH * c * c // 2) for c in (8, 12)}


def hooks(spec, rom):
    h = {"__bytes__": []}
    h["__bytes__"] += font_patches()
    return h


def preview(out):
    """dev: both fonts as a sheet"""
    from cleanroom.gfx import png
    chars, widths = char_table()
    rows = []
    for c in (8, 12):
        b = font_bytes(c, chars, widths[c])
        cells = []
        for i in range(NGLYPH):
            g = np.frombuffer(b[i * c * c // 2:(i + 1) * c * c // 2], np.uint8)
            px = np.empty(c * c, np.uint8)
            px[0::2], px[1::2] = g & 15, g >> 4
            cells.append(px.reshape(c, c) * 17)
        per = 37
        grid = [np.concatenate(cells[r * per:(r + 1) * per] + [np.zeros((c, c), np.uint8)] *
                               (per - len(cells[r * per:(r + 1) * per])), 1) for r in range(10)]
        rows.append(np.concatenate(grid, 0))
    wmax = max(r.shape[1] for r in rows)
    img = np.concatenate([np.pad(r, ((0, 4), (0, wmax - r.shape[1]))) for r in rows], 0)
    img = np.repeat(np.repeat(img, 3, 0), 3, 1)
    png.write(out, np.stack([img] * 3 + [np.full_like(img, 255)], -1))


if __name__ == "__main__":
    import sys
    preview(sys.argv[1])
