"""Dirty room: ROM + texscan.json -> spec/ (facts only: format, size, colour grid, 2-bit alpha outline).

    python -m games.pokemonsnap.extract_spec <dirty tree> <texscan.json> games/pokemonsnap/spec

spec/textures.json  one entry per texture range: space, off, fmt, siz, w, h, grid, alpha2, pal (CI)
spec/sprites.json   sprite composites: w, h, bitmap layout, grid, alpha2 (UI pictures)
spec/palettes.json  every palette range: n, alpha mask (which entries are transparent), coarse colours (8)
No pixel data leaves the dirty room: grids are block means (4x4, 16x16 for >= 128 px).
"""
import json
import os
import sys

import numpy as np

from cleanroom.decomp.spec import alpha2, grid
from cleanroom.gfx import texfmt
from games.pokemonsnap.sheet import FMTN, SIZN, load_spaces


def grid_n(w, h):
    return 16 if max(w, h) >= 128 else 4


def pal_rgba(spaces, sp, off, n):
    raw = spaces[sp][off:off + 2 * n]
    return texfmt.decode(raw, n, 1, 0, 2).reshape(n, 4)


def decode(spaces, t):
    fmt, siz = FMTN[t["fmt"]], SIZN[t["siz"]]
    nb = texfmt.texel_bytes(t["w"], t["h"], siz)
    raw = spaces[t["space"]][t["off"]:t["off"] + nb]
    if len(raw) < nb:
        return None
    pal = None
    if fmt == 2:
        n = 16 if siz == 0 else 256
        if t.get("pals"):
            sp, off, cnt = t["pals"][0]
            pal = pal_rgba(spaces, sp, off, min(cnt, n))
            if len(pal) < n:
                pal = np.concatenate([pal, np.zeros((n - len(pal), 4), np.uint8)])
        else:
            pal = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
            pal[:, :3] = pal[:, :3] * (17 if siz == 0 else 1)
    return texfmt.decode(raw, t["w"], t["h"], fmt, siz, pal)


def fact(rgba):
    h, w = rgba.shape[:2]
    d = {"grid": grid(rgba, grid_n(w, h))}
    if (rgba[..., 3] < 250).any():
        d["alpha2"] = alpha2(rgba[..., 3])
    return d


def composite(spaces, s, tex_by_key):
    """paste the sprite's bitmaps in draw order (ultralib spDraw: left to right, wrap at sprite width)"""
    W, H = s["w"], s["h"]
    img = np.zeros((H, W, 4), np.uint8)
    x = y = 0
    rowh = s["bmh"] if s["bmh"] > 0 else 0
    place = []
    for sp, off, bw, bwi, rows, bs, bt in s["bitmaps"]:
        t = tex_by_key.get((sp, off))
        rh = rowh or rows
        if t is not None:
            im = decode(spaces, t)
            if im is not None:
                part = im[bt:bt + rh, bs:bs + bw]
                ph, pw = min(part.shape[0], H - y), min(part.shape[1], W - x)
                if ph > 0 and pw > 0:
                    img[y:y + ph, x:x + pw] = part[:ph, :pw]
        place.append([x, y])
        x += bw
        if x >= W:
            x, y = 0, y + rh
    return img, place


def main(argv):
    tree, js, out = argv[1], json.load(open(argv[2])), argv[3]
    os.makedirs(out, exist_ok=True)
    spaces = load_spaces(tree)
    tex_by_key = {(t["space"], t["off"]): t for t in js["tex"]}
    texs = []
    nopal = 0
    for t in js["tex"]:
        im = decode(spaces, t)
        if im is None:
            continue
        e = {k: t[k] for k in ("space", "off", "fmt", "siz", "w", "h")}
        if t["fmt"] == "CI":
            if t.get("pals"):
                e["pal"] = t["pals"][0]
            else:
                nopal += 1
        e.update(fact(im))
        texs.append(e)
    sprites = []
    for s in js["sprites"]:
        img, place = composite(spaces, s, tex_by_key)
        e = {"space": s["space"], "off": s["off"], "w": s["w"], "h": s["h"], "bmh": s["bmh"],
             "bitmaps": [[b[0], b[1], b[2], b[3], b[4], b[5], b[6], p[0], p[1]] for b, p in zip(s["bitmaps"], place)]}
        e.update(fact(img))
        sprites.append(e)
    pals = []
    for p in js["pal"]:
        rgba = pal_rgba(spaces, p["space"], p["off"], p["n"])
        k = 8 if p["n"] >= 8 else p["n"]
        groups = np.array_split(rgba[:, :3].astype(np.float32), k)
        pals.append({"space": p["space"], "off": p["off"], "n": p["n"],
                     "clear": "".join("1" if a < 128 else "0" for a in rgba[:, 3]),
                     "coarse": [[int(round(v)) for v in g.mean(0)] for g in groups]})
    json.dump(texs, open(f"{out}/textures.json", "w"), separators=(",", ":"))
    json.dump(sprites, open(f"{out}/sprites.json", "w"), separators=(",", ":"))
    json.dump(pals, open(f"{out}/palettes.json", "w"), separators=(",", ":"))
    print(f"spec: {len(texs)} textures ({nopal} CI without a known palette), {len(sprites)} sprites, "
          f"{len(pals)} palettes -> {out}")


if __name__ == "__main__":
    main(sys.argv)
