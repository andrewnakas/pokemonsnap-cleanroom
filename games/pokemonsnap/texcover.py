"""Dirty room: coverage/overlap report for texscan.json.

    python -m games.pokemonsnap.texcover <dirty tree> <texscan.json> [--bins]
"""
import json
import sys
from collections import defaultdict

from games.pokemonsnap.layout import load
from games.pokemonsnap.texscan import CODE_TYPES


def ranges(js):
    out = []
    for t in js["tex"]:
        n = t["w"] * t["h"] * t["siz"] // 8
        out.append((t["space"], t["off"], t["off"] + n, "tex", t))
    for p in js["pal"]:
        out.append((p["space"], p["off"], p["off"] + 2 * p["n"], "pal", p))
    return out


def main(argv):
    ents = load(argv[1])
    js = json.load(open(argv[2]))
    rs = ranges(js)
    by = defaultdict(list)
    for r in rs:
        by[r[0]].append(r)
    over = 0
    code_hits = 0
    for sp, lst in by.items():
        lst.sort(key=lambda r: r[1])
        for a, b in zip(lst, lst[1:]):
            if b[1] < a[2]:
                over += 1
    # coverage of layout entries in rom
    cov = defaultdict(int)
    rom = sorted([r for r in rs if r[0] == "rom"], key=lambda r: r[1])
    import bisect
    starts = [e["start"] for e in ents]
    for r in rom:
        i = bisect.bisect_right(starts, r[1]) - 1
        e = ents[i]
        if e["type"] in CODE_TYPES:
            code_hits += 1
        cov[i] += min(r[2], e["end"]) - r[1]
    print(f"overlapping neighbours: {over}; textures starting in code: {code_hits}")
    tot = defaultdict(lambda: [0, 0])
    for i, e in enumerate(ents):
        k = e["type"]
        tot[k][0] += e["end"] - e["start"]
        tot[k][1] += cov.get(i, 0)
    for k, (a, b) in sorted(tot.items(), key=lambda kv: -kv[1][0]):
        if a > 4096:
            print(f"  {k:24s} {a / 1024:8.0f} KB  covered {b / 1024:7.0f} KB")
    if "--suspect" in argv:
        suspect(argv[1], ents, rs)
    if "--bins" in argv:
        for i, e in enumerate(ents):
            n = e["end"] - e["start"]
            if e["type"] in ("bin", "data", ".data", "gap") and n >= 4096:
                print(f"  {e['start']:07X} {n:8d} {100 * cov.get(i, 0) / n:5.0f}% {e['type']:5s} {e['seg']}/{e['name']}")



def structured(b):
    """fraction of 4-byte words that look like struct data (pointers, floats, zeros, small ints, dl commands)"""
    import struct as _s
    n = len(b) // 4
    if n == 0:
        return 1.0
    # Vtx arrays (geometry): 16-byte records with a zero flag at +6
    nv = len(b) // 16
    if nv >= 4:
        for ph in range(0, 16, 2):
            recs = [b[ph + 16 * i + 6:ph + 16 * i + 8] for i in range(nv - 1)]
            if sum(r == bytes(2) for r in recs) >= 0.8 * len(recs):
                return 1.0
    k = 0
    for i in range(n):
        w = _s.unpack_from(">I", b, 4 * i)[0]
        hi = w >> 24
        if w == 0 or w < 0x10000 or 0x80000000 <= w < 0x80800000 or hi in range(0x3A, 0x47) or hi in range(0xBA, 0xC7) or (w & 0xFFFF) == 0:
            k += 1
    return k / n


SPANS = []


def suspect(tree, ents, rs):
    """uncovered runs (>=256 B) in data/bin that do not look like structures: likely unfound pixels"""
    rom = open(f"{tree}/pokemonsnap.z64", "rb").read()
    cov = bytearray(len(rom))
    for r in rs:
        if r[0] == "rom":
            cov[r[1]:r[2]] = b"" * (r[2] - r[1])
    tot = defaultdict(int)
    for e in ents:
        if e["type"] not in ("bin", "data", ".data", "gap") or str(e["name"]).startswith("audio") or e["name"] == "padding":
            continue
        o = e["start"]
        while o < e["end"]:
            if cov[o]:
                o += 1
                continue
            q = o
            while q < e["end"] and not cov[q]:
                q += 1
            for c in range(o - o % 256, q, 256):
                blk = rom[max(c, o):min(c + 256, q)]
                if len(blk) >= 64 and structured(blk) < 0.45:
                    tot[(e["seg"], e["name"], e["start"])] += len(blk)
                    SPANS.append([max(c, o), len(blk)])
            o = q
    print(f"suspect (unstructured, uncovered) bytes: {sum(tot.values()) / 1024:.0f} KB")
    import json as _j
    _j.dump(SPANS, open("D:/n64work/pokemonsnap/suspect_spans.json", "w"))
    for k, v in sorted(tot.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {k[2]:07X} {v:7d} {k[0]}/{k[1]}")


if __name__ == "__main__":
    main(sys.argv)
