/*
 * Test double for the Swift NativeBridge, so the generated JavaScript layer can be exercised in a
 * desktop browser (Chromium via Playwright). Mirrors NativeBridge.swift's method names and semantics.
 */
(function () {
  var files = {};            // virtual path -> base64 data
  var dirs = { '/': true };
  var store = {};
  var clipboard = '';
  window.__mockNative = { files: files, dirs: dirs, store: store, calls: [], shared: [], opened: [] };

  function norm(p) {
    p = String(p).replace(/\\/g, '/').replace(/^[A-Za-z]:/, '');
    var out = [];
    p.split('/').forEach(function (s) { if (!s || s === '.') return; if (s === '..') { if (!out.length) throw new Error('Path is outside the app sandbox: ' + p); out.pop(); } else out.push(s); });
    return '/' + out.join('/');
  }
  function parent(p) { var i = p.lastIndexOf('/'); return i <= 0 ? '/' : p.slice(0, i); }
  function enoent(p) { return new Error("ENOENT: no such file or directory, '" + p + "'"); }
  function utf8ToB64(s) { return btoa(unescape(encodeURIComponent(s))); }
  function b64ToUtf8(s) { return decodeURIComponent(escape(atob(s))); }
  function mkdirp(p) { var parts = p.split('/').filter(Boolean), cur = ''; parts.forEach(function (s) { cur += '/' + s; dirs[cur] = true; }); }

  function handleSync(method, a) {
    window.__mockNative.calls.push(method);
    switch (method) {
      case 'platform.info': return { platform: 'ios', idiom: 'pad', systemVersion: '18.0', appVersion: '1.0', appName: 'Test', locale: 'en', documents: '/' };
      case 'clipboard.readText': return clipboard;
      case 'clipboard.writeText': clipboard = a.text; return true;
      case 'clipboard.clear': clipboard = ''; return true;
      case 'store.get': return store.hasOwnProperty(a.key) ? store[a.key] : null;
      case 'store.set': store[a.key] = a.value; return true;
      case 'store.delete': delete store[a.key]; return true;
      case 'store.all': return Object.assign({}, store);
      case 'store.clear': Object.keys(store).forEach(function (k) { delete store[k]; }); return true;
      case 'fs.readFile': { var p = norm(a.path); if (!(p in files)) throw enoent(p); return a.encoding === 'base64' ? files[p] : b64ToUtf8(files[p]); }
      case 'fs.writeFile': case 'fs.appendFile': {
        var q = norm(a.path); mkdirp(parent(q));
        var data = a.encoding === 'base64' ? a.data : utf8ToB64(a.data);
        if (method === 'fs.appendFile' && files[q]) data = utf8ToB64(b64ToUtf8(files[q]) + b64ToUtf8(data));
        files[q] = data; return true;
      }
      case 'fs.exists': { var e = norm(a.path); return e in files || !!dirs[e]; }
      case 'fs.stat': { var s = norm(a.path); if (s in files) return { size: atob(files[s]).length, isDirectory: false, isFile: true, mtimeMs: 0, birthtimeMs: 0 }; if (dirs[s]) return { size: 0, isDirectory: true, isFile: false, mtimeMs: 0, birthtimeMs: 0 }; throw enoent(s); }
      case 'fs.readdir': {
        var d = norm(a.path); if (!dirs[d]) throw enoent(d);
        var prefix = d === '/' ? '/' : d + '/', names = {};
        Object.keys(files).concat(Object.keys(dirs)).forEach(function (k) { if (k !== d && k.indexOf(prefix) === 0) names[k.slice(prefix.length).split('/')[0]] = 1; });
        return Object.keys(names).sort();
      }
      case 'fs.mkdir': mkdirp(norm(a.path)); return true;
      case 'fs.unlink': case 'fs.rm': case 'fs.rmdir': {
        var r = norm(a.path);
        if (!(r in files) && !dirs[r]) { if (a.force) return true; throw enoent(r); }
        delete files[r]; delete dirs[r];
        Object.keys(files).forEach(function (k) { if (k.indexOf(r + '/') === 0) delete files[k]; });
        return true;
      }
      case 'fs.rename': { var f = norm(a.from), t = norm(a.to); if (!(f in files)) throw enoent(f); mkdirp(parent(t)); files[t] = files[f]; delete files[f]; return true; }
      case 'fs.copyFile': { var f2 = norm(a.from), t2 = norm(a.to); if (!(f2 in files)) throw enoent(f2); mkdirp(parent(t2)); files[t2] = files[f2]; return true; }
      case 'app.quit': return true;
    }
    throw new Error('Unknown ipadport method: ' + method);
  }

  function handleAsync(method, a) {
    switch (method) {
      case 'dialog.open': return Promise.resolve(window.__mockNative.nextPick || []);
      case 'dialog.message': return Promise.resolve(0);
      case 'share': window.__mockNative.shared.push(a); return Promise.resolve(true);
      case 'shell.openExternal': window.__mockNative.opened.push(a.url); return Promise.resolve(true);
      case 'notification.show': window.__mockNative.calls.push('notification.show'); return Promise.resolve(true);
    }
    try { return Promise.resolve(handleSync(method, a)); } catch (e) { return Promise.reject(e.message); }
  }

  window.webkit = { messageHandlers: { ipadport: { postMessage: function (body) {
    return handleAsync(body.method, body.args || {}).then(function (v) { return v === undefined ? null : v; }, function (e) { throw new Error(String(e)); });
  } } } };

  var realPrompt = window.prompt;
  window.prompt = function (message, def) {
    if (message === '__ipadport_sync__') {
      var payload = JSON.parse(def);
      try { return JSON.stringify({ ok: true, value: handleSync(payload.method, payload.args || {}) }); }
      catch (e) { return JSON.stringify({ ok: false, error: e.message }); }
    }
    return realPrompt.call(window, message, def);
  };
  window.__IPADPORT_INITIAL__ = { horizontalSizeClass: 'regular', verticalSizeClass: 'regular', idiom: 'pad' };
})();
