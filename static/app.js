function root() { return document.getElementById('root').value.trim(); }
function channel() { return document.getElementById('channel').value; }
function log(text) {
  const el = document.getElementById('log');
  el.textContent += text + "\n";
  el.scrollTop = el.scrollHeight;
}
function clearLog() { document.getElementById('log').textContent = ''; }

async function api(path, opts) {
  const resp = await fetch(path, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}

let lastScan = null;
let browseCurrentPath = null;

async function pickFolder() {
  try {
    const res = await api('/api/pick-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: 'Выберите папку EFI/OC' }),
    });
    if (res.path) {
      document.getElementById('root').value = res.path;
    } else if (res.cancelled) {
      // user hit Cancel in the native dialog - nothing to do
    } else if (res.unavailable) {
      log('Нативный диалог недоступен (не macOS?) - открываю встроенный обзор папок.');
      openBrowse();
    }
  } catch (e) {
    log('Выбор папки: ' + e.message);
  }
}

function openBrowse() {
  document.getElementById('browse-panel').hidden = false;
  browseTo(root() || null);
}
function closeBrowse() {
  document.getElementById('browse-panel').hidden = true;
}
function browseHome() {
  browseTo(null); // server defaults an empty path to the home directory
}
function browseUp() {
  const parent = lastBrowseResult && lastBrowseResult.parent;
  if (parent) browseTo(parent);
}
let lastBrowseResult = null;

async function browseTo(path) {
  try {
    const qs = path ? `?path=${encodeURIComponent(path)}` : '';
    const data = await api(`/api/browse${qs}`);
    lastBrowseResult = data;
    browseCurrentPath = data.path;
    document.getElementById('browse-path').value = data.path;
    document.getElementById('browse-current-hint').textContent = data.is_efi_oc
      ? 'Эта папка похожа на настоящий EFI/OC (есть Kexts/ и config.plist).'
      : '';
    const list = document.getElementById('browse-list');
    list.innerHTML = '';
    for (const d of data.dirs) {
      const li = document.createElement('li');
      li.textContent = d.name;
      if (d.is_efi_oc) li.classList.add('efi-oc');
      li.onclick = () => browseTo(data.path + '/' + d.name);
      list.appendChild(li);
    }
  } catch (e) {
    log('Обзор: ' + e.message);
  }
}

function selectBrowsePath() {
  if (!browseCurrentPath) return;
  document.getElementById('root').value = browseCurrentPath;
  closeBrowse();
}

async function scanRoot() {
  clearLog();
  try {
    lastScan = await api(`/api/scan?root=${encodeURIComponent(root())}`);
    renderScan(lastScan);
    saveLastSettings();
    log('Скан завершён (без обращения к сети).');
  } catch (e) {
    log('Ошибка: ' + e.message);
  }
}

async function checkUpdates() {
  log('Проверяю GitHub (' + channel() + ')...');
  try {
    lastScan = await api(`/api/check-updates?root=${encodeURIComponent(root())}&channel=${channel()}`);
    renderScan(lastScan);
    saveLastSettings();
    saveLastScanCache(lastScan);
    log('Готово.');
  } catch (e) {
    log('Ошибка: ' + e.message);
  }
}

const LAST_SETTINGS_KEY = 'ocut-last-settings';
const LAST_SCAN_KEY = 'ocut-last-scan';

function saveLastSettings() {
  try {
    localStorage.setItem(LAST_SETTINGS_KEY, JSON.stringify({ root: root(), channel: channel() }));
  } catch (e) { /* private browsing / storage disabled - fine, just skip remembering */ }
}

function saveLastScanCache(data) {
  try {
    localStorage.setItem(LAST_SCAN_KEY, JSON.stringify(data));
  } catch (e) { /* same as above - non-fatal if storage isn't available */ }
}

function restoreLastSettingsAndAutoCheck() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(LAST_SETTINGS_KEY) || 'null');
  } catch (e) {
    return;
  }
  if (!saved || !saved.root) return;
  document.getElementById('root').value = saved.root;
  if (saved.channel) document.getElementById('channel').value = saved.channel;

  // Render whatever we saw last time immediately, before the network round
  // trip - so a page refresh shows the same table right away instead of
  // going blank while /api/check-updates is in flight (that's what "всё
  // сбрасывается" on refresh meant: sections start `hidden` in the HTML
  // and only appear once renderScan() runs).
  let cached = null;
  try {
    cached = JSON.parse(localStorage.getItem(LAST_SCAN_KEY) || 'null');
  } catch (e) { /* corrupt/missing cache - fall through to a plain background check */ }

  if (cached) {
    renderScan(cached);
    log('Показаны данные с прошлого раза, обновляю в фоне...');
  } else {
    log(`Найден запомненный путь (${saved.root}) - проверяю обновления в фоне...`);
  }
  checkUpdates();
}

window.addEventListener('DOMContentLoaded', restoreLastSettingsAndAutoCheck);

function renderScan(data) {
  document.getElementById('components-section').hidden = false;
  document.getElementById('opencore-section').hidden = false;
  document.getElementById('drivers-section').hidden = false;

  const tbody = document.querySelector('#components-table tbody');
  tbody.innerHTML = '';
  for (const c of data.components) {
    const latest = c.latest_version || (c.error ? 'ошибка' : '?');
    const sourceBadge = sourceBadgeHtml(c.source);
    for (const k of c.kexts) {
      const tr = document.createElement('tr');
      tr.appendChild(kextCheckboxCell(k));
      tr.innerHTML += `
        <td>${c.name}<br><span class="hint">${k.bundle}</span></td>
        <td>${k.local_version || (k.present ? '?' : '—')}</td>
        <td>${latest} ${sourceBadge}</td>
        <td>${kextStatusCell(k)}</td>
        <td>
          <button onclick="updateComponent('${c.name}')">обновить</button>
          <button class="remove-btn" onclick="removeKextFromConfig('${k.bundle}')"
              ${k.wired ? '' : 'disabled'}>убрать из конфига</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  const oc = data.opencore;
  document.getElementById('oc-channel-label').textContent = channel();
  document.getElementById('oc-current-version').textContent =
    oc.live_booted_version || oc.last_known_version || (oc.present ? '?' : 'нет файла');
  document.getElementById('oc-latest-version').innerHTML =
    (oc.latest_version || (oc.error ? 'ошибка' : '?')) + ' ' + sourceBadgeHtml(oc.source);

  const ocInfo = document.getElementById('opencore-info');
  if (!oc.present) {
    ocInfo.textContent = 'OpenCore.efi не найден по этому пути.';
  } else {
    const lines = [
      data.dortania_error ? `Dortania build-repo недоступен (${data.dortania_error}) - используется официальный GitHub-релиз как запасной вариант.` : null,
      oc.live_booted_version ?
        'Версия взята из NVRAM текущей загруженной системы - совпадает с файлом по этому пути, только если вы сейчас загружены именно с него.' :
        'NVRAM-версия недоступна (не macOS, или Misc.Security.ExposeSensitiveData без бита 0x02) - показана версия, которую последний раз применил сам OCUT.',
      oc.last_known_version ? null : (oc.live_booted_version ? null :
        'Версия ещё не отслеживалась этим инструментом (обновите хотя бы раз, чтобы начать трекинг).'),
      oc.last_known_version && oc.changed_since_last_update ?
        'Файл изменился с последнего known-апдейта (обновили чем-то другим или вручную).' : null,
      oc.error || null,
    ].filter(Boolean);
    ocInfo.innerHTML = lines.join('<br>');
  }

  const dtbody = document.querySelector('#drivers-table tbody');
  dtbody.innerHTML = '';
  for (const d of data.drivers) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${d.file}</td><td>${d.last_known_version || '—'}</td>
      <td>${d.changed_since_last_update ? 'да' : 'нет'}</td>`;
    dtbody.appendChild(tr);
  }
}

function kextCheckboxCell(k) {
  const td = document.createElement('td');
  if (!k.wired) {
    const btn = document.createElement('button');
    btn.className = 'wire-btn';
    btn.textContent = '+';
    btn.title = 'Подключить в Kernel->Add';
    btn.disabled = !k.present;
    btn.onclick = () => wireKextToConfig(k.bundle);
    td.appendChild(btn);
    return td;
  }
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!k.enabled;
  cb.onchange = () => toggleKext(k.bundle, cb.checked);
  td.appendChild(cb);
  return td;
}

function sourceBadgeHtml(source) {
  if (source === 'dortania') return '<span class="badge badge-dortania" title="Dortania build-repo - continuous build from upstream master, ahead of official releases">Dortania</span>';
  if (source === 'github') return '<span class="badge badge-github" title="официальный релиз/pre-release из GitHub">GitHub</span>';
  return '';
}

function kextStatusCell(k) {
  if (!k.wired) return '<span class="enabled-no">не подключён</span>';
  if (!k.present) return '<span class="enabled-missing">подключён, но файла нет!</span>';
  return k.enabled ? '<span class="enabled-yes">включён</span>' : '<span class="enabled-no">выключен</span>';
}

async function toggleKext(bundle, enabled) {
  try {
    await api('/api/kext/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), bundle, enabled }),
    });
    log(`${bundle}: ${enabled ? 'включён' : 'выключен'}`);
  } catch (e) {
    log(`${bundle}: ошибка - ${e.message}`);
  }
  scanRoot();
}

async function wireKextToConfig(bundle) {
  try {
    await api('/api/kext/add-to-config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), bundle }),
    });
    log(`${bundle}: добавлен в Kernel->Add`);
  } catch (e) {
    log(`${bundle}: ошибка - ${e.message}`);
  }
  scanRoot();
}

async function removeKextFromConfig(bundle) {
  if (!confirm(`Убрать ${bundle} из Kernel->Add? Сам файл кекста останется в Kexts/, просто перестанет грузиться.`)) return;
  try {
    await api('/api/kext/remove-from-config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), bundle }),
    });
    log(`${bundle}: убран из Kernel->Add`);
  } catch (e) {
    log(`${bundle}: ошибка - ${e.message}`);
  }
  scanRoot();
}

function openAddComponent() {
  document.getElementById('add-component-panel').hidden = false;
}
function closeAddComponent() {
  document.getElementById('add-component-panel').hidden = true;
}
async function submitAddComponent() {
  const name = document.getElementById('add-comp-name').value.trim();
  const repo = document.getElementById('add-comp-repo').value.trim();
  const kexts = document.getElementById('add-comp-kexts').value.split(',').map(s => s.trim()).filter(Boolean);
  if (!name || !repo || !kexts.length) { log('Заполните название, репозиторий и хотя бы один .kext.'); return; }
  try {
    await api('/api/components/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, repo, kexts }),
    });
    log(`Добавлен компонент ${name} (${repo}).`);
    closeAddComponent();
    scanRoot();
  } catch (e) {
    log('Добавить компонент: ' + e.message);
  }
}

async function updateComponent(name) {
  log(`Обновляю ${name}...`);
  try {
    const res = await api('/api/update-kext', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ component: name, root: root(), channel: channel() }),
    });
    res.log.forEach(log);
  } catch (e) {
    log(`[${name}] ошибка: ${e.message}`);
  }
  scanRoot();
}

async function updateAllComponents() {
  if (!lastScan) { log('Сначала сканируйте.'); return; }
  const names = lastScan.components.map(c => c.name);
  if (!confirm(`Обновить все отслеживаемые кексты (${names.length})?`)) return;
  for (const name of names) {
    await updateComponent(name);
  }
}

async function updateOpenCore() {
  const parts = [];
  if (document.getElementById('oc-part-efi').checked) parts.push('efi');
  if (document.getElementById('oc-part-drivers').checked) parts.push('drivers');
  if (document.getElementById('oc-part-resources').checked) parts.push('resources');
  if (!parts.length) { log('Ничего не выбрано.'); return; }
  if (!confirm(`Применить к OpenCorePkg (${parts.join(', ')})? Это затрагивает загрузчик напрямую.`)) return;
  try {
    const res = await api('/api/update-opencore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), channel: channel(), parts }),
    });
    res.log.forEach(log);
  } catch (e) {
    log('Ошибка: ' + e.message);
  }
  scanRoot();
}

async function applyTheme() {
  const repo = document.getElementById('theme-repo').value.trim();
  const ref = document.getElementById('theme-ref').value.trim();
  if (!repo) { log('Укажите репозиторий темы.'); return; }
  if (!confirm(`Заменить Resources/ содержимым из ${repo}?`)) return;
  try {
    const res = await api('/api/apply-theme', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, root: root(), ref: ref || undefined }),
    });
    res.log.forEach(log);
  } catch (e) {
    log('Ошибка: ' + e.message);
  }
}

async function previewMigration() {
  try {
    const res = await api('/api/migrate-config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), channel: channel() }),
    });
    renderMigrationReport(res.report);
  } catch (e) {
    log('Ошибка миграции: ' + e.message);
  }
}

async function saveMigration() {
  if (!confirm('Сохранить результат как config.migrated.plist рядом с текущим config.plist? ' +
    'Текущий config.plist не будет тронут.')) return;
  try {
    const res = await api('/api/migrate-config/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root(), channel: channel() }),
    });
    renderMigrationReport(res.report);
    log(`Сохранено: ${res.saved_to}`);
  } catch (e) {
    log('Ошибка миграции: ' + e.message);
  }
}

function renderMigrationReport(report) {
  const lines = [];
  lines.push(`Целевая версия OpenCore: ${report.target_version} (${report.channel})`);
  lines.push('');
  lines.push(`=== Несовместимость типов (${report.type_mismatch.length}) — использован новый дефолт, проверьте руками ===`);
  report.type_mismatch.forEach(t => lines.push(`  ${t.path}: было ${t.old_type}, стало ${t.new_type}`));
  lines.push('');
  lines.push(`=== Убрано из новой схемы (${report.removed_in_new.length}) ===`);
  report.removed_in_new.forEach(p => lines.push('  ' + p));
  lines.push('');
  lines.push(`=== Новые ключи, оставлены по дефолту новой схемы (${report.kept_new_default.length}) ===`);
  report.kept_new_default.forEach(p => lines.push('  ' + p));
  document.getElementById('migration-report').textContent = lines.join('\n');
}
