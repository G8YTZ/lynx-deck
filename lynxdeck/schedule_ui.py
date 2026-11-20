"""The schedule page, served at /schedule."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lynx Deck Schedule</title>
<style>
  :root { --red:#e10a0a; --bg:#111; --panel:#1c1c1c; --line:#333; --text:#eee; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); }
  header { background:var(--red); padding:14px 20px; font-size:20px; font-weight:700;
           display:flex; justify-content:space-between; align-items:center; }
  header a { color:#fff; font-size:14px; font-weight:400; }
  main { max-width:1000px; margin:0 auto; padding:20px; }
  .panel { background:var(--panel); border:1px solid var(--line);
           border-radius:8px; padding:16px; margin-bottom:18px; overflow-x:auto; }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  button { background:var(--red); color:#fff; border:0; border-radius:6px;
           padding:9px 16px; font-size:14px; font-weight:600; cursor:pointer; }
  button.ghost { background:#2a2a2a; border:1px solid var(--line); }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:middle; }
  th { font-size:12px; text-transform:uppercase; opacity:.6; }
  tr.off td { opacity:.45; }
  tr.now td { background:#2a1010; }
  input, select { background:#2a2a2a; color:var(--text); border:1px solid var(--line);
                  border-radius:5px; padding:5px 8px; font-size:14px; }
  .muted { opacity:.6; font-size:13px; }
  .days label { margin-right:8px; font-size:13px; white-space:nowrap; }
  .link { color:var(--red); cursor:pointer; text-decoration:underline; }
  .mono { font-family:ui-monospace,Menlo,Consolas,monospace; }
  .warn { color:#ffb454; }
</style>
</head>
<body>
<header>Lynx Deck Schedule <a href="/">Back to the Deck</a></header>
<main>
  <div class="panel">
    <div class="row" style="justify-content:space-between">
      <div><strong>On air now (by the schedule)</strong>
        <div id="nowline" class="muted">...</div></div>
      <div class="muted" id="clock"></div>
    </div>
  </div>

  <div class="panel">
    <strong id="formtitle">Add an entry</strong>
    <input type="hidden" id="f-id">
    <table style="margin-top:8px">
      <tr><th>Repeat</th><td>
        <select id="f-repeat" onchange="repeatChanged()">
          <option value="daily">at a time of day</option>
          <option value="hourly">every hour, at minutes:seconds</option>
        </select></td></tr>
      <tr><th>Time</th><td><input id="f-time" class="mono" size="9" placeholder="19:00">
        <span class="muted" id="f-timehint">hh:mm or hh:mm:ss, the time it reaches viewers</span></td></tr>
      <tr><th>Days</th><td class="days" id="f-days"></td></tr>
      <tr><th>Clip</th><td><select id="f-clip"></select></td></tr>
      <tr><th>In the guide</th><td><label><input type="checkbox" id="f-guide" onchange="guideChanged()">
        include this in the programme guide (EPG)</label></td></tr>
      <tr class="g-row"><th>Guide title</th><td><input id="f-title" size="40" maxlength="80"
        placeholder="empty: the clip's name"></td></tr>
      <tr class="g-row"><th>Guide length</th><td><input id="f-minutes" type="number" min="1" max="1440" style="width:90px">
        minutes <span class="muted">(empty: an hour, or until the next programme)</span></td></tr>
      <tr><th>On</th><td><input type="checkbox" id="f-enabled" checked></td></tr>
    </table>
    <div class="row" style="margin-top:12px">
      <button onclick="saveEntry()">Save</button>
      <button class="ghost" onclick="clearForm()">Clear</button>
      <span id="formmsg" class="muted"></span>
    </div>
  </div>

  <div class="panel">
    <strong>The schedule</strong>
    <div class="muted">Times are on-air times: the Deck cuts early by the clock's
      <i>ahead by</i> setting. After a cut, each clip does what its behaviour says.</div>
    <table style="margin-top:8px">
      <thead><tr><th>When</th><th>Days</th><th>Clip</th><th>In the guide</th><th></th></tr></thead>
      <tbody id="entries"></tbody>
    </table>
  </div>

  <div class="panel">
    <strong>The guide, next 24 hours</strong>
    <table style="margin-top:8px"><tbody id="guide"></tbody></table>
  </div>

  <div class="panel">
    <strong>Import from Companion</strong>
    <div class="muted">Brings in Companion's switched-on time-of-day triggers that cut the
      Deck to a clip: <span class="mono">EPG:</span> ones as programmes in the guide, the rest
      (the clock) outside it; the same clip every hour becomes one hourly entry. Its times
      become on-air times, so the Deck will cut them <i>ahead by</i> earlier. Entries already
      here are skipped; any whose clip is not on this Deck are added switched off.</div>
    <div class="row" style="margin-top:10px">
      <input id="c-addr" placeholder="Companion address, e.g. 192.168.40.103:8000" size="38">
      <button onclick="importFrom()">Import</button>
      <span class="muted">or an export file:</span>
      <input type="file" id="c-file" accept=".companionconfig,.json">
    </div>
    <div id="importmsg" class="muted" style="margin-top:8px"></div>
  </div>
</main>
<script>
const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
let entries = [], clips = [];

async function api(path, method='GET', body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof Blob) { opt.body = body; }
    else { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  }
  const r = await fetch(path, opt);
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch (e) { data = text; }
  if (!r.ok) throw new Error((data && data.detail) || text);
  return data;
}

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function daysText(d) {
  if (d.length === 7) return 'every day';
  if (d.join() === '0,1,2,3,4') return 'Mon to Fri';
  if (d.join() === '5,6') return 'Sat, Sun';
  return d.map(i => DAYS[i]).join(', ');
}

function repeatChanged() {
  const hourly = document.getElementById('f-repeat').value === 'hourly';
  document.getElementById('f-timehint').textContent = hourly
    ? 'mm:ss past each hour, e.g. 58:56' : 'hh:mm or hh:mm:ss, the time it reaches viewers';
  document.getElementById('f-time').placeholder = hourly ? '58:56' : '19:00';
}

function guideChanged() {
  const on = document.getElementById('f-guide').checked;
  document.querySelectorAll('.g-row').forEach(r => r.style.display = on ? '' : 'none');
}

function drawDays(sel) {
  document.getElementById('f-days').innerHTML = DAYS.map((d, i) =>
    `<label><input type="checkbox" value="${i}" ${sel.includes(i) ? 'checked' : ''}> ${d}</label>`).join('') +
    ' <span class="link" onclick="drawDays([0,1,2,3,4,5,6])">all</span>';
}

function drawClips(sel) {
  document.getElementById('f-clip').innerHTML = '<option value="">(choose a clip)</option>' +
    clips.map(c => `<option ${c === sel ? 'selected' : ''}>${esc(c)}</option>`).join('') +
    (sel && !clips.includes(sel) ? `<option selected>${esc(sel)}</option>` : '');
}

function clearForm() {
  document.getElementById('formtitle').textContent = 'Add an entry';
  ['f-id','f-time','f-title','f-minutes'].forEach(i => document.getElementById(i).value = '');
  document.getElementById('f-repeat').value = 'daily'; repeatChanged();
  document.getElementById('f-enabled').checked = true;
  document.getElementById('f-guide').checked = false; guideChanged();
  drawDays([0,1,2,3,4,5,6]); drawClips('');
  document.getElementById('formmsg').textContent = '';
}

function edit(id) {
  const e = entries.find(x => x.id === id);
  document.getElementById('formtitle').textContent = 'Change an entry';
  document.getElementById('f-id').value = e.id;
  document.getElementById('f-repeat').value = e.repeat; repeatChanged();
  document.getElementById('f-time').value = e.time;
  document.getElementById('f-title').value = e.title;
  document.getElementById('f-minutes').value = e.minutes || '';
  document.getElementById('f-enabled').checked = e.enabled;
  document.getElementById('f-guide').checked = e.guide; guideChanged();
  drawDays(e.days); drawClips(e.clip);
  window.scrollTo(0, 0);
}

async function saveEntry() {
  const msg = document.getElementById('formmsg');
  const days = [...document.querySelectorAll('#f-days input:checked')].map(i => Number(i.value));
  try {
    await api('/schedule/entries', 'PUT', {
      id: document.getElementById('f-id').value || undefined,
      repeat: document.getElementById('f-repeat').value,
      time: document.getElementById('f-time').value.trim(),
      days, clip: document.getElementById('f-clip').value,
      guide: document.getElementById('f-guide').checked,
      title: document.getElementById('f-title').value.trim(),
      minutes: Number(document.getElementById('f-minutes').value) || null,
      enabled: document.getElementById('f-enabled').checked,
    });
    clearForm(); msg.textContent = 'Saved.'; load();
  } catch (e) { msg.textContent = 'Not saved: ' + e.message; }
}

async function del(id) {
  const e = entries.find(x => x.id === id);
  if (!confirm('Delete ' + (e.title || e.clip) + ' at ' + e.time + '?')) return;
  await api('/schedule/entries/' + id, 'DELETE'); load();
}

async function toggle(id) {
  const e = entries.find(x => x.id === id);
  await api('/schedule/entries', 'PUT', {...e, enabled: !e.enabled}); load();
}

async function load() {
  const s = await api('/schedule/entries');
  entries = s.entries;
  clips = (await api('/media/workingset')).workingset.map(c => c.name);
  document.getElementById('nowline').innerHTML = s.now
    ? `${esc(s.now.title || s.now.clip)} <span class="muted">since ${esc(s.now.at)}</span>`
    : 'nothing scheduled yet';
  document.getElementById('entries').innerHTML = entries.map(e => `
    <tr class="${e.enabled ? '' : 'off'} ${s.now && s.now.id === e.id ? 'now' : ''}">
      <td class="mono">${e.repeat === 'hourly' ? 'every hour at ' + esc(e.time) : esc(e.time)}</td>
      <td>${daysText(e.days)}</td>
      <td>${esc(e.clip) || '<span class="warn">no clip</span>'}
        ${e.clip && !clips.includes(e.clip) ? ' <span class="warn">(not in the library)</span>' : ''}</td>
      <td>${e.guide ? esc(e.title) + (e.minutes ? ` <span class="muted">(${e.minutes} min)</span>` : '') : '<span class="muted">not in the guide</span>'}</td>
      <td style="white-space:nowrap">
        <span class="link" onclick="edit('${e.id}')">change</span> &nbsp;
        <span class="link" onclick="toggle('${e.id}')">${e.enabled ? 'switch off' : 'switch on'}</span> &nbsp;
        <span class="link" onclick="del('${e.id}')">delete</span></td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">No entries yet.</td></tr>';
  const g = await api('/schedule/guide?hours=24');
  document.getElementById('guide').innerHTML = g.guide.map(p => {
    const t = new Date(p.start);
    return `<tr><td class="mono">${t.toLocaleDateString('en-GB', {weekday:'short'})} ${t.toTimeString().slice(0,5)}</td>
      <td>${esc(p.title)}</td><td class="muted">${p.minutes} min</td></tr>`;
  }).join('') || '<tr><td class="muted">Nothing in the guide (tick <i>In the guide</i> on an entry).</td></tr>';
}

async function importFrom() {
  const msg = document.getElementById('importmsg');
  const file = document.getElementById('c-file').files[0];
  const addr = document.getElementById('c-addr').value.trim();
  if (!file && !addr) { msg.textContent = 'Give the Companion address or choose an export file.'; return; }
  msg.textContent = 'Importing...';
  try {
    const r = file ? await api('/schedule/import', 'POST', file)
                   : await api('/schedule/import?companion=' + encodeURIComponent(addr), 'POST');
    msg.innerHTML = `Added ${r.added} entries` + (r.skipped ? `, ${r.skipped} already here` : '') + '.' +
      (r.notes.length ? '<br>' + r.notes.map(esc).join('<br>') : '');
    load();
  } catch (e) { msg.textContent = 'Import failed: ' + e.message; }
}

setInterval(() => {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');
}, 500);
clearForm();
load();
setInterval(load, 15000);
</script>
</body>
</html>
"""
