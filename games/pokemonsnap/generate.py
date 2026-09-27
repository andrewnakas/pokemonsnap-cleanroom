"""Clean room: spec/ + the decomp's kept code/data -> clean ROM.

    python -m games.pokemonsnap.generate <rom (kept code source)> games/pokemonsnap/spec <out.z64>

Every texture, palette and UI picture range listed in spec/ is regenerated in place (same format and size), so the
decomp's layout (code, geometry, animation, text, note sequences) is unchanged. Picture sources, in order:
  1. colour grid + our own noise detail + kept 2-bit alpha (every range),
  2. sprite composites (UI pictures generated whole, then cut into the game's bitmap strips),
  3. drawn overrides (fonts, text-bearing textures, faces, pictures) from `hooks`.
CI textures sharing a palette are generated together and re-indexed against one new palette.
vpk0 blobs are recompressed into their slots; the header checksum (CIC-6103) is recomputed.
"""
import json
import sys
from collections import defaultdict

import numpy as np

from cleanroom.decomp.gen import detail, h32, unpack_alpha2, upsample_grid
from cleanroom.gfx import texfmt
from games.pokemonsnap import romio

FMTN = {"RGBA": 0, "YUV": 1, "CI": 2, "IA": 3, "I": 4}
SIZN = {4: 0, 8: 1, 16: 2, 32: 3}


def from_grid(key, d, w, h, amount=None):
    n = int(round(len(d["grid"]) ** 0.5))
    if key.startswith("vpk0") or key.startswith("sprite:vpk0"):
        # compressed blobs must fit their slots: flat cells (posterised), no noise
        g = (np.asarray(d["grid"], np.float32).reshape(n, n, 4) // 8) * 8
        ys = np.minimum(np.arange(h) * n // max(1, h), n - 1)
        xs = np.minimum(np.arange(w) * n // max(1, w), n - 1)
        rgba = g[ys][:, xs].copy()
        rgba[..., 3] = unpack_alpha2(d["alpha2"], w, h) if "alpha2" in d else 255
        return np.clip(rgba, 0, 255).astype(np.uint8)
    rgba = upsample_grid(d["grid"], n, w, h)
    amt = amount if amount is not None else (0.03 if n > 4 else 0.07)
    if key.startswith("vpk0") or key.startswith("sprite:vpk0"):
        amt = min(amt, 0.01)  # compressed blobs must fit their slots
    rgba[..., :3] *= detail(h32("detail", key), w, h, amt, 4.0 if n == 4 else 8.0)[..., None]
    rgba[..., 3] = unpack_alpha2(d["alpha2"], w, h) if "alpha2" in d else 255
    return np.clip(rgba, 0, 255).astype(np.uint8)


def quantize(pixels, k, seed):
    """k-means palette (deterministic init from luminance quantiles) -> (k,3) float"""
    px = pixels.astype(np.float32)
    if len(px) == 0:
        return np.zeros((k, 3), np.float32)
    rng = np.random.default_rng(seed)
    if len(px) > 20000:
        px = px[rng.choice(len(px), 20000, replace=False)]
    lum = px @ np.array([0.299, 0.587, 0.114], np.float32)
    order = np.argsort(lum)
    cent = px[order[np.linspace(0, len(px) - 1, k).astype(int)]].copy()
    for _ in range(8):
        d = ((px[:, None, :] - cent[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                cent[j] = px[m].mean(0)
    return cent


def index(rgba, cent, clear_idx, seed=0):
    px = rgba[..., :3].reshape(-1, 3).astype(np.float32)
    d = ((px[:, None, :] - cent[None]) ** 2).sum(-1)
    idx = d.argmin(1)
    if len(cent) > 1:
        # ordered-ish dither: some pixels take the second-nearest colour when it is nearly as close
        o = np.argsort(d, 1)
        d1, d2 = d[np.arange(len(d)), o[:, 0]], d[np.arange(len(d)), o[:, 1]]
        rng = np.random.default_rng(seed)
        swap = (rng.random(len(d)) < 0.2) & (d2 <= 4 * d1 + 300)
        idx = np.where(swap, o[:, 1], idx)
    if clear_idx is not None:
        idx = np.where(idx >= clear_idx, idx + 1, idx)  # skip the transparent slot
        idx[rgba[..., 3].reshape(-1) < 128] = clear_idx
    return idx.reshape(rgba.shape[:2]).astype(np.uint8)


STEP = {("RGBA", 16): 8, ("RGBA", 32): 1, ("IA", 16): 1, ("IA", 8): 16, ("IA", 4): 32, ("I", 8): 1, ("I", 4): 16}


def dither(rgba, fmt, siz, seed, steps=1):
    """+-steps of the format's colour precision: flat areas never repeat retail runs exactly"""
    st = STEP.get((fmt, siz), 1)
    if isinstance(seed, tuple):
        return rgba
    rng = np.random.default_rng(seed)
    d = rng.integers(-steps, steps + 1, size=rgba.shape[:2] + (3,)) * st
    out = rgba.astype(np.int32)
    out[..., :3] += d
    return np.clip(out, 0, 255).astype(np.uint8)


def pal_bytes(rgba_n):
    return texfmt.encode(rgba_n.reshape(1, -1, 4), 0, 2)


class Image:
    def __init__(self, rom):
        self.sp = {k: bytearray(v) for k, v in romio.spaces(rom).items()}
        self.written = 0

    def put(self, space, off, data):
        self.sp[space][off:off + len(data)] = data
        self.written += len(data)


def reseed():
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spec", "reseed.json")
    return set(json.load(open(p))) if os.path.exists(p) else set()


def gen_textures(img, texs, pals, hooks):
    """pass 1: every texture range; CI textures grouped by palette"""
    rs = reseed()
    ci_groups = defaultdict(list)
    for t in texs:
        key = f"{t['space']}:{t['off']:X}"
        rgba = hooks.get(key) if hooks else None
        if rgba is None:
            rgba = from_grid(key, t, t["w"], t["h"])
        if t["fmt"] == "CI":
            ci_groups[tuple(t["pal"]) if "pal" in t else None].append((t, rgba))
            continue
        rgba = dither(rgba, t["fmt"], t["siz"], () if t["space"] != "rom" else h32("dither", key, key in rs),
                      steps=2 if key in rs else 1)
        img.put(t["space"], t["off"], texfmt.encode(rgba, FMTN[t["fmt"]], SIZN[t["siz"]]))
    done_pals = set()
    for pk, members in ci_groups.items():
        if pk is None:
            # palette unknown: indices from luminance (the game's palette colours them)
            for t, rgba in members:
                n = 16 if t["siz"] == 4 else 256
                lum = rgba[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
                idx = np.clip(lum / 256 * n, 0, n - 1).astype(np.uint8)
                img.put(t["space"], t["off"], texfmt.encode(np.stack([idx] * 4, -1), 2, SIZN[t["siz"]]))
            continue
        sp, off, cnt = pk
        n = cnt
        allpx = np.concatenate([r.reshape(-1, 4) for _, r in members])
        need_clear = (allpx[:, 3] < 128).any()
        k = max(1, n - (1 if need_clear else 0))
        cent = quantize(allpx[allpx[:, 3] >= 128][:, :3], k, h32("pal", sp, off))
        clear_idx = 0 if need_clear else None
        pal = np.zeros((n, 4), np.uint8)
        if need_clear:
            pal[0] = (0, 0, 0, 0)
            pal[1:1 + k, :3] = np.clip(cent, 0, 255)
            pal[1:1 + k, 3] = 255
        else:
            pal[:k, :3] = np.clip(cent, 0, 255)
            pal[:k, 3] = 255
        salt = any(f"{t['space']}:{t['off']:X}" in rs for t, _ in members)
        pal = dither(pal.reshape(1, n, 4), "RGBA", 16, h32("pald", sp, off, salt), steps=3 if salt else 2).reshape(n, 4)
        img.put(sp, off, pal_bytes(pal))
        done_pals.add((sp, off))
        for t, rgba in members:
            idx = index(rgba, cent, clear_idx, h32("idx", t["space"], t["off"]) if t["space"] == "rom" else 0)
            if t["siz"] == 4:
                idx = np.minimum(idx, 15)
            img.put(t["space"], t["off"], texfmt.encode(np.stack([idx] * 4, -1), 2, SIZN[t["siz"]]))
    # palettes no texture of ours used: coarse colours spread over the entries, transparency mask kept
    for p in pals:
        if (p["space"], p["off"]) in done_pals:
            continue
        n = p["n"]
        co = np.asarray(p["coarse"], np.float32)
        xs = np.linspace(0, len(co) - 1, n)
        rgb = np.stack([np.interp(xs, np.arange(len(co)), co[:, c]) for c in range(3)], -1)
        rgb *= detail(h32("palx", p["off"]), n, 1, 0.05, 2.0).reshape(n, 1)
        a = np.array([0 if c == "1" else 255 for c in p["clear"]], np.float32)
        out = np.concatenate([np.clip(rgb, 0, 255), a[:, None]], -1).astype(np.uint8)
        img.put(p["space"], p["off"], pal_bytes(out))


def gen_sprites(img, sprites, texs, hooks):
    """pass 2: UI pictures generated whole and cut into bitmap strips (non-CI only)"""
    tfmt = {(t["space"], t["off"]): t for t in texs}
    n = 0
    for s in sprites:
        key = f"sprite:{s['space']}:{s['off']:X}"
        comp = hooks.get(key) if hooks else None
        if comp is None:
            comp = from_grid(key, s, s["w"], s["h"], amount=0.02)
        for sp, off, bw, bwi, rows, bs, bt, x, y in s["bitmaps"]:
            t = tfmt.get((sp, off))
            if t is None or t["fmt"] == "CI":
                continue
            buf = from_grid(f"{sp}:{off:X}", t, t["w"], t["h"], amount=0.02)
            rh = s["bmh"] if s["bmh"] > 0 else rows
            part = comp[y:y + rh, x:x + bw]
            ph, pw = min(part.shape[0], t["h"] - bt), min(part.shape[1], t["w"] - bs)
            if ph > 0 and pw > 0:
                buf[bt:bt + ph, bs:bs + pw] = part[:ph, :pw]
            buf = dither(buf, t["fmt"], t["siz"], () if sp != "rom" else h32("dither", sp, off))
            img.put(sp, off, texfmt.encode(buf, FMTN[t["fmt"]], SIZN[t["siz"]]))
        n += 1
    return n


def audio_patches(rom):
    """audio depends only on spec/audio.json and overrides/sounds: cache the result"""
    import hashlib
    import os
    import pickle
    from games.pokemonsnap import audio
    h = hashlib.sha1(open(audio.SPEC, "rb").read())
    for root, _, files in os.walk(audio.OVR):
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(p.encode() + str(os.path.getmtime(p)).encode())
    cache = f"D:/n64work/pokemonsnap/cache/audio_{h.hexdigest()[:12]}.pkl"
    if os.path.exists(cache):
        return pickle.load(open(cache, "rb"))
    out = audio.patches(rom)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    pickle.dump(out, open(cache, "wb"))
    return out


def main(argv):
    rom = open(argv[1], "rb").read()
    spec = argv[2]
    texs = json.load(open(f"{spec}/textures.json"))
    pals = json.load(open(f"{spec}/palettes.json"))
    sprites = json.load(open(f"{spec}/sprites.json"))
    hooks = {}
    try:
        from games.pokemonsnap import drawn
        hooks = drawn.hooks(spec, rom)
    except ImportError:
        pass
    img = Image(rom)
    gen_textures(img, texs, pals, hooks)
    ns = gen_sprites(img, sprites, texs, hooks)
    for extra in (hooks.get("__bytes__") or []):
        img.put(*extra)
    if "--no-audio" not in argv:
        for extra in audio_patches(rom):
            img.put(*extra)
    out = romio.pack(img.sp)
    romio.fix_crc(out, 6103)
    open(argv[3], "wb").write(out)
    print(f"clean ROM -> {argv[3]}: {len(texs)} textures, {len(pals)} palettes, {ns} sprite pictures, "
          f"{len([k for k in hooks if not k.startswith('__')])} drawn, {img.written / 1024:.0f} KB written")


if __name__ == "__main__":
    main(sys.argv)
