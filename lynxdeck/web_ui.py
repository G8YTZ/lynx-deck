"""The web UI, served as a single self-contained page."""

PAGE = r"""<!doctype html>
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
  .drop { border:2px dashed var(--line); border-radius:8px; padding:26px;
          text-align:center; margin-top:10px; transition:.15s; }
  .drop.over { border-color:var(--red); background:#2a1010; }
  .link { color:var(--red); cursor:pointer; text-decoration:underline; }
  .bar { height:6px; background:#2a2a2a; border-radius:99px; overflow:hidden; margin-top:6px; }
  .bar i { display:block; height:100%; background:var(--red); width:0; }
  select { background:#2a2a2a; color:var(--text); border:1px solid var(--line);
           border-radius:5px; padding:4px 6px; font-size:13px; }
  .del { color:#888; cursor:pointer; }
  table.kv th { width:150px; opacity:.6; font-weight:600; vertical-align:top; }
  table.kv td { font-size:14px; }
  table.kv td, table.kv th { border-bottom:1px solid #262626; padding:7px 10px 7px 0; }
  input[type=number] { background:#2a2a2a; color:var(--text); border:1px solid var(--line);
                       border-radius:5px; padding:5px 8px; width:90px; font-size:13px; }
  .warn { color:#ffb454; }
  .del:hover { color:var(--red); }
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
    <table><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Duration</th>
      <th>At end</th><th></th></tr></thead>
    <tbody id="clips"></tbody></table>
  </div>

  <div class="panel">
    <strong>Upload media</strong>
    <div id="drop" class="drop">
      Drop video or stills here, or <label class="link">choose files
      <input type="file" id="file" multiple hidden
             accept=".mp4,.mov,.mkv,.m4v,.ts,.png,.jpg,.jpeg"></label>
    </div>
    <div id="progress" class="muted" style="margin-top:10px"></div>
    <div class="muted">H.264 or H.265 video, PNG or JPG stills. Number the
      filenames (01_, 02_ ...) to set the running order.</div>
  </div>

  <div class="panel">
    <div class="row" style="justify-content:space-between; margin-bottom:10px">
      <strong>Status</strong>
      <span class="muted" id="statusline"></span>
    </div>
    <table class="kv">
      <tr><th>Output</th><td id="s-output">-</td></tr>
      <tr><th>Playing</th><td id="s-clip">-</td></tr>
      <tr><th>Controllers</th><td id="s-ctrl">-</td></tr>
      <tr><th>Network</th><td id="s-net">-</td></tr>
      <tr><th>Player</th><td id="s-health">-</td></tr>
    </table>
    <div class="row" style="margin-top:12px">
      <button class="ghost" id="wifibtn" onclick="toggleWifi()">Wi-Fi</button>
      <span class="muted">Wi-Fi off avoids a second route at a repeater site.</span>
    </div>
  </div>

  <div class="panel">
    <strong>Settings</strong>
    <table class="kv" style="margin-top:8px">
      <tr><th>Default clip</th><td>
        <select id="set-defaultClip"></select></td></tr>
      <tr><th>Default behaviour</th><td>
        <select id="set-defaultBehaviour">
          <option value="auto">auto - move on to the next clip</option>
          <option value="once">once - same as auto</option>
          <option value="loop">loop - repeat this clip</option>
          <option value="hold">hold - stop on the last frame</option>
        </select></td></tr>
      <tr><th>Still duration</th><td>
        <input type="number" id="set-stillDuration" min="1" max="3600" step="1"> seconds
        <span class="muted">(only used by auto)</span></td></tr>
      <tr><th>Volume</th><td>
        <input type="number" id="set-volume" min="0" max="130" step="1"> %</td></tr>
    </table>
    <div class="row" style="margin-top:12px">
      <button onclick="saveSettings()">Save settings</button>
      <span class="muted" id="setmsg"></span>
    </div>
  </div>

  <div class="panel">
    <strong>Maintenance</strong>
    <div class="row" style="margin-top:10px">
      <button class="ghost" onclick="restartPlayer()">Restart player</button>
      <button class="ghost" onclick="checkUpdate()">Check for updates</button>
      <button id="updbtn" onclick="doUpdate()" style="display:none">Update &amp; restart</button>
      <button onclick="reboot()">Reboot deck</button>
      <button onclick="shutdown()">Shut down</button>
    </div>
    <div class="muted" id="updinfo" style="margin-top:8px">Reboot takes about 30 seconds. Always shut down before removing power.</div>

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
async function toggle(key) {
  state[key] = !state[key];
  paint(state);
  await api('/transports/0/settings', 'PUT',
            {loop: state.loop, singleClip: state.singleClip});
  refresh();
}
async function setBehaviour(name, behaviour) {
  await api('/media/' + encodeURIComponent(name) + '/behaviour', 'PUT', {behaviour});
  loadClips();
}
async function goto(i) { await api('/transports/0/clipIndex', 'PUT', {clipIndex:i}); refresh(); }
async function rescan() { await api('/media/rescan', 'POST'); loadClips(); }
async function restartPlayer() { await api('/system/restartPlayer', 'POST'); }

async function checkUpdate() {
  const info = document.getElementById('updinfo');
  const btn = document.getElementById('updbtn');
  info.textContent = 'Checking...';
  try {
    const u = await api('/system/update');
    if (!u.git) { info.textContent = 'v' + u.version + ' (not a git checkout)'; return; }
    let line = `v${u.version} \u00b7 ${u.branch} @ ${u.git} \u00b7 ${u.message}`;
    if (u.localChanges) line += ' \u00b7 local changes present, update blocked';
    else if (u.updateAvailable) line += ` \u00b7 ${u.commitsBehind} update(s) available`;
    else line += ' \u00b7 up to date';
    info.textContent = line;
    btn.style.display = (u.updateAvailable && !u.localChanges) ? '' : 'none';
  } catch (e) { info.textContent = 'Check failed: ' + e.message; }
}

async function doUpdate() {
  if (!confirm('Update and restart the deck? Playback stops briefly.')) return;
  const info = document.getElementById('updinfo');
  info.textContent = 'Updating...';
  try {
    const r = await api('/system/update', 'POST');
    info.textContent = r.updated
      ? `Updated to ${r.git}, restarting...`
      : 'Already up to date.';
    document.getElementById('updbtn').style.display = 'none';
  } catch (e) { info.textContent = 'Update failed: ' + e.message; }
}

async function loadStatus() {
  try {
    const [o, n, c, h] = await Promise.all([
      api('/system/output'), api('/system/network'),
      api('/system/controllers'), api('/player/health')]);

    let out = o.connected ? (o.mode || '?') : 'no display connected';
    if (o.refresh) out += ` @ ${o.refresh.toFixed(2)} Hz`;
    if (o.source) out += ` <span class="muted">(${o.source})</span>`;
    if (o.configured) {
      // does what we tell controllers match what we are actually sending?
      const m = String(o.configured).match(/(\d+)p(\d+)/);
      const mismatch = m && o.refresh && Math.abs(Number(m[2]) - o.refresh) > 1;
      out += ` \u00b7 reported as <span class="${mismatch ? 'warn' : ''}">${o.configured}</span>`;
      if (mismatch) out += ' <span class="warn">- does not match the output</span>';
    }
    document.getElementById('s-output').innerHTML =
      o.connected ? out : `<span class="warn">${out}</span>`;

    document.getElementById('s-clip').textContent = o.clip
      ? `${o.clip.name} \u00b7 ${o.clip.kind} ${o.clip.codec} \u00b7 at end: ${o.clip.behaviour}`
      : 'nothing cued';

    const ctrl = c.controllers || [];
    document.getElementById('s-ctrl').innerHTML = ctrl.length
      ? ctrl.map(x => `${x.address} \u00b7 last: ${x.lastCommand || '-'} ` +
          `(${x.secondsSinceLastCommand}s ago)`).join('<br>')
      : '<span class="warn">none connected</span>';

    document.getElementById('s-net').innerHTML =
      (n.interfaces || []).map(i =>
        `${i.name} ${i.address} <span class="muted">(${i.state})</span>`).join('<br>')
      + (n.wifiBlocked === true ? '<br><span class="muted">Wi-Fi blocked</span>' : '');
    const wb = document.getElementById('wifibtn');
    wb.textContent = n.wifiBlocked ? 'Enable Wi-Fi' : 'Disable Wi-Fi';
    wb.dataset.enable = n.wifiBlocked ? '1' : '0';

    const bad = (h.decoderDrops || h.lateFrames);
    document.getElementById('s-health').innerHTML =
      `<span class="${bad ? 'warn' : ''}">decoder drops ${h.decoderDrops} \u00b7 ` +
      `late frames ${h.lateFrames}</span>`;
    document.getElementById('statusline').textContent = '';
  } catch (e) {
    document.getElementById('statusline').textContent = 'status unavailable';
  }
}

async function toggleWifi() {
  const on = document.getElementById('wifibtn').dataset.enable === '1';
  if (!on && !confirm('Disable Wi-Fi? Only do this if the deck is on Ethernet.')) return;
  try { await api('/system/wifi', 'POST', {enabled: on}); }
  catch (e) { alert(e.message); }
  loadStatus();
}

async function loadSettings() {
  const s = await api('/settings');
  const clips = await api('/media/workingset');
  const sel = document.getElementById('set-defaultClip');
  sel.innerHTML = '<option value="">(none - cue clip 1 and stop)</option>' +
    clips.workingset.map(c =>
      `<option value="${c.name}" ${c.name === s.defaultClip ? 'selected' : ''}>${c.name}</option>`).join('');
  document.getElementById('set-defaultBehaviour').value = s.defaultBehaviour;
  document.getElementById('set-stillDuration').value = s.stillDuration;
  document.getElementById('set-volume').value = s.volume;
}

async function saveSettings() {
  const msg = document.getElementById('setmsg');
  msg.textContent = 'Saving...';
  try {
    await api('/settings', 'PUT', {
      defaultClip: document.getElementById('set-defaultClip').value,
      defaultBehaviour: document.getElementById('set-defaultBehaviour').value,
      stillDuration: Number(document.getElementById('set-stillDuration').value),
      volume: Number(document.getElementById('set-volume').value),
    });
    msg.textContent = 'Saved.';
    setTimeout(() => msg.textContent = '', 3000);
  } catch (e) { msg.textContent = 'Failed: ' + e.message; }
}


async function reboot() {
  if (confirm('Reboot the deck now?')) await api('/system/reboot', 'POST');
}

async function shutdown() {
  if (!confirm('Shut the deck down? It will need the power cycling to start again.')) return;
  await api('/system/shutdown', 'POST');
  document.getElementById('updinfo').textContent =
    'Shutting down. Wait for the activity light to stop before removing power.';
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
       <td>${c.duration}</td>
       <td onclick="event.stopPropagation()">
         <select onchange="setBehaviour('${c.name}', this.value)">
           ${['auto','once','loop','hold'].map(b =>
             `<option value="${b}" ${b === c.behaviour ? 'selected' : ''}>${b}</option>`).join('')}
         </select>
       </td>
       <td class="del" onclick="event.stopPropagation(); del('${c.name}')">&times;</td>
     </tr>`).join('');
}

async function del(name) {
  if (!confirm('Delete ' + name + '?')) return;
  await api('/media/' + encodeURIComponent(name), 'DELETE');
  loadClips();
}

function upload(file) {
  return new Promise((resolve, reject) => {
    const box = document.getElementById('progress');
    const line = document.createElement('div');
    line.innerHTML = `${file.name} <div class="bar"><i></i></div>`;
    box.appendChild(line);
    const bar = line.querySelector('i');
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', '/media/upload/' + encodeURIComponent(file.name));
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + '%';
    };
    xhr.onload = () => {
      if (xhr.status < 300) { bar.style.width = '100%'; resolve(); }
      else { line.innerHTML = `${file.name} &mdash; rejected: ${xhr.responseText}`; reject(); }
    };
    xhr.onerror = () => { line.innerHTML = `${file.name} &mdash; upload failed`; reject(); };
    xhr.send(file);
  });
}

async function uploadAll(files) {
  for (const f of files) { try { await upload(f); } catch (e) {} }
  loadClips();
}

const drop = () => document.getElementById('drop');
document.addEventListener('DOMContentLoaded', () => {
  const d = drop();
  ['dragenter','dragover'].forEach(ev => d.addEventListener(ev, e => {
    e.preventDefault(); d.classList.add('over'); }));
  ['dragleave','drop'].forEach(ev => d.addEventListener(ev, e => {
    e.preventDefault(); d.classList.remove('over'); }));
  d.addEventListener('drop', e => uploadAll(e.dataTransfer.files));
  document.getElementById('file').addEventListener('change', e => uploadAll(e.target.files));
});

(async () => {
  const s = await api('/system');
  document.getElementById('model').textContent = s.model + ' \\u00b7 v' + s.softwareVersion;
  document.getElementById('fmt').textContent = s.videoFormat;
  await loadClips();
  refresh();
  checkUpdate();
  loadStatus();
  loadSettings();
  setInterval(refresh, 1000);
  setInterval(loadStatus, 5000);
})();
</script>
</body>
</html>
"""
