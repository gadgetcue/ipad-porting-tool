"""Step-by-step porting guides per app kind (used in PORTING_PLAN.md and `ipadport analyze`)."""

from __future__ import annotations

GUIDES: dict[str, dict] = {
    "electron": {
        "summary": "Your renderer (HTML/CSS/JS) runs unchanged inside a native iPad/iPhone app. The Electron "
                   "main process (Node.js) cannot run on iOS, so its IPC handlers are re-implemented in "
                   "`ipc-handlers.js` using ipadport's native APIs.",
        "steps": [
            "Build your renderer first if it uses a bundler (`npm run build`).",
            "Run `ipadport port . --out ipad-port` and open `ipad-port/PORTING_PLAN.md`.",
            "Port each IPC channel listed in the plan: edit `ipad-port/BundleResources/ipc-handlers.js`, then copy "
            "it to `ipadport/ipc-handlers.js` in your project so re-running the tool keeps your work.",
            "On a Mac: `brew install xcodegen`, then `cd ipad-port && xcodegen generate && open *.xcodeproj`.",
            "Pick your team under Signing & Capabilities and run on an iPad or iPhone simulator.",
        ],
    },
    "web": {
        "summary": "The web app is bundled into a native iPad/iPhone app (WKWebView) with an adaptive viewport, "
                   "working alert/confirm/prompt, file inputs, downloads, external links and a native bridge.",
        "steps": [
            "Build the production bundle (`npm run build`) if the project uses a bundler.",
            "Run `ipadport port . --out ipad-port` (or `--remote-url https://...` to wrap a hosted app).",
            "On a Mac: `brew install xcodegen`, then `cd ipad-port && xcodegen generate && open *.xcodeproj`.",
            "Run on simulators of different sizes and in Split View to check the responsive layout.",
        ],
    },
    "tauri": {
        "summary": "Tauri 2 supports iOS directly. Use Tauri's own mobile tooling so your Rust commands keep working.",
        "steps": [
            "Upgrade to Tauri 2 if needed (`npm install @tauri-apps/cli@latest @tauri-apps/api@latest`).",
            "Run `npm run tauri ios init`, then `npm run tauri ios dev` on a Mac with Xcode.",
            "Replace desktop-only plugins (shell, global-shortcut, tray, updater) flagged below.",
            "Alternative for frontend-only apps: `ipadport port . --out ipad-port` wraps the built frontend.",
        ],
    },
    "react-native": {
        "summary": "React Native already targets iOS. Desktop forks (react-native-macos / -windows) share most code.",
        "steps": [
            "If there is no `ios/` folder, create a fresh RN app with the same version and move `src/` across.",
            "Replace desktop-only native modules flagged below.",
            "`cd ios && pod install`, then `npx react-native run-ios`.",
            "Use `useWindowDimensions()` to adapt layouts between iPhone, iPad and Split View.",
        ],
    },
    "flutter": {
        "summary": "Flutter supports iOS directly. Most code works unchanged; desktop-only plugins need replacing.",
        "steps": [
            "Run `flutter create --platforms=ios .` in the project to add the iOS runner (if `ios/` is missing).",
            "Remove or guard desktop-only plugins flagged below with `Platform.isIOS` checks.",
            "Use `LayoutBuilder` / `MediaQuery` breakpoints so layouts adapt from iPhone to iPad.",
            "`flutter run -d ios` on a Mac with Xcode.",
        ],
    },
    "swift": {
        "summary": "SwiftUI code mostly runs on iPad and iPhone. AppKit code must move to SwiftUI or UIKit. ipadport "
                   "adds an iOS target that compiles your sources plus a compatibility file for shared code.",
        "steps": [
            "Run `ipadport port . --out ipad-port`; it creates `ipad-port/project.yml` (iOS target using your "
            "sources) and `ipad-port/PlatformCompat.swift`.",
            "On a Mac: `brew install xcodegen`, `cd ipad-port && xcodegen generate && open *.xcodeproj`.",
            "Build for an iPad simulator. Fix each compile error using the findings below: wrap Mac-only code in "
            "`#if os(macOS)` and add iOS versions (UIViewRepresentable, .fileImporter, UIPasteboard...).",
            "Alternatively add 'iPad' / 'iPhone' as a supported destination of your existing target in Xcode "
            "(Project > General > Supported Destinations) and fix the same errors there.",
        ],
    },
    "qt": {
        "summary": "Qt supports iOS. Qt Quick (QML) apps port well; Qt Widgets apps run but look like desktop software.",
        "steps": [
            "Install Qt for iOS with the Qt Maintenance Tool (on a Mac with Xcode).",
            "Configure with `<Qt>/ios/bin/qt-cmake -G Xcode .` (CMake) or `qmake -spec macx-ios-clang` (qmake).",
            "Replace QProcess, tray icons and desktop-only modules flagged below.",
            "For a touch-friendly UI, move screens to Qt Quick Controls with adaptive layouts.",
        ],
    },
    "dotnet-maui": {
        "summary": ".NET MAUI supports iOS directly.",
        "steps": [
            "Add `net8.0-ios` (or the matching version) to `<TargetFrameworks>`.",
            "Pair Visual Studio with a Mac (or build on a Mac) and run on an iOS simulator.",
            "Replace Windows-only APIs flagged below.",
        ],
    },
    "dotnet-avalonia": {
        "summary": "Avalonia supports iOS.",
        "steps": [
            "Create an `<App>.iOS` head project from the Avalonia cross-platform template and reference your shared project.",
            "Replace Windows-only APIs flagged below, then build on a Mac with Xcode.",
        ],
    },
    "dotnet-wpf": {
        "summary": "WPF only runs on Windows. Keep your view models and business logic, rebuild the views.",
        "steps": [
            "Move models, services and view models into a .NET class library (no WPF references).",
            "Create a .NET MAUI app (closest XAML dialect) or an Avalonia app (very close to WPF XAML).",
            "Re-create each window as a page with adaptive layouts (Grid with breakpoints, FlexLayout).",
            "Replace registry, P/Invoke and Process.Start usage flagged below.",
        ],
    },
    "dotnet-winforms": {
        "summary": "Windows Forms only runs on Windows. Keep the logic, rebuild the UI.",
        "steps": [
            "Move non-UI code out of Form classes into a .NET class library.",
            "Rebuild the UI in .NET MAUI or Avalonia; both deploy to iPad and iPhone.",
            "Replace registry, P/Invoke and Process.Start usage flagged below.",
        ],
    },
    "dotnet": {
        "summary": ".NET code can run on iOS through .NET MAUI / Avalonia. UI code must use one of those.",
        "steps": [
            "Move portable code into a class library targeting `net8.0`.",
            "Create a .NET MAUI or Avalonia app for the UI.",
        ],
    },
    "win32": {
        "summary": "Win32/MFC UI cannot run on iOS. Portable C/C++ logic can be reused from a new native UI.",
        "steps": [
            "Split the code into a portable core (no windows.h) and the Windows UI.",
            "Build the core for iOS (CMake with `-DCMAKE_SYSTEM_NAME=iOS`, or add the files to an Xcode target).",
            "Write a SwiftUI front end and call the core through Swift's C++ interoperability or a C header.",
            "Replace DirectX rendering with Metal, and Win32 file/registry/process calls with iOS APIs.",
        ],
    },
    "cpp": {
        "summary": "Portable C/C++ code can be compiled for iOS and used from a SwiftUI app.",
        "steps": [
            "Build the library for iOS (CMake `-DCMAKE_SYSTEM_NAME=iOS -G Xcode`).",
            "Create a SwiftUI app and call the library through Swift/C++ interop.",
        ],
    },
}


def guide_for(kind: str) -> dict:
    return GUIDES.get(kind, {
        "summary": "ipadport could not recognise this project type.",
        "steps": ["Check that you pointed ipadport at the app's source folder (the one with package.json, "
                  "*.xcodeproj, pubspec.yaml, *.csproj, CMakeLists.txt...)."],
    })
