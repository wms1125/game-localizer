import { useEffect, useMemo, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import {
  Archive,
  ArrowDownToLine,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleUserRound,
  ExternalLink,
  FileCode2,
  FileJson2,
  Folder,
  FolderOpen,
  Languages,
  LayoutPanelLeft,
  ListChecks,
  LoaderCircle,
  LogIn,
  LogOut,
  Menu,
  Play,
  RotateCcw,
  RefreshCw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  ShieldAlert,
  Square,
  Upload,
  UserPlus,
  Users,
  Workflow,
  X,
} from "lucide-react";

type Mode = "professional" | "normal";
type View = "workspace" | "single" | "package" | "tasks";

const statusLabel: Record<TranslationRow["status"], string> = {
  translated: "已完成",
  pending: "待定",
  draft: "草稿",
  warning: "需检查",
};

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || "未选择项目";
}

function backendMode(mode: Mode) {
  return mode === "professional" ? "studio" : "player";
}

function selectedDetectionCandidate(report: DetectionReport | null) {
  return report?.candidate || report?.candidates?.find((item) => item.engine_id === report.selected_engine) || null;
}

function capabilityNames(candidate: DetectionCandidate | null) {
  if (!candidate) return [];
  return Array.isArray(candidate.capability) ? candidate.capability : candidate.capability ? [candidate.capability] : [];
}

function isPathInside(root: string, target: string) {
  const normalize = (value: string) => value.replace(/[\\/]+/g, "\\").replace(/\\$/, "").toLowerCase();
  const source = normalize(root);
  const output = normalize(target);
  return Boolean(source) && (source === output || output.startsWith(`${source}\\`));
}

function parseJsonOutput<T>(output: string): T | null {
  try {
    return JSON.parse(output) as T;
  } catch {
    return null;
  }
}

function taskStateLabel(state: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    paused: "已暂停",
    retrying: "重试中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[state] || state;
}

function normalizeEngineId(engine: string | null) {
  if (!engine) return null;
  return engine.replace(/^hanengine\./, "").replace(/-maker-/g, "_maker_");
}

function App() {
  const [authReady, setAuthReady] = useState(false);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [mode, setMode] = useState<Mode>("normal");
  const [view, setView] = useState<View>("workspace");
  const [projectPath, setProjectPath] = useState("");
  const [resourcePath, setResourcePath] = useState("");
  const [catalogPath, setCatalogPath] = useState("");
  const [dictionaryPath, setDictionaryPath] = useState("");
  const [engine, setEngine] = useState("auto");
  const [detection, setDetection] = useState<DetectionReport | null>(null);
  const [tree, setTree] = useState<ProjectNode[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<TranslationRow[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState("");
  const [logs, setLogs] = useState<string[]>(["HanEngine 已就绪。请选择项目目录或目录文件开始工作。"]);
  const [running, setRunning] = useState(false);
  const [activeTask, setActiveTask] = useState("");
  const [activeWorkflowTaskIds, setActiveWorkflowTaskIds] = useState<string[]>([]);
  const [quickOutputPath, setQuickOutputPath] = useState("");
  const [quickStatus, setQuickStatus] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [tasks, setTasks] = useState<TaskStatus[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [taskDetails, setTaskDetails] = useState<TaskStatus | null>(null);
  const [taskActionId, setTaskActionId] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    void initializeAuth();
  }, []);

  async function initializeAuth() {
    try {
      const status = await window.hanengine.authStatus();
      setCurrentUser(status.authenticated ? status.user : null);
      setNeedsSetup(Boolean(status.needsSetup));
    } catch (error) {
      appendLog(`认证服务不可用：${String(error)}`);
    } finally {
      setAuthReady(true);
    }
  }

  function handleAuthenticated(status: AuthStatus) {
    setCurrentUser(status.user);
    setNeedsSetup(false);
  }

  async function logout() {
    try {
      await window.hanengine.logout();
      setCurrentUser(null);
      setProjectPath("");
      setTree([]);
      setRows([]);
      setTasks([]);
      setDetection(null);
      setCatalogPath("");
      setDictionaryPath("");
      setQuickOutputPath("");
      setQuickStatus("idle");
    } catch (error) {
      appendLog(`退出登录失败：${String(error)}`);
    }
  }

  useEffect(() => {
    if (!window.hanengine) return;
    return window.hanengine.onPythonEvent((event) => {
      if (event.channel === "control") return;
      if (event.type === "stdout" || event.type === "stderr") {
        const text = event.text || "";
        const chunks = text.split(/\r?\n/).filter(Boolean);
        if (chunks.length) setLogs((current) => [...current, ...chunks].slice(-240));
        const taskIds = [
          ...[...text.matchAll(/\(task=([^\)]+)\)/g)].map((match) => match[1]),
          ...[...text.matchAll(/\[HanTask persisted\] ([^ #\r\n]+)/g)].map((match) => match[1]),
        ];
        if (taskIds.length) setActiveWorkflowTaskIds((current) => [...new Set([...current, ...taskIds])]);
      }
      if (event.type === "finished" || event.type === "error") {
        setRunning(false);
        setActiveWorkflowTaskIds([]);
        void refreshTasks();
      }
    });
  }, []);

  useEffect(() => {
    if (!currentUser) return;
    void refreshTasks();
    const timer = window.setInterval(() => {
      if (running || view === "tasks") void refreshTasks();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [currentUser, running, view]);

  useEffect(() => {
    if (projectPath) void detectProject(projectPath);
    if (mode === "normal" && (view === "single" || view === "package")) setView("workspace");
  }, [mode]);

  const selected = rows.find((row) => row.id === selectedId) || rows[0];
  const filteredRows = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter((row) => `${row.id} ${row.context} ${row.source} ${row.target}`.toLowerCase().includes(query));
  }, [filter, rows]);
  const translatedCount = rows.filter((row) => row.status === "translated").length;
  const pendingCount = rows.length - translatedCount;
  const detectedCandidate = selectedDetectionCandidate(detection);
  const detectedCapabilities = capabilityNames(detectedCandidate);
  const allowedOperations = detection?.allowed_operations || [];
  const localizationOperations = ["extract", "validate", "build", "verify"];
  const capabilityAllowsLocalization = localizationOperations.every((item) => detectedCapabilities.includes(item));
  const guardAllowsLocalization = localizationOperations.every((item) => allowedOperations.includes(item));
  const canLocalizeProject = detection?.status === "ready" && capabilityAllowsLocalization && guardAllowsLocalization;
  const selectedTask = taskDetails || tasks.find((task) => task.task_id === selectedTaskId) || tasks[0] || null;

  function appendLog(message: string) {
    setLogs((current) => [...current, message].slice(-240));
  }

  async function refreshTasks() {
    if (!window.hanengine) return;
    const result = await window.hanengine.listTasks();
    if (result.code !== 0) return;
    const payload = parseJsonOutput<TaskStatus[]>(result.stdout);
    if (!payload) return;
    const ordered = [...payload].map((task) => ({ ...task, engine_id: normalizeEngineId(task.engine_id) })).sort((left, right) => (right.updated_at || right.created_at || "").localeCompare(left.updated_at || left.created_at || ""));
    setTasks(ordered);
    if (selectedTaskId && !ordered.some((task) => task.task_id === selectedTaskId)) {
      setSelectedTaskId("");
      setTaskDetails(null);
    }
  }

  async function selectTask(taskId: string) {
    setSelectedTaskId(taskId);
    const summary = tasks.find((task) => task.task_id === taskId) || null;
    setTaskDetails(summary);
    if (!window.hanengine) return;
    const result = await window.hanengine.showTask(taskId);
    if (result.code === 0) {
      const detail = parseJsonOutput<TaskStatus>(result.stdout);
      if (detail) setTaskDetails({ ...detail, engine_id: normalizeEngineId(detail.engine_id) });
    }
  }

  async function retrySelectedTask() {
    if (!selectedTask || !selectedTask.retryable || selectedTask.state === "completed" || taskActionId) return;
    setTaskActionId(selectedTask.task_id);
    const result = await window.hanengine?.retryTask(selectedTask.task_id);
    setTaskActionId("");
    if (result?.code === 0) {
      appendLog(`[任务] 已请求继续：${selectedTask.task_id}`);
      await refreshTasks();
    } else {
      appendLog(`[任务] 继续失败：${result?.stderr || "未知错误"}`);
    }
  }

  async function cancelTaskById(taskId: string) {
    if (!taskId || taskActionId) return;
    setTaskActionId(taskId);
    const result = await window.hanengine?.cancelTask(taskId);
    setTaskActionId("");
    if (result?.code === 0) {
      appendLog(`[任务] 已请求取消：${taskId}`);
      await refreshTasks();
    } else {
      appendLog(`[任务] 取消失败：${result?.stderr || "未知错误"}`);
    }
  }

  async function cancelActiveWorkflow() {
    const current = tasks
      .filter((task) => task.source_root === projectPath && ["queued", "running", "paused", "retrying"].includes(task.state))
      .sort((left, right) => (right.updated_at || "").localeCompare(left.updated_at || ""))[0]?.task_id
      || activeWorkflowTaskIds[activeWorkflowTaskIds.length - 1];
    if (!current) {
      appendLog("当前没有可请求取消的持久化任务。");
      return;
    }
    await cancelTaskById(current);
  }

  async function openProject() {
    const result = await window.hanengine?.selectDirectory({ title: "选择游戏项目" });
    if (!result || result.canceled || !result.filePaths[0]) return;
    const selectedPath = result.filePaths[0];
    setProjectPath(selectedPath);
    setQuickStatus("idle");
    setQuickOutputPath("");
    setDetection(null);
    setTasks([]);
    setTaskDetails(null);
    setSelectedTaskId("");
    appendLog(`已打开项目：${selectedPath}`);
    try {
      const projectTree = await window.hanengine.scanProject(selectedPath);
      setTree(projectTree);
      setExpanded(new Set(projectTree.filter((node) => node.type === "directory").slice(0, 2).map((node) => node.relativePath)));
      await detectProject(selectedPath);
    } catch (error) {
      appendLog(`读取项目结构失败：${String(error)}`);
    }
  }

  async function detectProject(rootPath: string): Promise<string | null> {
    const result = await runPython(["engine", "inspect", "auto", rootPath, "--json", "--mode", backendMode(mode)], "识别游戏引擎和可用能力");
    if (!result) return null;
    const report = parseJsonOutput<DetectionReport>(result.stdout);
    if (!report) {
      appendLog(`引擎检测结果无法解析：${result.stderr || result.stdout}`);
      return null;
    }
    setDetection(report);
    if (report.selected_engine) {
      setEngine(report.selected_engine);
      const selectedCandidate = selectedDetectionCandidate(report);
      appendLog(`[检测] ${selectedCandidate?.display_name || report.selected_engine}（${report.status}）`);
      if (report.status !== "ready") appendLog("[安全门控] 当前项目仅允许检测，提取和构建已禁用。");
    } else {
      appendLog(`[检测] 未能自动确定引擎（${report.status}），请手动选择。`);
    }
    return report.selected_engine;
  }

  async function loadCatalog(selectedPath: string) {
    setCatalogPath(selectedPath);
    try {
      const catalog = await window.hanengine.readCatalog(selectedPath);
      setRows(catalog.rows);
      setSelectedId(catalog.rows[0]?.id || "");
      if (catalog.metadata.engine && catalog.metadata.engine !== "auto") setEngine(catalog.metadata.engine);
      appendLog(`已加载 ${catalog.rows.length} 条翻译记录：${selectedPath}`);
    } catch (error) {
      appendLog(`目录读取失败：${String(error)}`);
    }
  }

  async function chooseCatalog() {
    const result = await window.hanengine?.selectFile({ title: "打开翻译目录", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (!result || result.canceled || !result.filePaths[0]) return;
    await loadCatalog(result.filePaths[0]);
  }

  async function chooseDictionary() {
    const result = await window.hanengine?.selectFile({ title: "加载翻译字典", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (result && !result.canceled && result.filePaths[0]) setDictionaryPath(result.filePaths[0]);
  }

  async function runPython(args: string[], label: string): Promise<{ code: number; stdout: string; stderr: string } | null> {
    if (running) return null;
    const taskId = `ui-${Date.now()}`;
    setActiveTask(taskId);
    setRunning(true);
    appendLog(`[开始] ${label}`);
    const result = await window.hanengine?.runPython(taskId, args);
    if (!result) {
      appendLog("Electron 主进程不可用，请通过 npm run dev 启动桌面壳。");
      setRunning(false);
      return null;
    }
    if (result.code === 0) appendLog(`[完成] ${label}`);
    else appendLog(`[失败] ${label}（退出码 ${result.code}）`);
    setRunning(false);
    return result;
  }

  async function extractCatalog() {
    if (!projectPath) return appendLog("请先选择项目目录。");
    if (!canLocalizeProject) return appendLog("HanGuard 或适配器能力未允许提取，请检查项目类型和检测结果。");
    let output = catalogPath;
    if (!output) {
      const result = await window.hanengine?.saveFile({ title: "保存翻译目录", defaultPath: "catalog.json", filters: [{ name: "JSON", extensions: ["json"] }] });
      if (!result || result.canceled || !result.filePath) return;
      output = result.filePath;
      setCatalogPath(output);
    }
    let selectedEngine = engine;
    if (selectedEngine === "auto") selectedEngine = detection?.selected_engine || (await detectProject(projectPath)) || "auto";
    if (selectedEngine === "auto") return appendLog("无法提取：请手动选择一个引擎。");
    const args = ["engine", "extract", selectedEngine, projectPath, "--output", output, "--mode", backendMode(mode)];
    const result = await runPython(args, "提取翻译目录");
    if (result?.code === 0) await loadCatalog(output);
  }

  async function localizeProject() {
    if (!projectPath) return appendLog("请先选择项目目录。");
    if (!dictionaryPath) return appendLog("请先加载翻译字典。");
    const result = await window.hanengine?.selectDirectory({ title: "选择汉化输出目录" });
    if (!result || result.canceled || !result.filePaths[0]) return;
    const selectedEngine = engine === "auto" ? detection?.selected_engine || "auto" : engine;
    await runPython(["engine", "localize", selectedEngine, projectPath, "--output", result.filePaths[0], "--dictionary", dictionaryPath, "--mode", backendMode(mode)], "翻译、构建并验证");
  }

  async function chooseQuickOutput() {
    const result = await window.hanengine?.selectDirectory({ title: "选择独立汉化输出目录" });
    if (!result || result.canceled || !result.filePaths[0]) return;
    const selectedPath = result.filePaths[0];
    if (isPathInside(projectPath, selectedPath)) {
      appendLog("[安全门控] 输出目录不能是游戏项目目录或其子目录。");
      return;
    }
    setQuickOutputPath(selectedPath);
  }

  async function runQuickLocalization() {
    if (!projectPath || !dictionaryPath || !quickOutputPath) return;
    if (!canLocalizeProject) {
      appendLog("[安全门控] 当前项目未获得提取、校验、构建和验证权限。");
      return;
    }
    if (isPathInside(projectPath, quickOutputPath)) {
      appendLog("[安全门控] 输出目录必须位于游戏项目之外。");
      return;
    }
    setQuickStatus("running");
    setActiveWorkflowTaskIds([]);
    const result = await runPython(
      ["engine", "localize", "auto", projectPath, "--output", quickOutputPath, "--dictionary", dictionaryPath, "--mode", "player"],
      "一键汉化：提取、翻译、校验、构建和验证",
    );
    setQuickStatus(result?.code === 0 ? "completed" : "failed");
    await refreshTasks();
    if (result?.code === 0) setView("tasks");
  }

  async function saveCatalog() {
    if (!catalogPath || !window.hanengine) return appendLog("请先加载或提取翻译目录。");
    try {
      const result = await window.hanengine.writeCatalog(catalogPath, rows);
      appendLog(`已保存 ${result.updated} 条翻译：${result.path}`);
    } catch (error) {
      appendLog(`保存失败：${String(error)}`);
    }
  }

  function updateSelectedTarget(value: string) {
    setRows((current) => current.map((row) => row.id === selectedId ? { ...row, target: value, status: value.trim() ? "translated" : "draft" } : row));
  }

  function toggleNode(node: ProjectNode) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(node.relativePath)) next.delete(node.relativePath); else next.add(node.relativePath);
      return next;
    });
  }

  function renderTree(nodes: ProjectNode[], depth = 0): ReactElement[] {
    return nodes.flatMap((node) => {
      const isOpen = expanded.has(node.relativePath);
      const icon = node.type === "directory" ? (isOpen ? <FolderOpen size={15} /> : <Folder size={15} />) : (node.extension === ".json" ? <FileJson2 size={15} /> : <FileCode2 size={15} />);
      const item = <button className={`tree-item ${catalogPath.endsWith(node.relativePath) ? "selected" : ""}`} key={node.relativePath} style={{ paddingLeft: 12 + depth * 16 }} onClick={() => node.type === "directory" ? toggleNode(node) : loadCatalog(projectPath ? `${projectPath.replace(/[\\/]$/, "")}${projectPath.includes("\\") ? "\\" : "/"}${node.relativePath}` : node.relativePath)}>{node.type === "directory" && (isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />)}{icon}<span>{node.name}</span>{node.type === "file" && <span className="tree-dot" />}</button>;
      return node.type === "directory" && isOpen ? [item, ...renderTree(node.children || [], depth + 1)] : [item];
    });
  }

  const navItems = [
    { id: "workspace" as View, label: "工作台", icon: <LayoutPanelLeft size={16} /> },
    { id: "single" as View, label: "单文件", icon: <FileCode2 size={16} /> },
    { id: "package" as View, label: "封包输出", icon: <Archive size={16} /> },
    { id: "tasks" as View, label: "任务中心", icon: <ListChecks size={16} /> },
  ];
  const visibleNavItems = mode === "normal"
    ? navItems.filter((item) => item.id === "workspace" || item.id === "tasks")
    : navItems;

  if (!authReady) return <AuthLoadingScreen />;
  if (!currentUser) {
    return <AuthScreen needsSetup={needsSetup} onAuthenticated={handleAuthenticated} />;
  }

  return (
    <div className="app-shell">
      <header className="titlebar">
        <div className="brand-mark"><Languages size={18} /><span>HanEngine</span><small>本地游戏汉化工作台</small></div>
        <div className="mode-switch" role="tablist" aria-label="工作模式">
          <button className={mode === "normal" ? "active" : ""} onClick={() => setMode("normal")}><Users size={15} />普通</button>
          <button className={mode === "professional" ? "active" : ""} onClick={() => setMode("professional")}><Workflow size={15} />专业</button>
        </div>
        <div className="title-actions"><button className="icon-button no-drag" title="刷新项目" onClick={() => projectPath && openProject()}><RefreshCw size={16} /></button><button className="icon-button no-drag" title="设置"><Settings2 size={16} /></button><span className="account-chip no-drag"><CircleUserRound size={15} /><span>{currentUser.display_name || currentUser.username}</span></span><button className="icon-button no-drag" title="退出登录" onClick={() => void logout()}><LogOut size={16} /></button></div>
      </header>

      <div className={`body-grid ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <aside className="sidebar">
          <div className="sidebar-top"><button className="new-project" onClick={openProject}><FolderOpen size={16} />打开项目</button><button className="icon-button" title="收起工作栏" onClick={() => setSidebarCollapsed(true)}><Menu size={16} /></button></div>
          <nav className="nav-list">{visibleNavItems.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>{item.icon}<span>{item.label}</span></button>)}</nav>
          <div className="sidebar-section"><div className="section-title"><span>项目结构</span><button className="small-icon" title="重新扫描" onClick={() => projectPath && openProject()}><RefreshCw size={13} /></button></div>{projectPath ? <div className="project-name"><CircleDot size={13} /><span title={projectPath}>{basename(projectPath)}</span></div> : <div className="empty-state compact"><Folder size={22} /><span>打开一个项目开始</span></div>}<div className="tree">{renderTree(tree)}</div></div>
          <div className="sidebar-footer"><div className="ethics"><ShieldCheck size={14} /><span>仅处理合法拥有或获授权的资源</span></div><button className="collapse-button" onClick={() => setSidebarCollapsed(true)}><ChevronRight size={14} />收起</button></div>
        </aside>

        <main className="workspace">
          {sidebarCollapsed && <button className="restore-sidebar icon-button" title="展开工作栏" onClick={() => setSidebarCollapsed(false)}><Menu size={16} /></button>}
          <div className="workspace-header"><div><div className="breadcrumbs"><span>{mode === "professional" ? "专业" : "普通"}</span><ChevronRight size={13} /><strong>{projectPath ? basename(projectPath) : "未选择项目"}</strong>{catalogPath && <><ChevronRight size={13} /><span>{basename(catalogPath)}</span></>}</div><h1>{view === "workspace" ? (mode === "normal" ? "快速汉化" : "翻译工作区") : navItems.find((item) => item.id === view)?.label}</h1></div><div className="header-actions"><span className={`connection ${running ? "busy" : ""}`}><span className="connection-dot" />{running ? "处理中" : "本地模式"}</span>{mode === "professional" && <button className="secondary-button" onClick={chooseCatalog}><Upload size={15} />打开目录</button>}</div></div>

          {view === "workspace" && mode === "professional" && <>
            <div className="command-bar"><div className="command-group"><button className="primary-button" onClick={extractCatalog} disabled={running}><ArrowDownToLine size={15} />提取文本</button><button className="secondary-button" onClick={localizeProject} disabled={running}><Play size={15} />运行汉化</button><button className="secondary-button" onClick={saveCatalog}><Save size={15} />保存</button></div><div className="command-group"><label className="inline-control">引擎<select value={engine} onChange={(event) => setEngine(event.target.value)}><option value="auto">自动识别</option><option value="renpy">Ren'Py</option><option value="rpg_maker_mv">RPG Maker MV</option><option value="rpg_maker_mz">RPG Maker MZ</option><option value="godot">Godot</option><option value="unity">Unity</option><option value="unreal">Unreal</option></select></label><button className="icon-button" title="加载字典" onClick={chooseDictionary}><Languages size={16} /></button></div></div>
            <div className="stats-strip"><div><span>总条目</span><strong>{rows.length.toLocaleString()}</strong></div><div><span>已完成</span><strong className="success-text">{translatedCount.toLocaleString()}</strong></div><div><span>待翻译</span><strong className="warning-text">{pendingCount.toLocaleString()}</strong></div><div className="stats-spacer" /><div className="file-context"><FileJson2 size={14} /><span>{catalogPath ? basename(catalogPath) : "提取或打开 catalog JSON 后显示翻译条目"}</span></div></div>
            <div className="filter-bar"><div className="search-box"><Search size={15} /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="搜索 ID、上下文或文本" /></div><button className="filter-button"><CircleAlert size={14} />仅看待翻译</button></div>
            <section className="translation-area"><div className="table-wrap"><table><thead><tr><th className="id-col">ID</th><th className="context-col">上下文</th><th>原文</th><th>译文</th><th className="status-col">状态</th></tr></thead><tbody>{filteredRows.length ? filteredRows.map((row) => <tr key={row.id} className={row.id === selectedId ? "selected-row" : ""} onClick={() => setSelectedId(row.id)}><td className="mono">{row.id}</td><td className="muted-cell">{row.context}</td><td>{row.source}</td><td className={!row.target ? "placeholder-cell" : ""}>{row.target || "点击下方编辑译文"}</td><td><span className={`status-pill ${row.status}`}>{statusLabel[row.status]}</span></td></tr>) : <tr><td className="empty-table" colSpan={5}>尚未加载翻译目录。打开项目后点击“提取文本”，或直接打开 catalog JSON。</td></tr>}</tbody></table></div><div className="editor-panel"><div className="editor-heading"><div><span className="eyebrow">当前条目</span><strong>{selected?.context || "未选择"}</strong></div><span className="editor-id">{selected?.id || "-"}</span></div><div className="editor-fields"><div><label>原文</label><div className="source-preview">{selected?.source || "选择一条翻译记录"}</div></div><div><label>译文</label><textarea value={selected?.target || ""} onChange={(event) => updateSelectedTarget(event.target.value)} placeholder="输入简体中文译文..." /></div></div></div></section>
          </>}
          {view === "workspace" && mode === "normal" && <QuickLocalizationView
            projectPath={projectPath}
            detection={detection}
            candidate={detectedCandidate}
            dictionaryPath={dictionaryPath}
            outputPath={quickOutputPath}
            running={running}
            status={quickStatus}
            canLocalize={Boolean(canLocalizeProject)}
            onOpenProject={openProject}
            onChooseDictionary={chooseDictionary}
            onChooseOutput={chooseQuickOutput}
            onRun={runQuickLocalization}
            onOpenTasks={() => setView("tasks")}
          />}

          {view === "single" && <OperationView title="单文件翻译" description="使用现有 translator.py 处理 TXT、KS、RPY、SCRIPT、CSV 或 JSON 资源。" primaryLabel="执行汉化" onPrimary={() => resourcePath && dictionaryPath && runPython([resourcePath, dictionaryPath], "单文件汉化")}><PathField label="资源文件" value={resourcePath} onPick={async () => { const result = await window.hanengine?.selectFile(); if (result && !result.canceled) setResourcePath(result.filePaths[0]); }} /><PathField label="翻译字典" value={dictionaryPath} onPick={chooseDictionary} /></OperationView>}
          {view === "package" && <OperationView title="封包输出" description="生成独立 ZIP 副本，保留原始项目不被覆盖。" primaryLabel="生成 ZIP 副本" onPrimary={() => appendLog("封包参数已保留，请在工作室模式选择源包和补丁文件。")}><div className="notice-card"><Archive size={20} /><div><strong>安全输出边界</strong><span>Electron 仅负责选择路径和展示结果，实际 ZIP 校验与写入仍由 Python `cli.py package` 执行。</span></div></div></OperationView>}
          {view === "tasks" && <TaskView
            tasks={tasks}
            selectedTask={selectedTask}
            selectedTaskId={selectedTaskId}
            logs={logs}
            actionId={taskActionId}
            onRefresh={refreshTasks}
            onSelect={selectTask}
            onRetry={retrySelectedTask}
            onCancel={cancelTaskById}
          />}

          <footer className="statusbar"><span><span className="connection-dot" />HanEngine Core</span><span>模式：{mode === "professional" ? "专业" : "普通"}</span><span>Python CLI 已连接</span><span className="status-spacer" />{running ? <button className="cancel-button" onClick={cancelActiveWorkflow}><Square size={12} />请求停止</button> : <span>就绪</span>}</footer>
        </main>
      </div>
    </div>
  );
}

function AuthLoadingScreen() {
  return <div className="auth-screen auth-loading"><div className="auth-loading-mark"><Languages size={22} /><span>HanEngine</span></div><LoaderCircle size={18} className="spin" /><span>正在准备本地账户</span></div>;
}

function AuthScreen({
  needsSetup,
  onAuthenticated,
}: {
  needsSetup: boolean;
  onAuthenticated: (status: AuthStatus) => void;
}) {
  const [registerMode, setRegisterMode] = useState(needsSetup);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setRegisterMode(needsSetup);
  }, [needsSetup]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (registerMode && password !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      const status = registerMode
        ? await window.hanengine.register({ username, password, display_name: displayName })
        : await window.hanengine.login({ username, password });
      onAuthenticated(status);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message.replace(/^Error:\s*/i, "") || "认证失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="auth-screen">
    <div className="auth-panel">
      <div className="auth-brand"><div className="auth-brand-icon"><Languages size={22} /></div><div><strong>HanEngine</strong><span>本地游戏汉化工作台</span></div></div>
      <div className="auth-rule" />
      <div className="auth-copy"><span className="eyebrow">本地身份</span><h1>{registerMode ? "创建本地账户" : "登录 HanEngine"}</h1><p>{registerMode ? "账户只保存在这台设备上。" : "使用本地账户继续进入工作台。"}</p></div>
      <form className="auth-form" onSubmit={submit}>
        <label><span>用户名</span><input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" autoFocus placeholder="输入用户名" required /></label>
        {registerMode && <label><span>显示名称 <em>可选</em></span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" placeholder="工作台中显示的名称" /></label>}
        <label><span>密码</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={registerMode ? "new-password" : "current-password"} placeholder="至少 8 个字符" required /></label>
        {registerMode && <label><span>确认密码</span><input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" placeholder="再次输入密码" required /> </label>}
        {error && <div className="auth-error" role="alert"><CircleAlert size={16} /><span>{error}</span></div>}
        <button className="primary-button auth-submit" type="submit" disabled={submitting}>{submitting ? <LoaderCircle size={16} className="spin" /> : registerMode ? <UserPlus size={16} /> : <LogIn size={16} />}{submitting ? "处理中" : registerMode ? "创建账户并进入" : "登录"}</button>
      </form>
      <button className="auth-switch" type="button" onClick={() => { setError(""); setRegisterMode((value) => !value); }}>{registerMode ? "已有账户，改为登录" : "创建新的本地账户"}</button>
      <div className="auth-footnote"><ShieldCheck size={14} /><span>密码使用本地加盐哈希保存，不会写入项目、任务日志或命令行参数。</span></div>
    </div>
  </div>;
}

function PathField({ label, value, onPick }: { label: string; value: string; onPick: () => void }) {
  return <label className="path-field"><span>{label}</span><input value={value} readOnly placeholder="尚未选择" /><button className="secondary-button" onClick={onPick}>浏览</button></label>;
}

function OperationView({ title, description, primaryLabel, onPrimary, children }: { title: string; description: string; primaryLabel: string; onPrimary: () => void; children: ReactNode }) {
  return <section className="operation-view"><div className="operation-heading"><div><span className="eyebrow">HanEngine / 工具</span><h2>{title}</h2><p>{description}</p></div><button className="primary-button" onClick={onPrimary}><Play size={15} />{primaryLabel}</button></div><div className="operation-content">{children}</div></section>;
}

function QuickLocalizationView({
  projectPath,
  detection,
  candidate,
  dictionaryPath,
  outputPath,
  running,
  status,
  canLocalize,
  onOpenProject,
  onChooseDictionary,
  onChooseOutput,
  onRun,
  onOpenTasks,
}: {
  projectPath: string;
  detection: DetectionReport | null;
  candidate: DetectionCandidate | null;
  dictionaryPath: string;
  outputPath: string;
  running: boolean;
  status: "idle" | "running" | "completed" | "failed";
  canLocalize: boolean;
  onOpenProject: () => void;
  onChooseDictionary: () => void;
  onChooseOutput: () => void;
  onRun: () => void;
  onOpenTasks: () => void;
}) {
  const capability = capabilityNames(candidate);
  const ready = Boolean(projectPath && candidate && canLocalize);
  return <section className="operation-view quick-view">
    <div className="operation-heading">
      <div><span className="eyebrow">HanEngine / 普通模式</span><h2>快速汉化</h2><p>选择游戏、字典和输出目录，HanEngine 会自动完成提取、翻译、校验、构建和验证。</p></div>
      <button className="secondary-button" onClick={onOpenTasks}><ListChecks size={15} />查看任务</button>
    </div>
    <div className="quick-steps">
      <div className={`quick-step ${projectPath ? "done" : "active"}`}><span>1</span><div><strong>选择游戏目录</strong><small>{projectPath || "从一个已授权的原始工程开始"}</small></div><button className="secondary-button" onClick={onOpenProject}>{projectPath ? "更换" : "选择"}</button></div>
      <div className={`quick-step ${candidate ? "done" : projectPath ? "active" : "locked"}`}><span>2</span><div><strong>自动检测引擎</strong><small>{candidate ? `${candidate.display_name} · ${candidate.score}%` : "选择目录后自动检测"}</small></div>{candidate && <Check size={16} className="step-check" />}</div>
      <div className={`quick-step ${dictionaryPath ? "done" : projectPath ? "active" : "locked"}`}><span>3</span><div><strong>选择本地字典</strong><small>{dictionaryPath || "UTF-8 JSON 字典"}</small></div><button className="secondary-button" onClick={onChooseDictionary} disabled={!projectPath}>浏览</button></div>
      <div className={`quick-step ${outputPath ? "done" : projectPath ? "active" : "locked"}`}><span>4</span><div><strong>选择输出目录</strong><small>{outputPath || "必须位于游戏项目之外"}</small></div><button className="secondary-button" onClick={onChooseOutput} disabled={!projectPath}>浏览</button></div>
    </div>
    {detection && <div className={`capability-card ${ready ? "allowed" : "blocked"}`}>
      {ready ? <ShieldCheck size={19} /> : <ShieldAlert size={19} />}
      <div><strong>{ready ? "可以执行一键汉化" : "当前项目仅允许检测"}</strong><span>{ready ? `HanGuard 已允许：${capability.filter((item) => item !== "detect").join("、") || "结构化构建"}` : (candidate?.limitations?.join("；") || "适配器能力或 HanGuard 路由不足，已禁用提取和构建。")}</span></div>
      <span className="capability-state">{detection.status}</span>
    </div>}
    <div className="quick-actions"><button className="primary-button" disabled={!ready || !dictionaryPath || !outputPath || running} onClick={onRun}>{running ? <LoaderCircle size={15} className="spin" /> : status === "completed" ? <CircleCheck size={15} /> : <Play size={15} />}{running ? "处理中" : status === "completed" ? "再次运行" : "一键汉化"}</button><span className="quick-hint">原项目不会被覆盖，所有产物写入独立目录。</span></div>
    {status !== "idle" && <div className={`quick-result ${status}`}><span>{status === "completed" ? "汉化流程已完成，可在任务中心查看产物。" : status === "failed" ? "汉化流程失败，可从任务中心查看原因并重试。" : "正在执行 HanTask 流程，关闭应用后仍可从任务中心继续。"}</span><button className="icon-button" title="打开任务中心" onClick={onOpenTasks}><ExternalLink size={15} /></button></div>}
  </section>;
}

function TaskView({
  tasks,
  selectedTask,
  selectedTaskId,
  logs,
  actionId,
  onRefresh,
  onSelect,
  onRetry,
  onCancel,
}: {
  tasks: TaskStatus[];
  selectedTask: TaskStatus | null;
  selectedTaskId: string;
  logs: string[];
  actionId: string;
  onRefresh: () => Promise<void>;
  onSelect: (taskId: string) => Promise<void>;
  onRetry: () => Promise<void>;
  onCancel: (taskId: string) => Promise<void>;
}) {
  const selectedState = selectedTask?.state || "";
  const active = ["queued", "running", "paused", "retrying"].includes(selectedState);
  const progress = selectedTask?.progress;
  const percent = progress?.total ? Math.min(100, Math.round((progress.completed / progress.total) * 100)) : 0;
  const guard = selectedTask?.hanguard;
  const artifacts = selectedTask?.artifacts || [];
  return <section className="operation-view task-center-view">
    <div className="operation-heading"><div><span className="eyebrow">HanTask Center</span><h2>任务中心</h2><p>任务状态、检查点和安全决策均来自持久化 HanStore。</p></div><button className="secondary-button" onClick={() => void onRefresh()}><RefreshCw size={15} />刷新</button></div>
    <div className="task-center-grid">
      <div className="task-list task-table"><div className="task-row task-head"><span>任务</span><span>状态</span><span>阶段</span><span>进度</span></div>{tasks.length ? tasks.map((task) => { const taskProgress = task.progress?.total ? `${task.progress.completed}/${task.progress.total}` : "-"; return <button key={task.task_id} className={`task-row task-select ${task.task_id === selectedTaskId ? "selected" : ""}`} onClick={() => void onSelect(task.task_id)}><span><strong>{task.engine_id || task.kind}</strong><small>{task.project_name} · {task.task_id}</small></span><span className={`status-pill task-${task.state}`}>{taskStateLabel(task.state)}</span><span>{task.stage}</span><span>{taskProgress}</span></button>; }) : <div className="task-empty"><ListChecks size={24} /><span>还没有持久化任务</span></div>}</div>
      <div className="task-detail-panel">{selectedTask ? <><div className="task-detail-heading"><div><span className="eyebrow">任务详情</span><strong>{selectedTask.task_id}</strong></div><div className="task-actions">{selectedTask.retryable && selectedState !== "completed" && <button className="secondary-button" disabled={Boolean(actionId)} onClick={() => void onRetry()}><RotateCcw size={14} />{actionId === selectedTask.task_id ? "处理中" : "继续/重试"}</button>}{active && <button className="secondary-button danger" disabled={Boolean(actionId)} onClick={() => void onCancel(selectedTask.task_id)}><Square size={13} />{actionId === selectedTask.task_id ? "处理中" : "请求取消"}</button>}</div></div><div className="task-metadata"><span>引擎 <strong>{selectedTask.engine_id || "-"}</strong></span><span>阶段 <strong>{selectedTask.stage}</strong></span><span>状态 <strong>{taskStateLabel(selectedTask.state)}</strong></span></div><div className="task-progress"><div className="progress-label"><span>{progress?.current_item || "当前检查点"}</span><strong>{progress?.total ? `${percent}%` : "-"}</strong></div><div className="progress-track"><span style={{ width: `${percent}%` }} /></div></div><div className="task-detail-sections"><div><label>HanGuard 决策</label><pre>{guard ? `允许：${JSON.stringify(guard.allowed_operations || [], null, 2)}\n阻止：${JSON.stringify(guard.blocked_operations || [], null, 2)}\n原因：${JSON.stringify(guard.decision_reasons || [], null, 2)}` : "尚无最终决策"}</pre></div><div><label>失败原因</label><p className={selectedTask.failure_reason ? "failure-text" : "muted-cell"}>{selectedTask.failure_reason || "无"}</p></div><div><label>最近检查点</label><p>{selectedTask.latest_checkpoint ? `${String(selectedTask.latest_checkpoint.step_id || selectedTask.stage)} · 序号 ${String(selectedTask.latest_checkpoint.sequence || "-")}` : "无"}</p></div><div><label>产物</label>{artifacts.length ? <ul>{artifacts.map((artifact) => <li key={artifact.artifact_id}>{artifact.relative_path || artifact.artifact_id}</li>)}</ul> : <p className="muted-cell">暂无产物</p>}</div></div></> : <div className="task-empty detail-empty"><ListChecks size={28} /><strong>选择一个任务查看详情</strong><span>应用重启后，未完成任务会保留在这里。</span></div>}</div>
    </div>
    <pre className="log-panel">{logs.join("\n")}</pre>
  </section>;
}

export default App;
