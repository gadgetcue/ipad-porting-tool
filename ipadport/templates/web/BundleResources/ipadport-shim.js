/*
 * ipadport runtime shim (generated). Injected before any page script runs.
 *
 *  - window.ipadport: native APIs (fs, store, clipboard, dialogs, share, notifications, platform info)
 *  - Electron renderer compatibility: require('electron'), ipcRenderer, contextBridge, shell, clipboard,
 *    dialog, app, plus small 'fs', 'path', 'os' and 'events' modules
 *  - Adaptive layout helpers: viewport meta, size-class classes on <html>, iOS-friendly base CSS
 */
(function () {
  'use strict';
  if (window.ipadport) return;

  var CONFIG = window.__IPADPORT_CONFIG__ || {};
  var INITIAL = window.__IPADPORT_INITIAL__ || {};
  var bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.ipadport;
  var SYNC_PREFIX = '__ipadport_sync__';
  var nativePrompt = window.prompt.bind(window);

  function call(method, args) {
    if (!bridge) return Promise.reject(new Error('ipadport native bridge is not available'));
    return bridge.postMessage({ method: method, args: args || {} });
  }

  function callSync(method, args) {
    var raw = nativePrompt(SYNC_PREFIX, JSON.stringify({ method: method, args: args || {} }));
    var res;
    try { res = JSON.parse(raw); } catch (e) { throw new Error('ipadport: bad sync response for ' + method); }
    if (!res.ok) {
      var err = new Error(res.error);
      if (/^ENOENT/.test(res.error)) err.code = 'ENOENT';
      throw err;
    }
    return res.value;
  }

  // ------------------------------------------------------------------ events
  function Emitter() { this._l = {}; }
  Emitter.prototype.on = function (name, fn) { (this._l[name] = this._l[name] || []).push(fn); return this; };
  Emitter.prototype.addListener = Emitter.prototype.on;
  Emitter.prototype.once = function (name, fn) {
    var self = this;
    function wrap() { self.removeListener(name, wrap); fn.apply(this, arguments); }
    wrap.listener = fn;
    return this.on(name, wrap);
  };
  Emitter.prototype.off = Emitter.prototype.removeListener = function (name, fn) {
    var list = this._l[name] || [];
    this._l[name] = list.filter(function (l) { return l !== fn && l.listener !== fn; });
    return this;
  };
  Emitter.prototype.removeAllListeners = function (name) { if (name) delete this._l[name]; else this._l = {}; return this; };
  Emitter.prototype.emit = function (name) {
    var args = Array.prototype.slice.call(arguments, 1);
    var list = (this._l[name] || []).slice();
    list.forEach(function (fn) { fn.apply(null, args); });
    return list.length > 0;
  };
  Emitter.prototype.listenerCount = function (name) { return (this._l[name] || []).length; };
  Emitter.prototype.listeners = function (name) { return (this._l[name] || []).slice(); };

  // ------------------------------------------------------------------ path (posix)
  var path = {
    sep: '/',
    delimiter: ':',
    normalize: function (p) {
      var abs = p.charAt(0) === '/';
      var out = [];
      String(p).replace(/\\/g, '/').split('/').forEach(function (part) {
        if (!part || part === '.') return;
        if (part === '..') { if (out.length && out[out.length - 1] !== '..') out.pop(); else if (!abs) out.push('..'); }
        else out.push(part);
      });
      var res = (abs ? '/' : '') + out.join('/');
      return res || (abs ? '/' : '.');
    },
    join: function () {
      var parts = Array.prototype.filter.call(arguments, function (p) { return p !== ''; });
      return path.normalize(parts.join('/') || '.');
    },
    resolve: function () {
      var resolved = '';
      for (var i = arguments.length - 1; i >= 0; i--) {
        var p = String(arguments[i]).replace(/\\/g, '/');
        if (!p) continue;
        resolved = p + (resolved ? '/' + resolved : '');
        if (p.charAt(0) === '/') break;
      }
      return path.normalize(resolved.charAt(0) === '/' ? resolved : '/' + resolved);
    },
    dirname: function (p) {
      p = String(p).replace(/\\/g, '/').replace(/\/+$/, '');
      var i = p.lastIndexOf('/');
      return i < 0 ? '.' : (i === 0 ? '/' : p.slice(0, i));
    },
    basename: function (p, ext) {
      var b = String(p).replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop();
      if (ext && b.slice(-ext.length) === ext) b = b.slice(0, -ext.length);
      return b;
    },
    extname: function (p) {
      var b = path.basename(p);
      var i = b.lastIndexOf('.');
      return i <= 0 ? '' : b.slice(i);
    },
    isAbsolute: function (p) { return /^([\/\\]|[A-Za-z]:)/.test(String(p)); },
    relative: function (from, to) {
      var a = path.resolve(from).split('/').filter(Boolean);
      var b = path.resolve(to).split('/').filter(Boolean);
      while (a.length && b.length && a[0] === b[0]) { a.shift(); b.shift(); }
      return a.map(function () { return '..'; }).concat(b).join('/');
    },
    parse: function (p) {
      var base = path.basename(p), ext = path.extname(p);
      return { root: path.isAbsolute(p) ? '/' : '', dir: path.dirname(p), base: base, ext: ext, name: ext ? base.slice(0, -ext.length) : base };
    },
    format: function (o) { return (o.dir ? o.dir + '/' : '') + (o.base || ((o.name || '') + (o.ext || ''))); }
  };
  path.posix = path;
  path.win32 = path;

  // ------------------------------------------------------------------ fs (sandboxed in Documents)
  function toPath(p) {
    if (p && typeof p === 'object' && p.href) p = p.pathname; // URL objects
    return String(p);
  }
  function encOf(opts) { return typeof opts === 'string' ? opts : (opts && opts.encoding) || null; }

  function bytesToBase64(bytes) {
    var bin = '';
    for (var i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  function base64ToBytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function makeBuffer(bytes) {
    // A Uint8Array with a Node-like toString(encoding).
    bytes.toString = function (enc) {
      if (enc === 'base64') return bytesToBase64(bytes);
      return new TextDecoder().decode(bytes);
    };
    return bytes;
  }
  function encodeData(data) {
    if (typeof data === 'string') return { data: data, encoding: 'utf8' };
    if (data instanceof ArrayBuffer) data = new Uint8Array(data);
    if (ArrayBuffer.isView(data)) return { data: bytesToBase64(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)), encoding: 'base64' };
    return { data: String(data), encoding: 'utf8' };
  }
  function makeStats(s) {
    return {
      size: s.size, mtimeMs: s.mtimeMs, birthtimeMs: s.birthtimeMs,
      mtime: new Date(s.mtimeMs), birthtime: new Date(s.birthtimeMs), ctime: new Date(s.mtimeMs), atime: new Date(s.mtimeMs),
      isDirectory: function () { return s.isDirectory; }, isFile: function () { return s.isFile; },
      isSymbolicLink: function () { return false; }
    };
  }

  var fsSync = {
    readFileSync: function (p, opts) {
      var enc = encOf(opts);
      if (enc && enc !== 'base64') return callSync('fs.readFile', { path: toPath(p) });
      var b64 = callSync('fs.readFile', { path: toPath(p), encoding: 'base64' });
      return enc === 'base64' ? b64 : makeBuffer(base64ToBytes(b64));
    },
    writeFileSync: function (p, data) { var e = encodeData(data); callSync('fs.writeFile', { path: toPath(p), data: e.data, encoding: e.encoding }); },
    appendFileSync: function (p, data) { var e = encodeData(data); callSync('fs.appendFile', { path: toPath(p), data: e.data, encoding: e.encoding }); },
    existsSync: function (p) { try { return callSync('fs.exists', { path: toPath(p) }); } catch (e) { return false; } },
    statSync: function (p) { return makeStats(callSync('fs.stat', { path: toPath(p) })); },
    readdirSync: function (p, opts) {
      var names = callSync('fs.readdir', { path: toPath(p) });
      if (opts && opts.withFileTypes) {
        return names.map(function (n) {
          var st = callSync('fs.stat', { path: path.join(toPath(p), n) });
          return { name: n, isDirectory: function () { return st.isDirectory; }, isFile: function () { return st.isFile; } };
        });
      }
      return names;
    },
    mkdirSync: function (p, opts) { callSync('fs.mkdir', { path: toPath(p), recursive: !opts || opts.recursive !== false }); },
    unlinkSync: function (p) { callSync('fs.unlink', { path: toPath(p) }); },
    rmSync: function (p, opts) { callSync('fs.rm', { path: toPath(p), force: !!(opts && opts.force) }); },
    rmdirSync: function (p) { callSync('fs.rmdir', { path: toPath(p) }); },
    renameSync: function (a, b) { callSync('fs.rename', { from: toPath(a), to: toPath(b) }); },
    copyFileSync: function (a, b) { callSync('fs.copyFile', { from: toPath(a), to: toPath(b) }); },
    accessSync: function (p) { if (!fsSync.existsSync(p)) { var e = new Error('ENOENT: no such file or directory, access \'' + p + '\''); e.code = 'ENOENT'; throw e; } }
  };

  function promisify(fn) {
    return function () {
      var args = arguments;
      return new Promise(function (resolve, reject) {
        try { resolve(fn.apply(null, args)); } catch (e) { reject(e); }
      });
    };
  }

  var fsPromises = {
    readFile: function (p, opts) {
      var enc = encOf(opts);
      if (enc && enc !== 'base64') return call('fs.readFile', { path: toPath(p) });
      return call('fs.readFile', { path: toPath(p), encoding: 'base64' }).then(function (b64) {
        return enc === 'base64' ? b64 : makeBuffer(base64ToBytes(b64));
      });
    },
    writeFile: function (p, data) { var e = encodeData(data); return call('fs.writeFile', { path: toPath(p), data: e.data, encoding: e.encoding }).then(function () {}); },
    appendFile: function (p, data) { var e = encodeData(data); return call('fs.appendFile', { path: toPath(p), data: e.data, encoding: e.encoding }).then(function () {}); },
    stat: function (p) { return call('fs.stat', { path: toPath(p) }).then(makeStats); },
    readdir: promisify(fsSync.readdirSync),
    mkdir: function (p, opts) { return call('fs.mkdir', { path: toPath(p), recursive: !opts || opts.recursive !== false }).then(function () {}); },
    unlink: function (p) { return call('fs.unlink', { path: toPath(p) }).then(function () {}); },
    rm: function (p, opts) { return call('fs.rm', { path: toPath(p), force: !!(opts && opts.force) }).then(function () {}); },
    rmdir: function (p) { return call('fs.rmdir', { path: toPath(p) }).then(function () {}); },
    rename: function (a, b) { return call('fs.rename', { from: toPath(a), to: toPath(b) }).then(function () {}); },
    copyFile: function (a, b) { return call('fs.copyFile', { from: toPath(a), to: toPath(b) }).then(function () {}); },
    access: promisify(fsSync.accessSync)
  };
  // ENOENT codes for async errors too
  Object.keys(fsPromises).forEach(function (k) {
    var fn = fsPromises[k];
    fsPromises[k] = function () {
      return fn.apply(null, arguments).catch(function (e) {
        if (!(e instanceof Error)) e = new Error(String(e));
        if (/^ENOENT/.test(e.message)) e.code = 'ENOENT';
        throw e;
      });
    };
  });

  var fs = Object.assign({}, fsSync, { promises: fsPromises, constants: { F_OK: 0, R_OK: 4, W_OK: 2, X_OK: 1 } });
  // Node-style callback APIs: fs.readFile(path, [opts], cb)
  Object.keys(fsPromises).forEach(function (k) {
    fs[k] = function () {
      var args = Array.prototype.slice.call(arguments);
      var cb = typeof args[args.length - 1] === 'function' ? args.pop() : null;
      var p = fsPromises[k].apply(null, args);
      if (!cb) return p;
      p.then(function (v) { cb(null, v); }, function (e) { cb(e); });
    };
  });
  fs.exists = function (p, cb) { call('fs.exists', { path: toPath(p) }).then(function (v) { cb(!!v); }, function () { cb(false); }); };
  ['watch', 'watchFile', 'createReadStream', 'createWriteStream', 'openSync', 'open'].forEach(function (k) {
    fs[k] = function () { throw new Error('fs.' + k + ' is not available on iPad/iPhone (ipadport). Use readFile/writeFile.'); };
  });

  // ------------------------------------------------------------------ store (persistent key/value)
  var store = {
    get: function (key, fallback) {
      var raw = callSync('store.get', { key: String(key) });
      if (raw === null || raw === undefined) return fallback;
      try { return JSON.parse(raw); } catch (e) { return raw; }
    },
    set: function (key, value) { callSync('store.set', { key: String(key), value: JSON.stringify(value === undefined ? null : value) }); },
    delete: function (key) { callSync('store.delete', { key: String(key) }); },
    has: function (key) { return callSync('store.get', { key: String(key) }) != null; },
    clear: function () { callSync('store.clear', {}); },
    all: function () {
      var raw = callSync('store.all', {}) || {}, out = {};
      Object.keys(raw).forEach(function (k) { try { out[k] = JSON.parse(raw[k]); } catch (e) { out[k] = raw[k]; } });
      return out;
    }
  };

  // ------------------------------------------------------------------ public API
  var events = new Emitter();
  var ipadport = {
    version: '__IPADPORT_VERSION__',
    isNative: !!bridge,
    call: call,
    callSync: callSync,
    fs: fs,
    path: path,
    store: store,
    platform: function () { return callSync('platform.info', {}); },
    clipboard: {
      readText: function () { return callSync('clipboard.readText', {}); },
      writeText: function (text) { callSync('clipboard.writeText', { text: String(text) }); },
      clear: function () { callSync('clipboard.clear', {}); }
    },
    dialog: {
      // -> Promise<string[]> of sandbox paths (files are copied into Documents/Imported)
      open: function (opts) { return call('dialog.open', opts || {}); },
      message: function (opts) { return call('dialog.message', opts || {}); }
    },
    share: function (opts) { return call('share', opts || {}); },
    openExternal: function (url) { return call('shell.openExternal', { url: String(url) }); },
    notify: function (title, body) { return call('notification.show', { title: String(title || ''), body: String(body || '') }); },
    on: function (n, f) { events.on(n, f); },
    off: function (n, f) { events.removeListener(n, f); },
    emit: function () { return events.emit.apply(events, arguments); },
    sizeClass: { horizontal: INITIAL.horizontalSizeClass || 'regular', vertical: INITIAL.verticalSizeClass || 'regular' },
    idiom: INITIAL.idiom || 'pad',
    _setSizeClass: function (h, v) {
      ipadport.sizeClass = { horizontal: h, vertical: v };
      applyClasses();
      events.emit('sizeclass', ipadport.sizeClass);
      try { window.dispatchEvent(new CustomEvent('ipadport:sizeclass', { detail: ipadport.sizeClass })); } catch (e) {}
    }
  };
  window.ipadport = ipadport;

  // ------------------------------------------------------------------ Web Notification -> local notification
  if (CONFIG.shimNotifications !== false) {
    var NotificationShim = function (title, options) {
      ipadport.notify(title, options && options.body);
      this.title = title; this.body = options && options.body;
      this.close = function () {};
    };
    NotificationShim.permission = 'granted';
    NotificationShim.requestPermission = function (cb) { if (cb) cb('granted'); return Promise.resolve('granted'); };
    try { window.Notification = NotificationShim; } catch (e) {}
  }

  // ------------------------------------------------------------------ Electron compatibility
  if (CONFIG.electron) {
    var handlers = function () { return window.ipadportHandlers || {}; };
    var ipcRenderer = new Emitter();
    var fakeEvent = { sender: ipcRenderer, senderId: 0, ports: [], reply: function () {} };
    function missing(channel) {
      return new Error('IPC channel "' + channel + '" has not been ported yet. Implement it in ipadport/ipc-handlers.js.');
    }
    function runHandler(channel, args) {
      var h = handlers()[channel];
      if (typeof h !== 'function') throw missing(channel);
      return h.apply({ channel: channel, event: fakeEvent }, args);
    }
    ipcRenderer.invoke = function (channel) {
      var args = Array.prototype.slice.call(arguments, 1);
      try { return Promise.resolve(runHandler(channel, args)); } catch (e) { return Promise.reject(e); }
    };
    ipcRenderer.send = function (channel) {
      var args = Array.prototype.slice.call(arguments, 1);
      try {
        var result = runHandler(channel, args);
        if (result && typeof result.catch === 'function') result.catch(function (e) { console.error(e); });
      } catch (e) { console.warn(e.message); }
    };
    ipcRenderer.sendSync = function (channel) {
      var res = runHandler(channel, Array.prototype.slice.call(arguments, 1));
      if (res && typeof res.then === 'function') console.warn('ipcRenderer.sendSync("' + channel + '"): handler returned a Promise; return a plain value instead.');
      return res;
    };
    ipcRenderer.postMessage = ipcRenderer.send;
    ipcRenderer.sendToHost = ipcRenderer.send;
    var baseOn = ipcRenderer.on;
    ipcRenderer.on = function (channel, listener) {
      var wrapped = function () { listener.apply(null, [fakeEvent].concat(Array.prototype.slice.call(arguments))); };
      wrapped.listener = listener;
      return baseOn.call(ipcRenderer, channel, wrapped);
    };
    ipcRenderer.addListener = ipcRenderer.on;
    // Ported main-process code calls webContents.send(...) as ipadport.send(channel, ...args)
    ipadport.send = function () { ipcRenderer.emit.apply(ipcRenderer, arguments); };
    ipadport.webContents = { send: ipadport.send };

    var appPaths = {
      home: '/', appData: '/AppData', userData: '/AppData/' + (CONFIG.appName || 'app'), sessionData: '/AppData/' + (CONFIG.appName || 'app'),
      temp: '/tmp', exe: '/', module: '/', desktop: '/Desktop', documents: '/', downloads: '/Downloads',
      music: '/Music', pictures: '/Pictures', videos: '/Videos', logs: '/Logs', crashDumps: '/Logs'
    };
    var electron = {
      ipcRenderer: ipcRenderer,
      contextBridge: {
        exposeInMainWorld: function (key, api) { window[key] = api; },
        exposeInIsolatedWorld: function (id, key, api) { window[key] = api; }
      },
      shell: {
        openExternal: function (url) { return ipadport.openExternal(url).then(function () {}); },
        openPath: function (p) { return ipadport.share({ path: p }).then(function () { return ''; }); },
        showItemInFolder: function (p) { ipadport.share({ path: p }); },
        trashItem: function (p) { return fsPromises.rm(p, { force: true }); },
        beep: function () {}
      },
      clipboard: {
        readText: ipadport.clipboard.readText, writeText: ipadport.clipboard.writeText,
        readHTML: ipadport.clipboard.readText, writeHTML: ipadport.clipboard.writeText,
        clear: ipadport.clipboard.clear, availableFormats: function () { return ['text/plain']; }
      },
      dialog: {
        showOpenDialog: function (a, b) {
          var o = (b || a) || {};
          var props = o.properties || [];
          var exts = [];
          (o.filters || []).forEach(function (f) { (f.extensions || []).forEach(function (e) { if (e !== '*') exts.push(e); }); });
          return ipadport.dialog.open({ multiple: props.indexOf('multiSelections') >= 0, directory: props.indexOf('openDirectory') >= 0, extensions: exts })
            .then(function (paths) { return { canceled: paths.length === 0, filePaths: paths }; });
        },
        showSaveDialog: function (a, b) {
          var o = (b || a) || {};
          var name = path.basename(o.defaultPath || 'Untitled');
          return Promise.resolve({ canceled: false, filePath: '/' + name });
        },
        showMessageBox: function (a, b) {
          var o = (b || a) || {};
          return ipadport.dialog.message({ title: o.title, message: o.message || '', detail: o.detail, buttons: o.buttons, cancelId: o.cancelId })
            .then(function (i) { return { response: i, checkboxChecked: false }; });
        },
        showErrorBox: function (title, content) { ipadport.dialog.message({ title: title, message: content || '' }); }
      },
      app: {
        getName: function () { return CONFIG.appName || ''; },
        getVersion: function () { return CONFIG.appVersion || '1.0.0'; },
        getPath: function (name) { return appPaths[name] || '/'; },
        getLocale: function () { return navigator.language; },
        isPackaged: true,
        quit: function () {}, exit: function () {}, relaunch: function () { location.reload(); },
        on: function () {}, whenReady: function () { return Promise.resolve(); }
      },
      webFrame: {
        setZoomFactor: function (f) { document.documentElement.style.zoom = f; },
        getZoomFactor: function () { return parseFloat(document.documentElement.style.zoom) || 1; },
        setVisualZoomLevelLimits: function () {}, setZoomLevel: function () {}, getZoomLevel: function () { return 0; }
      },
      nativeTheme: {
        get shouldUseDarkColors() { return window.matchMedia('(prefers-color-scheme: dark)').matches; },
        themeSource: 'system', on: function () {}
      }
    };
    electron.remote = electron; // legacy @electron/remote style access
    ipadport.electron = electron;

    var os = {
      platform: function () { return 'ios'; }, type: function () { return 'Darwin'; }, arch: function () { return 'arm64'; },
      homedir: function () { return '/'; }, tmpdir: function () { return '/tmp'; }, hostname: function () { return 'iPad'; },
      EOL: '\n', cpus: function () { return [{ model: 'Apple', speed: 0 }]; }, totalmem: function () { return 0; }, freemem: function () { return 0; },
      release: function () { return ''; }, userInfo: function () { return { username: 'mobile', homedir: '/' }; }
    };
    var modules = {
      electron: electron, fs: fs, 'fs/promises': fsPromises, path: path, os: os,
      events: Object.assign(Emitter, { EventEmitter: Emitter }),
      '@electron/remote': electron
    };
    var nodeRequire = function (name) {
      var key = String(name).replace(/^node:/, '');
      if (modules.hasOwnProperty(key)) return modules[key];
      throw new Error('require("' + name + '") is not available on iPad/iPhone (ipadport). Bundle it for the browser instead.');
    };
    ipadport.require = nodeRequire;
    ipadport.registerModule = function (name, value) { modules[name] = value; };
    if (CONFIG.nodeRequire && typeof window.require === 'undefined') window.require = nodeRequire;

    if (typeof window.process === 'undefined') {
      window.process = {
        platform: 'ios', arch: 'arm64', env: {}, argv: [], cwd: function () { return '/'; },
        versions: { electron: 'ipadport', node: '0', chrome: '0' }, type: 'renderer',
        nextTick: function (fn) { var a = Array.prototype.slice.call(arguments, 1); Promise.resolve().then(function () { fn.apply(null, a); }); },
        on: function () {}
      };
    }
  }

  // ------------------------------------------------------------------ adaptive layout
  function applyClasses() {
    var root = document.documentElement;
    if (!root) return;
    var sc = ipadport.sizeClass;
    root.classList.remove('ipadport-compact', 'ipadport-regular', 'ipadport-vcompact', 'ipadport-vregular');
    root.classList.add('ipadport', 'ipadport-' + sc.horizontal, 'ipadport-v' + sc.vertical, 'ipadport-' + ipadport.idiom);
    root.setAttribute('data-size-class', sc.horizontal);
  }

  function ensureViewport() {
    var head = document.head || document.getElementsByTagName('head')[0];
    if (!head) return;
    var mode = CONFIG.viewport || 'device';
    var existing = document.querySelector('meta[name="viewport"]');
    if (existing && mode !== 'force') return;
    var content;
    if (mode === 'desktop') content = 'width=1024, viewport-fit=cover';
    else content = 'width=device-width, initial-scale=1, viewport-fit=cover';
    var meta = existing || document.createElement('meta');
    meta.name = 'viewport';
    meta.content = content;
    if (!existing) head.insertBefore(meta, head.firstChild);
  }

  function injectBaseStyle() {
    if (CONFIG.baseStyle === false) return;
    var style = document.createElement('style');
    style.id = 'ipadport-base';
    style.textContent = [
      'html{-webkit-text-size-adjust:100%;text-size-adjust:100%;}',
      '*{-webkit-tap-highlight-color:transparent;}',
      ':root{--ipadport-safe-top:env(safe-area-inset-top,0px);--ipadport-safe-right:env(safe-area-inset-right,0px);',
      '--ipadport-safe-bottom:env(safe-area-inset-bottom,0px);--ipadport-safe-left:env(safe-area-inset-left,0px);}',
      '[style*="-webkit-app-region"],.titlebar-drag{-webkit-user-select:none;}'
    ].join('');
    (document.head || document.documentElement).appendChild(style);
  }

  applyClasses();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { applyClasses(); ensureViewport(); injectBaseStyle(); });
  } else {
    ensureViewport(); injectBaseStyle();
  }
  // Viewport must exist as early as possible; try again once the <head> is parsed.
  var tries = 0;
  (function early() {
    if (document.head) { ensureViewport(); return; }
    if (tries++ < 50) setTimeout(early, 0);
  })();
})();
