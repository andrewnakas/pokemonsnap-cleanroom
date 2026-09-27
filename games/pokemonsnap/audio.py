"""Sound banks (instruments + sound effects, libultra .ctl/.tbl in the ROM): dirty facts -> resynthesised samples.

    python -m games.pokemonsnap.audio extract <rom>        -> spec/audio.json (facts only)
    (build is called by generate.py: patches() -> [(space, off, bytes)])

Kept per wave: byte length (frame count), loop start/end/count, the codebook's predictor count (ctl keeps its
size, so the game's fixed audio heap still fits), a coarse spectral outline (cleanroom.audio.descriptor), the RMS
level and the median pitch. Bank structure (envelopes, keymaps, pans) stays as the game's data. Generated: every
waveform, our own VADPCM codebooks and loop states. Each .tbl is rebuilt from zeros, so no retail sample byte
survives. Music sequences (audio/seq, sbk) are kept as the user-approved melodies.
Overrides: overrides/sounds/<bank>/<wave ctl offset>.wav (e.g. placeholder voices) replace the resynthesis.
"""
import json
import os
import struct
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from cleanroom.audio import descriptor, vadpcm
from cleanroom.audio.pitch import median_f0

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec", "audio.json")
OVR = os.path.join(HERE, "overrides", "sounds")
RATE = 22050
# bank name -> (ctl rom offset, ctl size, tbl rom offset, tbl size)
BANKS = {"music": (0xAFEEE0, 21840, 0xB04430, 665584), "sfx": (0xBA6C20, 64800, 0xBB6940, 3787776)}


def waves_of(ctl):
    """{wave_off: dict(base, len, type, loop_off, book_off, snd)} reachable from the bank file."""
    out = {}
    rev, n = struct.unpack_from(">hh", ctl, 0)
    for bo in struct.unpack_from(">%dI" % n, ctl, 4):
        if not bo:
            continue
        cnt, fl, pad, rate, perc = struct.unpack_from(">hBBiI", ctl, bo)
        insts = [i for i in struct.unpack_from(">%dI" % cnt, ctl, bo + 12) if i] + ([perc] if perc else [])
        for ii, io in enumerate(insts):
            ns = struct.unpack_from(">h", ctl, io + 14)[0]
            for si, so in enumerate(struct.unpack_from(">%dI" % ns, ctl, io + 16)):
                if not so:
                    continue
                wt = struct.unpack_from(">I", ctl, so + 8)[0]
                base, ln, typ, wfl, lp, bk = struct.unpack_from(">IiBBxxII", ctl, wt)
                out.setdefault(wt, dict(base=base, len=ln, type=typ, loop_off=lp, book_off=bk, snd=[ii, si]))
    return out


def book_at(ctl, off):
    order, npred = struct.unpack_from(">ii", ctl, off)
    return {"order": order, "npred": npred,
            "book": list(struct.unpack_from(">%dh" % (order * npred * 8), ctl, off + 8))}


def _describe(args):
    key, data, book, typ = args
    if typ == 0:
        pcm = vadpcm.decode(data, book)
    else:
        pcm = np.frombuffer(data[:len(data) // 2 * 2], ">i2").astype(np.int64)
    d = descriptor.describe(pcm, RATE)
    f0 = median_f0(pcm.astype(np.float32) / 32768.0, RATE) if len(pcm) > 2048 else None
    return key, d, f0, int(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) if len(pcm) else 0


def extract(rom):
    spec, jobs = {}, []
    for name, (co, cn, to, tn) in BANKS.items():
        ctl, tbl = rom[co:co + cn], rom[to:to + tn]
        ws = waves_of(ctl)
        spec[name] = {"waves": {}}
        for wt, w in sorted(ws.items()):
            bk = book_at(ctl, w["book_off"]) if w["type"] == 0 and w["book_off"] else {"order": 0, "npred": 0}
            loop = None
            if w["loop_off"]:
                s, e, c = struct.unpack_from(">III", ctl, w["loop_off"])
                loop = [s, e, c]
            spec[name]["waves"][str(wt)] = dict(base=w["base"], len=w["len"], type=w["type"], snd=w["snd"],
                                                 npred=bk["npred"], order=bk["order"], loop=loop,
                                                 book_off=w["book_off"], loop_off=w["loop_off"])
            jobs.append(((name, str(wt)), tbl[w["base"]:w["base"] + w["len"]], bk, w["type"]))
    with ProcessPoolExecutor(4) as ex:
        for (name, wt), d, f0, rms in ex.map(_describe, jobs, chunksize=4):
            spec[name]["waves"][wt].update(desc=d, f0=f0, rms=rms)
    json.dump(spec, open(SPEC, "w"))
    n = sum(len(v["waves"]) for v in spec.values())
    lp = sum(1 for v in spec.values() for w in v["waves"].values() if w["loop"])
    print(f"audio: {n} waves ({lp} looped) -> {SPEC}")


def _make(args):
    name, wt, w = args
    adpcm = w["type"] == 0
    nsamp = w["len"] // 9 * 16 if adpcm else w["len"] // 2
    ovr = os.path.join(OVR, name, f"{wt}.wav")
    if os.path.exists(ovr):
        import scipy.io.wavfile as wavfile
        sr, x = wavfile.read(ovr)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        if x.ndim > 1:
            x = x.mean(1)
        x = np.interp(np.linspace(0, len(x) - 1, nsamp), np.arange(len(x)), x) if len(x) != nsamp else x
    else:
        x = descriptor.synthesize(w["desc"], nsamp, RATE, seed=int(wt) * 7 + len(name))
    if w["loop"] and w["loop"][2]:
        s, e = w["loop"][0], min(w["loop"][1], nsamp)
        if e - s > 64:
            x = descriptor.make_loop_seamless(np.asarray(x, np.float64), s, e)
    x = np.asarray(x, np.float64)
    peak = np.abs(x).max() + 1e-9
    target = max(w["rms"], 16) / 32768.0
    cur = np.sqrt(np.mean(x ** 2)) + 1e-9
    x = x * min(target / cur, 0.95 / peak)
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int64)
    if not adpcm:
        data = pcm.astype(">i2").tobytes()
        return name, wt, data[:w["len"]] + bytes(max(0, w["len"] - len(data))), None, None
    fam = vadpcm.PREDICTORS if w["npred"] >= 4 else [(1.0, 0.0), (1.9, -0.92)][:max(1, w["npred"])]
    book = vadpcm.make_book(fam)
    data, book, dec = vadpcm.encode(pcm, book)
    data = data[:w["len"]] + bytes(max(0, w["len"] - len(data)))
    state = vadpcm.loop_state(dec, w["loop"][0]) if w["loop"] else None
    return name, wt, data, book, state


def patches(rom):
    """-> [(space, off, bytes)]: the rebuilt .ctl (books, loop states) and .tbl of both banks"""
    spec = json.load(open(SPEC))
    jobs = [(name, wt, w) for name in spec for wt, w in spec[name]["waves"].items()]
    res = {}
    with ProcessPoolExecutor(4) as ex:
        for name, wt, data, book, state in ex.map(_make, jobs, chunksize=2):
            res[(name, wt)] = (data, book, state)
    out = []
    for name, (co, cn, to, tn) in BANKS.items():
        ctl = bytearray(rom[co:co + cn])
        tbl = bytearray(tn)
        for wt, w in spec[name]["waves"].items():
            data, book, state = res[(name, wt)]
            tbl[w["base"]:w["base"] + w["len"]] = data
            if book is not None:
                assert len(book["book"]) == w["order"] * w["npred"] * 8, (name, wt, len(book["book"]))
                struct.pack_into(">%dh" % len(book["book"]), ctl, w["book_off"] + 8, *book["book"])
            if w["loop_off"]:
                st = state if state is not None else [0] * 16
                struct.pack_into(">16h", ctl, w["loop_off"] + 12, *[max(-32768, min(32767, int(v))) for v in st])
        out += [("rom", co, bytes(ctl)), ("rom", to, bytes(tbl))]
    print(f"audio: {len(jobs)} waves regenerated")
    return out


if __name__ == "__main__":
    if sys.argv[1] == "extract":
        extract(open(sys.argv[2], "rb").read())
