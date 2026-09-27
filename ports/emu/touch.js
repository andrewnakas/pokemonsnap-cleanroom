// Touch controls for N64Wasm (our own code).
// Portrait: game screen on top, controls below. Landscape: full-height screen, translucent controls on the sides.
// Feeds N64Wasm's mobile input path (updateMobileControls: 14 buttons + analog vector), including L/R which
// N64Wasm's own mobile UI leaves out (SF64 needs Z/R for tilts and barrel rolls).
// Enabled on touch devices (pointer: coarse) or with ?touch=1; ?touch=0 forces it off.
(function () {
  const q = new URLSearchParams(location.search);
  const want = q.get('touch') === '1' || (q.get('touch') !== '0' && window.matchMedia && matchMedia('(pointer: coarse)').matches);
  window.cleanroomTouchWanted = want;
  if (!want) return;

  const S = { A: 0, B: 0, Start: 0, Z: 0, L: 0, R: 0, CU: 0, CD: 0, CL: 0, CR: 0, x: 0, y: 0 };
  window.cleanroomTouchState = S;

  const css = `
  html, body { background:#000 !important; overscroll-behavior:none; }
  body.cr-touch { margin:0; overflow:hidden; touch-action:none; -webkit-user-select:none; user-select:none;
                  -webkit-touch-callout:none; position:fixed; inset:0; }
  body.cr-touch > *:not(#cr-root):not(#soundBtn):not(script) { display:none !important; }
  #cr-root { position:fixed; inset:0; background:#000; color:#fff; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  #cr-screen { position:absolute; background:#000; display:flex; align-items:center; justify-content:center; }
  #cr-screen canvas { width:100% !important; height:100% !important; object-fit:contain; display:block; image-rendering:auto; }
  .cr-btn { position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center;
            border-radius:50%; font-weight:800; letter-spacing:.5px; touch-action:none; box-sizing:border-box;
            border:2px solid rgba(255,255,255,.35); box-shadow:0 3px 10px rgba(0,0,0,.5), inset 0 -4px 0 rgba(0,0,0,.25);
            transition:transform .05s, filter .05s; }
  .cr-btn small { font-size:10px; font-weight:700; opacity:.85; margin-top:1px; }
  .cr-btn.on { transform:scale(.92); filter:brightness(1.35); }
  .cr-pill { border-radius:14px; }
  #cr-A { background:radial-gradient(circle at 35% 30%, #5d8cff, #1d3fb8); }
  #cr-B { background:radial-gradient(circle at 35% 30%, #4fd06a, #16803a); }
  #cr-Z, #cr-R { background:linear-gradient(#6b6f80, #3a3d4a); }
  #cr-CL, #cr-CD, #cr-CU, #cr-CR { background:radial-gradient(circle at 35% 30%, #ffd84a, #c99a00); color:#2a2100; }
  #cr-Start { background:linear-gradient(#e24b4b, #9b1c1c); }
  #cr-stick { position:absolute; touch-action:none; }
  #cr-base { position:absolute; border-radius:50%; border:3px solid rgba(255,255,255,.35);
             background:radial-gradient(circle, rgba(255,255,255,.10), rgba(255,255,255,.03)); pointer-events:none; }
  #cr-knob { position:absolute; border-radius:50%; pointer-events:none;
             background:radial-gradient(circle at 35% 30%, #d9dce6, #7c8194); box-shadow:0 3px 10px rgba(0,0,0,.6); }
  #cr-bar { position:absolute; top:6px; left:8px; display:flex; gap:8px; z-index:5; }
  #cr-bar button { background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.25);
                   border-radius:14px; padding:5px 10px; font-size:13px; font-weight:700; }
  #cr-hint { position:absolute; left:0; right:0; text-align:center; font-size:11px; opacity:.55; pointer-events:none; }
  body.cr-land .cr-btn, body.cr-land #cr-base, body.cr-land #cr-knob { opacity:.72; }
  `;

  function el(tag, id, html, parent) {
    const e = document.createElement(tag);
    if (id) e.id = id;
    if (html) e.innerHTML = html;
    (parent || document.body).appendChild(e);
    return e;
  }

  const BUTTONS = [
    ['A', 'A<small>FIRE</small>'], ['B', 'B<small>BOMB</small>'],
    ['Z', 'Z<small>TILT</small>'], ['R', 'R<small>TILT</small>'],
    ['CL', '&#9664;C<small>BOOST</small>'], ['CD', '&#9660;C<small>BRAKE</small>'],
    ['CU', '&#9650;C<small>VIEW</small>'], ['CR', '&#9654;C'], ['Start', 'START'],
  ];

  let root, screen, stick, base, knob, hint;

  function build() {
    el('style', null, css, document.head);
    const vp = document.querySelector('meta[name=viewport]') || el('meta', null, null, document.head);
    vp.setAttribute('name', 'viewport');
    vp.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover');
    root = el('div', 'cr-root');
    screen = el('div', 'cr-screen', null, root);
    stick = el('div', 'cr-stick', null, root);
    base = el('div', 'cr-base', null, stick);
    knob = el('div', 'cr-knob', null, stick);
    for (const [k, label] of BUTTONS) {
      const b = el('div', 'cr-' + k, label, root);
      b.className = 'cr-btn' + (k === 'Z' || k === 'R' || k === 'Start' ? ' cr-pill' : '');
      bindButton(b, k);
    }
    const bar = el('div', 'cr-bar', null, root);
    const fs = el('button', null, 'Fullscreen', bar);
    fs.addEventListener('click', () => {
      const d = document.documentElement;
      (d.requestFullscreen || d.webkitRequestFullscreen || function () {}).call(d);
      try { window.screen.orientation.lock('landscape').catch(() => {}); } catch (e) {}
    });
    hint = el('div', 'cr-hint', 'Drag the left side to steer &middot; Z/R twice = barrel roll', root);
    bindStick();
    document.body.classList.add('cr-touch');
    window.addEventListener('resize', layout);
    window.addEventListener('orientationchange', () => setTimeout(layout, 200));
    layout();
  }

  function place(e, x, y, w, h, fs) {
    e.style.left = x + 'px'; e.style.top = y + 'px'; e.style.width = w + 'px'; e.style.height = h + 'px';
    if (fs) e.style.fontSize = fs + 'px';
  }

  let stickR = 60;

  function layout() {
    const W = window.innerWidth, H = window.innerHeight;
    const land = W > H;
    document.body.classList.toggle('cr-land', land);
    const $ = id => document.getElementById('cr-' + id);
    if (!land) {
      // portrait: screen on top (4:3), controls below
      const sh = Math.min(W * 0.75, H * 0.52);
      const sw = sh / 0.75;
      place(screen, (W - sw) / 2, 0, sw, sh);
      const top = sh, ch = H - sh, u = Math.min(W / 7.2, ch / 4.6);
      // top row: Z  C-up  START  C-right  R, evenly spaced
      const row = [['Z', 1.45, 0.8, 0.3], ['CU', 0.9, 0.9, 0.22], ['Start', 1.5, 0.7, 0.26], ['CR', 0.9, 0.9, 0.22], ['R', 1.45, 0.8, 0.3]];
      const tot = row.reduce((a, r) => a + r[1] * u, 0), gap = (W * 0.94 - tot) / (row.length - 1);
      let x = W * 0.03;
      for (const [k, w, h, f] of row) { place($(k), x, top + u * 0.25 + (0.9 - h) * u / 2, w * u, h * u, f * u); x += w * u + gap; }
      stickR = u * 1.25;
      place(stick, 0, top + u * 1.2, W * 0.5, ch - u * 1.2);
      const bx = W * 0.96, by = top + ch - u * 0.4;
      place($('A'), bx - u * 1.55, by - u * 1.6, u * 1.55, u * 1.55, u * 0.42);
      place($('B'), bx - u * 3.05, by - u * 1.1, u * 1.3, u * 1.3, u * 0.38);
      place($('CL'), bx - u * 2.95, by - u * 2.95, u * 1.15, u * 1.15, u * 0.3);
      place($('CD'), bx - u * 1.45, by - u * 3.25, u * 1.15, u * 1.15, u * 0.3);
      hint.style.top = (top + ch - 16) + 'px';
    } else {
      // landscape: full-height screen, controls float on the sides
      const sh = H, sw = Math.min(W, H / 0.75);
      place(screen, (W - sw) / 2, 0, sw, sh);
      const u = Math.min(H / 5.2, W / 11);
      place($('Z'), u * 0.3, u * 0.6, u * 1.9, u * 0.75, u * 0.28);
      place($('R'), W - u * 2.2, u * 0.6, u * 1.9, u * 0.75, u * 0.28);
      place($('Start'), W / 2 - u * 0.8, H - u * 0.8, u * 1.6, u * 0.62, u * 0.24);
      stickR = u * 1.1;
      place(stick, 0, u * 1.5, W * 0.4, H - u * 1.5);
      const bx = W - u * 0.3, by = H - u * 0.3;
      place($('A'), bx - u * 1.45, by - u * 1.5, u * 1.45, u * 1.45, u * 0.4);
      place($('B'), bx - u * 2.85, by - u * 1.0, u * 1.2, u * 1.2, u * 0.35);
      place($('CL'), bx - u * 2.75, by - u * 2.75, u * 1.05, u * 1.05, u * 0.28);
      place($('CD'), bx - u * 1.35, by - u * 3.0, u * 1.05, u * 1.05, u * 0.28);
      place($('CU'), bx - u * 3.9, by - u * 2.0, u * 0.9, u * 0.9, u * 0.24);
      place($('CR'), bx - u * 4.0, by - u * 0.9, u * 0.8, u * 0.8, u * 0.24);
      hint.style.top = '4px';
      hint.style.display = 'none';
    }
    // resting stick position: centre of its zone, lower half
    const r = stick.getBoundingClientRect();
    rest = { x: r.width * 0.5, y: r.height * 0.55 };
    drawStick(rest.x, rest.y, 0, 0);
  }

  let rest = { x: 0, y: 0 }, origin = null, stickId = null;

  function drawStick(ox, oy, dx, dy) {
    const R = stickR;
    place(base, ox - R, oy - R, 2 * R, 2 * R);
    const k = R * 0.55;
    place(knob, ox + dx - k, oy + dy - k, 2 * k, 2 * k);
  }

  function bindStick() {
    stick.addEventListener('pointerdown', ev => {
      if (stickId !== null) return;
      stickId = ev.pointerId;
      stick.setPointerCapture(ev.pointerId);
      const r = stick.getBoundingClientRect();
      origin = { x: ev.clientX - r.left, y: ev.clientY - r.top };   // floating stick: centre where the thumb lands
      move(ev);
      ev.preventDefault();
    });
    const move = ev => {
      if (ev.pointerId !== stickId) return;
      const r = stick.getBoundingClientRect();
      let dx = ev.clientX - r.left - origin.x, dy = ev.clientY - r.top - origin.y;
      const R = stickR, d = Math.hypot(dx, dy);
      if (d > R) {   // drag the base along so the thumb never "loses" the stick
        origin.x += dx * (1 - R / d); origin.y += dy * (1 - R / d);
        dx *= R / d; dy *= R / d;
      }
      let x = dx / R, y = -dy / R;
      const m = Math.hypot(x, y), dead = 0.1;
      if (m < dead) { x = 0; y = 0; } else { const s = (m - dead) / (1 - dead) / m; x *= s; y *= s; }
      S.x = x; S.y = y;
      drawStick(origin.x, origin.y, dx, dy);
      ev.preventDefault();
    };
    stick.addEventListener('pointermove', move);
    const end = ev => {
      if (ev.pointerId !== stickId) return;
      stickId = null; S.x = 0; S.y = 0;
      drawStick(rest.x, rest.y, 0, 0);
    };
    stick.addEventListener('pointerup', end);
    stick.addEventListener('pointercancel', end);
  }

  function bindButton(b, k) {
    const down = ev => {
      b.setPointerCapture && b.setPointerCapture(ev.pointerId);
      S[k] = 1; b.classList.add('on');
      if (navigator.vibrate) try { navigator.vibrate(8); } catch (e) {}
      ev.preventDefault();
    };
    const up = ev => { S[k] = 0; b.classList.remove('on'); ev.preventDefault(); };
    b.addEventListener('pointerdown', down);
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('contextmenu', e => e.preventDefault());
  }

  // dev hook: ?touchscript=t:key:dur,... presses touch buttons (A B Z R CL CD CU CR Start) or the stick
  // (up/down/left/right) as the overlay would, for headless checks.
  const ts = q.get('touchscript');
  if (ts) ts.split(',').forEach(item => {
    const [t, k, dur] = item.split(':');
    setTimeout(() => {
      const dir = { up: [0, 1], down: [0, -1], left: [-1, 0], right: [1, 0] }[k];
      if (dir) { S.x = dir[0]; S.y = dir[1]; } else S[k] = 1;
      setTimeout(() => { if (dir) { S.x = 0; S.y = 0; } else S[k] = 0; }, 1000 * parseFloat(dur || '0.2'));
    }, 1000 * parseFloat(t));
  });

  // Called from the page's module-ready hook: take over N64Wasm's mobile mode.
  window.cleanroomTouchInstall = function (app) {
    app.mobileMode = true;
    app.setupMobileMode = function () {
      if (!root) build();
      const c = document.getElementById('canvas');
      screen.appendChild(c);
      document.getElementById('canvasDiv') && (document.getElementById('canvasDiv').style.display = 'none');
      layout();
    };
    const ic = app.rivetsData.inputController;
    ic.updateMobileControls = function () {
      const b = v => (v ? '1' : '0');
      const s = '0000' + b(S.A) + b(S.B) + b(S.Start) + b(S.Z) + b(S.L) + b(S.R) +
                b(S.CU) + b(S.CD) + b(S.CL) + b(S.CR);
      app.sendMobileControls(s, S.x.toString(), S.y.toString());
    };
    ic.VectorX = 0; ic.VectorY = 0;
  };
})();
