# Pokemon Snap clean room: status

Play: **https://andrewnakas.github.io/pokemonsnap-cleanroom/** (repo andrewnakas/pokemonsnap-cleanroom, site on gh-pages,
published by `games/pokemonsnap/publish.sh`, which refuses unless the taint log says 0 failing).

## For the morning
- Play it in Chrome/Edge: arrows = stick, D = A, S = B, A = Z (camera), E = R, Enter = Start; gamepads work.
- Verified headless (clean ROM): N64/Nintendo/HAL logos, intro flyby, title, name entry (our font), Professor Oak's
  PKMN Report intro dialogue (readable), 60 fps.
- Taint: 7,120 streams, **0 failing**.
- Look at: faces and pictures are still blurry colour grids (Oak's face, the name card, Pokemon eyes) — next work.
- Voices: not started (Pokemon cries = placeholder TTS of the names; practice pack still to build).

## Decisions (log)
- 2026-09-26 23:15 ROM `Pokemon Snap (USA).z64` sha1 edc7c49c… = decomp's `checksum.sha1`. Decomp ethteck/pokemonsnap
  (WIP, splat + ninja, IDO 7.1 game / IDO 5.3 libultra) cloned depth 1, LF, to `D:/n64work/pokemonsnap/pristine`.
- **Web route = 3: clean N64 ROM + N64Wasm** (MIT, prebuilt ParaLLEl core, same as SF64/GoldenEye; `ports/emu`).
  Why: no PC port of Snap exists (no Emscripten target), no WSL on this PC. Retail runs at 60 fps in headless N64Wasm.
- **Clean ROM = decomp layout with every asset regenerated in place** (`generate.py`), not a ninja build: the IDO 7.1
  + asm-processor toolchain has no Windows asm-processor binary and the decomp matches byte for byte, so with same-size
  assets the ninja output is these exact bytes. vpk0 blobs are recompressed with the decomp's own codec (round trip
  byte-identical on retail) and must fit their slots; header CRC recomputed (CIC-6103).
- Dirty extraction: splat 0.50 in `D:/n64work/pokemonsnap/venv`, `configure.py` on `D:/n64work/pokemonsnap/dirty`.
- **Texture finder** (`texscan.py`): splat names only ~600 textures; the rest are in `bin` blobs. Found by
  (1) a linear F3DEX2 display-list walk with tile state carried across lists (HAL sets tiles in a shared `first` list;
  LoadBlock `dxt` gives the row size), (2) material `Texture` structs (render.c: load fmt/siz at 0x32/0x33, block dims
  at 0x34), (3) ultralib Sprite/Bitmap structs, (4) Bitmap families (animation frames swapped in by code),
  (5) palettes stored next to images. 2,630 textures, 750 palettes, 341 sprite pictures.
- Uncovered-data check (`texcover.py --suspect`): 228 KB of data neither referenced nor struct-like remains; viewed as
  pixels it is noise/stripes (animation curves, display lists), not images. Kept as data.
- Text font (window/text.c): 370 glyphs × 8×8/12×12 4-bit, typeset with OFL fonts (M PLUS Rounded 1c, Press Start 2P).
- Audio: 2 libultra banks (music 84 waves, sfx 298), resynthesised from outlines, own VADPCM books; .tbl rebuilt
  from zeros. Sequences kept.
- Taint: decoded RGBA of CI textures coincided with retail in flat areas (5-bit colours). Fixed with per-pixel dither,
  index dither, ±2-step palette jitter, and an automatic reseed list (`spec/reseed.json`, `cycle.sh`).

## Next
1. Faces: Pokemon eyes/mouths (material-animated textures, e.g. Meowth's eye set), Oak's face → facepaint briefs.
2. Text-bearing textures/sprites: title logo, PRESS START, menu labels, name card → re-typeset.
3. Pictures: boot N64 logo (vpk0 intro blob), HAL logo, album/report pictures.
4. Voices: find Pokemon cry samples in the sfx bank, Piper placeholders, practice pack.
