"""The web UI, served as a single self-contained page."""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lynx Deck</title>
<style>
  :root { --red:#e10a0a; --bg:#111; --panel:#1c1c1c; --line:#333; --text:#eee; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); }
  header { background:var(--red); padding:14px 20px; font-size:20px; font-weight:700; }
  header span { font-weight:400; opacity:.85; font-size:14px; margin-left:8px; }
  main { max-width:900px; margin:0 auto; padding:20px; }
  .panel { background:var(--panel); border:1px solid var(--line);
           border-radius:8px; padding:16px; margin-bottom:18px; }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  button { background:var(--red); color:#fff; border:0; border-radius:6px;
           padding:10px 18px; font-size:15px; font-weight:600; cursor:pointer; }
  button.ghost { background:#2a2a2a; border:1px solid var(--line); }
  button:disabled { opacity:.4; cursor:default; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { font-size:12px; text-transform:uppercase; opacity:.6; }
  tr.on td { background:#2a1010; }
  tr.clip:hover td { background:#242424; cursor:pointer; }
  .tc { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:22px; }
  .pill { padding:2px 10px; border-radius:99px; font-size:12px; font-weight:700; }
  .ok { background:#12451f; color:#7ee08f; }
  .bad { background:#4a1212; color:#ff9c9c; }
  .muted { opacity:.6; font-size:13px; }
</style>
</head>
<body>
<header>Lynx Deck <span id="model"></span></header>
<main>
  <div class="panel">
    <div class="row" style="justify-content:space-between">
      <div>
        <div class="tc" id="tc">00:00:00:00</div>
        <div class="muted"><span id="status">-</span> &middot; clip <span id="clip">-</span></div>
      </div>
      <div class="row">
        <span class="pill" id="health">...</span>
        <span class="muted" id="fmt"></span>
      </div>
    </div>
    <div class="row" style="margin-top:14px">
      <button onclick="act('play')">Play</button>
      <button class="ghost" onclick="act('stop')">Stop</button>
      <button class="ghost" onclick="toggle('loop')">Loop: <span id="loop">off</span></button>
      <button class="ghost" onclick="toggle('singleClip')">Single: <span id="single">off</span></button>
    </div>
  </div>

  <div class="panel">
    <div class="row" style="justify-content:space-between; margin-bottom:8px">
      <strong>Clips</strong>
      <button class="ghost" onclick="rescan()">Rescan</button>
    </div>
    <table><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Duration</th></tr></thead>
    <tbody id="clips"></tbody></table>
  </div>

  <div class="panel">
    <strong>Maintenance</strong>
    <div class="row" style="margin-top:10px">
      <button class="ghost" onclick="restartPlayer()">Restart player</button>
      <button onclick="reboot()">Reboot deck</button>
    </div>
    <div class="muted" style="margin-top:8px">Reboot takes about 30 seconds.</div>
  </div>
</main>
<script>
let state = {loop:false, singleClip:false};

async function api(path, method='GET', body) {
  const r = await fetch(path, {
    method,
    headers: body ? {'Content-Type':'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function act(what) {
  const body = what === 'play' ? {loop: state.loop, singleClip: state.singleClip} : null;
  await api('/transports/0/' + what, 'PUT', body || {});
  refresh();
}
function toggle(key) { state[key] = !state[key]; paint(state); if (key) act('play'); }
async function goto(i) { await api('/transports/0/clipIndex', 'PUT', {clipIndex:i}); refresh(); }
async function rescan() { await api('/media/rescan', 'POST'); loadClips(); }
async function restartPlayer() { await api('/system/restartPlayer', 'POST'); }
async function reboot() {
  if (confirm('Reboot the deck now?')) await api('/system/reboot', 'POST');
}

function paint(t) {
  document.getElementById('tc').textContent = t.timecode || '00:00:00:00';
  document.getElementById('status').textContent = t.status || '-';
  document.getElementById('clip').textContent = t.clipIndex ?? '-';
  document.getElementById('loop').textContent = state.loop ? 'on' : 'off';
  document.getElementById('single').textContent = state.singleClip ? 'on' : 'off';
  const h = document.getElementById('health');
  if (t.player) {
    h.textContent = t.player;
    h.className = 'pill ' + (t.player === 'ok' ? 'ok' : 'bad');
  }
  document.querySelectorAll('tr.clip').forEach(tr => {
    tr.classList.toggle('on', Number(tr.dataset.i) === t.clipIndex);
  });
}

async function refresh() {
  try {
    const t = await api('/transports/0');
    if (t.loop !== undefined) { state.loop = t.loop; state.singleClip = t.singleClip; }
    paint(t);
  } catch (e) { document.getElementById('health').textContent = 'offline'; }
}

async function loadClips() {
  const d = await api('/media/workingset');
  document.getElementById('clips').innerHTML = d.workingset.map(c =>
    `<tr class="clip" data-i="${c.clipIndex}" onclick="goto(${c.clipIndex})">
       <td>${c.clipIndex}</td><td>${c.name}</td><td>${c.kind} ${c.codec}</td>
       <td>${c.duration}</td></tr>`).join('');
}

(async () => {
  const s = await api('/system');
  document.getElementById('model').textContent = s.model + ' \\u00b7 v' + s.softwareVersion;
  document.getElementById('fmt').textContent = s.videoFormat;
  await loadClips();
  refresh();
  setInterval(refresh, 1000);
})();
</script>
</body>
</html>
"""
