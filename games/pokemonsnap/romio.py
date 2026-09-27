"""ROM address spaces (ROM + decompressed vpk0 blobs), vpk0 repacking and the N64 header checksum."""
import struct
import sys
from pathlib import Path

# vpk0 blobs: name -> (rom start, slot end = next segment start)
VPK0 = {"main_menu_vpk0": (0xA0F830, 0xA5CC50), "intro_code_vpk0": (0xAA0B80, 0xAA18E0),
        "unk_segment_AA18E0_vpk0": (0xAAA610, 0xAAA660)}
DECOMP_TOOLS = Path("D:/n64work/pokemonsnap/pristine/tools")


def codec():
    if str(DECOMP_TOOLS) not in sys.path:
        sys.path.insert(0, str(DECOMP_TOOLS))
    import vpk0_codec
    return vpk0_codec


def spaces(rom: bytes) -> dict:
    v = codec()
    d = {"rom": rom}
    for n, (a, b) in VPK0.items():
        d["vpk0:" + n] = v.decompress_vpk0(rom[a:b])[0]
    return d


def pack(sp: dict) -> bytearray:
    """write decompressed vpk0 blobs back (recompressed) into the ROM; each must fit its slot"""
    v = codec()
    rom = bytearray(sp["rom"])
    for n, (a, b) in VPK0.items():
        c = v.compress_vpk0(bytes(sp["vpk0:" + n]))
        if len(c) > b - a:
            raise SystemExit(f"vpk0 {n}: {len(c)} bytes > slot {b - a}")
        rom[a:b] = c + bytes(b - a - len(c))
    return rom


SEEDS = {6102: 0xF8CA4DDC, 6103: 0xA3886759, 6105: 0xDF26F436, 6106: 0x1FEA617A}


def crc(rom, cic):
    M = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = SEEDS[cic]
    words = struct.unpack_from(">262144I", rom, 0x1000)
    for i, d in enumerate(words):
        s = (t6 + d) & M
        if s < t6:
            t4 = (t4 + 1) & M
        t6 = s
        t3 ^= d
        sh = d & 0x1F
        r = ((d << sh) | (d >> (32 - sh))) & M if sh else d
        t5 = (t5 + r) & M
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        if cic == 6105:
            t1 = (t1 + (struct.unpack_from(">I", rom, 0x40 + 0x0710 + ((i * 4) & 0xFF))[0] ^ d)) & M
        else:
            t1 = (t1 + (t5 ^ d)) & M
    if cic == 6103:
        return ((t6 ^ t4) + t3) & M, ((t5 ^ t2) + t1) & M
    if cic == 6106:
        return ((t6 * t4) + t3) & M, ((t5 * t2) + t1) & M
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def detect_cic(rom):
    want = struct.unpack_from(">II", rom, 0x10)
    for cic in SEEDS:
        if crc(rom, cic) == want:
            return cic
    return None


def fix_crc(rom, cic):
    struct.pack_into(">II", rom, 0x10, *crc(rom, cic))
