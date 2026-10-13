// At2-Radio : page de programmation. Dépend de js/base.js (kit : $, $$, esc, toast, store, NAV, showView, wireNav…).
'use strict';

// ---------- Appels au service ----------
let apiKey = '';
try { apiKey = sessionStorage.getItem('at2key') || ''; } catch { /* navigation privée */ }

function askKey() {
  return new Promise((resolve) => {
    const dlg = $('#dlg-key');
    $('#key-form').onsubmit = () => {
      apiKey = $('#key-input').value.trim();
      try { sessionStorage.setItem('at2key', apiKey); } catch { /* ignoré */ }
      resolve();
    };
    if (!dlg.open) dlgOpen(dlg);
    setTimeout(() => $('#key-input').focus(), 20);
  });
}

async function call(method, path, body, retry = true) {
  const headers = apiKey ? { Authorization: `Bearer ${apiKey}` } : {};
  let payload;
  if (body instanceof Blob || body instanceof ArrayBuffer || typeof body === 'string') payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const r = await fetch(path, { method, headers, body: payload, cache: 'no-store' });
  if (r.status === 401 && retry) { await askKey(); return call(method, path, body, false); }
  if (r.status === 204) return null;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error((j.error && j.error.message) || (r.status === 422 ? 'Valeur refusée par le service' : r.statusText) || 'Erreur');
    e.status = r.status; e.code = j.error && j.error.code;
    throw e;
  }
  return j;
}
const fail = (e) => toast(e.message || String(e), true);
const rid = () => encodeURIComponent($('#radio-id').value.trim() || 'radio1');
const base = () => `/v1/radios/${rid()}`;

// ---------- État de connexion ----------
let connected = false;
function showStatus(s) {
  connected = !!s && s.status === 'connectée';
  const pill = $('#status-pill');
  pill.classList.toggle('up', connected);
  pill.classList.toggle('lost', !!s && s.status === 'perdue');
  $('#status-label').textContent = connected ? (s.kind === 'ble' ? 'Bluetooth' : 'USB') + ' · ' + s.target : 'Non connectée';
  $('#conn-sub').textContent = connected ? 'connectée' + (s.current_channel ? ` · canal ${s.current_channel}` : '') : 'non connectée';
  $('#btn-connect').hidden = connected;
  $('#btn-disconnect').hidden = !connected;
}
async function refreshStatus() {
  try { showStatus(await call('GET', `${base()}/status`)); }
  catch (e) { if (e.status === 404) showStatus(null); }
}

// ---------- Radio : recherche et connexion ----------
let kind = 'ble';
wireSeg($('#kind-seg'), (v) => { kind = v; $('#target-select').innerHTML = '<option value="">— cherche d\'abord —</option>'; });

$('#btn-scan').onclick = async () => {
  const btn = $('#btn-scan'); btn.setAttribute('disabled', ''); btn.textContent = 'Recherche…';
  try {
    const rows = kind === 'ble' ? await call('POST', '/v1/ble/scan?timeout=5') : await call('GET', '/v1/serial/ports');
    const sel = $('#target-select');
    sel.innerHTML = rows.length
      ? rows.map((r) => kind === 'ble'
          ? `<option value="${esc(r.address)}">${esc(r.name)} · ${esc(r.address)} · ${r.rssi} dBm</option>`
          : `<option value="${esc(r.path)}">${esc(r.path)} · ${esc(r.description)}</option>`).join('')
      : '<option value="">Rien trouvé</option>';
    if (!rows.length) toast(kind === 'ble' ? 'Aucune radio Bluetooth à portée : allume-la et rapproche-toi.' : 'Aucun port USB trouvé.', true);
  } catch (e) { fail(e); }
  btn.removeAttribute('disabled'); btn.textContent = 'Chercher';
};

$('#btn-connect').onclick = async () => {
  const target = $('#target-manual').value.trim() || $('#target-select').value;
  if (!target) return toast('Choisis un appareil ou saisis une adresse.', true);
  const btn = $('#btn-connect'); btn.setAttribute('disabled', ''); btn.textContent = 'Connexion…';
  try {
    showStatus(await call('POST', `${base()}/connect`, { kind, target }));
    toast('Radio connectée');
    openEvents();
  } catch (e) { fail(e); }
  btn.removeAttribute('disabled'); btn.textContent = 'Connecter';
};
$('#btn-disconnect').onclick = async () => {
  try { showStatus(await call('POST', `${base()}/disconnect`)); toast('Radio déconnectée'); } catch (e) { fail(e); }
};
$('#radio-id').addEventListener('change', () => { refreshStatus(); openEvents(); });

// ---------- Canaux ----------
const FLAGS = [['bandwidth_narrow', 'Bande étroite'], ['high_power', 'Puissance haute'], ['scan_add', 'Dans le scan'],
  ['mode_digital', 'Numérique'], ['busy_lock', 'Busy lock'], ['hop_on', 'Saut de fréquence']];
let tones = ['OFF'];
const fmtMhz = (v) => (v == null ? '' : String(v).replace('.', ','));
const parseMhz = (s) => {
  const t = String(s).trim().replace(',', '.');
  if (!t) return null;
  const v = Number(t);
  if (!isFinite(v) || v < 30 || v > 520) throw new Error(`Fréquence invalide : « ${s} » (30 à 520 MHz)`);
  return v;
};

function buildChannelRows() {
  const opts = tones.map((t) => `<option>${esc(t)}</option>`).join('');
  $('#ch-body').innerHTML = Array.from({ length: 30 }, (_, i) => `<tr data-ch="${i + 1}" class="empty-row">
    <td class="num-ch">${String(i + 1).padStart(2, '0')}</td>
    <td><input class="mhz" data-f="rx_mhz" inputmode="decimal" aria-label="RX canal ${i + 1}"></td>
    <td><input class="mhz" data-f="tx_mhz" inputmode="decimal" aria-label="TX canal ${i + 1}"></td>
    <td><select data-f="rx_tone" aria-label="Ton RX canal ${i + 1}">${opts}</select></td>
    <td><select data-f="tx_tone" aria-label="Ton TX canal ${i + 1}">${opts}</select></td>
    ${FLAGS.map(([f, l]) => `<td class="c"><input type="checkbox" data-f="${f}" aria-label="${l} canal ${i + 1}"></td>`).join('')}
    <td><input class="key" type="number" min="0" max="31" data-f="encrypt_key" aria-label="Clé canal ${i + 1}"></td>
    <td class="acts"><button class="btn small" type="button" data-write="${i + 1}">Écrire</button></td></tr>`).join('');
}

function fillRow(n, c, dirty = false) {
  const tr = $(`#ch-body tr[data-ch="${n}"]`);
  const set = (f, v) => { const el = tr.querySelector(`[data-f="${f}"]`); if (el.type === 'checkbox') el.checked = !!v; else el.value = v; };
  set('rx_mhz', fmtMhz(c.rx_mhz)); set('tx_mhz', fmtMhz(c.tx_mhz));
  set('rx_tone', c.rx_tone); set('tx_tone', c.tx_tone); set('encrypt_key', c.encrypt_key);
  FLAGS.forEach(([f]) => set(f, c[f]));
  tr.classList.toggle('empty-row', c.rx_mhz == null && c.tx_mhz == null);
  tr.classList.toggle('dirty', dirty);
  tr.classList.remove('bad'); tr.title = '';
}

function rowConfig(n) {
  const tr = $(`#ch-body tr[data-ch="${n}"]`);
  const get = (f) => tr.querySelector(`[data-f="${f}"]`);
  const cfg = { rx_mhz: parseMhz(get('rx_mhz').value), tx_mhz: parseMhz(get('tx_mhz').value),
    rx_tone: get('rx_tone').value, tx_tone: get('tx_tone').value, encrypt_key: Number(get('encrypt_key').value || 0) };
  FLAGS.forEach(([f]) => { cfg[f] = get(f).checked; });
  if (cfg.rx_mhz != null && cfg.tx_mhz == null) cfg.tx_mhz = cfg.rx_mhz;
  return cfg;
}

function markResult(n, res) {
  if (res.actual) fillRow(n, res.actual, false);
  const tr = $(`#ch-body tr[data-ch="${n}"]`);
  tr.classList.remove('dirty');
  tr.classList.toggle('bad', !res.verified);
  tr.title = res.verified ? '' : 'La radio renvoie autre chose : ' + res.differences.join(' ; ');
}

$('#ch-body').addEventListener('input', (e) => { const tr = e.target.closest('tr'); if (tr) tr.classList.add('dirty'); });
$('#ch-body').addEventListener('change', (e) => { const tr = e.target.closest('tr'); if (tr) tr.classList.add('dirty'); });
$('#ch-body').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-write]');
  if (!b) return;
  const n = Number(b.dataset.write);
  try {
    b.setAttribute('disabled', '');
    const res = await call('PUT', `${base()}/channels/${n}`, rowConfig(n));
    markResult(n, res);
    $('#ch-result').textContent = res.verified ? `Canal ${n} : enregistré et vérifié.` : `Canal ${n} : écrit, mais la radio renvoie autre chose (${res.differences.join(' ; ')}).`;
    toast(res.verified ? 'Enregistré et vérifié' : 'Écrit, mais pas confirmé par la relecture', !res.verified);
  } catch (err) { fail(err); }
  b.removeAttribute('disabled');
});

$('#btn-read-all').onclick = async () => {
  const b = $('#btn-read-all'); b.setAttribute('disabled', ''); b.textContent = 'Lecture…';
  try {
    const list = await call('GET', `${base()}/channels`);
    list.forEach((c) => fillRow(c.channel, c));
    $('#ch-sub').textContent = 'lus à l\'instant';
    $('#ch-result').textContent = '30 canaux lus.';
  } catch (e) { fail(e); }
  b.removeAttribute('disabled'); b.textContent = 'Lire les 30 canaux';
};

$('#btn-write-all').onclick = async () => {
  if (!confirmDanger('Écrire les 30 canaux dans la radio ? Leur contenu actuel sera remplacé.')) return;
  let configs;
  try { configs = Array.from({ length: 30 }, (_, i) => ({ channel: i + 1, ...rowConfig(i + 1) })); } catch (e) { return fail(e); }
  const b = $('#btn-write-all'); b.setAttribute('disabled', ''); b.textContent = 'Écriture…';
  try {
    const res = await call('PUT', `${base()}/channels`, configs);
    res.forEach((r) => markResult(r.channel, r));
    const bad = res.filter((r) => !r.verified);
    $('#ch-result').textContent = bad.length ? `${bad.length} canal(aux) écrit(s) mais non confirmé(s) par la relecture : ${bad.map((r) => r.channel).join(', ')}.` : '30 canaux enregistrés et vérifiés.';
    toast(bad.length ? 'Écrits, mais certains ne sont pas confirmés' : 'Enregistré et vérifié', !!bad.length);
  } catch (e) { fail(e); }
  b.removeAttribute('disabled'); b.textContent = 'Écrire les 30 canaux';
};

$('#btn-import').onclick = () => $('#xml-file').click();
$('#xml-file').onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try {
    const list = await call('POST', '/v1/cps-xml/parse', await f.arrayBuffer());
    list.forEach((c) => fillRow(c.channel, c, true));
    $('#ch-result').textContent = `${list.length} canaux importés. Ils ne sont pas encore écrits : relis-les, puis écris.`;
    toast('Import terminé');
  } catch (err) { fail(err); }
};

// ---------- Réglages ----------
// type : sw = interrupteur, range = curseur, text/number/select = champ
const GROUPS = [
  ['Audio', [
    { n: 'volume', label: 'Volume', t: 'range', min: 1, max: 8 },
    { n: 'squelch', label: 'Squelch', help: 'Plus il est haut, plus le signal doit être fort pour ouvrir le son.', t: 'range', min: 0, max: 9 },
    { n: 'noise_reduction', label: 'Réduction de bruit', t: 'sw' },
    { n: 'prompt_tone', label: 'Tonalité de confirmation', t: 'sw' }]],
  ['Émission', [
    { n: 'tot_seconds', label: 'Temporisation d\'émission', help: '0 = désactivée, 240 s au maximum.', t: 'range', min: 0, max: 240, step: 10, unit: ' s' },
    { n: 'tx_interval_seconds', label: 'Intervalle entre émissions', help: '0 = désactivé, 240 s au maximum.', t: 'range', min: 0, max: 240, step: 10, unit: ' s' },
    { n: 'tx_inhibit', label: 'Interdire l\'émission', help: 'Bloque tout envoi depuis la radio.', t: 'sw' }]],
  ['Activation vocale (VOX)', [
    { n: 'vox', label: 'VOX activé', t: 'sw' },
    { n: 'vox_sensitivity', label: 'Sensibilité du VOX', t: 'range', min: 1, max: 5 }]],
  ['Appareil', [
    { n: 'device_name', label: 'Nom de l\'appareil', help: 'La radio ne renvoie pas son nom : le champ reste vide tant que tu n\'en saisis pas un.', t: 'text', write: true },
    { n: 'prompt_language', label: 'Annonces vocales en anglais', help: 'Décoché : en chinois.', t: 'sw' },
    { n: 'smart_link', label: 'Smart Link', help: 'Pont vers des applications tierces.', t: 'sw' },
    { n: 'main_ptt_target', label: 'Bouton PTT principal (appui long)', help: 'Application ouverte par l\'appui long.', t: 'select', write: true,
      options: [['', '— ne pas changer —'], ['zello', 'Zello'], ['olaradio', 'Olaradio'], ['autre1', 'Autre 1'], ['autre2', 'Autre 2'], ['autre3', 'Autre 3'], ['autre4', 'Autre 4']] }]],
];
let spec = {};
let values = {};
const dirty = new Map();
const readOnlyOnce = new Set(['device_name', 'main_ptt_target']);   // pas relus

function renderSettings() {
  const cols = [[], []];
  GROUPS.forEach(([title, items], gi) => {
    const rows = items.map((it) => {
      const st = spec[it.n] ? spec[it.n].status : '';
      const unverified = st && st !== 'relu sur matériel';
      const tag = unverified ? ` <span class="tag no" title="${esc(st)}">non vérifié</span>` : '';
      const help = it.help ? `<small>${esc(it.help)}</small>` : '';
      let ctl = '';
      if (it.t === 'sw') ctl = `<label class="sw"><input type="checkbox" data-s="${it.n}"><i></i></label>`;
      else if (it.t === 'range') ctl = `<input type="range" data-s="${it.n}" min="${it.min}" max="${it.max}" step="${it.step || 1}"><span class="val" data-v="${it.n}">—</span>`;
      else if (it.t === 'text') ctl = `<input type="text" data-s="${it.n}" maxlength="24" placeholder="AT2_XXXX">`;
      else ctl = `<select data-s="${it.n}">${it.options.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('')}</select>`;
      return `<div class="srow" data-row="${it.n}"><div class="lab">${esc(it.label)}${tag}${help}</div><div class="ctl">${ctl}</div></div>`;
    }).join('');
    cols[gi % 2].push(`<div class="sgroup"><h3>${esc(title)}</h3>${rows}</div>`);
  });
  // Dual Watch : actions immédiates (la radio ne relit pas les canaux A et B)
  cols[1].push(`<div class="sgroup"><h3>Dual Watch</h3>
    <div class="srow" data-row="dual_watch"><div class="lab">Dual Watch activé<small>Écoute deux canaux, A et B.</small></div><div class="ctl"><label class="sw"><input type="checkbox" data-s="dual_watch"><i></i></label></div></div>
    <div class="srow"><div class="lab">Canal A<small>Envoyé tout de suite.</small></div><div class="ctl"><input type="number" min="1" max="30" value="1" id="dw-a"><button class="btn small" type="button" data-dw="A">Envoyer</button></div></div>
    <div class="srow"><div class="lab">Canal B<small>Envoyé tout de suite.</small></div><div class="ctl"><input type="number" min="1" max="30" value="2" id="dw-b"><button class="btn small" type="button" data-dw="B">Envoyer</button></div></div>
    <div class="srow"><div class="lab">Canal actif pour le PTT</div><div class="ctl"><div class="seg" id="dw-focus"><button type="button" data-v="A" aria-selected="false">Focus A</button><button type="button" data-v="B" aria-selected="false">Focus B</button></div></div></div></div>`);
  $('#settings-root').innerHTML = cols.map((c) => `<div>${c.join('')}</div>`).join('');
  wireSeg($('#dw-focus'), async (v) => {
    try { await call('PUT', `${base()}/dual-watch?side=${v}&focus=true`); toast(`Focus sur ${v}`); } catch (e) { fail(e); }
  });
}

function paintSetting(name) {
  const el = $(`[data-s="${name}"]`);
  if (!el || !(name in values) || values[name] == null) return;
  const v = values[name];
  if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
  const lab = $(`[data-v="${name}"]`);
  if (lab) { const it = GROUPS.flatMap((g) => g[1]).find((x) => x.n === name); lab.textContent = v + (it && it.unit || ''); }
}

function setDirty(name, value) {
  dirty.set(name, value);
  const row = $(`[data-row="${name}"]`); if (row) row.classList.add('dirty');
  $('#dirty-tag').hidden = false; $('#btn-apply-settings').removeAttribute('disabled');
}
function clearDirty() {
  dirty.clear();
  $$('.srow.dirty').forEach((r) => r.classList.remove('dirty'));
  $('#dirty-tag').hidden = true; $('#btn-apply-settings').setAttribute('disabled', '');
}

$('#settings-root').addEventListener('input', (e) => {
  const el = e.target.closest('[data-s]'); if (!el) return;
  const name = el.dataset.s;
  const v = el.type === 'checkbox' ? el.checked : (el.type === 'range' ? Number(el.value) : el.value);
  const lab = $(`[data-v="${name}"]`);
  if (lab) { const it = GROUPS.flatMap((g) => g[1]).find((x) => x.n === name); lab.textContent = v + (it && it.unit || ''); }
  if (el.type === 'text' && !String(v).trim()) { dirty.delete(name); return; }
  if (el.tagName === 'SELECT' && !v) { dirty.delete(name); return; }
  setDirty(name, v);
});
$('#settings-root').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-dw]'); if (!b) return;
  const side = b.dataset.dw, ch = Number($(`#dw-${side.toLowerCase()}`).value);
  try { await call('PUT', `${base()}/dual-watch?side=${side}&channel=${ch}`); toast(`Canal ${ch} envoyé pour le côté ${side}`); } catch (err) { fail(err); }
});

async function readSettings() {
  const b = $('#btn-read-settings'); b.setAttribute('disabled', ''); b.textContent = 'Lecture…';
  try {
    values = await call('GET', `${base()}/settings`);
    Object.keys(values).forEach(paintSetting);
    clearDirty();
    const n = Object.values(values).filter((v) => v != null).length;
    $('#set-sub').textContent = `${n} réglages lus`;
    const missing = Object.entries(values).filter(([, v]) => v == null).map(([k]) => k);
    if (missing.length) toast(`${missing.length} réglage(s) sans réponse de la radio`, true);
  } catch (e) { fail(e); }
  b.removeAttribute('disabled'); b.textContent = 'Relire les réglages';
}
$('#btn-read-settings').onclick = readSettings;

$('#btn-apply-settings').onclick = async () => {
  const entries = [...dirty.entries()];
  if (!entries.length) return;
  const b = $('#btn-apply-settings'); b.setAttribute('disabled', ''); b.textContent = 'Envoi…';
  const errors = [];
  for (const [name, value] of entries) {
    try { await call('PUT', `${base()}/settings/${name}`, { value }); } catch (e) { errors.push(`${name} : ${e.message}`); }
  }
  // vérification : on relit et on compare (sauf les réglages que la radio ne renvoie pas)
  await new Promise((r) => setTimeout(r, 400));
  let changed = [];
  try {
    const after = await call('GET', `${base()}/settings`);
    changed = entries.filter(([n, v]) => !readOnlyOnce.has(n) && after[n] != null && after[n] !== v).map(([n]) => n);
    values = after; Object.keys(values).forEach(paintSetting);
  } catch (e) { errors.push(e.message); }
  clearDirty();
  b.textContent = 'Appliquer les changements';
  if (errors.length) toast(errors[0], true);
  else if (changed.length) toast(`La radio n'a pas pris : ${changed.join(', ')}`, true);
  else toast('Réglages appliqués et relus');
};


// ---------- Messagerie ----------
const chatLog = (cls, who, html) => {
  const box = $('#chat-log');
  const d = document.createElement('div'); d.className = 'msg ' + cls;
  d.innerHTML = `<span class="who">${esc(who)}</span>${html}`;
  box.appendChild(d); box.scrollTop = box.scrollHeight;
};
function showIncoming(m) {
  const who = m.sender || '?';
  if (m.type === 'image' && m.data) chatLog('in', who, `<img alt="image reçue" src="data:image/jpeg;base64,${m.data}">`);
  else if (m.type === 'voice') chatLog('in', who, `Message vocal reçu${m.duration_ms ? ' (' + (m.duration_ms / 1000).toFixed(1) + ' s)' : ''}`);
  else if (m.lat != null) chatLog('in', who, `${m.type === 'sos' ? '<b>SOS</b> ' : ''}${esc(m.text || '')} 📍 ${m.lat}, ${m.lon}`);
  else chatLog('in', who, esc(m.text || ''));
}
const sender = () => $('#chat-sender').value.trim() || 'At2Radio';
function setChat(open) {
  $('#btn-chat-open').hidden = open; $('#btn-chat-close').hidden = !open;
  $('#chat-sub').textContent = open ? 'session ouverte' : 'session fermée';
}
$('#btn-chat-open').onclick = async () => {
  try { await call('POST', `${base()}/chat/open`); setChat(true); toast('Session ouverte'); } catch (e) { fail(e); }
};
$('#btn-chat-close').onclick = async () => {
  try { await call('POST', `${base()}/chat/close`); setChat(false); } catch (e) { fail(e); }
};
async function send(label, fn, echo) {
  try { await fn(); chatLog('out', sender(), echo); setChat(true); return true; } catch (e) { fail(e); return false; }
}
$('#btn-send-text').onclick = () => {
  const text = $('#chat-text').value.trim();
  if (!text) return;
  send('texte', () => call('POST', `${base()}/messages/text`, { sender: sender(), text }), esc(text))
    .then((ok) => { if (ok) $('#chat-text').value = ''; });
};
$('#chat-text').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#btn-send-text').click(); });
function readPos() {
  const lat = Number($('#pos-lat').value.replace(',', '.')), lon = Number($('#pos-lon').value.replace(',', '.'));
  if (!$('#pos-lat').value || !$('#pos-lon').value || !isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    toast('Latitude et longitude invalides', true); return null;
  }
  return { lat, lon };
}
$('#btn-send-pos').onclick = () => {
  const p = readPos(); if (!p) return;
  send('position', () => call('POST', `${base()}/messages/position`, { sender: sender(), ...p }), `📍 ${p.lat}, ${p.lon}`);
};
$('#btn-send-sos').onclick = () => {
  const p = readPos(); if (!p) return;
  if (!confirmDanger('Envoyer un SOS à toutes les radios à portée ?')) return;
  const message = $('#chat-text').value.trim() || 'SOS';
  send('sos', () => call('POST', `${base()}/messages/sos`, { sender: sender(), message, ...p }), `<b>SOS</b> ${esc(message)} 📍 ${p.lat}, ${p.lon}`);
};
$('#btn-send-image').onclick = () => $('#img-file').click();
$('#img-file').onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try {
    const bmp = await createImageBitmap(f);
    const k = Math.min(1, 300 / Math.max(bmp.width, bmp.height));
    const cv = document.createElement('canvas');
    cv.width = Math.max(1, Math.round(bmp.width * k)); cv.height = Math.max(1, Math.round(bmp.height * k));
    cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
    const blob = await new Promise((r) => cv.toBlob(r, 'image/jpeg', 0.75));
    const q = `sender=${encodeURIComponent(sender())}&width=${bmp.width}&height=${bmp.height}`;
    await call('POST', `${base()}/messages/image?${q}`, blob);
    chatLog('out', sender(), `<img alt="image envoyée" src="${cv.toDataURL('image/jpeg', 0.75)}">`);
    setChat(true);
  } catch (err) { fail(err); }
};

// ---------- Push-to-talk ----------
let pttWs = null, pttCtx = null, pttStream = null, pttProc = null, pttNext = 0, pttBuf = [];
const pttTag = (t) => { $('#ptt-tag').textContent = t; $('#ptt-sub').textContent = t; };
function playPcm(ab) {
  if (!pttCtx) return;
  const i16 = new Int16Array(ab), f = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) f[i] = i16[i] / 32768;
  const b = pttCtx.createBuffer(1, f.length, 8000); b.copyToChannel(f, 0);
  const src = pttCtx.createBufferSource(); src.buffer = b; src.connect(pttCtx.destination);
  pttNext = Math.max(pttNext, pttCtx.currentTime + 0.05);
  src.start(pttNext); pttNext += b.duration;
}
async function pttStart() {
  if (pttWs) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return toast('Micro indisponible : ouvre la page en https ou en localhost.', true);
  try {
    pttCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 8000 });
    pttStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) { pttStop(); return toast('Micro refusé ou indisponible', true); }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  pttWs = new WebSocket(`${proto}://${location.host}${base()}/ptt${apiKey ? '?key=' + encodeURIComponent(apiKey) : ''}`);
  pttWs.binaryType = 'arraybuffer';
  pttWs.onmessage = (m) => playPcm(m.data);
  pttWs.onclose = () => { if (pttWs) { toast('Session PTT fermée par le service (canal numérique ? codec installé ?)', true); } pttStop(); };
  pttWs.onopen = () => {
    pttTag('émission'); $('#btn-ptt').classList.add('on');
    const src = pttCtx.createMediaStreamSource(pttStream);
    pttProc = pttCtx.createScriptProcessor(2048, 1, 1);
    pttProc.onaudioprocess = (ev) => {
      const inp = ev.inputBuffer.getChannelData(0);
      for (let i = 0; i < inp.length; i++) pttBuf.push(Math.max(-1, Math.min(1, inp[i])) * 32767 | 0);
      while (pttBuf.length >= 160 && pttWs && pttWs.readyState === 1) pttWs.send(Int16Array.from(pttBuf.splice(0, 160)).buffer);
    };
    src.connect(pttProc); pttProc.connect(pttCtx.destination);
  };
}
function pttStop() {
  const w = pttWs; pttWs = null;
  if (w) { w.onclose = null; try { w.close(); } catch { /* déjà fermée */ } }
  if (pttProc) { pttProc.disconnect(); pttProc = null; }
  if (pttStream) { pttStream.getTracks().forEach((t) => t.stop()); pttStream = null; }
  if (pttCtx) { pttCtx.close().catch(() => {}); pttCtx = null; }
  pttBuf = []; pttNext = 0;
  $('#btn-ptt').classList.remove('on'); pttTag('silence');
}
const pttBtn = $('#btn-ptt');
pttBtn.addEventListener('pointerdown', (e) => { e.preventDefault(); pttBtn.setPointerCapture(e.pointerId); pttStart(); });
['pointerup', 'pointercancel'].forEach((n) => pttBtn.addEventListener(n, pttStop));

// ---------- Diagnostic : journal des trames en direct ----------
let ws = null, wsFor = '', lines = [];
function renderLog() {
  const f = $('#diag-filter').value.trim().toLowerCase();
  const shown = f ? lines.filter((l) => l.toLowerCase().includes(f)) : lines;
  $('#diag-log').innerHTML = shown.slice(-600).map((l) => `<span class="${l.startsWith('TX') ? 'tx' : l.startsWith('RX') ? 'rx' : ''}">${esc(l)}</span>`).join('\n');
  $('#diag-sub').textContent = `${lines.length} ligne(s)`;
  const el = $('#diag-log'); el.scrollTop = el.scrollHeight;
}
function openEvents() {
  const id = decodeURIComponent(rid());
  if (ws && wsFor === id && ws.readyState <= 1) return;
  if (ws) { ws.onclose = null; ws.close(); }
  wsFor = id;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}${base()}/events?frames=true${apiKey ? '&key=' + encodeURIComponent(apiKey) : ''}`);
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.event === 'frame') { lines.push(ev.data); if (lines.length > 2000) lines.splice(0, 500); if (NAV.cur === 'diag') renderLog(); }
    else if (ev.event === 'connection' || ev.event === 'state') refreshStatus();
    else if (ev.event === 'hello') showStatus(ev.data);
    else if (ev.event === 'message') showIncoming(ev.data);
    else if (ev.event === 'ptt_state' && !pttWs) pttTag(ev.data === 'rx' ? 'réception' : 'silence');
  };
  ws.onclose = () => { setTimeout(() => { if (wsFor === id) openEvents(); }, 4000); };
}
$('#diag-filter').addEventListener('input', renderLog);
$('#btn-diag-clear').onclick = () => { lines = []; renderLog(); };
$('#btn-diag-copy').onclick = async () => {
  try { await navigator.clipboard.writeText(lines.join('\n')); toast('Copié'); } catch { toast('Copie impossible : utilise Exporter', true); }
};
$('#btn-diag-export').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/plain' }));
  a.download = `at2radio-trames-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
  a.click(); URL.revokeObjectURL(a.href);
};

// ---------- Démarrage ----------
NAV.onShow.radio = refreshStatus;
NAV.onShow.diag = renderLog;
NAV.onShow.settings = () => { if (connected && !Object.keys(values).length) readSettings(); };
NAV.onShow.channels = () => {};

(async () => {
  try { tones = await call('GET', '/v1/tones'); } catch (e) { if (e.status !== 401) fail(e); }
  try { spec = await call('GET', '/v1/settings-spec'); } catch { /* sans les statuts */ }
  buildChannelRows();
  renderSettings();
  wireNav();
  await refreshStatus();
  openEvents();
  setInterval(refreshStatus, 5000);
})();
