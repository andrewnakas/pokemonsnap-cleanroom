"""Assemble the web site: N64Wasm (MIT, prebuilt ParaLLEl core) + our page hooks + a ROM.

    python ports/emu/make_site.py <out dir> <rom.z64> [--n64wasm C:/Users/andre/n64work/n64wasm/dist]

Hooks added to N64Wasm's script.js:
  ?rom=<url>    auto-load that ROM when the wasm module is ready (default: the site's ROM)
  ?keys=t:key:dur,...   scripted key presses (dev: headless checks)
The ROM is written as game.z64. Never point this at a retail ROM for a published site.
"""
import argparse
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

AUTOLOAD = r"""
    async initModule(){
        console.log('module initialized');
        myClass.rivetsData.moduleInitializing = false;
        let q = new URLSearchParams(location.search);
        let rom = q.get('rom') || window.SITE_ROM;
        if (q.get('rice')) myClass.rivetsData.ricePlugin = true;
        if (q.get('angry')) myClass.rivetsData.forceAngry = true;
        if (window.cleanroomTouchWanted) window.cleanroomTouchInstall(myClass);
        if (rom) { myClass.rom_name = myClass.extractRomName(rom); myClass.load_url(rom); }
        if (q.get('keys')) window.cleanroomKeys(q.get('keys'));
        if (q.get('nosave')) myClass.SaveSram = function () {};
        window.cleanroomAudioUnlock();
        if (q.get('audiolog')) setInterval(function () {
            let b = myClass.audioBufferResampled, peak = 0, ss = 0, clip = 0;
            if (b) for (let i = 0; i < b.length; i++) { let v = Math.abs(b[i]); peak = Math.max(peak, v); ss += v * v; if (v > 30000) clip++; }
            console.log('audio', myClass.audioContext ? myClass.audioContext.state : 'none', 'peak', peak,
                        'rms', b ? Math.round(Math.sqrt(ss / b.length)) : 0, 'clip', clip);
        }, 3000);
    }
"""

KEYS_JS = r"""
// Sound: the ROM starts without a click, so the browser creates the AudioContext suspended and N64Wasm never
// resumes it. Resume on the first tap / click / key, and show a button until sound is running.
window.cleanroomAudioUnlock = function () {
  const btn = document.createElement('button');
  btn.id = 'soundBtn';
  btn.textContent = 'Tap for sound';
  btn.style.cssText = 'position:fixed;top:10px;right:10px;z-index:9999;padding:10px 16px;font-size:16px;' +
    'border-radius:22px;border:0;background:#ffcc33;color:#222;font-weight:bold;box-shadow:0 2px 8px #0006;display:none';
  document.body.appendChild(btn);
  const ok = () => window.myClass && myClass.audioContext && myClass.audioContext.state === 'running';
  const tryResume = () => {
    if (window.myClass && myClass.audioContext && myClass.audioContext.state !== 'running')
      myClass.audioContext.resume().then(() => { if (ok()) btn.style.display = 'none'; });
  };
  ['pointerdown', 'touchstart', 'keydown', 'click'].forEach(ev =>
    window.addEventListener(ev, tryResume, { capture: true, passive: true }));
  setInterval(() => { btn.style.display = (window.myClass && myClass.audioContext && !ok()) ? 'block' : 'none'; }, 500);
};
// dev hook: ?keys=t:key:dur,... (seconds; key = KeyboardEvent.key, e.g. Enter, d, ArrowLeft)
window.cleanroomKeys = function (spec) {
  const t0 = performance.now();
  spec.split(',').forEach(item => {
    const [t, key, dur] = item.split(':');
    setTimeout(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: key, bubbles: true }));
      setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup', { key: key, bubbles: true })),
                 1000 * parseFloat(dur || '0.15'));
    }, 1000 * parseFloat(t));
  });
};
"""


SAFE_LOADSRAM = r"""
    async LoadSram() {
        return new Promise(function (resolve) {
            try {
                var request = indexedDB.open('N64WASMDB');
                request.onupgradeneeded = function (ev) {
                    let db = ev.target.result;
                    if (!db.objectStoreNames.contains('N64WASMSTATES'))
                        db.createObjectStore('N64WASMSTATES', { autoIncrement: true });
                };
                request.onsuccess = function (ev) {
                    try {
                        var db = ev.target.result;
                        var romStore = db.transaction("N64WASMSTATES", "readwrite").objectStore("N64WASMSTATES");
                        var rom = romStore.get(myClass.rom_name + '.sram');
                        rom.onsuccess = function () {
                            if (rom.result) FS.writeFile('/game.savememory', rom.result);
                            resolve();
                        };
                        rom.onerror = function () { resolve(); };
                    } catch (e) { console.log('sram load skipped', e); resolve(); }
                };
                request.onerror = function () { resolve(); };
            } catch (e) { console.log('sram load skipped', e); resolve(); }
        });
    }
"""


INFO = """
<div style="max-width:720px;margin:16px auto;font-size:14px;line-height:1.45;text-align:left">
<p><b>Controls</b>: arrow keys = stick &middot; <b>D</b> = A &middot; <b>S</b> = B &middot; <b>A</b> = Z (take a picture) &middot;
<b>E</b> = R &middot; <b>Q</b> = L &middot; <b>I J K L</b> = C buttons &middot; <b>Enter</b> = Start &middot; gamepads work too
(remap under the <code>`</code> menu). On phones a touch pad appears. If you hear nothing, tap the page once.</p>
<p>Built from the <a href="https://github.com/ethteck/pokemonsnap">pokemonsnap</a> decompilation (US).
Every texture, font, palette, menu picture and instrument/sound sample was regenerated from coarse facts
(size, format, a colour grid, a 2-bit alpha outline; sample length, loops and a spectral outline) &mdash; no
original pixels or samples are included. Game code, geometry, animation, text and music note data come from the decomp.
Voices are placeholders. Runs on <a href="https://github.com/nbarkhina/N64Wasm">N64Wasm</a> (MIT).
Source: <a href="https://github.com/andrewnakas/pokemonsnap-cleanroom">andrewnakas/pokemonsnap-cleanroom</a>.</p>
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("rom")
    ap.add_argument("--n64wasm", default="C:/Users/andre/n64work/n64wasm/dist")
    ap.add_argument("--index", default=os.path.join(HERE, "index.html"))
    a = ap.parse_args()
    tree = os.path.dirname(os.path.dirname(os.path.abspath(a.rom)))
    if os.path.exists(os.path.join(tree, "DEV_RETAIL_AUDIO")) and "dev" not in os.path.basename(a.out.rstrip("/\\")):
        raise SystemExit("refusing: this ROM was built with retail audio (dev only); site dir name must contain 'dev'")
    os.makedirs(a.out, exist_ok=True)
    for f in ("assets.zip", "input_controller.js", "n64wasm.js", "n64wasm.wasm", "settings.js"):
        shutil.copy(os.path.join(a.n64wasm, f), os.path.join(a.out, f))
    src = open(os.path.join(a.n64wasm, "script.js"), encoding="utf-8").read()
    old_start = src.index("    async initModule(){")
    old_end = src.index("    //not being used currently")
    src = src[:old_start] + AUTOLOAD.lstrip("\n") + "\n" + src[old_end:]
    # first visit: LoadSram could open the DB before its object store exists and reject/throw, so the emulator
    # never started. Create the store on upgrade and always resolve (a missing save is not fatal).
    a0 = src.index("    async LoadSram() {")
    a1 = src.index("    SaveSram() {")
    src = src[:a0] + SAFE_LOADSRAM + "\n" + src[a1:]
    open(os.path.join(a.out, "script.js"), "w", encoding="utf-8").write(KEYS_JS + src)
    open(os.path.join(a.out, "romlist.js"), "w").write("var ROMLIST = [];\nwindow.SITE_ROM = 'game.z64';\n")
    idx = a.index if os.path.exists(a.index) else os.path.join(a.n64wasm, "index.html")
    html = open(idx, encoding="utf-8").read()
    html = html.replace("<title>N64 Wasm</title>", "<title>Pokemon Snap clean room</title>")
    html = re.sub(r"<h1>\s*N64 Wasm", '<h1>Pokemon Snap <small style="font-size:50%">clean room</small>', html, 1)
    html = html.replace('<div id="bottomPanel"', INFO + '<div id="bottomPanel"', 1)
    # vendor the CDN scripts/styles (all MIT): a slow or blocked CDN otherwise leaves `$` undefined and the page dead
    vend = os.path.join(HERE, "vendor")
    os.makedirs(os.path.join(a.out, "vendor"), exist_ok=True)
    for url in re.findall(r'(?:src|href)="(https://[^"]+\.(?:js|css))"', html):
        name = os.path.basename(url).replace("latest", "")
        if url.endswith("toastr.min.js"):
            name = "toastr.min.js"
        if url.endswith("toastr.min.css"):
            name = "toastr.min.css"
        if os.path.exists(os.path.join(vend, name)):
            shutil.copy(os.path.join(vend, name), os.path.join(a.out, "vendor", name))
            html = html.replace(url, "vendor/" + name)
    # our touch controls (portrait + landscape), loaded before the app script
    shutil.copy(os.path.join(HERE, "touch.js"), os.path.join(a.out, "touch.js"))
    html = html.replace("</head>", '<script src="touch.js"></script>\n</head>', 1)
    open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(a.out, ".nojekyll"), "w").write("")
    shutil.copy(a.rom, os.path.join(a.out, "game.z64"))
    print("site ->", a.out)


if __name__ == "__main__":
    main()
