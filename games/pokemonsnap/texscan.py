"""Dirty room: find every texture/palette/sprite bitmap in the ROM from the game's own references.

    python -m games.pokemonsnap.texscan <dirty tree> <out.json>

Sources of texture facts (format, size, palette):
  dl      F3DEX2 display lists found anywhere outside code (SETTIMG/SETTILE/LOAD*/SETTILESIZE state machine)
  mat     Texture structs (material animations: image + palette pointer arrays)
  sprite  ultralib Sprite + Bitmap structs (UI, menus, album)
  splat   textures splat already names in splat.yaml
Address spaces: the ROM, plus each decompressed vpk0 blob ("vpk0:<name>").
Pointers are resolved against the segment holding the reference first, then other segments with the
same vram range (same level group preferred). Prints a one-screen summary.
"""
import json
import struct
import sys
from collections import Counter, defaultdict

from games.pokemonsnap.layout import load

CODE_TYPES = {"c", "hasm", "asm", "header", "rodata", ".rodata", "pad"}
TEX_TYPES = {"ci4": ("CI", 4), "ci8": ("CI", 8), "i4": ("I", 4), "i8": ("I", 8), "ia4": ("IA", 4), "ia8": ("IA", 8),
             "ia16": ("IA", 16), "rgba16": ("RGBA", 16), "rgba32": ("RGBA", 32)}
FMT = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
SIZ = {0: 4, 1: 8, 2: 16, 3: 32}
VPK = {"main_menu_vpk0": 0x802B5000, "intro_code_vpk0": 0x802B5000, "unk_segment_AA18E0_vpk0": 0x802B5000}
# valid F3DEX2 opcodes (for display-list validation)
OPS = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0xD7, 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF,
       0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xF0, 0xF1,
       0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF}


class Spaces:
    def __init__(self, tree):
        self.tree = tree
        self.ents = load(tree)
        self.data = {"rom": open(f"{tree}/pokemonsnap.z64", "rb").read()}
        for n in VPK:
            self.data["vpk0:" + n] = open(f"{tree}/assets/{n}.bin", "rb").read()
        # top-level segments: (space, start, end, vram, name)
        segs = {}
        for e in self.ents:
            s = e["seg"] or e["name"]
            if e.get("vram") is None:
                continue
            base = e["vram"] - e["start"]
            if s not in segs:
                segs[s] = ["rom", e["start"], e["end"], base, s]
            else:
                segs[s][2] = max(segs[s][2], e["end"])
        self.segs = [tuple(v) for v in segs.values()]
        for n, v in VPK.items():
            self.segs.append(("vpk0:" + n, 0, len(self.data["vpk0:" + n]), v, n))
        # ROM type per offset (for code exclusion)
        self.kind = []
        for e in self.ents:
            self.kind.append((e["start"], e["end"], e["type"], e))

    def seg_of(self, space, off):
        for s in self.segs:
            if s[0] == space and s[1] <= off < s[2]:
                return s
        return None

    def type_at(self, space, off):
        if space != "rom":
            return "vpk0"
        lo, hi = 0, len(self.kind) - 1
        while lo <= hi:
            m = (lo + hi) // 2
            a, b, t, _ = self.kind[m]
            if off < a:
                hi = m - 1
            elif off >= b:
                lo = m + 1
            else:
                return t
        return None

    def resolve(self, addr, ctx):
        """vram address -> (space, off) using the context segment first."""
        if ctx and ctx[3] + ctx[1] <= addr < ctx[3] + ctx[2]:
            return ctx[0], addr - ctx[3]
        cands = [s for s in self.segs if s[3] + s[1] <= addr < s[3] + s[2]]
        if not cands:
            return None
        if len(cands) > 1 and ctx:
            pre = ctx[4].split("_")[0]
            same = [s for s in cands if s[4].split("_")[0] == pre]
            if same:
                cands = same
        s = cands[0]
        return s[0], addr - s[3]


def be32(b, o):
    return struct.unpack_from(">I", b, o)[0]


class Found:
    def __init__(self):
        self.tex = {}  # (space, off) -> dict
        self.pal = {}
        self.amb = 0
        self.sprites = {}
        self.bitmaps = {}  # (space, Bitmap struct offset) -> (fmt, siz, pal, ctx)

    PRI = {"splat": 3, "mat": 2, "sprite": 2, "dl": 2, "guess": 0}

    def add_tex(self, key, fmt, siz, w, h, src, pal=None):
        t = self.tex.get(key)
        rec = {"fmt": fmt, "siz": siz, "w": w, "h": h, "pri": self.PRI[src]}
        if t is None:
            t = self.tex[key] = dict(rec, src=[], refs=0, pals=[])
        elif (t["fmt"], t["siz"], t["w"], t["h"]) != (fmt, siz, w, h):
            if rec["pri"] > t["pri"] or (rec["pri"] == t["pri"] and w * h * siz > t["w"] * t["h"] * t["siz"]):
                if t["pri"] > 0:
                    t.setdefault("alts", []).append([t["fmt"], t["siz"], t["w"], t["h"]])
                t.update(rec)
            elif rec["pri"] > 0 and [fmt, siz, w, h] not in t.get("alts", []):
                t.setdefault("alts", []).append([fmt, siz, w, h])
        if src not in t["src"]:
            t["src"].append(src)
        t["refs"] += 1
        if pal and list(pal) not in t["pals"]:
            t["pals"].append(list(pal))

    def add_pal(self, key, n, src):
        p = self.pal.get(key)
        if p is None or p["n"] < n:
            self.pal[key] = {"n": n, "src": src}


def scan_dl(sp, found):
    """Linear pass over non-code data: runs of valid F3DEX2 commands are simulated with tile state carried
    across consecutive display lists (HAL models set tiles in a shared `first` list)."""
    nlist = 0
    for space, blob in sp.data.items():
        n = len(blob)
        st = None
        for o in range(0, n - 8, 8):
            op = blob[o]
            if op not in OPS or (space == "rom" and sp.type_at(space, o) in CODE_TYPES):
                if st:
                    _flush(sp, found, st["ctx"], st["loads"], st["tiles"], st["pal"])
                st = None
                continue
            w0, w1 = struct.unpack_from(">II", blob, o)
            if st is None:
                if op != 0xFD and op != 0xF5 and op != 0xE7:
                    continue
                ctx = sp.seg_of(space, o)
                if ctx is None:
                    continue
                st = {"ctx": ctx, "tiles": defaultdict(dict), "timg": None, "loads": [], "pal": None}
            if not _step(sp, found, st, op, w0, w1):
                _flush(sp, found, st["ctx"], st["loads"], st["tiles"], st["pal"])
                st = None
            elif op == 0xFD:
                nlist += 1
    return nlist


def _step(sp, found, st, op, w0, w1):
    tiles, ctx = st["tiles"], st["ctx"]
    if op == 0xFD:
        if not (0x80000000 <= w1 < 0x80800000):
            return False
        st["timg"] = (FMT.get((w0 >> 21) & 7, "?"), SIZ[(w0 >> 19) & 3], (w0 & 0xFFF) + 1, w1)
    elif op == 0xF5:
        t = (w1 >> 24) & 7
        tiles[t].update(fmt=FMT.get((w0 >> 21) & 7, "?"), siz=SIZ[(w0 >> 19) & 3], line=(w0 >> 9) & 0x1FF,
                        tmem=w0 & 0x1FF, pal=(w1 >> 20) & 0xF)
    elif op == 0xF2:
        t = (w1 >> 24) & 7
        uls, ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
        lrs, lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
        if lrs < uls or lrt < ult:
            return True
        tiles[t].update(w=(lrs - uls) // 4 + 1, h=(lrt - ult) // 4 + 1)
    elif op in (0x01, 0x05, 0x06, 0x07, 0xDE, 0xDF, 0xE4):
        _flush(sp, found, ctx, st["loads"], tiles, st["pal"])
    elif op == 0xF3 and st["timg"]:
        timg = st["timg"]
        t = (w1 >> 24) & 7
        texels = ((w1 >> 12) & 0xFFF) + 1
        dxt = w1 & 0xFFF
        st["loads"].append(dict(addr=timg[3], lfmt=timg[0], lsiz=timg[1], bytes=texels * timg[1] // 8, dxt=dxt,
                                rowbytes=round(16384 / dxt) if dxt else 0,
                                tmem=tiles[t].get("tmem", 0), kind="block"))
    elif op == 0xF4 and st["timg"]:
        timg = st["timg"]
        t = (w1 >> 24) & 7
        lrt = w1 & 0xFFF
        rows = lrt // 4 + 1
        st["loads"].append(dict(addr=timg[3], lfmt=timg[0], lsiz=timg[1], bytes=timg[2] * rows * timg[1] // 8,
                                tmem=tiles[t].get("tmem", 0), kind="tile", imgw=timg[2], rows=rows))
    elif op == 0xF0 and st["timg"]:
        cnt = ((w1 >> 14) & 0x3FF) + 1
        r = sp.resolve(st["timg"][3], ctx)
        if r:
            found.add_pal(r, cnt, "dl")
            st["pal"] = (r[0], r[1], cnt)
    return True


def _flush(sp, found, ctx, loads, tiles, pal):
    """commit pending loads against the render tile (0..6, not the load tile 7) sharing their tmem"""
    for ld in loads:
        tl = None
        for t in range(7):
            c = tiles.get(t)
            if c and c.get("tmem") == ld["tmem"] and "w" in c and t != 5:
                tl = c
                break
        _commit(sp, found, ctx, ld, tl, pal)
    loads.clear()


def _commit(sp, found, ctx, ld, tl, pal):
    r = sp.resolve(ld["addr"], ctx)
    if r is None:
        return
    if ld["tmem"] >= 0x100 and ld["lfmt"] == "RGBA" and ld["lsiz"] == 16:
        found.add_pal(r, ld["bytes"] // 2, "dl")
        return
    if tl and "w" in tl:
        fmt, siz, w, h = tl["fmt"], tl["siz"], tl["w"], tl["h"]
        if ld["kind"] == "tile":
            w = ld["imgw"] * ld["lsiz"] // siz
            h = max(h, ld["rows"])
        elif ld.get("rowbytes"):
            rb = ld["rowbytes"]
            # dxt gives the row size in bytes (rounded to 8): trust it over a stale tile size
            if not (w * siz // 8 <= rb < w * siz // 8 + 8):
                w = rb * 8 // siz
            h = max(1, ld["bytes"] // max(1, w * siz // 8))
        elif w * h * siz // 8 != ld["bytes"] and w * siz // 8:
            h = max(1, ld["bytes"] * 8 // (w * siz))
    else:
        fmt, siz = ld["lfmt"], ld["lsiz"]
        w, h = (ld.get("imgw") or 0), (ld.get("rows") or 0)
        if not w:
            w, h = ld["bytes"] * 8 // siz, 1
        found.add_tex(r, fmt, siz, w, h, "guess", pal if fmt == "CI" else None)
        return
    found.add_tex(r, fmt, siz, w, h, "dl", pal if fmt == "CI" else None)


def scan_mat(sp, found):
    """Texture structs (sys/render.c): palette depth(0x03) images**(0x04) palettes**(0x2C) flags(0x30)
    load fmt/siz (0x32/0x33) block w/h (0x34/0x36). Images are LoadBlock'ed at fmt/siz, blockWidth x blockHeight."""
    n = 0
    for space, blob in sp.data.items():
        for o in range(0, len(blob) - 0x78, 4):
            if blob[o] != 0 or blob[o + 1] != 0:
                continue
            pbd = blob[o + 3]
            fmt, siz = blob[o + 0x32], blob[o + 0x33]
            if blob[o + 2] > 4 or pbd > 3 or fmt > 4 or siz > 3:
                continue
            imgs = be32(blob, o + 4)
            w, h = struct.unpack_from(">HH", blob, o + 0x34)
            if not (0x80000000 <= imgs < 0x80800000) or not (1 <= w <= 512 and 1 <= h <= 512):
                continue
            if space == "rom" and sp.type_at(space, o) in CODE_TYPES:
                continue
            fs, ft = struct.unpack_from(">ff", blob, o + 0x1C)
            if not (0 <= fs < 64 and 0 <= ft < 64):
                continue
            ctx = sp.seg_of(space, o)
            if ctx is None:
                continue
            ra = sp.resolve(imgs, ctx)
            if ra is None:
                continue
            ptrs = _ptr_array(sp, ra, ctx)
            if not ptrs:
                continue
            pals = be32(blob, o + 0x2C)
            ppt = []
            npal = 256 if pbd == 1 else 16
            if 0x80000000 <= pals < 0x80800000:
                rp = sp.resolve(pals, ctx)
                if rp:
                    ppt = _ptr_array(sp, rp, ctx)
            n += 1
            for p in ppt:
                found.add_pal(p, npal, "mat")
            for p in ptrs:
                found.add_tex(p, FMT[fmt], SIZ[siz], w, h, "mat", (ppt[0][0], ppt[0][1], npal) if ppt else None)
    return n


def _ptr_array(sp, r, ctx, maxn=64):
    blob = sp.data[r[0]]
    out = []
    o = r[1]
    while len(out) < maxn and o + 4 <= len(blob):
        v = be32(blob, o)
        if not (0x80000000 <= v < 0x80800000):
            break
        rr = sp.resolve(v, ctx)
        if rr is None:
            break
        out.append(rr)
        o += 4
    return out


def scan_sprites(sp, found):
    """ultralib Sprite (0x44): scalex/scaley f32 at 0x08, bmfmt/bmsiz at 0x30, Bitmap* at 0x34, LUT* at 0x20."""
    n = 0
    for space, blob in sp.data.items():
        for o in range(0, len(blob) - 0x44, 4):
            sx, sy = struct.unpack_from(">ff", blob, o + 8)
            if not (0.01 <= sx <= 64 and 0.01 <= sy <= 64):
                continue
            bmfmt, bmsiz = blob[o + 0x30], blob[o + 0x31]
            if bmfmt > 4 or bmsiz > 3:
                continue
            bmp = be32(blob, o + 0x34)
            if not (0x80000000 <= bmp < 0x80800000):
                continue
            nbm = struct.unpack_from(">h", blob, o + 0x28)[0]
            if not 1 <= nbm <= 256:
                continue
            width, height = struct.unpack_from(">hh", blob, o + 4)
            if not (1 <= width <= 1024 and 1 <= height <= 1024):
                continue
            if space == "rom" and sp.type_at(space, o) in CODE_TYPES:
                continue
            ctx = sp.seg_of(space, o)
            if ctx is None:
                continue
            rb = sp.resolve(bmp, ctx)
            if rb is None:
                continue
            bmh = struct.unpack_from(">h", blob, o + 0x2C)[0]
            lut = be32(blob, o + 0x20)
            ntl = struct.unpack_from(">h", blob, o + 0x1E)[0]
            pal = None
            if bmfmt == 2 and 0x80000000 <= lut < 0x80800000:
                rl = sp.resolve(lut, ctx)
                if rl:
                    cnt = ntl if ntl > 0 else (16 if bmsiz == 0 else 256)
                    found.add_pal(rl, cnt, "sprite")
                    pal = (rl[0], rl[1], cnt)
            bblob = sp.data[rb[0]]
            ok = 0
            grp = {"w": width, "h": height, "fmt": FMT[bmfmt], "siz": SIZ[bmsiz], "bmh": bmh, "pal": pal,
                   "bitmaps": []}
            for i in range(nbm):
                bo = rb[1] + 16 * i
                if bo + 16 > len(bblob):
                    break
                bw, bwi, bs, bt = struct.unpack_from(">hhhh", bblob, bo)
                buf = be32(bblob, bo + 8)
                ah, luto = struct.unpack_from(">hh", bblob, bo + 12)
                if not (0x80000000 <= buf < 0x80800000) or not (1 <= bwi <= 1024):
                    continue
                rows = ah if ah > 0 else bmh
                if not 1 <= rows <= 1024:
                    continue
                rr = sp.resolve(buf, ctx)
                if rr is None:
                    continue
                found.add_tex(rr, FMT[bmfmt], SIZ[bmsiz], bwi, rows, "sprite", pal)
                found.bitmaps[(rb[0], bo)] = (FMT[bmfmt], SIZ[bmsiz], pal, ctx)
                grp["bitmaps"].append([rr[0], rr[1], bw, bwi, rows, bs, bt])
                ok += 1
            if ok:
                n += 1
                found.sprites[(space, o)] = grp
    return n


def _bitmap_at(sp, space, bo, ctx):
    blob = sp.data[space]
    if bo < 0 or bo + 16 > len(blob):
        return None
    bw, bwi, bs, bt = struct.unpack_from(">hhhh", blob, bo)
    buf = be32(blob, bo + 8)
    ah, luto = struct.unpack_from(">hh", blob, bo + 12)
    if not (1 <= bw <= 1024 and bw <= bwi <= 1024 and 0 <= bs < bwi and 0 <= bt < 1024 and 1 <= ah <= 1024):
        return None
    if not (0x80000000 <= buf < 0x80800000):
        return None
    rr = sp.resolve(buf, ctx)
    if rr is None or (rr[0] == "rom" and sp.type_at("rom", rr[1]) in CODE_TYPES):
        return None
    return rr, bwi, ah


def scan_bitmap_families(sp, found):
    """animation frames: Bitmaps the code swaps into a sprite. Found as (a) neighbours of a known Bitmap with the
    same width/width_img/height, (b) entries of Bitmap* arrays that contain a known Bitmap."""
    n = 0
    known = dict(found.bitmaps)
    for (space, bo), (fmt, siz, pal, ctx) in known.items():
        blob = sp.data[space]
        ref = struct.unpack_from(">hhhh", blob, bo)[:2] + struct.unpack_from(">h", blob, bo + 12)
        for step in (16, -16):
            q = bo + step
            while True:
                b = _bitmap_at(sp, space, q, ctx)
                if b is None:
                    break
                cur = struct.unpack_from(">hh", blob, q)[:2] + struct.unpack_from(">h", blob, q + 12)
                if cur != ref:
                    break
                if (space, q) not in found.bitmaps:
                    found.bitmaps[(space, q)] = (fmt, siz, pal, ctx)
                    found.add_tex(b[0], fmt, siz, b[1], b[2], "sprite", pal)
                    n += 1
                q += step
    # pointer arrays
    vaddr = {}
    for (space, bo), v in found.bitmaps.items():
        ctx = v[3]
        if ctx[0] == space:
            vaddr[ctx[3] + bo] = (space, bo, v)
    for space, blob in sp.data.items():
        for o in range(0, len(blob) - 4, 4):
            w = be32(blob, o)
            if w not in vaddr:
                continue
            _, _, (fmt, siz, pal, ctx) = vaddr[w]
            q = o - 4
            while q >= 0 and 0x80000000 <= be32(blob, q) < 0x80800000:
                q -= 4
            q += 4
            while q + 4 <= len(blob):
                v = be32(blob, q)
                if not (0x80000000 <= v < 0x80800000):
                    break
                r = sp.resolve(v, ctx)
                if r is None:
                    break
                b = _bitmap_at(sp, r[0], r[1], ctx)
                if b is None:
                    break
                if (r[0], r[1]) not in found.bitmaps:
                    found.bitmaps[(r[0], r[1])] = (fmt, siz, pal, ctx)
                    found.add_tex(b[0], fmt, siz, b[1], b[2], "sprite", pal)
                    n += 1
                q += 4
    return n


def scan_splat(sp, found):
    n = 0
    for e in sp.ents:
        if e["type"] in TEX_TYPES:
            fmt, siz = TEX_TYPES[e["type"]]
            w = e.get("width") or (e.get("args") or [0, 0])[0]
            h = e.get("height") or (e.get("args") or [0, 0])[1]
            if w and h:
                found.add_tex(("rom", e["start"]), fmt, siz, w, h, "splat")
                n += 1
        elif e["type"] == "palette":
            size = e.get("size") or (e["end"] - e["start"])
            found.add_pal(("rom", e["start"]), size // 2, "splat")
    return n


def attach_palettes(f):
    """CI textures with no palette reference: use a palette stored right after or right before the image."""
    by = defaultdict(list)
    for (sp, off), p in f.pal.items():
        by[sp].append((off, off + 2 * p["n"], p["n"]))
    n = 0
    for (sp, off), t in f.tex.items():
        if t["fmt"] != "CI" or t["pals"]:
            continue
        end = off + t["w"] * t["h"] * t["siz"] // 8
        best = None
        for a, b, cnt in by[sp]:
            d = a - end if a >= end else (off - b if b <= off else None)
            if d is not None and d <= 16 and (best is None or d < best[0]):
                best = (d, a, cnt)
        if best:
            t["pals"].append([sp, best[1], best[2]])
            t["pal_near"] = True
            n += 1
    return n


def main(argv):
    sp = Spaces(argv[1])
    f = Found()
    c = {"splat": scan_splat(sp, f), "dl": scan_dl(sp, f), "mat": scan_mat(sp, f), "sprite": scan_sprites(sp, f)}
    c["bitmap_family"] = scan_bitmap_families(sp, f)
    c["pal_near"] = attach_palettes(f)
    print("references:", c)
    src = Counter("+".join(sorted(t["src"])) for t in f.tex.values())
    print("textures:", len(f.tex), dict(src))
    print("palettes:", len(f.pal))
    byt = sum(t["w"] * t["h"] * t["siz"] // 8 for t in f.tex.values())
    print(f"texture bytes: {byt / 1024:.0f} KB; with size conflicts: {sum(1 for t in f.tex.values() if 'alts' in t)}")
    out = {"tex": [dict(space=k[0], off=k[1], **v) for k, v in sorted(f.tex.items())],
           "pal": [dict(space=k[0], off=k[1], **v) for k, v in sorted(f.pal.items())],
           "sprites": [dict(space=k[0], off=k[1], **v) for k, v in sorted(f.sprites.items())]}
    json.dump(out, open(argv[2], "w"), indent=0)


if __name__ == "__main__":
    main(sys.argv)
