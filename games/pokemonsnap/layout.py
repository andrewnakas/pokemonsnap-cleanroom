"""Flatten the decomp's splat.yaml into ROM ranges (facts about the layout, no ROM bytes).

    python -m games.pokemonsnap.layout <tree> [--bins]

Each entry: rom start/end, type, name, top segment, vram (when the segment has one).
Nested `.data` subsegments are expanded; bare `[start]` entries become type "gap".
"""
import sys

import yaml

ROM_SIZE = 0x1000000


def _entries(subs, seg, vram0, rom0, out, dirp=""):
    for s in subs:
        if isinstance(s, list):
            start = s[0]
            typ = s[1] if len(s) > 1 else "gap"
            name = s[2] if len(s) > 2 else ""
            extra = {}
            if len(s) > 3:
                extra["args"] = s[3:]
        else:
            start = s.get("start")
            typ = s.get("type", "gap")
            name = s.get("name", "")
            extra = {k: v for k, v in s.items() if k not in ("start", "type", "name", "subsegments")}
            if "subsegments" in s:
                d = s.get("dir", dirp)
                _entries(s["subsegments"], seg, s.get("vram", vram0) if "vram" in s else vram0, rom0, out, d)
                if start is not None and not any(e["start"] == start for e in out):
                    pass
                continue
        if start == "auto" or start is None:
            continue
        e = {"start": start, "type": typ, "name": name, "seg": seg, "dir": extra.get("dir", dirp), **extra}
        if vram0 is not None:
            e["vram"] = vram0 + (start - rom0)
        out.append(e)


def load(tree):
    y = yaml.load(open(f"{tree}/splat.yaml", encoding="utf-8"), Loader=yaml.SafeLoader)
    out = []
    for s in y["segments"]:
        if isinstance(s, list):
            e = {"start": s[0], "type": s[1] if len(s) > 1 else "end", "name": s[2] if len(s) > 2 else "", "seg": ""}
            if len(s) > 3:
                e["args"] = s[3:]
            out.append(e)
            continue
        vram = s.get("vram")
        start = s["start"]
        seg = s.get("name", "")
        if "subsegments" in s:
            n0 = len(out)
            _entries(s["subsegments"], seg, vram, start, out, s.get("dir", ""))
            if len(out) == n0 or out[n0]["start"] != start:
                out.insert(n0, {"start": start, "type": "gap", "name": "", "seg": seg, "vram": vram})
        else:
            out.append({"start": start, "type": s.get("type", "bin"), "name": seg, "seg": seg, "vram": vram,
                        "dir": s.get("dir", "")})
    out = [e for e in out if isinstance(e["start"], int)]
    out.sort(key=lambda e: e["start"])
    # dedupe equal starts: keep the most specific (non-gap) entry
    ded = []
    for e in out:
        if ded and ded[-1]["start"] == e["start"]:
            if ded[-1]["type"] in ("gap", "end") or e["type"] not in ("gap", "end"):
                ded[-1] = e
            continue
        ded.append(e)
    for a, b in zip(ded, ded[1:]):
        a["end"] = b["start"]
    ded[-1]["end"] = ROM_SIZE
    return [e for e in ded if e["end"] > e["start"]]


def main(argv):
    ents = load(argv[1])
    tot = {}
    for e in ents:
        tot.setdefault(e["type"], [0, 0])
        tot[e["type"]][0] += 1
        tot[e["type"]][1] += e["end"] - e["start"]
    for t, (n, b) in sorted(tot.items(), key=lambda kv: -kv[1][1]):
        print(f"{t:26s} {n:5d} {b / 1024:9.1f} KB")
    if "--bins" in argv:
        for e in ents:
            if e["type"] in ("bin", "gap", "end", "vpk0"):
                print(f"  {e['start']:07X}-{e['end']:07X} {e['end'] - e['start']:8d} {e['type']:5s} {e['seg']}/{e['name']}")


if __name__ == "__main__":
    main(sys.argv)
