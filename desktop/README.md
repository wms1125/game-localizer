# HanEngine Desktop

Electron + React desktop shell for the existing Python HanEngine backend.

The desktop app is a multi-engine client. Its default `普通` mode maps to the
Python `player` authorization mode and exposes the guarded one-click workflow;
`专业` maps to `studio` and exposes manual catalogs, packaging and task
controls. Engine support is capability-gated: RPG Maker MV/MZ, Godot, Unity,
Unreal and the legacy Ren'Py workflow are presented according to their actual
AdapterV1 maturity and resource format. Packaged, encrypted or binary-only
projects remain detection-only.

The first launch creates a local SQLite account store under Electron's
`userData` directory. Passwords use salted PBKDF2-SHA256 hashes, credentials
are sent to the Python backend over stdin rather than process arguments, and
raw session tokens remain in the Electron main process. Project and task IPC
handlers reject unauthenticated renderer requests. This is local-only account
gating; it does not provide cloud identity or cross-device synchronization.

```powershell
npm install --registry=https://registry.npmjs.org
npm run build
npm run dev
```

在网络无法访问 Electron GitHub 下载源时，补充执行：

```powershell
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
node node_modules/electron/install.js
```

The app expects to be launched from this directory during development. The
Electron main process resolves `../cli.py` and `../game_localizer/`, then
streams Python stdout/stderr to the React task log through a task-scoped IPC
channel.
