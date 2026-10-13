/* =====================================================================
   Kit de design des apps maison : FONCTIONS COMMUNES (JavaScript sans dépendance)
   Formats français, appels d'API, notifications, dialogues, mémoire locale,
   navigation latérale (vues, mode réduit, tiroir mobile) et recherche rapide.
   ===================================================================== */

// ---------- Raccourcis DOM ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
// toujours échapper ce qui vient des données avant de l'insérer en HTML
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- Formats français (valeur absente : tiret cadratin) ----------
const NONE = '—';
const n2 = (v, d = 2) => (v == null || isNaN(v) ? NONE : v.toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }));
const eur = (v, d = 0) => (v == null || isNaN(v) ? NONE : v.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', minimumFractionDigits: d, maximumFractionDigits: d }));
const unit = (v, u, d = 1) => (v == null || isNaN(v) ? NONE : `${n2(v, d)} ${u}`);          // « 22,5 °C », « 466 ppm »
const pct = (v, d = 1) => (v == null ? '' : `<span class="pill ${v >= 0 ? 'g' : 'l'}">${v >= 0 ? '+' : '−'}${n2(Math.abs(v), d)} %</span>`);
const kfmt = (v) => (Math.abs(v) >= 1000 ? n2(v / 1000, Math.abs(v) < 10000 ? 1 : 0) + ' k' : String(Math.round(v)));   // axes de graphiques
const dfmt = (d) => (d ? String(d).slice(0, 10).split('-').reverse().join('/') : NONE);   // 2026-10-13 -> 13/10/2026
const hfmt = (iso) => (iso ? String(iso).slice(11, 16).replace(':', ' h ') : NONE);       // -> 17 h 32
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const MOIS_C = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
function ago(t) {   // durée relative
  if (!t) return 'jamais';
  const s = Math.max(0, (Date.now() - (typeof t === 'number' ? t * 1000 : new Date(t))) / 1000);
  if (s < 90) return 'à l’instant';
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return `il y a ${Math.round(s / 86400)} j`;
}

// ---------- Appels d'API : JSON, message d'erreur lisible ----------
async function api(path, opt = {}) {
  if (opt.json !== undefined) { opt = { ...opt, method: opt.method || 'POST', headers: { 'Content-Type': 'application/json', ...(opt.headers || {}) }, body: JSON.stringify(opt.json) }; delete opt.json; }
  const r = await fetch(path, { cache: 'no-store', ...opt });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText || 'Erreur');
  return j;
}

// ---------- Notification (pilule en bas, 3 s) ----------
function toast(text, bad = false) {
  const d = document.createElement('div');
  d.className = 'toast' + (bad ? ' bad' : ''); d.setAttribute('role', 'status'); d.textContent = text;
  document.body.append(d); setTimeout(() => d.remove(), 3000);
}
// action avec retour : « Enregistré » ou le message d'erreur
async function act(fn, ok) { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, true); } }

// ---------- Dialogues natifs <dialog class="dlg"> ----------
const dlgOpen = (d) => (typeof d === 'string' ? $(d) : d).showModal();
const dlgClose = (d) => (typeof d === 'string' ? $(d) : d).close();
const dialogOpen = () => !!$('dialog[open]');
// confirmation simple, ou forte (recopier un mot) pour une suppression grave
function confirmDanger(message, word) {
  if (!word) return confirm(message);
  const v = prompt(`${message}\n\nRecopie « ${word} » pour confirmer :`);
  return v != null && v.trim() === word;
}

// ---------- Mémoire locale (préférences d'affichage seulement, jamais de données) ----------
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* navigation privée */ } },
};

// ---------- Onglets segmentés et puces ----------
// <div class="seg" data-seg="periode"><button aria-selected="true" data-v="m">Mois</button>…</div>
function wireSeg(root, cb) {
  $$('button', root).forEach((b) => b.addEventListener('click', () => {
    $$('button', root).forEach((x) => x.setAttribute('aria-selected', x === b)); cb && cb(b.dataset.v);
  }));
}
// <div class="chips"><button aria-pressed="false" data-v="x">…</button></div> : bascule indépendante
function wireChips(root, cb) {
  $$('button', root).forEach((b) => b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', on); cb && cb(b.dataset.v, on);
  }));
}
// <div class="range"><button data-r="24h">24 h</button>…</div>
function wireRange(root, cb) {
  $$('button', root).forEach((b) => b.addEventListener('click', () => {
    $$('button', root).forEach((x) => x.setAttribute('aria-pressed', x === b)); cb && cb(b.dataset.r);
  }));
}

// ---------- Navigation : vues, sous-pages, ancre d'URL, mode réduit, tiroir mobile ----------
// Chaque bouton de .tabs porte data-view="nom" ; chaque vue est <div class="grid view" id="v-nom">.
// L'URL suit la vue (#/nom) : le bouton Retour du navigateur et les favoris fonctionnent.
const NAV = { cur: null, onShow: {} };   // NAV.onShow.nom = () => {…} : chargement d'une vue
function showView(name, push = true) {
  if (!$(`#v-${name}`)) name = $('.tabs [data-view]').dataset.view;
  NAV.cur = name;
  $$('.tabs [data-view]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.view === name));
  $$('.view').forEach((v) => (v.hidden = v.id !== 'v-' + name));
  const t = $(`.tabs [data-view="${name}"] .nl`); if (t && $('#mob-title')) $('#mob-title').textContent = t.textContent;
  document.body.classList.remove('nav-open');
  if (push && location.hash !== '#/' + name) history.pushState(null, '', '#/' + name);
  window.scrollTo({ top: 0 });
  NAV.onShow[name] && NAV.onShow[name]();
}
function wireNav() {
  $$('.tabs [data-view]').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
  addEventListener('popstate', () => showView(location.hash.slice(2) || '', false));
  const mini = $('#side-mini');
  if (mini) {
    const pref = store.get('side-mini', null);
    if (pref === true || (pref === null && innerWidth < 1100 && innerWidth > 760)) document.body.classList.add('side-mini');
    mini.addEventListener('click', () => store.set('side-mini', document.body.classList.toggle('side-mini')));
  }
  $('#nav-open')?.addEventListener('click', () => document.body.classList.add('nav-open'));
  $('#nav-back')?.addEventListener('click', () => document.body.classList.remove('nav-open'));
  showView(location.hash.slice(2) || '', false);
}

// ---------- Recherche rapide : Ctrl+K ou « / » ----------
// items : [{t: 'Libellé', p: 'Page ou type', go: () => …}] ; par défaut, toutes les pages de la barre latérale
const CMDK = { sel: 0, items: [], extra: () => [] };
const norm = (x) => x.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
function cmdkAll() {
  return [...$$('.tabs [data-view]').filter((b) => !b.hidden).map((b) => ({ t: b.querySelector('.nl')?.textContent || b.title, p: 'Page', go: () => showView(b.dataset.view) })), ...CMDK.extra()];
}
function cmdkDraw() {
  const q = norm($('#cmdk-q').value.trim()), all = cmdkAll();
  CMDK.items = (q ? all.filter((i) => norm(i.t + ' ' + i.p).includes(q)) : all).slice(0, 40);
  CMDK.sel = Math.min(CMDK.sel, Math.max(CMDK.items.length - 1, 0));
  $('#cmdk-l').innerHTML = CMDK.items.map((i, k) => `<button type="button" role="option" data-k="${k}" aria-selected="${k === CMDK.sel}">${esc(i.t)}<span class="p">${esc(i.p)}</span></button>`).join('') || '<p class="help" style="padding:8px">Aucun résultat.</p>';
}
function cmdkOpen() { CMDK.sel = 0; $('#cmdk-q').value = ''; cmdkDraw(); dlgOpen('#cmdk'); setTimeout(() => $('#cmdk-q').focus(), 20); }
function cmdkGo(k) { const i = CMDK.items[k]; if (i) { dlgClose('#cmdk'); i.go(); } }
function wireCmdk() {
  if (!$('#cmdk')) return;
  $$('[data-cmdk-open]').forEach((b) => b.addEventListener('click', cmdkOpen));
  $('#cmdk-q').addEventListener('input', () => { CMDK.sel = 0; cmdkDraw(); });
  $('#cmdk-q').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { CMDK.sel = Math.min(CMDK.sel + 1, CMDK.items.length - 1); cmdkDraw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { CMDK.sel = Math.max(CMDK.sel - 1, 0); cmdkDraw(); e.preventDefault(); }
    else if (e.key === 'Enter') { cmdkGo(CMDK.sel); e.preventDefault(); }
  });
  $('#cmdk-l').addEventListener('click', (e) => { const b = e.target.closest('[data-k]'); if (b) cmdkGo(+b.dataset.k); });
  $('#cmdk').addEventListener('click', (e) => { if (e.target.id === 'cmdk') dlgClose('#cmdk'); });
  addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdkOpen(); }
    else if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName) && !dialogOpen()) { e.preventDefault(); cmdkOpen(); }
  });
}

// ---------- Web app : service worker (page hors ligne uniquement) ----------
function registerSW(url = 'sw.js') { if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register(url).catch(() => {}); }
