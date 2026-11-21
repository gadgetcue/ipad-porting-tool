// Usage: node run.js <generated-project-dir>
// Loads the generated web app in Chromium with the mock native bridge and exercises the Electron example.
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const out = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, 'utf8');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

function check(cond, msg) { if (!cond) { console.error('FAIL: ' + msg); process.exitCode = 1; } else console.log('ok - ' + msg); }

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());

  await page.addInitScript({ content: read(path.join(__dirname, 'mock-native.js')) });
  for (const name of ['ipadport-shim', 'ipc-handlers', 'preload']) {
    const file = path.join(out, 'BundleResources', name + '.js');
    if (fs.existsSync(file)) await page.addInitScript({ content: read(file) });
  }
  await page.route('http://app.local/**', (route) => {
    const rel = decodeURIComponent(new URL(route.request().url()).pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.join(out, 'web', rel);
    if (!file.startsWith(path.join(out, 'web')) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: 'nf' });
    route.fulfill({ status: 200, contentType: mime[path.extname(file)] || 'application/octet-stream', body: fs.readFileSync(file) });
  });

  await page.goto('http://app.local/index.html');
  await page.waitForSelector('#list div');

  check(await page.evaluate(() => typeof window.ipadport === 'object'), 'window.ipadport is defined');
  check(await page.evaluate(() => typeof window.notesApi === 'object'), 'preload exposed notesApi via contextBridge');
  check(await page.evaluate(() => !!document.querySelector('meta[name=viewport]')), 'responsive viewport meta was added');
  check(await page.evaluate(() => document.documentElement.classList.contains('ipadport-regular')), 'size class class on <html>');
  check((await page.textContent('#list div')).includes('Welcome'), 'notes:load handler ran (default note shown)');

  await page.click('#add');
  await page.fill('#editor', 'Shopping list\nmilk');
  await page.waitForTimeout(100);
  const saved = await page.evaluate(() => window.ipadport.fs.readFileSync('/AppData/Notes Example/notes.json', 'utf8'));
  check(JSON.parse(saved)[0] === 'Shopping list\nmilk', 'notes:save wrote JSON into the sandbox via fs shim');

  await page.click('#export');
  await page.waitForTimeout(100);
  const exported = await page.evaluate(() => window.ipadport.fs.readFileSync('/notes.txt', 'utf8'));
  check(exported.includes('Shopping list'), 'notes:export wrote the export file');
  check(await page.evaluate(() => window.__mockNative.shared.length === 1), 'export opened the share sheet');

  await page.click('#help');
  await page.waitForTimeout(50);
  check(await page.evaluate(() => window.__mockNative.opened[0] && window.__mockNative.opened[0].startsWith('https://')), 'shell.openExternal routed to native');

  // Reload: data persists through the native store (mock keeps state per page, so re-check via API)
  const api = await page.evaluate(async () => {
    const r = {};
    const fs = window.ipadport.fs;
    await fs.promises.writeFile('/a/b.txt', 'hello');
    r.read = await fs.promises.readFile('/a/b.txt', 'utf8');
    r.buf = (await fs.promises.readFile('/a/b.txt')).toString();
    r.list = fs.readdirSync('/a');
    r.exists = fs.existsSync('/a/b.txt');
    r.stat = fs.statSync('/a/b.txt').isFile();
    try { fs.readFileSync('/missing'); } catch (e) { r.code = e.code; }
    await new Promise((res) => fs.readFile('/a/b.txt', 'utf8', (err, data) => { r.cb = data; res(); }));
    fs.writeFileSync('/bin.dat', new Uint8Array([0, 255, 10]));
    r.bin = Array.from(fs.readFileSync('/bin.dat'));
    window.ipadport.store.set('k', { x: 1 });
    r.store = window.ipadport.store.get('k').x;
    window.ipadport.clipboard.writeText('copied');
    r.clip = window.require ? 'has-require' : window.ipadport.clipboard.readText();
    r.path = window.ipadport.path.join('/a', '../b', 'c.txt');
    r.platform = window.process.platform;
    try { await window.ipadport.electron.ipcRenderer.invoke('nope'); } catch (e) { r.missing = e.message; }
    return r;
  });
  check(api.read === 'hello' && api.buf === 'hello' && api.cb === 'hello', 'fs promise, buffer and callback reads');
  check(JSON.stringify(api.list) === '["b.txt"]' && api.exists && api.stat, 'fs readdir/exists/stat');
  check(api.code === 'ENOENT', 'missing files raise ENOENT');
  check(JSON.stringify(api.bin) === '[0,255,10]', 'binary write/read round-trip');
  check(api.store === 1, 'store round-trip');
  check(api.clip === 'copied', 'clipboard round-trip (window.require not leaked without nodeIntegration)');
  check(api.path === '/b/c.txt', 'path.join normalises');
  check(api.platform === 'ios', 'process.platform is ios');
  check(/not been ported/.test(api.missing || ''), 'unported IPC channel gives a clear error');

  // Adaptive: iPhone-sized viewport switches to the compact layout
  await page.evaluate(() => window.ipadport._setSizeClass('compact', 'regular'));
  const cols = await page.evaluate(() => getComputedStyle(document.body).gridTemplateColumns.split(' ').length);
  check(cols === 1, 'compact size class switches the example to a single-column layout');

  check(errors.length === 0, 'no page errors' + (errors.length ? ': ' + errors.join('; ') : ''));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
