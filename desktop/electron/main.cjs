const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, "hanengine-backend")
  : PROJECT_ROOT;
const runningProcesses = new Map();
const authSessions = new Map();
const IGNORED_DIRECTORIES = new Set([
  ".git",
  ".test-runs",
  ".worktrees",
  "node_modules",
  "dist",
  "build",
  "release",
  "__pycache__",
]);

function pythonExecutable() {
  return process.env.HANENGINE_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function sendPythonEvent(sender, payload) {
  if (!sender.isDestroyed()) {
    sender.send("python:event", payload);
  }
}

function taskControlId(command) {
  return `control-${command}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function appendStateRoot(args, stateRoot) {
  if (stateRoot === undefined || stateRoot === null || stateRoot === "") return args;
  if (typeof stateRoot !== "string") throw new TypeError("stateRoot must be a string");
  return [...args, "--state-root", stateRoot];
}

function runPython(sender, taskId, args, options = {}) {
  if (!Array.isArray(args) || args.some((item) => typeof item !== "string")) {
    throw new TypeError("Python arguments must be an array of strings");
  }
  const { input = null, emitEvents = true } = options;
  if (runningProcesses.has(taskId)) {
    throw new Error(`Task is already running: ${taskId}`);
  }
  const child = spawn(pythonExecutable(), [path.join(BACKEND_ROOT, "cli.py"), ...args], {
    cwd: BACKEND_ROOT,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    windowsHide: true,
  });
  runningProcesses.set(taskId, child);
  const channel = taskId.startsWith("control-") ? "control" : "workflow";
  if (emitEvents) sendPythonEvent(sender, { taskId, channel, type: "started", args });
  if (input !== null) {
    child.stdin.end(input);
  } else {
    child.stdin.end();
  }
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      stdout += text;
      if (emitEvents) sendPythonEvent(sender, { taskId, channel, type: "stdout", text });
    });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      stderr += text;
      if (emitEvents) sendPythonEvent(sender, { taskId, channel, type: "stderr", text });
    });
    child.on("error", (error) => {
      runningProcesses.delete(taskId);
      if (emitEvents) sendPythonEvent(sender, { taskId, channel, type: "error", text: error.message });
      resolve({ code: -1, stdout, stderr: `${stderr}${error.message}` });
    });
    child.on("close", (code) => {
      runningProcesses.delete(taskId);
      if (emitEvents) sendPythonEvent(sender, { taskId, channel, type: "finished", code: code ?? -1 });
      resolve({ code: code ?? -1, stdout, stderr });
    });
  });
}

function authDatabasePath() {
  return path.join(app.getPath("userData"), "auth.db");
}

function authTaskId(command) {
  return `auth-${command}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function runAuthRequest(sender, command, payload = {}) {
  const result = await runPython(
    sender,
    authTaskId(command),
    ["auth", command, "--db", authDatabasePath()],
    { input: JSON.stringify(payload), emitEvents: false },
  );
  if (result.code !== 0) {
    throw new Error(result.stderr.trim() || "认证请求失败");
  }
  try {
    return JSON.parse(result.stdout.trim() || "{}");
  } catch {
    throw new Error("认证服务返回了无效结果");
  }
}

async function currentAuthenticatedUser(event) {
  const token = authSessions.get(event.sender.id);
  if (!token) return null;
  const result = await runAuthRequest(event.sender, "current", { token });
  const user = result.user || null;
  if (!user) authSessions.delete(event.sender.id);
  return user;
}

async function requireAuthenticated(event) {
  const user = await currentAuthenticatedUser(event);
  if (!user) throw new Error("请先登录 HanEngine");
  return user;
}

function runTaskControl(sender, args) {
  return runPython(sender, taskControlId(args[1] || args[0]), args);
}

async function scanDirectory(rootPath, relative = "", depth = 0) {
  if (depth > 8) return [];
  const directory = path.join(rootPath, relative);
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const result = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name.startsWith(".") && entry.name !== ".env") continue;
    if (entry.isDirectory() && IGNORED_DIRECTORIES.has(entry.name)) continue;
    const childRelative = relative ? path.join(relative, entry.name) : entry.name;
    if (entry.isDirectory()) {
      result.push({
        name: entry.name,
        relativePath: childRelative.replaceAll(path.sep, "/"),
        type: "directory",
        children: await scanDirectory(rootPath, childRelative, depth + 1),
      });
    } else if (entry.isFile()) {
      const extension = path.extname(entry.name).toLowerCase();
      result.push({
        name: entry.name,
        relativePath: childRelative.replaceAll(path.sep, "/"),
        type: "file",
        extension,
      });
    }
  }
  return result;
}

async function readCatalog(filePath) {
  const payload = JSON.parse(await fs.readFile(filePath, "utf8"));
  if (Array.isArray(payload.entries)) {
    return {
      kind: "catalog",
      metadata: {
        engine: payload.engine_id || "renpy",
        sourceLanguage: payload.source_language || "en",
        targetLanguage: payload.language || "zh-CN",
        fileCount: Array.isArray(payload.files) ? payload.files.length : 0,
      },
      rows: payload.entries.map((entry, index) => ({
        id: entry.segment_id || String(index + 1),
        context: entry.relative_path || entry.kind || "-",
        source: entry.source_text || "",
        target: entry.target_text || "",
        status: entry.target_text ? "translated" : "pending",
        locator: entry.locator || {},
      })),
    };
  }
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    return {
      kind: "dictionary",
      metadata: { engine: "dictionary", sourceLanguage: "en", targetLanguage: "zh-CN", fileCount: 1 },
      rows: Object.entries(payload).map(([source, target], index) => ({
        id: String(index + 1),
        context: "dictionary",
        source,
        target: typeof target === "string" ? target : "",
        status: target ? "translated" : "pending",
        locator: {},
      })),
    };
  }
  throw new Error("Unsupported catalog JSON shape");
}

async function writeCatalog(filePath, updates) {
  const payload = JSON.parse(await fs.readFile(filePath, "utf8"));
  if (!Array.isArray(payload.entries)) throw new Error("Only structured catalogs can be edited");
  const byId = new Map(updates.map((row) => [row.id, row.target]));
  payload.entries = payload.entries.map((entry, index) => {
    const id = entry.segment_id || String(index + 1);
    return byId.has(id) ? { ...entry, target_text: byId.get(id) } : entry;
  });
  const temporary = `${filePath}.tmp-${process.pid}`;
  await fs.writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await fs.rename(temporary, filePath);
  return { updated: byId.size, path: filePath };
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1120,
    minHeight: 720,
    backgroundColor: "#101419",
    title: "HanEngine",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#101419", symbolColor: "#e7edf2", height: 42 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  if (!app.isPackaged) {
    window.loadURL(process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173");
  } else {
    window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
  const webContentsId = window.webContents.id;
  window.webContents.once("destroyed", () => authSessions.delete(webContentsId));
  return window;
}

app.whenReady().then(() => {
  ipcMain.handle("auth:status", async (event) => {
    const user = await currentAuthenticatedUser(event);
    if (user) return { authenticated: true, needsSetup: false, user };
    const status = await runAuthRequest(event.sender, "status");
    return { authenticated: false, ...status, user: null };
  });
  ipcMain.handle("auth:register", async (event, credentials) => {
    if (await currentAuthenticatedUser(event)) throw new Error("当前会话已经登录");
    const session = await runAuthRequest(event.sender, "register", credentials || {});
    if (!session.token || !session.user) throw new Error("创建账户返回了无效结果");
    authSessions.set(event.sender.id, session.token);
    return { authenticated: true, needsSetup: false, user: session.user };
  });
  ipcMain.handle("auth:login", async (event, credentials) => {
    if (await currentAuthenticatedUser(event)) throw new Error("当前会话已经登录");
    const session = await runAuthRequest(event.sender, "login", credentials || {});
    if (!session.token || !session.user) throw new Error("登录返回了无效结果");
    authSessions.set(event.sender.id, session.token);
    return { authenticated: true, needsSetup: false, user: session.user };
  });
  ipcMain.handle("auth:logout", async (event) => {
    const token = authSessions.get(event.sender.id);
    if (token) await runAuthRequest(event.sender, "logout", { token });
    authSessions.delete(event.sender.id);
    return { authenticated: false };
  });
  ipcMain.handle("dialog:select-file", (_event, options) => dialog.showOpenDialog({ properties: ["openFile"], ...options }));
  ipcMain.handle("dialog:select-directory", (_event, options) => dialog.showOpenDialog({ properties: ["openDirectory"], ...options }));
  ipcMain.handle("dialog:save-file", (_event, options) => dialog.showSaveDialog(options));
  ipcMain.handle("project:scan", async (event, rootPath) => {
    await requireAuthenticated(event);
    return scanDirectory(path.resolve(rootPath));
  });
  ipcMain.handle("catalog:read", async (event, filePath) => {
    await requireAuthenticated(event);
    return readCatalog(path.resolve(filePath));
  });
  ipcMain.handle("catalog:write", async (event, filePath, updates) => {
    await requireAuthenticated(event);
    return writeCatalog(path.resolve(filePath), updates);
  });
  ipcMain.handle("python:run", async (event, taskId, args) => {
    await requireAuthenticated(event);
    return runPython(event.sender, taskId, args);
  });
  ipcMain.handle("tasks:list", async (event, stateRoot) => {
    await requireAuthenticated(event);
    return runTaskControl(event.sender, appendStateRoot(["tasks", "list", "--json"], stateRoot));
  });
  ipcMain.handle("tasks:show", async (event, taskId, stateRoot) => {
    await requireAuthenticated(event);
    if (typeof taskId !== "string" || !taskId) throw new TypeError("taskId must be a non-empty string");
    return runTaskControl(event.sender, appendStateRoot(["tasks", "show", taskId, "--json"], stateRoot));
  });
  ipcMain.handle("tasks:retry", async (event, taskId, stateRoot) => {
    await requireAuthenticated(event);
    if (typeof taskId !== "string" || !taskId) throw new TypeError("taskId must be a non-empty string");
    return runTaskControl(event.sender, appendStateRoot(["tasks", "retry", taskId], stateRoot));
  });
  ipcMain.handle("tasks:cancel", async (event, taskId, stateRoot) => {
    await requireAuthenticated(event);
    if (typeof taskId !== "string" || !taskId) throw new TypeError("taskId must be a non-empty string");
    return runTaskControl(event.sender, appendStateRoot(["tasks", "cancel", taskId], stateRoot));
  });
  ipcMain.handle("python:cancel", async (event, taskId) => {
    await requireAuthenticated(event);
    const child = runningProcesses.get(taskId);
    if (!child) return false;
    child.kill();
    return true;
  });
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
