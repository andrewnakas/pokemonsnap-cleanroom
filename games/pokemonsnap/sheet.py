"""Contact sheet of textures listed in a texscan-style json (dirty: from the ROM; clean: from a clean ROM).

    python -m games.pokemonsnap.sheet <rom or tree> <texscan.json> <out.png> [--range A-B] [--space S]
        [--min 0] [--max 400] [--scale 2]

Decodes each texture (CI with its first palette) and packs them in rows with a hex label.
"""
import argparse
import os

import numpy as np

from cleanroom.gfx import png, texfmt

FMTN = {"RGBA": 0, "YUV": 1, "CI": 2, "IA": 3, "I": 4}
SIZN = {4: 0, 8: 1, 16: 2, 32: 3}


def load_spaces(path):
    if os.path.isdir(path):
        from games.pokemonsnap.texscan import VPK
        d = {"rom": open(f"{path}/pokemonsnap.z64", "rb").read()}
        for n in VPK:
            d["vpk0:" + n] = open(f"{path}/assets/{n}.bin", "rb").read()
        return d
    from games.pokemonsnap import romio
    return romio.spaces(open(path, "rb").read())


def palette(spaces, p):
    sp, off, n = p
    raw = spaces[sp][off:off + 2 * n]
    return texfmt.decode(raw, n, 1, 0, 2).reshape(n, 4)


def decode(spaces, t):
    fmt, siz = FMTN[t["fmt"]], SIZN[t["siz"]]
    raw = spaces[t["space"]][t["off"]:t["off"] + texfmt.texel_bytes(t["w"], t["h"], siz)]
    if len(raw) < texfmt.texel_bytes(t["w"], t["h"], siz):
        return None
    pal = None
    if fmt == 2:
        if t.get("pals"):
            pal = palette(spaces, t["pals"][0])
            n = 16 if siz == 0 else 256
            if len(pal) < n:
                pal = np.concatenate([pal, np.zeros((n - len(pal), 4), np.uint8)])
        else:
            pal = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
            if siz == 0:
                pal[:16, :3] *= 17
    return texfmt.decode(raw, t["w"], t["h"], fmt, siz, pal)


def glyph_label(img, x, y, text):
    """tiny 3x5 hex digits"""
    F = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
         "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
         "8": "111101111101111", "9": "111101111001111", "A": "111101111101101", "B": "110101110101110",
         "C": "111100100100111", "D": "110101101101110", "E": "111100111100111", "F": "111100111100100",
         ":": "000010000010000", "-": "000000111000000"}
    for i, ch in enumerate(text):
        f = F.get(ch.upper())
        if not f:
            continue
        for k, b in enumerate(f):
            if b == "1":
                yy, xx = y + k // 3, x + i * 4 + k % 3
                if 0 <= yy < img.shape[0] and 0 <= xx < img.shape[1]:
                    img[yy, xx] = (255, 255, 0, 255)


def sheet(images, width=1600, scale=2):
    x = y = rowh = 0
    pos = []
    for lab, im in images:
        h, w = im.shape[0] * scale, im.shape[1] * scale
        w = min(w, width)
        if x + max(w, len(lab) * 4) > width:
            x, y, rowh = 0, y + rowh + 8, 0
        pos.append((x, y))
        x += max(w, len(lab) * 4) + 4
        rowh = max(rowh, h)
    H = y + rowh + 8
    out = np.zeros((H, width, 4), np.uint8)
    out[..., :3] = 40
    out[..., 3] = 255
    # checker behind
    for (lab, im), (x, y) in zip(images, pos):
        im = np.repeat(np.repeat(im, scale, 0), scale, 1)[:, :width - x]
        h, w = im.shape[:2]
        chk = ((np.indices((h, w)).sum(0) // 8) % 2 * 60 + 90).astype(np.float32)[..., None]
        a = im[..., 3:4].astype(np.float32) / 255
        out[y + 6:y + 6 + h, x:x + w, :3] = (im[..., :3] * a + chk * (1 - a)).astype(np.uint8)
        glyph_label(out, x, y, lab)
    return out


def main():
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("js")
    ap.add_argument("out")
    ap.add_argument("--range", default="")
    ap.add_argument("--space", default="rom")
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--width", type=int, default=1600)
    a = ap.parse_args()
    spaces = load_spaces(a.src)
    js = json.load(open(a.js))
    lo, hi = 0, 1 << 32
    if a.range:
        lo, hi = (int(v, 16) for v in a.range.split("-"))
    imgs = []
    for t in js["tex"]:
        if t["space"] != a.space or not lo <= t["off"] < hi:
            continue
        im = decode(spaces, t)
        if im is not None:
            imgs.append((f"{t['off']:X}", im))
        if len(imgs) >= a.max:
            break
    png.write(a.out, sheet(imgs, a.width, a.scale))
    print(f"{len(imgs)} textures -> {a.out}")


if __name__ == "__main__":
    main()
