'use strict';

/* ---------- 工具函数 ---------- */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const SORTS = ['newest', 'oldest', 'score_high', 'score_low', 'random'];

const state = {
  filter: loadFilter(),
  sort: validSort(lsGet('ir.sort')),
  q: '',
  mode: 'ranking',
  stats: null,
  collections: [],
  rank: { items: [], index: 0, page: 0, last: 1, total: 0, loading: false, stale: false, seq: 0 },
  grid: { items: [], page: 0, last: 1, total: 0, loading: false, seq: 0 },
  selected: new Set(),
  anchor: null,
  detail: null,
  lightbox: { on: false, id: null, fromRank: false },
};

function lsGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* 隐私模式等忽略 */ }
}

function validSort(value) {
  return SORTS.includes(value) ? value : 'newest';
}

function loadFilter() {
  try {
    const f = JSON.parse(lsGet('ir.filter') || 'null');
    if (f && typeof f === 'object') {
      const score = Number(f.score);
      const collection = Number(f.collection);
      if (f.view === 'score' && Number.isInteger(score) && score >= 1 && score <= 5) return { view: 'score', score };
      if (f.view === 'collection' && Number.isInteger(collection)) return { view: 'collection', collection };
      if (['all', 'unrated', 'loved', 'trash'].includes(f.view)) return { view: f.view };
    }
  } catch { /* 忽略坏数据 */ }
  return { view: 'unrated' };
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'hidden') node[k] = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c !== null && c !== undefined && c !== false) node.append(c);
  }
  return node;
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
}

const AUTH_PATHS = new Set(['/api/login', '/api/setup']);

async function api(method, path, body) {
  const opt = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opt);
  } catch {
    throw new Error('网络错误，无法连接服务器');
  }
  let json = {};
  try { json = await res.json(); } catch { /* 空响应 */ }
  if (res.status === 401) {
    if (!AUTH_PATHS.has(path)) showLogin();
    throw new Error(json.detail || '未登录');
  }
  if (!res.ok) throw new Error(json.detail || `请求失败（HTTP ${res.status}）`);
  return json;
}

async function copy(text, label) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      // 局域网走 http 时不是安全上下文， clipboard API 不可用；退回临时 textarea。
      const area = el('textarea', { value: text });
      Object.assign(area.style, { position: 'fixed', left: '-9999px', top: '0', opacity: '0' });
      document.body.append(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      if (!ok) throw new Error('复制失败');
    }
    toast(`已复制${label ? ' ' + label : ''}`);
  } catch {
    toast('复制失败，请手动复制');
  }
}

function fmtSize(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  return bytes >= 1024 * 1024 ? `${(bytes / 1048576).toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
}

function fmtTime(ts) {
  return Number.isFinite(ts) ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }) : '—';
}

// 图片加载完淡入；已缓存的图片也要处理。
function fadeIn(img) {
  const done = () => img.classList.add('loaded');
  img.addEventListener('load', done, { once: true });
  img.addEventListener('error', done, { once: true });
  if (img.complete) done();
}

// 带退场动画关闭 dialog。
function closeDialog(d) {
  if (!d.open || d.classList.contains('closing')) return;
  // 焦点若留在对话框的输入框里，关闭后全局快捷键会被当成“正在输入”而失效。
  if (d.contains(document.activeElement)) document.activeElement.blur();
  d.classList.add('closing');
  setTimeout(() => {
    d.classList.remove('closing');
    d.close();
  }, 190);
}

const isTyping = (t) => t.matches?.('input, textarea, select') || t.isContentEditable;

/* ---------- 主题 ---------- */

const THEMES = [
  { key: 'system', icon: '◐', label: '跟随系统' },
  { key: 'light', icon: '☀', label: '浅色' },
  { key: 'dark', icon: '☾', label: '深色' },
];

function applyTheme(key) {
  const root = document.documentElement;
  if (key === 'system') {
    delete root.dataset.theme;
    try { localStorage.removeItem('theme'); } catch { /* 忽略 */ }
  } else {
    root.dataset.theme = key;
    try { localStorage.setItem('theme', key); } catch { /* 忽略 */ }
  }
  const theme = THEMES.find((x) => x.key === key) || THEMES[0];
  const btn = $('#btn-theme');
  btn.textContent = theme.icon;
  btn.title = `主题：${theme.label}（点击切换）`;
  btn.setAttribute('aria-label', btn.title);
}

$('#btn-theme').addEventListener('click', () => {
  const cur = document.documentElement.dataset.theme || 'system';
  const next = THEMES[(THEMES.findIndex((x) => x.key === cur) + 1) % THEMES.length];
  applyTheme(next.key);
  toast(`主题：${next.label}`);
});
applyTheme(document.documentElement.dataset.theme || 'system');

/* ---------- 视图（筛选与视图切换） ---------- */

const SIDE_VIEWS = [
  { filter: { view: 'all' }, label: '全部', count: (s) => s.total },
  { filter: { view: 'unrated' }, label: '未评分', count: (s) => s.unrated },
  ...[1, 2, 3, 4, 5].map((n) => ({
    filter: { view: 'score', score: n },
    label: `★${n}`,
    count: (s) => s.scores?.[String(n)] ?? 0,
  })),
  { filter: { view: 'loved' }, label: '❤ 收藏', count: (s) => s.loved },
  { filter: { view: 'trash' }, label: '🗑 Trash', count: (s) => s.trash },
];

function sameFilter(a, b) {
  if (a.view !== b.view) return false;
  if (a.view === 'score') return Number(a.score) === Number(b.score);
  if (a.view === 'collection') return Number(a.collection) === Number(b.collection);
  return true;
}

function filterLabel(filter) {
  if (filter.view === 'score') return `★${filter.score}`;
  if (filter.view === 'collection') {
    const c = state.collections.find((x) => x.id === Number(filter.collection));
    return c ? c.name : 'Collection';
  }
  return { all: '全部', unrated: '未评分', loved: '❤ 收藏', trash: '🗑 Trash' }[filter.view] || '全部';
}

function saveFilter() {
  lsSet('ir.filter', JSON.stringify(state.filter));
}

function sideItem(filter, label, count) {
  const active = sameFilter(filter, state.filter);
  const btn = el('button', {
    type: 'button',
    class: `side-item${active ? ' active' : ''}`,
    'aria-current': active ? 'true' : 'false',
  }, el('span', { class: 'side-label', text: label }),
  el('span', { class: 'side-count', text: count === null || count === undefined ? '' : String(count) }));
  btn.addEventListener('click', () => setFilter(filter));
  return btn;
}

function collItem(c) {
  const active = sameFilter({ view: 'collection', collection: c.id }, state.filter);
  const name = el('button', {
    type: 'button',
    class: `coll-name${active ? ' active' : ''}`,
    title: c.name,
    'aria-current': active ? 'true' : 'false',
  }, el('span', { class: 'side-label', text: c.name }),
  el('span', { class: 'side-count', text: c.count === null || c.count === undefined ? '' : String(c.count) }));
  name.addEventListener('click', () => setFilter({ view: 'collection', collection: c.id }));
  const rename = el('button', {
    type: 'button', class: 'ghost mini', text: '✎', 'aria-label': `重命名 ${c.name}`,
  });
  rename.addEventListener('click', (e) => { e.stopPropagation(); renameCollection(c); });
  const del = el('button', {
    type: 'button', class: 'ghost mini danger', text: '✕', 'aria-label': `删除 ${c.name}`,
  });
  del.addEventListener('click', (e) => { e.stopPropagation(); deleteCollection(c); });
  return el('li', { class: 'coll' }, name, el('span', { class: 'coll-ops' }, rename, del));
}

function renderSidebar() {
  const stats = state.stats;
  $('#view-list').replaceChildren(...SIDE_VIEWS.map((v) => sideItem(v.filter, v.label, stats ? v.count(stats) : null)));
  $('#coll-list').replaceChildren(...state.collections.map(collItem));
}

function setFilter(filter) {
  state.filter = { ...filter };
  saveFilter();
  closeMenu();
  clearSelection();
  loadActive();
}

function renderMode() {
  const grid = state.mode === 'grid';
  $('#ranking').hidden = grid;
  $('#grid-wrap').hidden = !grid;
  const btn = $('#btn-mode');
  btn.textContent = grid ? '☰' : '▦';
  btn.title = grid ? '切换到单图评分' : '切换到网格视图';
  btn.setAttribute('aria-label', btn.title);
}

function loadActive() {
  renderTrashActions();
  if (state.mode === 'grid') loadGrid(1);
  else loadRanking();
}

// 「一键物理整理」只在 Trash 视图里出现。
function renderTrashActions() {
  const box = $('#trash-actions');
  if (box) box.hidden = state.filter.view !== 'trash';
}

function setMode(mode) {
  if (state.mode === mode) return;
  if (state.lightbox.on) closeLightbox();
  state.mode = mode;
  if (mode === 'grid') clearRankPrefetch();
  renderMode();
  closeMenu();
  clearSelection();
  loadActive();
}

$('#btn-mode').addEventListener('click', () => setMode(state.mode === 'grid' ? 'ranking' : 'grid'));

async function refreshCollections() {
  try {
    state.collections = await api('GET', '/api/collections');
    renderSidebar();
  } catch (err) {
    if (err.message !== '未登录') toast(err.message);
  }
}

let collNameResolve = null;

// 页面内命名对话框：确定 -> 名称，取消 / Esc -> null。
function askCollectionName(title, initial = '') {
  return new Promise((resolve) => {
    const dialog = $('#coll-name');
    // 上一次关闭动画尚未结束时再次打开，直接复位，避免 showModal 抛 InvalidStateError。
    if (dialog.open) {
      dialog.close();
      dialog.classList.remove('closing');
    }
    $('#coll-name-title').textContent = title;
    $('#coll-name-error').textContent = '';
    const input = $('#coll-name-input');
    input.value = initial;
    collNameResolve = resolve;
    dialog.showModal();
    input.focus();
    input.select();
  });
}

$('#coll-name-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const name = $('#coll-name-input').value.trim();
  if (!name) { $('#coll-name-error').textContent = '名称不能为空'; return; }
  const resolve = collNameResolve;
  collNameResolve = null;
  closeDialog($('#coll-name'));
  if (resolve) resolve(name);
});

$('#coll-name').addEventListener('close', () => {
  // 旧对话框的 close 事件可能晚到；此时新对话框已打开，忽略。
  if ($('#coll-name').open) return;
  const resolve = collNameResolve;
  collNameResolve = null;
  if (resolve) resolve(null);
});

async function createCollection() {
  const name = await askCollectionName('新建 Collection');
  if (name === null) return;
  try {
    await api('POST', '/api/collections', { name });
    toast('已新建 Collection');
    await refreshCollections();
  } catch (err) {
    toast(err.message);
  }
}

async function renameCollection(c) {
  const name = await askCollectionName('重命名 Collection', c.name);
  if (name === null) return;
  try {
    await api('PATCH', `/api/collections/${c.id}`, { name });
    toast('已重命名');
    await refreshCollections();
    if (state.filter.view === 'collection' && Number(state.filter.collection) === c.id) renderProgress();
  } catch (err) {
    toast(err.message);
  }
}

async function deleteCollection(c) {
  if (!confirm(`删除 Collection「${c.name}」？\n只删除集合与归属关系，不会删除图片文件。`)) return;
  try {
    await api('DELETE', `/api/collections/${c.id}`);
    toast('已删除 Collection');
    if (state.filter.view === 'collection' && Number(state.filter.collection) === c.id) {
      state.filter = { view: 'all' };
      saveFilter();
      clearSelection();
    }
    await refreshCollections();
    loadActive();
  } catch (err) {
    toast(err.message);
  }
}

$('#coll-new').addEventListener('click', createCollection);

/* ---------- 登录 / 首次设置 ---------- */

let setupMode = false;

function resetApp() {
  clearTimeout(scanTimer);
  clearTimeout(searchTimer);
  clearTimeout(metaTimer);
  scanRunning = false;
  scanNotify = false;
  renderScan(null);
  state.rank = { items: [], index: 0, page: 0, last: 1, total: 0, loading: false, stale: false, seq: state.rank.seq + 1 };
  state.grid = { items: [], page: 0, last: 1, total: 0, loading: false, seq: state.grid.seq + 1 };
  state.stats = null;
  state.collections = [];
  state.selected.clear();
  state.anchor = null;
  state.detail = null;
  $('#grid').replaceChildren();
  $('#view-list').replaceChildren();
  $('#coll-list').replaceChildren();
  renderBar();
}

function showLogin(setup = false) {
  resetApp();
  $$('dialog[open]').forEach((d) => d.close());
  $('#app').hidden = true;
  $('#login').hidden = false;
  setSetupForm(setup);
  $('#password').focus();
}

function setSetupForm(setup) {
  setupMode = setup;
  $('#login-sub').textContent = setup ? '首次使用：设置访问密码' : '输入访问密码';
  $('#login-submit').textContent = setup ? '设置密码' : '登录';
  $('#confirm-password').hidden = !setup;
  $('#confirm-password').required = setup;
  $('#confirm-label').hidden = !setup;
  $('#password').autocomplete = setup ? 'new-password' : 'current-password';
  $('#password').value = '';
  $('#confirm-password').value = '';
  $('#login-error').textContent = '';
}

async function showApp() {
  $('#login').hidden = true;
  $('#app').hidden = false;
  renderMode();
  renderSidebar();
  renderBar();
  // 恢复的 collection 筛选可能已被删除，先校验一次再加载。
  if (state.filter.view === 'collection') {
    try { state.collections = await api('GET', '/api/collections'); } catch { /* 交给后续加载报错 */ }
    if (!state.collections.some((c) => c.id === Number(state.filter.collection))) {
      state.filter = { view: 'all' };
      saveFilter();
    }
  }
  loadActive();
  watchScan();
}

function shakeLogin() {
  const card = $('#login-form');
  card.classList.remove('shake');
  void card.offsetWidth; // 重启动画
  card.classList.add('shake');
}

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const password = $('#password').value;
  const confirmPassword = $('#confirm-password').value;
  $('#login-error').textContent = '';
  if (setupMode) {
    if (password.length < 4) { $('#login-error').textContent = '密码至少 4 个字符'; shakeLogin(); return; }
    if (password !== confirmPassword) { $('#login-error').textContent = '两次输入的密码不一致'; shakeLogin(); return; }
  }
  const btn = $('#login-submit');
  btn.disabled = true;
  try {
    if (setupMode) {
      await api('POST', '/api/setup', { password });
      toast('密码已设置');
    } else {
      await api('POST', '/api/login', { password });
    }
    showApp();
  } catch (err) {
    $('#login-error').textContent = err.message;
    shakeLogin();
  } finally {
    btn.disabled = false;
  }
});

$('#btn-logout').addEventListener('click', async () => {
  try {
    await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
  } catch { /* 忽略网络错误，照常回登录页 */ }
  showLogin(false);
});

/* ---------- 列表与渲染 ---------- */

const PER_PAGE = 60;

function imageQuery(page) {
  const params = new URLSearchParams({
    view: state.filter.view,
    page: String(page),
    per_page: String(PER_PAGE),
    sort: state.sort,
  });
  if (state.filter.view === 'score') params.set('score', String(state.filter.score));
  if (state.filter.view === 'collection') params.set('collection', String(state.filter.collection));
  if (state.q) params.set('q', state.q);
  return params.toString();
}

function inFilter(item) {
  if (!item || item.missing) return false;
  if (state.q && !item.filename.toLowerCase().includes(state.q.toLowerCase())) return false;
  switch (state.filter.view) {
    case 'unrated': return item.score === null && !item.trashed;
    case 'score': return item.score === Number(state.filter.score) && !item.trashed;
    case 'loved': return !!item.loved;
    case 'trash': return !!item.trashed;
    case 'collection': return (item.collections || []).some((c) => c.id === Number(state.filter.collection));
    default: return true;
  }
}

function findItem(id) {
  return state.grid.items.find((x) => x.id === id) || state.rank.items.find((x) => x.id === id) || null;
}

function replaceItem(item) {
  let index = state.grid.items.findIndex((x) => x.id === item.id);
  if (index >= 0) state.grid.items[index] = item;
  index = state.rank.items.findIndex((x) => x.id === item.id);
  if (index >= 0) state.rank.items[index] = item;
}

function applyMeta(data) {
  if (data.stats) state.stats = data.stats;
  if (data.collections) state.collections = data.collections;
  renderSidebar();
  renderProgress();
}

function renderProgress() {
  const progress = $('#rank-progress');
  const stats = state.stats;
  if (!stats) { progress.textContent = '加载中…'; return; }
  const suffix = state.filter.view === 'all' ? '' : ` · 当前「${filterLabel(state.filter)}」`;
  progress.textContent = `未评分 ${stats.unrated} / 全部 ${stats.total}${suffix}`;
}

function syncStarButtons(container, item) {
  container.querySelectorAll('[data-score]').forEach((btn) => {
    const on = !!item && item.score === Number(btn.dataset.score);
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', String(on));
    btn.disabled = !item;
  });
}

// 服务端返回 item（可能叠加上仍在排队的本地预测）后同步本地数据；不再重复后端的联动规则。
function afterSingleChange(updated) {
  replaceItem(updated);
  if (state.detail && state.detail.id === updated.id) state.detail = updated;
  if (state.mode === 'grid') {
    updateGridCard(updated);
  } else {
    const current = currentItem();
    if (current && current.id === updated.id) {
      if (!inFilter(updated)) dropRankItem(updated.id);
      else renderRank();
    }
  }
  if (state.detail && $('#detail').open) renderDetail(state.detail);
  if (state.lightbox.on) renderLightbox();
  refreshMeta();
}

// 批量或无法直接拿到 item 的改动：简单刷新当前列表。
async function syncAfterChange(ids) {
  if (state.detail && ids.includes(state.detail.id)) {
    try {
      const fresh = await api('GET', `/api/images/${state.detail.id}`);
      replaceItem(fresh);
      state.detail = fresh;
    } catch { /* 抽屉里的保留旧数据 */ }
  }
  if (state.mode === 'grid') {
    await loadGrid(1, { keepSelection: true });
  } else {
    for (const id of ids) {
      try { replaceItem(await api('GET', `/api/images/${id}`)); } catch { /* 忽略单张失败 */ }
    }
    const current = currentItem();
    if (current && !inFilter(current)) await dropRankItem(current.id);
    else renderRank();
  }
  if (state.detail && $('#detail').open) renderDetail(state.detail);
  if (state.detail && !$('#d-coll-list').hidden) renderDetailCollChecks(state.detail);
  if (state.lightbox.on) renderLightbox();
  refreshMeta();
}

let metaTimer = null;
function refreshMeta() {
  clearTimeout(metaTimer);
  metaTimer = setTimeout(async () => {
    try {
      const data = await api('GET', `/api/images?${new URLSearchParams({ view: 'all', page: '1', per_page: '1' })}`);
      if ($('#app').hidden) return;
      state.stats = data.stats;
      state.collections = data.collections;
      renderSidebar();
      renderProgress();
    } catch { /* 元信息刷新失败不影响主流程 */ }
  }, 150);
}

/* ---------- 本地优先：乐观更新队列 ---------- */

let opSeq = 0;
let opCurrent = null;
const opQueue = [];
let opRunning = false;

// 服务端响应回来时，把仍排在后面的本地预测叠回去，避免界面被旧响应“盖回去”。
function pendingFieldsFor(id, excludeSeq) {
  const out = {};
  const ops = opCurrent ? [opCurrent, ...opQueue] : opQueue.slice();
  for (const op of ops) {
    if (excludeSeq !== undefined && op.seq === excludeSeq) continue;
    for (const patch of op.patches || []) {
      if (patch.id === id) Object.assign(out, patch.fields);
    }
  }
  return out;
}

function itemsOfResponse(data) {
  if (!data) return [];
  if (Array.isArray(data.items)) return data.items;
  if (data.item) return [data.item];
  return [];
}

function reconcileServerItems(items, excludeSeq) {
  for (const serverItem of items) {
    afterSingleChange(Object.assign({}, serverItem, pendingFieldsFor(serverItem.id, excludeSeq)));
  }
}

// 列表接口返回的 item 也叠上还没确认的本地预测，避免翻页时出现“旧数据回跳”。
function mergePendingFields(item) {
  const fields = pendingFieldsFor(item.id);
  return Object.keys(fields).length ? Object.assign({}, item, fields) : item;
}

async function refreshItemsFromServer(ids) {
  for (const id of [...new Set(ids)]) {
    try {
      const fresh = await api('GET', `/api/images/${id}`);
      const merged = Object.assign({}, fresh, pendingFieldsFor(id));
      afterSingleChange(merged);
      restoreItemsIntoRank([merged]);
    } catch { /* 恢复失败时保留本地状态，下一次操作再校准 */ }
  }
  if (state.mode === 'grid') loadGrid(1, { keepSelection: true });
}

function removeUndoEntry(entry) {
  if (!entry) return;
  const index = undoStack.indexOf(entry);
  if (index >= 0) undoStack.splice(index, 1);
}

// 只负责把请求排队并后台发送；界面在调用处已经先改好。
function enqueueOp(op) {
  opQueue.push(op);
  if (!opRunning) runOpQueue();
}

async function runOpQueue() {
  if (opRunning) return;
  opRunning = true;
  try {
    while (opQueue.length) {
      const op = opQueue.shift();
      opCurrent = op;
      try {
        const data = await op.request();
        reconcileServerItems(itemsOfResponse(data), op.seq);
        if (op.after) op.after(data);
      } catch (err) {
        if (op.undoEntry) removeUndoEntry(op.undoEntry);
        if (op.onError) {
          op.onError(err);
        } else {
          if (err.message !== '未登录') toast(`操作失败：${err.message}`);
          refreshItemsFromServer(op.ids);
        }
      } finally {
        opCurrent = null;
      }
    }
  } finally {
    opRunning = false;
    opCurrent = null;
  }
}

// 把预测字段写到本地所有引用这份 item 的地方（Ranking / Grid / 详情 / 刚被本地移出的缓存）。
function applyLocalPatches(patches) {
  const touched = new Map();
  for (const { id, fields } of patches) {
    for (const list of [state.rank.items, state.grid.items]) {
      const item = list.find((x) => x.id === id);
      if (item) Object.assign(item, fields);
    }
    if (state.detail && state.detail.id === id) Object.assign(state.detail, fields);
    const item = findItem(id)
      || (state.detail && state.detail.id === id ? state.detail : null)
      || removedItems.get(id)
      || null;
    if (!item) continue;
    Object.assign(item, fields);
    touched.set(id, item);
  }
  return [...touched.values()];
}

// 本地改完后立刻重画；不需要再等接口返回。
function refreshLocalItems(items) {
  for (const item of items) {
    if (state.mode === 'grid') {
      updateGridCard(item);
    } else {
      const current = currentItem();
      if (current && current.id === item.id) {
        if (!inFilter(item)) dropRankItem(item.id);
        else renderRank();
      }
    }
  }
  if (state.detail && $('#detail').open) {
    renderDetail(state.detail);
    if (!$('#d-coll-list').hidden) renderDetailCollChecks(state.detail);
  }
  if (state.lightbox.on) renderLightbox();
  refreshMeta();
}

// 撤回把图重新放回当前筛选时，Ranking 列表里也要补回来（并停在撤回的那张上）。
function restoreItemsIntoRank(items) {
  if (state.mode !== 'ranking') return;
  let changed = false;
  for (const item of items) {
    if (!inFilter(item)) continue;
    if (state.rank.items.some((x) => x.id === item.id)) continue;
    const at = Math.min(state.rank.index, state.rank.items.length);
    state.rank.items.splice(at, 0, item);
    state.rank.total += 1;
    removedItems.delete(item.id);
    changed = true;
  }
  if (changed) renderRank();
}

// 仅为「立即反馈」镜像后端的评分→Trash 联动；服务端响应回来后会覆盖这里的预测。
function predictedRateFields(item, score) {
  const fields = { score, rated_at: score === null ? null : Date.now() / 1000 };
  if (score === 0) fields.trashed = true;
  else if (score !== null) fields.trashed = false;
  return fields;
}

function setItemCollection(item, collection, add) {
  const rest = (item.collections || []).filter((c) => c.id !== collection.id);
  item.collections = add ? [...rest, { id: collection.id, name: collection.name }] : rest;
}

// 本地已知的 item：当前列表 / 详情 / 刚被本地移出 Ranking 的缓存。
function knownItem(id) {
  return locateItem(id) || removedItems.get(id) || null;
}

function knownItems(ids) {
  return [...new Set(ids)].map(knownItem).filter(Boolean);
}

function setCollectionsLocal(ids, collection, add) {
  for (const id of ids) {
    for (const list of [state.rank.items, state.grid.items]) {
      const item = list.find((x) => x.id === id);
      if (item) setItemCollection(item, collection, add);
    }
    if (state.detail && state.detail.id === id) setItemCollection(state.detail, collection, add);
    if (removedItems.has(id)) setItemCollection(removedItems.get(id), collection, add);
  }
}

/* ---------- 撤回（Ctrl+Z） ---------- */

const UNDO_LIMIT = 50;
const undoStack = [];

// 只记录这次操作真正改到的字段；撤回时精确回填，不覆盖期间的其他改动。
function metaPatch(item, fields) {
  const patch = { id: item.id };
  for (const field of fields) patch[field] = item[field] === undefined ? null : item[field];
  return patch;
}

function locateItem(id) {
  return findItem(id) || (state.detail && state.detail.id === id ? state.detail : null);
}

function pushUndo(entry) {
  undoStack.push(entry);
  if (undoStack.length > UNDO_LIMIT) undoStack.shift();
}

// 从本地已加载的 item 生成撤回补丁；找不到的 id 跳过。
function pushMetaUndo(label, ids, fields) {
  const patches = [];
  for (const id of ids) {
    const item = locateItem(id);
    if (item) patches.push(metaPatch(item, fields));
  }
  if (patches.length) pushUndo({ label, patches });
}

function undoLast() {
  const entry = undoStack.pop();
  if (!entry) {
    toast('没有可撤回的操作');
    return;
  }
  if (entry.collection) {
    const collection = state.collections.find((c) => c.id === entry.collection.id) || entry.collection;
    const wantAdd = entry.inverse === 'add';
    const touched = knownItems(entry.ids);
    setCollectionsLocal(entry.ids, collection, wantAdd);
    restoreItemsIntoRank(touched);
    refreshLocalItems(touched);
    enqueueOp({
      seq: ++opSeq,
      ids: entry.ids.slice(),
      patches: [],
      request: () => api('POST', `/api/collections/${entry.collection.id}/images`, {
        ids: entry.ids,
        action: entry.inverse,
      }),
      onError: (err) => {
        const failed = knownItems(entry.ids);
        setCollectionsLocal(entry.ids, collection, !wantAdd);
        restoreItemsIntoRank(failed);
        refreshLocalItems(failed);
        undoStack.push(entry);
        if (err.message !== '未登录') toast(`撤回失败：${err.message}`);
      },
    });
    toast(`已撤回：${entry.label}`);
    return;
  }

  const patches = entry.patches || [];
  if (!patches.length) return;
  const undoFields = patches.map(({ id, ...fields }) => ({ id, fields }));
  // 撤回本身也可能失败；先记下撤回前的值，失败时原样放回去。
  const beforeUndo = patches.map((patch) => {
    const item = knownItem(patch.id);
    const fields = {};
    for (const key of Object.keys(patch)) {
      if (key === 'id') continue;
      fields[key] = item ? item[key] : null;
    }
    return { id: patch.id, fields };
  });
  const undoTouched = applyLocalPatches(undoFields);
  restoreItemsIntoRank(undoTouched);
  refreshLocalItems(undoTouched);
  if (state.mode === 'grid') loadGrid(1, { keepSelection: true });
  enqueueOp({
    seq: ++opSeq,
    ids: patches.map((patch) => patch.id),
    patches: undoFields,
    request: () => api('POST', '/api/images/batch', { op: 'state', items: patches }),
    onError: (err) => {
      refreshLocalItems(applyLocalPatches(beforeUndo));
      undoStack.push(entry);
      if (err.message !== '未登录') toast(`撤回失败：${err.message}`);
    },
  });
  toast(`已撤回：${entry.label}`);
}

/* ---------- Ranking ---------- */

function currentItem() {
  return state.rank.items[state.rank.index] || null;
}

function rankMeta(item) {
  const rank = state.rank;
  const parts = [
    `${rank.index + 1} / ${rank.total}`,
    item.filename,
    `${item.width} × ${item.height}`,
    fmtSize(item.size),
    fmtTime(item.mtime),
  ];
  if (item.organized) parts.push('已整理到 _trash');
  if (item.score === 0) parts.push('作废');
  return parts.join(' · ');
}

// Ranking 预加载：提前缓存前后几张原图，快速翻页时不再“到了才开始加载”。
const PREFETCH_AHEAD = 4;
const PREFETCH_BEHIND = 1;
const PREFETCH_PAGE_AT = 4; // 距离当前页末尾还剩几张时预取下一页

const rankPrefetch = new Map(); // full_url -> Image，持有引用避免请求被提前回收
let rankMore = null; // 正在追加的下一页（避免并发重复请求）

function prefetchRankUrl(url) {
  if (!url || rankPrefetch.has(url)) return;
  const img = new Image();
  img.decoding = 'async';
  img.src = url;
  if (typeof img.decode === 'function') img.decode().catch(() => {});
  rankPrefetch.set(url, img);
}

function clearRankPrefetch() {
  for (const img of rankPrefetch.values()) img.src = '';
  rankPrefetch.clear();
}

function prefetchRankWindow() {
  const rank = state.rank;
  const keep = new Set();
  const first = Math.max(0, rank.index - PREFETCH_BEHIND);
  const last = Math.min(rank.items.length - 1, rank.index + PREFETCH_AHEAD);
  for (let i = first; i <= last; i += 1) {
    const item = rank.items[i];
    if (!item) continue;
    keep.add(item.full_url);
    if (i !== rank.index) prefetchRankUrl(item.full_url);
  }
  // 移出窗口的引用及时释放，避免长时间浏览占住已解码图片。
  for (const [url, img] of rankPrefetch) {
    if (keep.has(url)) continue;
    img.src = '';
    rankPrefetch.delete(url);
  }
}

function maybePrefetchNextRankPage() {
  const rank = state.rank;
  if (rank.loading || rankMore) return;
  if (!rank.stale && rank.page >= rank.last) return;
  if (rank.index + 1 < rank.items.length - PREFETCH_PAGE_AT) return;
  loadMoreRanking().then((more) => {
    if (more) prefetchRankWindow();
  });
}

function setRankControls(item) {
  syncStarButtons($('#rank-stars'), item);
  const loved = $('#rank-loved');
  loved.disabled = !item;
  loved.classList.toggle('active', !!item && !!item.loved);
  loved.setAttribute('aria-pressed', String(!!item && !!item.loved));
  loved.textContent = item && item.loved ? '❤ 已收藏' : '❤ 收藏';
  const trash = $('#rank-trash');
  trash.disabled = !item;
  trash.classList.toggle('active', !!item && !!item.trashed);
  trash.setAttribute('aria-pressed', String(!!item && !!item.trashed));
  trash.textContent = item && item.trashed ? '🗑 移出 Trash' : '🗑 移入 Trash';
  const coll = $('#rank-coll');
  coll.disabled = !item;
  coll.textContent = item && item.collections.length ? `+ Collection（${item.collections.length}）` : '+ Collection';
  $('#rank-organize').hidden = !item || !item.trashed || item.organized;
  $('#rank-organize').disabled = !item;
  $('#rank-restore').hidden = !item || !item.organized;
  $('#rank-restore').disabled = !item;
}

async function loadRanking() {
  const rank = state.rank;
  const seq = ++rank.seq;
  rank.loading = true;
  rankMore = null; // 旧筛选/旧列表的翻页请求作废（seq 会兜底）
  clearRankPrefetch();
  removedItems.clear();
  $('#rank-img').hidden = true;
  $('#rank-empty').hidden = false;
  $('#rank-empty').textContent = '加载中…';
  $('#rank-meta').textContent = '';
  setRankControls(null);
  try {
    const data = await api('GET', `/api/images?${imageQuery(1)}`);
    if (seq !== rank.seq) return;
    rank.items = data.items.map(mergePendingFields).filter(inFilter);
    rank.index = 0;
    rank.stale = false;
    rank.page = data.page;
    rank.last = data.last_page;
    rank.total = data.total;
    applyMeta(data);
    renderRank();
  } catch (err) {
    if (seq === rank.seq && err.message !== '未登录') {
      $('#rank-img').hidden = true;
      $('#rank-empty').hidden = false;
      $('#rank-empty').textContent = `加载失败：${err.message}`;
      toast(err.message);
    }
  } finally {
    if (seq === rank.seq) rank.loading = false;
  }
}

function renderRank() {
  const rank = state.rank;
  const item = rank.items[rank.index] || null;
  const img = $('#rank-img');
  const empty = $('#rank-empty');
  if (!item) {
    img.hidden = true;
    img.removeAttribute('src');
    delete img.dataset.src;
    img.classList.remove('loaded');
    clearRankPrefetch();
    empty.hidden = false;
    empty.textContent = state.q
      ? `没有匹配「${state.q}」的图片`
      : state.filter.view === 'all' ? '这里还没有图片' : '没有符合当前筛选的图片';
    $('#rank-meta').textContent = '';
    setRankControls(null);
    $('#rank-prev').disabled = true;
    $('#rank-next').disabled = true;
    renderProgress();
    if (state.lightbox.on && state.lightbox.fromRank) closeLightbox();
    return;
  }
  empty.hidden = true;
  img.hidden = false;
  img.alt = item.filename;
  // 同一张图只更新元数据时不重设 src，避免乐观更新时闪一下。
  if (img.dataset.src !== item.full_url) {
    img.dataset.src = item.full_url;
    img.classList.remove('loaded');
    img.src = item.full_url;
    fadeIn(img);
  }
  setRankControls(item);
  $('#rank-meta').textContent = rankMeta(item);
  $('#rank-prev').disabled = rank.index === 0;
  $('#rank-next').disabled = false;
  renderProgress();
  prefetchRankWindow();
  maybePrefetchNextRankPage();
  if (state.lightbox.on && state.lightbox.fromRank) renderLightbox();
}

// 追加下一页；localStorage 里筛选过的列表因评分移出会与分页错位，此时从头重扫并去重。
// 手动翻页和后台预加载共用同一个请求，避免同一页并发拉取。
function loadMoreRanking() {
  const rank = state.rank;
  if (rankMore) return rankMore;
  if (rank.loading) return Promise.resolve(false);
  if (!rank.stale && rank.page >= rank.last) return Promise.resolve(false);
  const req = loadMoreRankingOnce();
  rankMore = req;
  req.finally(() => { if (rankMore === req) rankMore = null; });
  return req;
}

async function loadMoreRankingOnce() {
  const rank = state.rank;
  const seq = rank.seq;
  rank.loading = true;
  try {
    const seen = new Set(rank.items.map((x) => x.id));
    let page = rank.stale ? 1 : rank.page + 1;
    for (;;) {
      const data = await api('GET', `/api/images?${imageQuery(page)}`);
      if (seq !== rank.seq) return false;
      applyMeta(data);
      rank.total = data.total;
      rank.last = data.last_page;
      rank.page = page;
      const fresh = data.items
        .map(mergePendingFields)
        .filter((item) => !seen.has(item.id) && inFilter(item));
      if (fresh.length) {
        rank.items.push(...fresh);
        for (const item of fresh) removedItems.delete(item.id);
        rank.stale = false;
        return true;
      }
      if (page >= data.last_page) {
        rank.stale = false;
        return false;
      }
      page += 1;
    }
  } catch (err) {
    if (err.message !== '未登录') toast(err.message);
    return false;
  } finally {
    if (seq === rank.seq) rank.loading = false;
  }
}

async function nextImage(notify) {
  const rank = state.rank;
  if (rank.index + 1 >= rank.items.length) {
    const more = await loadMoreRanking();
    if (!more && rank.index + 1 >= rank.items.length) {
      if (notify) toast('已到末尾');
      return;
    }
  }
  rank.index = Math.min(rank.index + 1, rank.items.length - 1);
  renderRank();
}

function prevImage() {
  const rank = state.rank;
  if (rank.index <= 0) { toast('已经是第一张'); return; }
  rank.index -= 1;
  renderRank();
}

const removedItems = new Map(); // 本地暂时移出 Ranking 的图，撤回时不用等接口就能放回来

async function dropRankItem(id) {
  const rank = state.rank;
  const index = rank.items.findIndex((x) => x.id === id);
  if (index >= 0) {
    removedItems.set(id, rank.items[index]);
    if (removedItems.size > 100) removedItems.delete(removedItems.keys().next().value);
    rank.items.splice(index, 1);
    rank.total = Math.max(0, rank.total - 1);
    rank.stale = true;
  }
  let needMore = false;
  if (rank.index >= rank.items.length) {
    if (rank.page < rank.last || rank.stale) needMore = true;
    else rank.index = Math.max(0, rank.items.length - 1);
  }
  // 先立刻显示下一张，再在后台补列表；网络慢时不阻塞操作。
  renderRank();
  if (needMore) {
    const more = await loadMoreRanking();
    if (!more) rank.index = Math.max(0, rank.items.length - 1);
    renderRank();
  }
}

const RATE_ADVANCE_MS = 140;

function rateCurrent(score) {
  const item = currentItem();
  if (!item) return;
  stageRate([item.id], score, { autoAdvance: true });
}

function toggleLovedCurrent() {
  const item = currentItem();
  if (item) stageLoved([item.id], !item.loved);
}

function toggleTrashCurrent() {
  const item = currentItem();
  if (item) stageTrash([item.id], !item.trashed, false);
}

function openRankCollectionMenu() {
  const item = currentItem();
  if (!item) return;
  const rect = $('#rank-coll').getBoundingClientRect();
  openCollectionCheck([item.id], rect.left, rect.bottom + 6, $('#rank-coll'));
}

$('#rank-stars').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-score]');
  if (btn) rateCurrent(Number(btn.dataset.score));
});
$('#rank-loved').addEventListener('click', toggleLovedCurrent);
$('#rank-trash').addEventListener('click', toggleTrashCurrent);
$('#rank-coll').addEventListener('click', openRankCollectionMenu);
$('#rank-prev').addEventListener('click', prevImage);
$('#rank-next').addEventListener('click', () => nextImage(true));
$('#rank-img').addEventListener('error', () => {
  if (!currentItem()) return;
  $('#rank-empty').hidden = false;
  $('#rank-empty').textContent = '图片加载失败';
  $('#rank-img').hidden = true;
});
$('#rank-organize').addEventListener('click', () => {
  const item = currentItem();
  if (item) organizeIds([item.id], false);
});
$('#rank-restore').addEventListener('click', () => {
  const item = currentItem();
  if (item) organizeIds([item.id], true);
});

/* ---------- 灯箱（放大看细节；Ranking 与网格/抽屉都能打开，快捷键照常可用） ---------- */

function lightboxTarget() {
  if (!state.lightbox.on) return null;
  if (state.lightbox.fromRank) return currentItem();
  return locateItem(state.lightbox.id);
}

function lightboxMeta(item) {
  const score = item.score === null ? '未评分' : item.score === 0 ? '作废' : `★${item.score}`;
  const parts = [item.filename, `${item.width} × ${item.height}`, fmtSize(item.size), score];
  if (item.loved) parts.push('❤ 已收藏');
  if (item.organized) parts.push('已整理到 _trash');
  return parts.join(' · ');
}

function renderLightbox() {
  if (!state.lightbox.on) return;
  const item = lightboxTarget();
  if (!item) {
    closeLightbox();
    return;
  }
  const img = $('#lb-img');
  if (img.dataset.src !== item.full_url) {
    img.dataset.src = item.full_url;
    img.classList.remove('loaded');
    img.alt = item.filename;
    img.src = item.full_url;
    fadeIn(img);
  }
  $('#lb-meta').textContent = lightboxMeta(item);
  syncStarButtons($('#lb-stars'), item);
  const loved = $('#lb-loved');
  loved.classList.toggle('active', !!item.loved);
  loved.setAttribute('aria-pressed', String(!!item.loved));
  loved.textContent = item.loved ? '❤ 已收藏' : '❤ 收藏';
  const trash = $('#lb-trash');
  trash.classList.toggle('active', !!item.trashed);
  trash.setAttribute('aria-pressed', String(!!item.trashed));
  trash.textContent = item.trashed ? '🗑 移出 Trash' : '🗑 移入 Trash';
}

// fromRank：灯箱跟随 Ranking 当前图，打分后随之前进；否则锁定到指定 item（网格/抽屉打开）。
function openLightbox(item, fromRank = false) {
  const target = item || currentItem();
  if (!target) return;
  state.lightbox = { on: true, id: target.id, fromRank };
  if (!$('#lightbox').open) $('#lightbox').showModal();
  document.body.classList.add('lightbox-open');
  renderLightbox();
}

function closeLightbox() {
  if (!state.lightbox.on) return;
  state.lightbox = { on: false, id: null, fromRank: false };
  document.body.classList.remove('lightbox-open');
  if ($('#lightbox').open) $('#lightbox').close();
  const img = $('#lb-img');
  img.removeAttribute('src');
  delete img.dataset.src;
  img.classList.remove('loaded');
}

function rateLightbox(score) {
  if (state.lightbox.on && !state.lightbox.fromRank) rateIds([state.lightbox.id], score);
  else rateCurrent(score);
}

function lovedLightbox() {
  if (state.lightbox.on && !state.lightbox.fromRank) {
    const item = lightboxTarget();
    if (item) lovedIds([item.id], !item.loved);
  } else {
    toggleLovedCurrent();
  }
}

function trashLightbox() {
  if (state.lightbox.on && !state.lightbox.fromRank) {
    const item = lightboxTarget();
    if (item) trashIds([item.id], !item.trashed, false);
  } else {
    toggleTrashCurrent();
  }
}

$('#rank-img').addEventListener('click', () => openLightbox(currentItem(), true));
$('#lb-close').addEventListener('click', closeLightbox);
$('#lb-close2').addEventListener('click', closeLightbox);
$('#lightbox').addEventListener('click', (e) => {
  if (e.target === $('#lightbox')) closeLightbox();
});
$('#lightbox').addEventListener('cancel', (e) => {
  e.preventDefault();
  closeLightbox();
});
$('#lb-stars').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-score]');
  if (btn) rateLightbox(Number(btn.dataset.score));
});
$('#lb-loved').addEventListener('click', lovedLightbox);
$('#lb-trash').addEventListener('click', trashLightbox);
$('#d-lightbox').addEventListener('click', () => {
  if (state.detail) openLightbox(state.detail, false);
});

/* ---------- Grid ---------- */

function card(item, i) {
  const img = el('img', { src: item.thumb_url, alt: item.filename, loading: 'lazy', decoding: 'async' });
  fadeIn(img);
  const score = item.score === null ? '未评分' : item.score === 0 ? '作废' : `★${item.score}`;
  const cardBtn = el('button', {
    type: 'button',
    class: 'card',
    'aria-label': `${item.filename}，${score}`,
  },
  el('div', { class: 'thumb' }, img),
  el('div', { class: 'cap' },
    el('div', { class: 'row-name' },
      item.loved ? el('span', { class: 'loved', text: '❤', title: '收藏' }) : null,
      el('span', { class: 'name', text: item.filename, title: item.filename })),
    el('div', { class: 'row-meta' },
      el('span', { class: `score${item.score === 0 ? ' bad' : ''}`, text: score }),
      el('span', { class: 'dots' }, ...item.collections.map((c) => el('span', { class: 'dot', title: c.name }))))));
  const check = el('button', {
    type: 'button',
    class: 'check',
    'aria-label': `选择 ${item.filename}`,
    'aria-pressed': String(state.selected.has(item.id)),
    tabindex: '-1',
  });
  const li = el('li', { 'data-id': String(item.id) }, cardBtn, check);
  li.style.setProperty('--i', Math.min(i, 20));
  if (state.selected.has(item.id)) markSelected(li, true);
  return li;
}

async function loadGrid(page = 1, opts = {}) {
  const grid = state.grid;
  if (page > grid.last) return;
  if (page > 1 && grid.loading) return;
  const seq = ++grid.seq;
  grid.loading = true;
  if (page === 1) {
    $('#grid-count').textContent = '加载中…';
    $('#empty').hidden = true;
  }
  try {
    const data = await api('GET', `/api/images?${imageQuery(page)}`);
    if (seq !== grid.seq) return;
    if (page === 1) {
      grid.items = [];
      $('#grid').replaceChildren();
      if (!opts.keepSelection) {
        state.selected.clear();
        state.anchor = null;
      }
    }
    for (const raw of data.items) {
      const item = mergePendingFields(raw);
      if (!inFilter(item)) continue; // 本地已改到别的筛选的 item 先不收进来
      grid.items.push(item);
      $('#grid').append(card(item, grid.items.length - 1));
    }
    grid.page = data.page;
    grid.last = data.last_page;
    grid.total = data.total;
    if (page === 1) {
      state.selected = new Set([...state.selected].filter((id) => grid.items.some((it) => it.id === id)));
    }
    applyMeta(data);
    $('#grid-count').textContent = `共 ${grid.total} 张`;
    $('#empty').hidden = grid.total > 0;
    $('#empty').textContent = '没有符合条件的图片';
    $('#more').hidden = grid.page >= grid.last;
    renderBar();
  } catch (err) {
    if (seq === grid.seq && err.message !== '未登录') {
      if (page === 1) {
        $('#empty').hidden = false;
        $('#empty').textContent = `加载失败：${err.message}`;
        $('#grid-count').textContent = '';
      }
      toast(err.message);
    }
  } finally {
    if (seq === grid.seq) grid.loading = false;
  }
  // 一页填不满屏幕时哨兵一直可见，IO 不会再触发，这里补一次。
  if (state.mode === 'grid' && grid.page < grid.last && !grid.loading) {
    const rect = $('#sentinel').getBoundingClientRect();
    if (rect.top < innerHeight + 800) loadGrid(grid.page + 1);
  }
}

function updateGridCard(item) {
  const grid = state.grid;
  const li = document.querySelector(`#grid li[data-id="${item.id}"]`);
  if (!inFilter(item)) {
    if (li) li.remove();
    grid.items = grid.items.filter((it) => it.id !== item.id);
    grid.total = Math.max(0, grid.total - 1);
    state.selected.delete(item.id);
    $('#grid-count').textContent = `共 ${grid.total} 张`;
    $('#empty').hidden = grid.total > 0;
    renderBar();
    return;
  }
  const index = grid.items.findIndex((it) => it.id === item.id);
  if (index < 0) return;
  grid.items[index] = item;
  if (li) li.replaceWith(card(item, index));
}

if ('IntersectionObserver' in window) {
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)
      && !$('#app').hidden
      && state.mode === 'grid'
      && !state.grid.loading
      && state.grid.page < state.grid.last) {
      loadGrid(state.grid.page + 1);
    }
  }, { rootMargin: '800px 0px' }).observe($('#sentinel'));
}

$('#more').addEventListener('click', () => loadGrid(state.grid.page + 1));

let searchTimer;
function applySearch(value) {
  state.q = value.trim();
  clearSelection();
  loadActive();
}
$('#search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const input = e.target;
  searchTimer = setTimeout(() => applySearch(input.value), 250);
});
$('#search').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  clearTimeout(searchTimer);
  applySearch(e.target.value);
});

$('#sort').addEventListener('change', (e) => {
  state.sort = validSort(e.target.value);
  lsSet('ir.sort', state.sort);
  clearSelection();
  loadActive();
});

/* ---------- 扫描 ---------- */

let scanTimer = null;
let scanNotify = false;
let scanRunning = false;

function renderScan(status) {
  scanRunning = !!(status && status.running);
  const btn = $('#btn-scan');
  btn.disabled = scanRunning;
  btn.textContent = scanRunning ? '…' : '⟳';
  if (!scanRunning) {
    $('#scan-state').textContent = '';
  } else {
    $('#scan-state').textContent = status.total ? `扫描中 ${status.done}/${status.total}` : '扫描中…';
  }
}

function pollScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(async () => {
    let status;
    try {
      status = await api('GET', '/api/scan/status');
    } catch (err) {
      if (err.message !== '未登录') toast(err.message);
      renderScan(null);
      return;
    }
    if ($('#app').hidden) return;
    renderScan(status);
    if (status.running) {
      pollScan();
      return;
    }
    const notify = scanNotify;
    scanNotify = false;
    if (status.error) toast(`扫描出错：${status.error}`);
    else if (notify) {
      const errors = status.errors ? `，错误 ${status.errors}` : '';
      toast(`扫描完成：新增 ${status.added}，更新 ${status.updated}，缺失 ${status.missing}${errors}`);
    }
    loadActive();
  }, 800);
}

function beginScanWatch(status) {
  scanNotify = true;
  renderScan(status && status.running ? status : { running: true, done: 0, total: 0 });
  pollScan();
}

async function startScan() {
  if (scanRunning) return;
  try {
    const data = await api('POST', '/api/scan');
    toast('开始扫描');
    beginScanWatch(data.status);
  } catch (err) {
    if (err.message !== '未登录') toast(err.message);
  }
}

async function watchScan() {
  try {
    const status = await api('GET', '/api/scan/status');
    renderScan(status);
    if (status.running) {
      scanNotify = false;
      pollScan();
    }
  } catch { /* 状态探测失败不打扰用户 */ }
}

$('#btn-scan').addEventListener('click', startScan);

/* ---------- 选择与批量操作 ---------- */

const cards = () => $$('#grid li[data-id]');

function markSelected(li, on) {
  li.classList.toggle('selected', on);
  const check = li.querySelector('.check');
  if (check) check.setAttribute('aria-pressed', String(on));
}

function setSelected(id, on) {
  if (on) state.selected.add(id);
  else state.selected.delete(id);
  const li = document.querySelector(`#grid li[data-id="${id}"]`);
  if (li) markSelected(li, on);
}

function clearSelection() {
  for (const id of [...state.selected]) setSelected(id, false);
  state.anchor = null;
  renderBar();
}

function selectRange(toId, additive) {
  const ids = cards().map((li) => Number(li.dataset.id));
  const a = ids.indexOf(state.anchor ?? toId);
  const b = ids.indexOf(toId);
  if (a < 0 || b < 0) return;
  if (!additive) for (const id of [...state.selected]) setSelected(id, false);
  const [lo, hi] = a < b ? [a, b] : [b, a];
  for (let i = lo; i <= hi; i += 1) setSelected(ids[i], true);
}

function selectedIds() {
  return state.grid.items.filter((it) => state.selected.has(it.id)).map((it) => it.id);
}

function renderBar() {
  const n = state.selected.size;
  const bar = $('#bar');
  bar.classList.toggle('show', n > 0);
  bar.setAttribute('aria-hidden', String(n === 0));
  $('#bar-count').textContent = `已选 ${n} 张`;
  document.body.classList.toggle('selecting', n > 0);
  const items = selectedIds().map(findItem).filter(Boolean);
  $('#bar-organize').hidden = !items.length || !items.every((it) => it.trashed && !it.organized);
}

$('#grid').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-id]');
  if (!li || suppressClick) return;
  const item = findItem(Number(li.dataset.id));
  if (!item) return;
  const onCheck = e.target.closest('.check');
  if (e.shiftKey) {
    selectRange(item.id, e.ctrlKey || e.metaKey);
  } else if (e.ctrlKey || e.metaKey || onCheck || state.selected.size) {
    setSelected(item.id, !state.selected.has(item.id));
    state.anchor = item.id;
  } else {
    openDetail(item);
    return;
  }
  renderBar();
});

// 空白处按住拖动框选；按住 Ctrl 在已选基础上追加。
const marquee = $('#marquee');
let drag = null;
let suppressClick = false;
let scrollTimer = null;

document.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || $('#app').hidden || e.pointerType === 'touch') return;
  if (state.mode !== 'grid' || !e.target.closest('#grid-wrap')) return;
  if (e.target.closest('li[data-id], button, input, select, a, .grid-bar, #ctx')) return;
  drag = {
    x: e.clientX, y: e.clientY, sx: scrollX, sy: scrollY, active: false,
    base: e.ctrlKey || e.metaKey ? new Set(state.selected) : new Set(),
  };
});

document.addEventListener('pointermove', (e) => {
  if (!drag) return;
  // 记录文档坐标，滚动后框选范围仍正确。
  const x0 = drag.x + drag.sx;
  const y0 = drag.y + drag.sy;
  const x1 = e.clientX + scrollX;
  const y1 = e.clientY + scrollY;
  if (!drag.active) {
    if (Math.abs(x1 - x0) + Math.abs(y1 - y0) < 6) return;
    drag.active = true;
    marquee.hidden = false;
    document.body.classList.add('dragging');
  }
  drag.last = e;
  const L = Math.min(x0, x1);
  const T = Math.min(y0, y1);
  const R = Math.max(x0, x1);
  const B = Math.max(y0, y1);
  Object.assign(marquee.style, {
    left: `${L - scrollX}px`, top: `${T - scrollY}px`, width: `${R - L}px`, height: `${B - T}px`,
  });
  for (const li of cards()) {
    const r = li.getBoundingClientRect();
    const hit = r.right + scrollX > L && r.left + scrollX < R
      && r.bottom + scrollY > T && r.top + scrollY < B;
    const id = Number(li.dataset.id);
    setSelected(id, hit || drag.base.has(id));
  }
  renderBar();
  autoScroll(e.clientY);
});

function autoScroll(y) {
  clearInterval(scrollTimer);
  const edge = 40;
  const dy = y < edge ? -12 : y > innerHeight - edge ? 12 : 0;
  if (!dy) return;
  scrollTimer = setInterval(() => {
    scrollBy(0, dy);
    if (drag?.last) document.dispatchEvent(new PointerEvent('pointermove', drag.last));
  }, 16);
}

function endDrag() {
  clearInterval(scrollTimer);
  if (drag?.active) {
    marquee.hidden = true;
    document.body.classList.remove('dragging');
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
  }
  drag = null;
}

document.addEventListener('pointerup', endDrag);
document.addEventListener('pointercancel', endDrag);

/* ---------- 右键菜单 ---------- */

const ctx = $('#ctx');
let ctxOwner = null;

function closeMenu(refocus) {
  if (ctx.hidden) return;
  const owner = ctxOwner;
  ctx.hidden = true;
  ctx.replaceChildren();
  ctxOwner = null;
  if (owner) {
    owner.classList.remove('active');
    if (refocus) owner.focus();
  }
}

// entries: [label, fn({x, y, owner}), extraClass?]、null（分隔线）或已构建的 <li>。
function openMenu(entries, x, y, owner) {
  closeMenu();
  ctxOwner = owner || null;
  if (owner) owner.classList.add('active');
  ctx.replaceChildren(...entries.map((entry) => {
    if (!entry) return el('li', { role: 'separator' });
    if (entry instanceof HTMLElement) return entry;
    const [label, fn, cls = ''] = entry;
    const btn = el('button', { type: 'button', role: 'menuitem', tabindex: '-1', class: cls },
      el('span', { text: label }));
    btn.addEventListener('click', (ev) => {
      const rect = ev.currentTarget.getBoundingClientRect();
      closeMenu(true);
      fn({ x: rect.left, y: rect.bottom, owner: ev.currentTarget });
    });
    return el('li', { role: 'none' }, btn);
  }));
  ctx.hidden = false;
  // 贴着光标，越界则翻转。
  const rect = ctx.getBoundingClientRect();
  const left = x + rect.width > innerWidth - 8 ? Math.max(8, x - rect.width) : x;
  const top = y + rect.height > innerHeight - 8 ? Math.max(8, y - rect.height) : y;
  ctx.style.left = `${left}px`;
  ctx.style.top = `${top}px`;
  ctx.style.transformOrigin = `${left < x ? 'right' : 'left'} ${top < y ? 'bottom' : 'top'}`;
  ctx.querySelector('[role="menuitem"], [role="menuitemcheckbox"]')?.focus();
}

function itemHasCollection(id, collectionId) {
  const item = findItem(id);
  return !!item && item.collections.some((c) => c.id === collectionId);
}

// 勾选菜单：点击立即 add / remove，菜单保持打开以便连续勾选。
function openCollectionCheck(ids, x, y, owner) {
  if (!ids.length) return;
  if (!state.collections.length) {
    toast('还没有 Collection，先在左侧新建');
    return;
  }
  const allHave = (collectionId) => ids.every((id) => itemHasCollection(id, collectionId));
  const entries = state.collections.map((c) => {
    const on = allHave(c.id);
    const btn = el('button', {
      type: 'button',
      role: 'menuitemcheckbox',
      tabindex: '-1',
      'aria-checked': String(on),
    }, el('span', { text: c.name }), el('span', { class: 'tick', text: on ? '✓' : '' }));
    btn.addEventListener('click', () => {
      const remove = allHave(c.id);
      const collection = { id: c.id, name: c.name };
      const undoEntry = {
        label: `${remove ? '移出' : '加入'}「${c.name}」`,
        collection,
        ids: ids.slice(),
        inverse: remove ? 'add' : 'remove',
      };
      pushUndo(undoEntry);
      setCollectionsLocal(ids, collection, !remove);
      refreshLocalItems(ids.map(locateItem).filter(Boolean));
      enqueueOp({
        seq: ++opSeq,
        ids: ids.slice(),
        patches: [],
        undoEntry,
        request: () => api('POST', `/api/collections/${c.id}/images`, {
          ids,
          action: remove ? 'remove' : 'add',
        }),
        onError: (err) => {
          const failed = knownItems(ids);
          removeUndoEntry(undoEntry);
          setCollectionsLocal(ids, collection, remove);
          restoreItemsIntoRank(failed);
          refreshLocalItems(failed);
          btn.setAttribute('aria-checked', String(remove));
          const tick = btn.querySelector('.tick');
          if (tick) tick.textContent = remove ? '✓' : '';
          if (err.message !== '未登录') toast(`操作失败：${err.message}`);
        },
      });
      toast(remove ? `已移出「${c.name}」` : `已加入「${c.name}」`);
      const now = !remove;
      btn.setAttribute('aria-checked', String(now));
      const tick = btn.querySelector('.tick');
      if (tick) tick.textContent = now ? '✓' : '';
    });
    return el('li', { role: 'none' }, btn);
  });
  openMenu(entries, x, y, owner);
}

function openRateMenu(ids, x, y, owner) {
  if (!ids.length) return;
  const entries = [1, 2, 3, 4, 5].map((n) => [`★${n}`, () => rateIds(ids, n)]);
  entries.push(null, ['作废（0 分）', () => rateIds(ids, 0), 'danger']);
  openMenu(entries, x, y, owner);
}

function itemMenu(item) {
  const entries = [
    ['查看详情', () => openDetail(item)],
    ['大图查看', () => openLightbox(item, false)],
    ['复制相对路径', () => copy(item.rel_path, '路径')],
    null,
    ['打分 ▾', ({ x, y }) => openRateMenu([item.id], x, y)],
    [item.loved ? '取消收藏' : '❤ 收藏', () => lovedIds([item.id], !item.loved)],
    [item.trashed ? '移出 Trash' : '移入 Trash', () => trashIds([item.id], !item.trashed, false)],
    ['加入 Collection ▾', ({ x, y }) => openCollectionCheck([item.id], x, y)],
  ];
  if (item.organized) entries.push(['恢复（移出 _trash）', () => organizeIds([item.id], true)]);
  else if (item.trashed) entries.push(['物理整理到 _trash', () => organizeIds([item.id], false)]);
  return entries;
}

// 网格里双击卡片也能进灯箱（会先收起可能已被单击打开的详情抽屉）。
$('#grid').addEventListener('dblclick', (e) => {
  const li = e.target.closest('li[data-id]');
  const item = li && findItem(Number(li.dataset.id));
  if (!item) return;
  if ($('#detail').open) closeDialog($('#detail'));
  openLightbox(item, false);
});

$('#grid').addEventListener('contextmenu', (e) => {
  const li = e.target.closest('li[data-id]');
  const item = li && findItem(Number(li.dataset.id));
  if (!item) return;
  e.preventDefault();
  const cardBtn = li.querySelector('.card');
  let { clientX: x, clientY: y } = e;
  if (!x && !y) { // 键盘触发（菜单键 / Shift+F10）
    const rect = cardBtn.getBoundingClientRect();
    x = rect.left + 12;
    y = rect.top + 12;
  }
  openMenu(itemMenu(item), x, y, cardBtn);
});

ctx.addEventListener('keydown', (e) => {
  const items = [...ctx.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"]')];
  if (!items.length) return;
  const i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const delta = e.key === 'ArrowDown' ? 1 : -1;
    items[(i + delta + items.length) % items.length].focus();
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault();
    items[e.key === 'Home' ? 0 : items.length - 1].focus();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    closeMenu(true);
  } else if (e.key === 'Tab') {
    closeMenu(true);
  }
});
ctx.addEventListener('contextmenu', (e) => e.preventDefault());
document.addEventListener('pointerdown', (e) => {
  if (!ctx.contains(e.target) && !e.target.closest('.menu-trigger')) closeMenu();
});
window.addEventListener('scroll', () => closeMenu(), { passive: true });
window.addEventListener('resize', () => closeMenu());
window.addEventListener('blur', () => closeMenu());

/* ---------- 批量操作 ---------- */

// 打分 / 收藏 / Trash / Collection 都是「先改本地，再排队后台确认」：
// 接口慢时界面仍然即时响应；服务端返回后按顺序校准。
function stageRate(ids, score, opts = {}) {
  if (!ids.length) return;
  const patches = [];
  const oldPatches = [];
  for (const id of ids) {
    const item = locateItem(id);
    if (!item) continue;
    oldPatches.push(metaPatch(item, ['score', 'trashed', 'rated_at']));
    patches.push({ id, fields: predictedRateFields(item, score) });
  }
  if (!patches.length) return;
  const sendIds = patches.map((patch) => patch.id);
  const undoEntry = {
    label: score === 0
      ? (sendIds.length === 1 ? '作废' : `作废 ${sendIds.length} 张`)
      : (sendIds.length === 1 ? `打分 ★${score}` : `打分 ★${score}（${sendIds.length} 张）`),
    patches: oldPatches,
  };
  pushUndo(undoEntry);
  refreshLocalItems(applyLocalPatches(patches));
  enqueueOp({
    seq: ++opSeq,
    ids: sendIds,
    patches,
    undoEntry,
    request: () => (sendIds.length === 1
      ? api('POST', `/api/images/${sendIds[0]}/rate`, { score })
      : api('POST', '/api/images/batch', { ids: sendIds, op: 'rate', score })),
  });
  if (opts.autoAdvance) {
    const advanceId = currentItem()?.id;
    if (advanceId === sendIds[0]) {
      setTimeout(() => {
        if (state.mode !== 'ranking') return;
        if (currentItem()?.id !== advanceId) return;
        nextImage(true);
      }, RATE_ADVANCE_MS);
    }
  }
  if (sendIds.length > 1) finishBatch();
  if (sendIds.length > 1) {
    toast(score === 0 ? `已作废 ${sendIds.length} 张` : `已给 ${sendIds.length} 张打分`);
  } else {
    toast(score === 0 ? '已作废' : `已评 ${score} 星`);
  }
}

function rateIds(ids, score) {
  stageRate(ids, score);
}

function stageLoved(ids, value) {
  if (!ids.length) return;
  const patches = [];
  const oldPatches = [];
  for (const id of ids) {
    const item = locateItem(id);
    if (!item) continue;
    oldPatches.push(metaPatch(item, ['loved']));
    patches.push({ id, fields: { loved: value } });
  }
  if (!patches.length) return;
  const sendIds = patches.map((patch) => patch.id);
  const undoEntry = {
    label: sendIds.length === 1
      ? (value ? '收藏' : '取消收藏')
      : (value ? `收藏 ${sendIds.length} 张` : `取消收藏 ${sendIds.length} 张`),
    patches: oldPatches,
  };
  pushUndo(undoEntry);
  refreshLocalItems(applyLocalPatches(patches));
  enqueueOp({
    seq: ++opSeq,
    ids: sendIds,
    patches,
    undoEntry,
    request: () => (sendIds.length === 1
      ? api('POST', `/api/images/${sendIds[0]}/loved`, { loved: value })
      : api('POST', '/api/images/batch', { ids: sendIds, op: 'loved', loved: value })),
  });
  if (sendIds.length > 1) finishBatch();
  toast(value ? '已收藏' : '已取消收藏');
}

function lovedIds(ids, value) {
  stageLoved(ids, value);
}

function stageTrash(ids, value, ask) {
  if (!ids.length) return;
  if (ask && !confirm(`将选中的 ${ids.length} 张移入 Trash？`)) return;
  const patches = [];
  const oldPatches = [];
  for (const id of ids) {
    const item = locateItem(id);
    if (!item) continue;
    oldPatches.push(metaPatch(item, ['trashed']));
    patches.push({ id, fields: { trashed: value } });
  }
  if (!patches.length) return;
  const sendIds = patches.map((patch) => patch.id);
  const undoEntry = {
    label: sendIds.length === 1
      ? (value ? '移入 Trash' : '移出 Trash')
      : (value ? `移入 Trash ${sendIds.length} 张` : `移出 Trash ${sendIds.length} 张`),
    patches: oldPatches,
  };
  pushUndo(undoEntry);
  refreshLocalItems(applyLocalPatches(patches));
  enqueueOp({
    seq: ++opSeq,
    ids: sendIds,
    patches,
    undoEntry,
    request: () => (sendIds.length === 1
      ? api('POST', `/api/images/${sendIds[0]}/trash`, { trashed: value })
      : api('POST', '/api/images/batch', { ids: sendIds, op: 'trash', trashed: value })),
  });
  if (sendIds.length > 1) finishBatch();
  toast(value ? '已移入 Trash' : '已移出 Trash');
}

function trashIds(ids, value, ask) {
  stageTrash(ids, value, ask);
}

async function organizeIds(ids, restore) {
  if (!ids.length) return;
  const verb = restore ? '恢复' : '物理整理';
  const note = restore ? '\n文件会从 _trash 移回原路径，并移出 Trash。' : '\n文件会移入 <root>/_trash/，不会删除。';
  if (!confirm(`${verb} ${ids.length} 张图片？${note}`)) return;
  try {
    const data = await api('POST', restore ? '/api/restore' : '/api/organize', { ids });
    const moved = data.moved || 0;
    const failed = data.failed || [];
    const parts = [];
    if (moved) parts.push(`已${restore ? '恢复' : '整理'} ${moved} 张`);
    if (failed.length) parts.push(`失败 ${failed.length} 张：${failed.map((f) => `#${f.id} ${f.reason || '未知原因'}`).join('；')}`);
    toast(parts.length ? parts.join('；') : '没有可处理的图片');
    await syncAfterChange(ids);
  } catch (err) {
    toast(err.message);
  }
}

// Trash 视图的一键整理：先取齐所有「在 Trash 且未整理」的 id，再走现有组织接口。
async function fetchTrashOrganizeIds() {
  const ids = [];
  let page = 1;
  for (;;) {
    const params = new URLSearchParams({ view: 'trash', page: String(page), per_page: '200' });
    const data = await api('GET', `/api/images?${params}`);
    for (const item of data.items) {
      if (item.trashed && !item.organized && !item.missing) ids.push(item.id);
    }
    if (page >= data.last_page) break;
    page += 1;
  }
  return ids;
}

let organizeAllBusy = false;

async function organizeAllTrash() {
  if (organizeAllBusy) return;
  organizeAllBusy = true;
  const btn = $('#btn-organize-all');
  const label = btn.textContent;
  btn.disabled = true;
  try {
    btn.textContent = '读取 Trash…';
    const ids = await fetchTrashOrganizeIds();
    if (!ids.length) {
      toast('Trash 中没有未整理的图片');
      return;
    }
    if (!confirm(`将 Trash 中 ${ids.length} 张未整理的图片移入 <root>/_trash/？\n不会删除任何文件，之后可以恢复。`)) return;
    btn.textContent = '整理中…';
    const data = await api('POST', '/api/organize', { ids });
    const moved = data.moved || 0;
    const failed = data.failed || [];
    const parts = [];
    if (moved) parts.push(`已整理 ${moved} 张`);
    if (failed.length) parts.push(`失败 ${failed.length} 张：${failed.map((f) => `#${f.id} ${f.reason || '未知原因'}`).join('；')}`);
    toast(parts.length ? parts.join('；') : '没有可处理的图片');
    await loadActive();
  } catch (err) {
    if (err.message !== '未登录') toast(err.message);
  } finally {
    organizeAllBusy = false;
    btn.disabled = false;
    btn.textContent = label;
  }
}

$('#btn-organize-all').addEventListener('click', organizeAllTrash);

// 批量操作的界面已经就地更新，不再整页重载等接口。
function finishBatch() {
  state.selected.clear();
  state.anchor = null;
  renderBar();
}

$('#bar-rate').addEventListener('click', (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  openRateMenu(selectedIds(), rect.left, rect.bottom + 6, e.currentTarget);
});
$('#bar-loved').addEventListener('click', () => lovedIds(selectedIds(), true));
$('#bar-trash').addEventListener('click', () => trashIds(selectedIds(), true, false));
$('#bar-untrash').addEventListener('click', () => trashIds(selectedIds(), false, false));
$('#bar-organize').addEventListener('click', () => organizeIds(selectedIds(), false));
$('#bar-clear').addEventListener('click', clearSelection);

/* ---------- 快捷键 ---------- */

document.addEventListener('keydown', (e) => {
  if ($('#app').hidden || isTyping(e.target)) return;
  // 灯箱也是 dialog，但要让快捷键继续生效，所以只被其他 dialog 挡住。
  if ($$('dialog[open]').some((d) => d.id !== 'lightbox')) return;
  if (!ctx.hidden) {
    if (e.key === 'Escape') closeMenu(true);
    return;
  }
  const key = e.key;
  if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === 'z') {
    e.preventDefault();
    undoLast();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === 'a' && state.mode === 'grid') {
    e.preventDefault();
    for (const li of cards()) setSelected(Number(li.dataset.id), true);
    renderBar();
    return;
  }
  if (key === 'Escape') {
    if (state.lightbox.on) {
      closeLightbox();
      return;
    }
    if (state.selected.size) clearSelection();
    return;
  }
  if (key === 'Delete' && state.mode === 'grid' && state.selected.size) {
    e.preventDefault();
    trashIds(selectedIds(), true, true);
    return;
  }
  if (key === '?' || (e.shiftKey && key === '/')) {
    e.preventDefault();
    $('#help').showModal();
    return;
  }
  if (key === 'g' || key === 'G') {
    e.preventDefault();
    setMode(state.mode === 'grid' ? 'ranking' : 'grid');
    return;
  }
  if (key === 'f' || key === 'F') {
    e.preventDefault();
    if (state.lightbox.on) {
      closeLightbox();
    } else if (state.mode === 'ranking') {
      openLightbox(currentItem(), true);
    } else {
      const id = state.selected.values().next().value;
      const item = id === undefined ? null : findItem(id);
      if (item) openLightbox(item, false);
    }
    return;
  }
  if (state.lightbox.on && !state.lightbox.fromRank) {
    // 从网格/抽屉打开的灯箱锁定单张：打分、收藏、Trash 快捷键可用，但不切换图片。
    if (/^[0-5]$/.test(key)) {
      rateLightbox(Number(key));
    } else if (key === 'l' || key === 'L') {
      lovedLightbox();
    } else if (key === 'x' || key === 'X') {
      trashLightbox();
    }
    return;
  }
  if (state.mode !== 'ranking') return;
  if (key === 'ArrowLeft') {
    e.preventDefault();
    prevImage();
  } else if (key === 'ArrowRight') {
    e.preventDefault();
    nextImage(true);
  } else if (key === 'l' || key === 'L') {
    toggleLovedCurrent();
  } else if (key === 'x' || key === 'X') {
    toggleTrashCurrent();
  } else if (key === 'c' || key === 'C') {
    openRankCollectionMenu();
  } else if (/^[0-5]$/.test(key)) {
    rateCurrent(Number(key));
  }
});

/* ---------- 详情抽屉 ---------- */

function detailStatus(item) {
  if (item.organized) return item.trashed ? 'Trash · 已整理到 _trash' : '已整理到 _trash';
  if (item.trashed) return '在 Trash 中';
  if (item.score === 0) return '作废';
  return '正常';
}

function renderDetail(item) {
  $('#d-title').textContent = item.filename;
  const img = $('#d-img');
  img.alt = item.filename;
  img.classList.remove('loaded');
  img.src = item.full_url;
  fadeIn(img);
  $('#d-open').href = item.full_url;
  const collections = item.collections.length ? item.collections.map((c) => c.name).join('、') : '—';
  const meta = [
    ['尺寸', `${item.width} × ${item.height}`],
    ['大小', fmtSize(item.size)],
    ['时间', fmtTime(item.mtime)],
    ['相对路径', item.rel_path],
    ['状态', detailStatus(item)],
    ['Collections', collections],
  ];
  $('#d-meta').replaceChildren(...meta.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: v })]));
  syncStarButtons($('#d-stars'), item);
  const voidBtn = $('#d-void');
  voidBtn.classList.toggle('active', item.score === 0);
  voidBtn.setAttribute('aria-pressed', String(item.score === 0));
  const loved = $('#d-loved');
  loved.classList.toggle('active', !!item.loved);
  loved.setAttribute('aria-pressed', String(!!item.loved));
  loved.textContent = item.loved ? '❤ 已收藏' : '❤ 收藏';
  const trash = $('#d-trash');
  trash.textContent = item.trashed ? '移出 Trash' : '移入 Trash';
  $('#d-organize').hidden = !(item.trashed && !item.organized);
  $('#d-restore').hidden = !item.organized;
  $('#d-colls').replaceChildren(...(item.collections.length
    ? item.collections.map((c) => el('span', { class: 'chip', text: c.name }))
    : [el('span', { class: 'muted', text: '未加入任何 Collection' })]));
  $('#d-coll').textContent = item.collections.length ? '+ 调整 Collection' : '+ 加入 Collection';
}

function renderDetailCollChecks(item) {
  const box = $('#d-coll-list');
  if (!state.collections.length) {
    box.replaceChildren(el('span', { class: 'muted', text: '还没有 Collection，先在左侧新建' }));
    return;
  }
  box.replaceChildren(...state.collections.map((c) => {
    const input = el('input', {
      type: 'checkbox',
      checked: item.collections.some((x) => x.id === c.id),
    });
    input.addEventListener('change', () => {
      const remove = !input.checked;
      const collection = { id: c.id, name: c.name };
      const undoEntry = {
        label: `${remove ? '移出' : '加入'}「${c.name}」`,
        collection,
        ids: [item.id],
        inverse: remove ? 'add' : 'remove',
      };
      pushUndo(undoEntry);
      setCollectionsLocal([item.id], collection, !remove);
      refreshLocalItems([locateItem(item.id) || item]);
      enqueueOp({
        seq: ++opSeq,
        ids: [item.id],
        patches: [],
        undoEntry,
        request: () => api('POST', `/api/collections/${c.id}/images`, {
          ids: [item.id],
          action: remove ? 'remove' : 'add',
        }),
        onError: (err) => {
          const failed = knownItems([item.id]);
          removeUndoEntry(undoEntry);
          setCollectionsLocal([item.id], collection, remove);
          restoreItemsIntoRank(failed);
          refreshLocalItems(failed);
          if (err.message !== '未登录') toast(`操作失败：${err.message}`);
        },
      });
      toast(remove ? `已移出「${c.name}」` : `已加入「${c.name}」`);
    });
    return el('label', { class: 'coll-check' }, input, el('span', { text: c.name }));
  }));
}

function openDetail(item) {
  state.detail = item;
  $('#d-coll-list').hidden = true;
  renderDetail(item);
  if (!$('#detail').open) $('#detail').showModal();
}

$('#d-stars').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-score]');
  if (btn && state.detail) rateIds([state.detail.id], Number(btn.dataset.score));
});
$('#d-void').addEventListener('click', () => {
  const item = state.detail;
  if (item) rateIds([item.id], 0);
});
$('#d-loved').addEventListener('click', () => {
  const item = state.detail;
  if (item) lovedIds([item.id], !item.loved);
});
$('#d-trash').addEventListener('click', () => {
  const item = state.detail;
  if (item) trashIds([item.id], !item.trashed, false);
});
$('#d-organize').addEventListener('click', () => {
  const item = state.detail;
  if (item) organizeIds([item.id], false);
});
$('#d-restore').addEventListener('click', () => {
  const item = state.detail;
  if (item) organizeIds([item.id], true);
});
$('#d-coll').addEventListener('click', () => {
  const item = state.detail;
  if (!item) return;
  const box = $('#d-coll-list');
  if (!box.hidden) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  renderDetailCollChecks(item);
});
$('#detail').addEventListener('close', () => {
  state.detail = null;
  $('#d-coll-list').hidden = true;
});

/* ---------- 设置 ---------- */

async function loadSettings() {
  const data = await api('GET', '/api/settings');
  $('#set-root').value = data.root || '';
  const rows = [
    ['版本', `v${data.version || '?'}`],
    ['监听地址', `${data.host}:${data.port}`],
    ['数据目录', String(data.data_dir)],
  ];
  $('#set-info').replaceChildren(...rows.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: v })]));
}

$('#btn-settings').addEventListener('click', async () => {
  $('#password-form').reset();
  $('#settings').showModal();
  try {
    await loadSettings();
  } catch (err) {
    if (err.message !== '未登录') toast(err.message);
  }
});

$('#settings-root-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const root = $('#set-root').value.trim();
  if (!root) { toast('根目录不能为空'); return; }
  const btn = e.currentTarget.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const data = await api('PUT', '/api/settings', { root });
    toast('已保存');
    if (data.scan_started) beginScanWatch(null);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
});

$('#password-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const current = $('#cur-password').value;
  const next = $('#new-password').value;
  const again = $('#new-password2').value;
  if (!current) { toast('请输入当前密码'); return; }
  if (next.length < 4) { toast('新密码至少 4 个字符'); return; }
  if (next !== again) { toast('两次输入的新密码不一致'); return; }
  const btn = e.currentTarget.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    await api('PUT', '/api/settings', { current_password: current, new_password: next });
    $('#password-form').reset();
    toast('密码已修改');
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 启动 ---------- */

$$('dialog').forEach((d) => {
  d.addEventListener('click', (e) => {
    if (e.target === d || e.target.closest('[data-close]')) closeDialog(d);
  });
  d.addEventListener('cancel', (e) => {
    e.preventDefault();
    closeDialog(d);
  });
});

$('#sort').value = state.sort;
renderMode();
renderSidebar();
renderBar();

async function initSession() {
  try {
    const res = await fetch('/api/session', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const session = await res.json();
    if (session.authed) showApp();
    else showLogin(!!session.needs_setup);
  } catch (err) {
    showLogin(false);
    $('#login-error').textContent = `无法连接服务器：${err.message}`;
  }
}

initSession();
