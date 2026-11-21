# ipadport

**Port Mac and Windows apps to iPad and iPhone, from their source code.**

`ipadport` is a command-line tool that reads a desktop app's project, tells you exactly what will and won't
work on iPadOS / iOS, and generates an adaptive iPad + iPhone Xcode project for it. For Electron and web apps
it produces a working native app with a bridge that keeps file access, dialogs, clipboard, links, downloads,
notifications and Electron IPC working. For other app types it creates the iOS target or a step-by-step
porting plan.

```text
$ ipadport analyze examples/electron-notes
Detected:  Electron app  (strategy: web-wrapper)
Score:     88/100  (0 blockers, 1 major, 6 minor, 0 info)
Verdict:   Good candidate: should port with little or no code change.

$ ipadport port examples/electron-notes --out NotesForIPad
Generated an adaptive iPad/iPhone app project 'NotesExample'.
```

## Read this first: what is and isn't possible

There is no tool, from anyone, that converts *any* compiled Mac or Windows program into a fully working
iPad app. iOS doesn't allow it:

- **Windows apps are x86/x64 Win32 code.** iOS can't run them, and App Store apps aren't allowed to ship an
  emulator that runs downloaded code with JIT. (Emulators like UTM SE exist, but they're slow and run a whole
  OS, not a ported app.)
- **Mac apps use AppKit**, which doesn't exist on iOS. Even Apple's own path (Mac Catalyst) goes the other way:
  iPad to Mac.
- **iOS sandboxing** blocks things many desktop apps rely on: launching other programs, reading files outside
  the app, system-wide shortcuts, tray icons, kernel extensions, self-updaters, loading plugins at runtime.

So `ipadport` works from **source code** and is honest about each feature: it either makes the feature work,
or tells you precisely where it is and what to replace it with.

## What it supports

| Desktop app type | What `ipadport port` does | How much works out of the box |
|---|---|---|
| **Electron** (Mac + Windows) | Generates a native SwiftUI + WKWebView app with your renderer, preload and an Electron compatibility layer | Renderer, preload, `contextBridge`, `ipcRenderer`, `shell`, `clipboard`, `dialog`, `app.getPath`, `fs`/`path`/`os` work. Main-process IPC handlers are stubbed per channel for you to port (Node can't run on iOS) |
| **Web apps / PWAs** (React, Vue, Svelte, Angular, static) | Same native shell around the built site, or around a hosted URL | Everything that works in Safari, plus the native bridge |
| **Installed Electron apps** (`.app` / install folder) | `ipadport extract` recovers the JS source from `app.asar`, then port as above | As for Electron. Only for apps you own or may modify |
| **SwiftUI / AppKit** (Mac) | Adds an iOS target that compiles your sources, plus `PlatformCompat.swift` | SwiftUI code mostly compiles; every AppKit use is listed with its UIKit/SwiftUI replacement |
| **Tauri, Flutter, React Native, Qt, .NET MAUI, Avalonia** | Porting plan using the framework's own iOS tooling | These frameworks already target iOS; desktop-only plugins/APIs are flagged |
| **WPF, Windows Forms, Win32/MFC, C++** | Porting plan | The UI has to be rebuilt (MAUI/Avalonia/SwiftUI); portable logic is kept |
| **Compiled `.exe`, `.msi`, `.dmg`, `.app` without source** | Refused, with an explanation | Not possible (see above) |

## Install

Requires Python 3.9+. No other dependencies.

```sh
pip install git+https://github.com/gadgetcue/ipad-porting-tool
# or, from a clone:
python3 -m ipadport --help
```

To build the generated projects you need a Mac with Xcode 15+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen)
(`brew install xcodegen`). `analyze` and `port` themselves run on macOS, Windows and Linux.

## Usage

```sh
# 1. See how portable the app is (text, Markdown or JSON)
ipadport analyze path/to/app
ipadport analyze path/to/app -o report.md
ipadport analyze path/to/app --format json --fail-on blocker   # for CI

# 2. Generate the iPad/iPhone project
ipadport port path/to/app --out path/to/app-ipad --bundle-id com.you.app --team-id ABCDE12345

# 3. Build it (on a Mac)
cd path/to/app-ipad
xcodegen generate
open *.xcodeproj        # pick a simulator or your iPad and press Run
```

Other commands:

```sh
ipadport extract "/Applications/Some Electron App.app" --out some-app-src   # recover Electron source
ipadport rules                                                              # list all compatibility rules
```

Useful `port` options:

| Option | Meaning |
|---|---|
| `--web-root DIR` / `--entry FILE` | Use a specific built web folder / HTML file |
| `--remote-url URL` | Wrap a hosted web app instead of bundling files (see App Store note below) |
| `--viewport device\|desktop\|keep\|force` | Responsive viewport (default), 1024px desktop layout, or leave the page's own |
| `--content-mode recommended\|mobile\|desktop` | Which layout WebKit asks websites for |
| `--edge-to-edge` | Draw under the status bar; use `env(safe-area-inset-*)` in CSS |
| `--ios 16.0` | Minimum iOS / iPadOS version |

## How Electron and web apps are ported

The generated project is a small native SwiftUI app:

```
NotesForIPad/
  project.yml                 XcodeGen spec: iPhone + iPad, all orientations, Split View, Stage Manager, multiple windows
  Sources/                    SwiftUI app, WKWebView host, app:// file server, native bridge
  BundleResources/
    ipadport-shim.js          window.ipadport API + Electron/Node compatibility layer
    ipc-handlers.js           your main-process IPC handlers, ported (stubs are generated)
    preload.js                your Electron preload script
  web/                        your built HTML/CSS/JS
  PORTING_PLAN.md             every finding, with file:line and the fix
```

What the shell takes care of so that existing code keeps working:

- **Files:** Node-style `fs` (sync, callback and promise forms) backed by the app's Documents folder, which
  shows up in the Files app. Desktop paths (`C:\Users\...`, `app.getPath('userData')`) are mapped into it.
- **Dialogs:** `dialog.showOpenDialog` opens the iOS document picker, `showMessageBox` shows an alert,
  `alert()/confirm()/prompt()` work (plain WKWebView ignores them).
- **Links and windows:** external links and `window.open` go to Safari, `mailto:`/`tel:` open the right app.
- **Downloads:** `<a download>` and file responses are saved to Documents/Downloads and offered in the share sheet.
- **Clipboard, notifications** (`new Notification()` becomes a local notification), **key-value storage**.
- **Serving:** files come from `app://local/`, so ES modules, `fetch()` of local files, absolute paths and
  single-page-app routes all work.
- **Adaptive layout:** a responsive viewport is added when the page has none, `<html>` gets
  `ipadport-compact` / `ipadport-regular` and `ipadport-pad` / `ipadport-phone` classes that update live in
  Split View, and `--ipadport-safe-*` CSS variables expose safe areas. Example:

  ```css
  .ipadport-compact .sidebar { display: none; }   /* iPhone and narrow Split View */
  ```

### Porting Electron IPC handlers

Electron's main process is Node.js, and Node can't run on iOS. `ipadport` finds every `ipcMain.handle/on`
channel and writes a stub in `ipc-handlers.js`, with the original code next to it as a comment. Port each one
using the same APIs:

```js
// main.js (Electron)
ipcMain.handle('notes:save', async (_e, notes) => {
  fs.writeFileSync(path.join(app.getPath('userData'), 'notes.json'), JSON.stringify(notes));
});

// ipadport/ipc-handlers.js (iPad)
'notes:save': function (notes) {
  fs.writeFileSync(path.join(app.getPath('userData'), 'notes.json'), JSON.stringify(notes));
}
```

Save your ported file as `ipadport/ipc-handlers.js` in your project and `ipadport port` will use it every time.
[`examples/electron-notes`](examples/electron-notes) is a complete, ported example.

### `window.ipadport` API

| API | |
|---|---|
| `ipadport.fs` | `readFile[Sync]`, `writeFile[Sync]`, `appendFile`, `readdir`, `mkdir`, `stat`, `exists[Sync]`, `unlink`, `rm`, `rename`, `copyFile`, `promises.*` |
| `ipadport.store` | `get(key, fallback)`, `set`, `delete`, `has`, `all`, `clear` (persistent, synchronous) |
| `ipadport.dialog` | `open({multiple, directory, extensions})` returns sandbox paths, `message({title, message, buttons})` |
| `ipadport.clipboard` | `readText`, `writeText`, `clear` |
| `ipadport.share({text, url, path})`, `ipadport.openExternal(url)`, `ipadport.notify(title, body)` | |
| `ipadport.platform()` | `{platform: 'ios', idiom: 'pad' \| 'phone', systemVersion, appVersion, ...}` |
| `ipadport.sizeClass`, `ipadport.on('sizeclass', fn)` | current horizontal/vertical size class |
| `ipadport.send(channel, ...args)` | emit to `ipcRenderer.on` listeners (replacement for `webContents.send`) |

## Known limitations

Be aware of these before you promise anyone "all features work":

- **Electron main-process code must be ported by hand** into `ipc-handlers.js`. The tool finds every channel and
  generates stubs, but it can't run Node.js logic on iOS. Unported channels throw a clear error.
- **Not available on iOS at all:** `child_process`, native `.node` add-ons, tray icons, global shortcuts,
  auto-updaters, local servers (`net`/`http.createServer`), screen capture, power monitoring, WebUSB/WebSerial/
  WebHID/Web Bluetooth, the File System Access API. The analyzer lists each use as a blocker or major issue.
- **Files** are limited to the app's own sandbox; files the user picks are copied in. No file watching or streams.
- **Menus:** there's no menu bar. Keyboard shortcuts still work with `keydown` listeners on an iPad keyboard,
  but menu-only actions need visible buttons.
- **Preload scripts** must be a single CommonJS file (bundle them with esbuild if they `import` or `require`
  local files).
- **Multiple Electron windows** become one window; build secondary windows as in-app panels.
- **Swift ports:** the generated iOS target will show compile errors wherever AppKit is used; the plan lists
  each with its replacement, but you write the UIKit/SwiftUI code.
- **Plan-only types** (WPF, WinForms, Win32, Qt, Flutter, ...) get guidance, not generated code.
- **App Store:** Apple rejects apps that are just a website in a wrapper (guideline 4.2). Ported apps with real
  offline functionality are fine; `--remote-url` wrappers of a plain website usually aren't.
- **Hover-only UI** needs touch-friendly alternatives. The analyzer flags common patterns but not all.
- The scanner is pattern-based. It catches the common desktop APIs, not every possible one, so test every
  feature on a real iPad and iPhone.

## How it's tested

- `python -m unittest discover -s tests` covers detection of every app type, the rules, scoring, project
  generation, `.asar` extraction (including path-traversal protection) and the CLI.
- `tests/browser/run.js` loads the generated Electron example in Chromium with a mock of the native bridge and
  checks the whole JS layer: preload + `contextBridge`, IPC routing to ported handlers, `fs`, store,
  clipboard, `shell.openExternal`, the share sheet, viewport and the compact layout switch.
- CI on GitHub Actions also generates the example's Xcode project on macOS and **compiles it with Xcode for
  the iOS Simulator** on every push.

## Contributing

New rules go in [`ipadport/rules.py`](ipadport/rules.py) (pattern, severity, fix text). Native bridge methods
live in [`NativeBridge.swift`](ipadport/templates/web/Sources/NativeBridge.swift) and the JS side in
[`ipadport-shim.js`](ipadport/templates/web/BundleResources/ipadport-shim.js); keep
[`tests/browser/mock-native.js`](tests/browser/mock-native.js) in sync when you add one.

## License

MIT
