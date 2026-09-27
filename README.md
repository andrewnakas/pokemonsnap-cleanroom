# Pokemon Snap — clean room web build

Play: **https://andrewnakas.github.io/pokemonsnap-cleanroom/**

Pokemon Snap (US) built from the [ethteck/pokemonsnap](https://github.com/ethteck/pokemonsnap) decompilation and run
in the browser on [N64Wasm](https://github.com/nbarkhina/N64Wasm) (MIT, ParaLLEl/mupen64plus core), with **every
asset the decomp extracts from the ROM regenerated**: textures, palettes, menu pictures, fonts, instrument and
sound-effect samples. No original pixels or samples are in the published ROM.

Controls: arrow keys = stick · `D` = A · `S` = B · `A` = Z · `E` = R · `Q` = L · `I J K L` = C buttons ·
`Enter` = Start · gamepads work (remap under the `` ` `` menu).

## What is kept, what is generated

| Asset | Kept fact | Generated |
|---|---|---|
| Game code, geometry (Vtx/display lists), animations, height maps, text, note sequences | as in the decomp (user scope) | — |
| Textures (2,630 ranges: Pokemon, levels, effects) | format, size, a 4×4 colour grid (16×16 for ≥128 px), a 2-bit alpha outline | colour from the grid + our own noise detail; CI textures re-indexed against our own palettes |
| Palettes (750) | entry count, which entries are transparent, 8 coarse colours | quantised from our generated textures |
| Menu / UI pictures (341 sprites, animation frames) | the same, per whole picture | generated whole, then cut into the game's bitmap strips |
| Text font (370 glyphs, 8×8 and 12×12) | character of each slot (decomp `UIText_CharTable`), advance widths | typeset with OFL fonts (M PLUS Rounded 1c, Press Start 2P) |
| Samples (382 waves, 2 banks) | length, rate, loops, predictor count, coarse spectral outline, level, median pitch | resynthesised; our own VADPCM codebooks and loop states; bank sizes unchanged |

How the textures were found: the decomp only names ~600 textures; the rest sit in `bin` blobs. `texscan.py`
walks every F3DEX2 display list, material (`Texture`) struct, ultralib `Sprite`/`Bitmap` (including animation
frames swapped in by code) in the ROM and in the decompressed vpk0 blobs.

`taint_report.py` scans every generated texture (stored bytes and decoded RGBA), palette, font table and sample
(ADPCM, decoded PCM, codebooks, loop states) against retail for shared byte runs of 32 bytes or more: **0 failing**.

## Build

Needs the US ROM (sha1 `edc7c49c…`) for the dirty-room steps and as the source of the decomp's kept code bytes.
```
python -m games.pokemonsnap.texscan <dirty tree> texscan.json        # dirty: find textures
python -m games.pokemonsnap.extract_spec <dirty tree> texscan.json games/pokemonsnap/spec
python -m games.pokemonsnap.audio extract <rom>
python -m games.pokemonsnap.generate <rom> games/pokemonsnap/spec clean.z64
python -m games.pokemonsnap.taint_report <rom> clean.z64
python ports/emu/make_site.py site clean.z64
```
The clean ROM keeps the decomp's layout (every asset regenerated in place at the same size; vpk0 blobs recompressed
with the decomp's own codec), so it is the ROM the decomp would build with these assets.
