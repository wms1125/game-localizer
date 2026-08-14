import { useEffect, useMemo, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import {
  Archive,
  ArrowDownToLine,
  Check,
  ChevronDown,
  ChevronLeft,
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
  ScanSearch,
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
type View = "workspace" | "single" | "package" | "tasks" | "visual";

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

function isLikelyUntranslated(source: string, target: string) {
  if (!target.trim() || source.trim() !== target.trim()) return false;
  if (/[\u3400-\u9fff]/.test(source)) return false;
  if (!/[A-Za-z]{2}/.test(source)) return false;
  if (/^([A-Za-z_][A-Za-z0-9_]*|[A-Z]{1,4}|[0-9A-Za-z_./:+-]+)$/.test(source.trim())) return false;
  return /\s/.test(source.trim()) || source.trim().length > 8;
}

function rowStatus(source: string, target: string): TranslationRow["status"] {
  if (!target.trim()) return "pending";
  return isLikelyUntranslated(source, target) ? "warning" : "translated";
}

function selectedDetectionCandidate(report: DetectionReport | null) {
  return report?.candidate || report?.candidates?.find((item) => item.engine_id === report.selected_engine) || null;
}

function capabilityNames(candidate: DetectionCandidate | null) {
  if (!candidate) return [];
  return Array.isArray(candidate.capability) ? candidate.capability : candidate.capability ? [candidate.capability] : [];
}

function capabilityMatrixLabel(matrix: CapabilityMatrix | undefined) {
  if (!matrix) return "";
  const labels: Record<string, string> = {
    native_text_replace: "原生文本",
    dynamic_text: "动态文本",
    raster_text: "栅格文字",
    detect_only: "仅检测",
  };
  const statuses: Record<string, string> = {
    implemented: "已实现",
    verified: "已验证",
    detect_only: "仅检测",
    unsupported: "不支持",
  };
  return matrix.capabilities
    .map((item) => `${labels[item.capability] || item.capability}：${statuses[item.status] || item.status}`)
    .join(" · ");
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
  const [gameLanguage, setGameLanguage] = useState<GameLanguage>(() => {
    try {
      const value = window.localStorage.getItem("hanengine.gameLanguage");
      return value === "source" ? "source" : "zh-CN";
    } catch {
      return "zh-CN";
    }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [gameExecutablePath, setGameExecutablePath] = useState(() => {
    try {
      return window.localStorage.getItem("hanengine.gameExecutablePath") || "";
    } catch {
      return "";
    }
  });
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
  const [reviewOnly, setReviewOnly] = useState(false);
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
  const [visualManifestPath, setVisualManifestPath] = useState("");
  const [visualReportPath, setVisualReportPath] = useState("");
  const [visualStatus, setVisualStatus] = useState<"idle" | "checking" | "passed" | "blocked" | "review" | "failed">("idle");
  const [visualSummary, setVisualSummary] = useState<VisualReportSummary | null>(null);
  const [visualReviewProof, setVisualReviewProof] = useState<VisualReviewProof | null>(null);
  const [visualProofSaving, setVisualProofSaving] = useState(false);
  const [visualSceneId, setVisualSceneId] = useState("");
  const [visualImagePair, setVisualImagePair] = useState<VisualImagePair | null>(null);
  const [visualConfirmedScenes, setVisualConfirmedScenes] = useState<Set<string>>(new Set());
  const [visualImageLoading, setVisualImageLoading] = useState(false);

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
    return rows.filter((row) => {
      const matchesQuery = !query || `${row.id} ${row.context} ${row.source} ${row.target}`.toLowerCase().includes(query);
      const needsReview = !reviewOnly || row.status === "pending" || row.status === "draft" || row.status === "warning";
      return matchesQuery && needsReview;
    });
  }, [filter, reviewOnly, rows]);
  const translatedCount = rows.filter((row) => row.status === "translated").length;
  const warningCount = rows.filter((row) => row.status === "warning").length;
  const pendingCount = rows.length - translatedCount - warningCount;
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

  function updateGameLanguage(value: GameLanguage) {
    setGameLanguage(value);
    try {
      window.localStorage.setItem("hanengine.gameLanguage", value);
    } catch {
      // Settings still apply to the current session when storage is unavailable.
    }
    appendLog("[语言] 客户端启动语言：" + (value === "zh-CN" ? "简体中文" : "原文"));
  }

  async function chooseGameExecutable() {
    const result = await window.hanengine?.selectFile({ title: "选择游戏启动程序", filters: [{ name: "程序", extensions: ["exe", "sh", "app"] }] });
    if (result && !result.canceled && result.filePaths[0]) {
      const selectedPath = result.filePaths[0];
      setGameExecutablePath(selectedPath);
      try {
        window.localStorage.setItem("hanengine.gameExecutablePath", selectedPath);
      } catch {
        // The path remains available in the current session when storage is unavailable.
      }
    }
  }

  async function launchSelectedGame() {
    if (!gameExecutablePath) return appendLog("请先在 HanEngine 设置中选择游戏启动程序。");
    try {
      const launched = await window.hanengine.launchGame(gameExecutablePath, gameLanguage === "zh-CN" ? "zh_cn" : "source");
      appendLog("[启动] 已按" + (gameLanguage === "zh-CN" ? "简体中文" : "原文") + "模式启动游戏" + (launched.pid ? "（PID " + launched.pid + "）" : ""));
    } catch (error) {
      appendLog("[启动] 游戏启动失败：" + String(error));
    }
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
      setRows(catalog.rows.map((row) => ({ ...row, status: rowStatus(row.source, row.target) })));
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
    const args = ["engine", "extract", selectedEngine, projectPath, "--output", output, "--language", "zh-CN", "--mode", backendMode(mode)];
    const result = await runPython(args, "提取翻译目录");
    if (result?.code === 0) await loadCatalog(output);
  }

  async function localizeProject() {
    if (!projectPath) return appendLog("请先选择项目目录。");
    if (!dictionaryPath) return appendLog("请先加载翻译字典。");
    const result = await window.hanengine?.selectDirectory({ title: "选择汉化输出目录" });
    if (!result || result.canceled || !result.filePaths[0]) return;
    const selectedEngine = engine === "auto" ? detection?.selected_engine || "auto" : engine;
    await runPython(["engine", "localize", selectedEngine, projectPath, "--output", result.filePaths[0], "--dictionary", dictionaryPath, "--language", "zh-CN", "--mode", backendMode(mode)], "翻译、构建并验证");
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
      ["engine", "localize", "auto", projectPath, "--output", quickOutputPath, "--dictionary", dictionaryPath, "--language", "zh-CN", "--mode", "player"],
      "一键汉化：提取、翻译、校验、构建和验证",
    );
    setQuickStatus(result?.code === 0 ? "completed" : "failed");
    await refreshTasks();
    if (result?.code === 0) setView("tasks");
  }

  async function chooseVisualManifest() {
    const result = await window.hanengine?.selectFile({ title: "选择视觉证据清单", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (result && !result.canceled && result.filePaths[0]) {
      setVisualManifestPath(result.filePaths[0]);
      resetVisualReview();
    }
  }

  async function chooseVisualReport() {
    const result = await window.hanengine?.saveFile({ title: "保存视觉验收报告", defaultPath: "visual-report.json", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (result && !result.canceled && result.filePath) {
      setVisualReportPath(result.filePath);
      resetVisualReview();
    }
  }

  async function openVisualReport() {
    const result = await window.hanengine?.selectFile({ title: "打开视觉验收报告", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (!result || result.canceled || !result.filePaths[0]) return;
    const selectedPath = result.filePaths[0];
    resetVisualReview();
    setVisualReportPath(selectedPath);
    await loadVisualReport(selectedPath);
  }

  function resetVisualReview() {
    setVisualStatus("idle");
    setVisualSummary(null);
    setVisualReviewProof(null);
    setVisualProofSaving(false);
    setVisualSceneId("");
    setVisualImagePair(null);
    setVisualConfirmedScenes(new Set());
    setVisualImageLoading(false);
  }

  async function selectVisualScene(sampleId: string, reportPath = visualReportPath) {
    if (!sampleId || !reportPath) return;
    setVisualSceneId(sampleId);
    setVisualImagePair(null);
    setVisualImageLoading(true);
    try {
      setVisualImagePair(await window.hanengine.readVisualImagePair(reportPath, sampleId));
    } catch (error) {
      appendLog(`视觉证据读取失败：${String(error)}`);
    } finally {
      setVisualImageLoading(false);
    }
  }

  function toggleVisualSceneConfirmation(sampleId: string, confirmed: boolean) {
    if (visualReviewProof || visualProofSaving) return;
    setVisualConfirmedScenes((current) => {
      const next = new Set(current);
      if (confirmed) next.add(sampleId); else next.delete(sampleId);
      return next;
    });
  }

  async function completeVisualReview() {
    if (!visualSummary || visualStatus !== "review") return;
    if (visualSummary.scenes.some((scene) => !visualConfirmedScenes.has(scene.sampleId))) return;
    setVisualProofSaving(true);
    try {
      const proof = await window.hanengine.createVisualReviewProof(visualReportPath, [...visualConfirmedScenes]);
      setVisualReviewProof(proof);
      setVisualStatus("passed");
      appendLog(`人工复核证明已保存：${proof.proofPath}`);
    } catch (error) {
      appendLog(`人工复核证明保存失败：${String(error)}`);
    } finally {
      setVisualProofSaving(false);
    }
  }

  async function loadVisualReport(reportPath: string) {
    try {
      const summary = await window.hanengine.readVisualReport(reportPath);
      setVisualSummary(summary);
      const proof = await window.hanengine.readVisualReviewProof(reportPath);
      setVisualReviewProof(proof);
      setVisualConfirmedScenes(proof ? new Set(summary.scenes.map((scene) => scene.sampleId)) : new Set());
      const nextStatus = summary.decision === "blocked" ? "blocked" : proof ? "passed" : "review";
      setVisualStatus(nextStatus);
      if (nextStatus !== "blocked" && summary.scenes[0]) await selectVisualScene(summary.scenes[0].sampleId, reportPath);
    } catch (error) {
      setVisualStatus("failed");
      appendLog(`视觉报告读取失败：${String(error)}`);
    }
  }

  async function runVisualVerification() {
    if (!visualManifestPath || !visualReportPath || running) return;
    setVisualStatus("checking");
    setVisualSummary(null);
    setVisualReviewProof(null);
    setVisualProofSaving(false);
    setVisualSceneId("");
    setVisualImagePair(null);
    setVisualConfirmedScenes(new Set());
    const result = await runPython(
      [
        "visual", "verify", "--manifest", visualManifestPath, "--output", visualReportPath,
        "--authorized", "--authorization-reference", "client-owner-authorized-visual-check",
        "--zhipu-model", "glm-4.6v", "--zhipu-timeout", "180",
        "--ocr-language", "chi_sim+eng", "--ocr-provider", "rapidocr",
      ],
      "视觉验收",
    );
    if (!result) {
      setVisualStatus("failed");
      return;
    }
    if (!result.stdout.includes("Report:")) {
      setVisualStatus("failed");
      return;
    }
    await loadVisualReport(visualReportPath);
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
    setRows((current) => current.map((row) => row.id === selectedId ? { ...row, target: value, status: rowStatus(row.source, value) } : row));
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
    { id: "visual" as View, label: "视觉验收", icon: <ScanSearch size={16} /> },
    { id: "tasks" as View, label: "任务中心", icon: <ListChecks size={16} /> },
  ];
  const visibleNavItems = mode === "normal"
    ? navItems.filter((item) => item.id === "workspace" || item.id === "visual" || item.id === "tasks")
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
        <div className="title-actions"><button className="icon-button no-drag" title="刷新项目" onClick={() => projectPath && openProject()}><RefreshCw size={16} /></button><button className="icon-button no-drag" title="启动游戏" onClick={() => void launchSelectedGame()}><Play size={16} /></button><button className="icon-button no-drag" title="设置" onClick={() => setSettingsOpen(true)}><Settings2 size={16} /></button><span className="account-chip no-drag"><CircleUserRound size={15} /><span>{currentUser.display_name || currentUser.username}</span></span><button className="icon-button no-drag" title="退出登录" onClick={() => void logout()}><LogOut size={16} /></button></div>
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
            <div className="stats-strip"><div><span>总条目</span><strong>{rows.length.toLocaleString()}</strong></div><div><span>已完成</span><strong className="success-text">{translatedCount.toLocaleString()}</strong></div><div><span>待翻译</span><strong className="warning-text">{pendingCount.toLocaleString()}</strong></div><div><span>需检查</span><strong className="warning-text">{warningCount.toLocaleString()}</strong></div><div className="stats-spacer" /><div className="file-context"><FileJson2 size={14} /><span>{catalogPath ? basename(catalogPath) : "提取或打开 catalog JSON 后显示翻译条目"}</span></div></div>
            <div className="filter-bar"><div className="search-box"><Search size={15} /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="搜索 ID、上下文或文本" /></div><button className={`filter-button ${reviewOnly ? "active" : ""}`} onClick={() => setReviewOnly((value) => !value)}><CircleAlert size={14} />仅看待检查</button></div>
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
          {view === "visual" && <VisualVerificationView
            manifestPath={visualManifestPath}
            reportPath={visualReportPath}
            status={visualStatus}
            summary={visualSummary}
            reviewProof={visualReviewProof}
            proofSaving={visualProofSaving}
            selectedSceneId={visualSceneId}
            imagePair={visualImagePair}
            imageLoading={visualImageLoading}
            confirmedScenes={visualConfirmedScenes}
            running={running}
            onChooseManifest={chooseVisualManifest}
            onChooseReport={chooseVisualReport}
            onOpenReport={() => void openVisualReport()}
            onRun={runVisualVerification}
            onSelectScene={(sampleId) => void selectVisualScene(sampleId)}
            onConfirmScene={toggleVisualSceneConfirmation}
            onCompleteReview={() => void completeVisualReview()}
          />}
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
      {settingsOpen && <ClientSettingsDialog
        language={gameLanguage}
        executablePath={gameExecutablePath}
        onClose={() => setSettingsOpen(false)}
        onLanguageChange={updateGameLanguage}
        onChooseExecutable={() => void chooseGameExecutable()}
        onLaunch={() => void launchSelectedGame()}
      />}
    </div>
  );
}

function ClientSettingsDialog({
  language,
  executablePath,
  onClose,
  onLanguageChange,
  onChooseExecutable,
  onLaunch,
}: {
  language: GameLanguage;
  executablePath: string;
  onClose: () => void;
  onLanguageChange: (value: GameLanguage) => void;
  onChooseExecutable: () => void;
  onLaunch: () => void;
}) {
  return <div className="settings-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="settings-dialog" role="dialog" aria-modal="true" aria-label="客户端设置" onMouseDown={(event) => event.stopPropagation()}>
      <div className="settings-heading"><div><span className="eyebrow">HanEngine</span><h2>客户端设置</h2></div><button className="icon-button" title="关闭" onClick={onClose}><X size={17} /></button></div>
      <div className="settings-field"><span>启动语言</span><div className="settings-segment" role="radiogroup" aria-label="启动语言"><button className={language === "zh-CN" ? "active" : ""} role="radio" aria-checked={language === "zh-CN"} onClick={() => onLanguageChange("zh-CN")}>简体中文</button><button className={language === "source" ? "active" : ""} role="radio" aria-checked={language === "source"} onClick={() => onLanguageChange("source")}>原文</button></div></div>
      <div className="settings-field"><span>游戏启动程序</span><div className="settings-path"><input value={executablePath} readOnly placeholder="尚未选择" /><button className="secondary-button" onClick={onChooseExecutable}>浏览</button></div></div>
      <div className="settings-actions"><button className="secondary-button" onClick={onClose}>关闭</button><button className="primary-button" onClick={onLaunch} disabled={!executablePath}><Play size={15} />启动游戏</button></div>
    </section>
  </div>;
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

function VisualVerificationView({
  manifestPath, reportPath, status, summary, reviewProof, proofSaving, selectedSceneId, imagePair, imageLoading,
  confirmedScenes, running, onChooseManifest, onChooseReport, onRun, onSelectScene,
  onOpenReport, onConfirmScene, onCompleteReview,
}: {
  manifestPath: string;
  reportPath: string;
  status: "idle" | "checking" | "passed" | "blocked" | "review" | "failed";
  summary: VisualReportSummary | null;
  reviewProof: VisualReviewProof | null;
  proofSaving: boolean;
  selectedSceneId: string;
  imagePair: VisualImagePair | null;
  imageLoading: boolean;
  confirmedScenes: Set<string>;
  running: boolean;
  onChooseManifest: () => void;
  onChooseReport: () => void;
  onOpenReport: () => void;
  onRun: () => void;
  onSelectScene: (sampleId: string) => void;
  onConfirmScene: (sampleId: string, confirmed: boolean) => void;
  onCompleteReview: () => void;
}) {
  const stateCopy = {
    idle: ["等待检查", "选择视觉证据清单和报告输出位置。"],
    checking: ["检查中", "正在运行本地 OCR、硬门禁和 GLM 视觉判官。"],
    passed: ["已通过", "确定性硬门禁与人工复核均已确认无阻断问题。"],
    blocked: ["已阻断", "硬门禁发现不可自动放行的问题，请先修复并重新验收。"],
    review: ["人工复核", "硬门禁未发现问题；GLM 结果仅作辅助，请由人工查看截图与报告。"],
    failed: ["执行失败", "未能生成或读取有效报告，请查看任务日志。"],
  }[status];
  const selectedIndex = summary?.scenes.findIndex((scene) => scene.sampleId === selectedSceneId) ?? -1;
  const reviewComplete = Boolean(summary?.scenes.length) && summary!.scenes.every((scene) => confirmedScenes.has(scene.sampleId));
  return <section className="operation-view visual-view">
    <div className="operation-heading"><div><span className="eyebrow">HanEngine / 发布前检查</span><h2>视觉验收</h2><p>客户端统一管理验收入口；游戏内不增加语言菜单。Key 仅由本机 Python 进程从环境变量读取。</p></div><button className="primary-button" onClick={onRun} disabled={!manifestPath || !reportPath || running}>{status === "checking" ? <LoaderCircle size={15} className="spin" /> : <ScanSearch size={15} />}{status === "checking" ? "检查中" : "开始验收"}</button></div>
    <div className="visual-controls">
      <PathField label="证据清单" value={manifestPath} onPick={onChooseManifest} />
      <PathField label="报告输出" value={reportPath} onPick={onChooseReport} />
      <button className="secondary-button" onClick={onOpenReport}><FolderOpen size={15} />打开已有报告</button>
      <div className="visual-settings"><span>视觉模型</span><strong>GLM-4.6V</strong><span>本地 OCR</span><strong>RapidOCR · chi_sim+eng</strong></div>
    </div>
    <div className={`visual-state ${status}`}><div className="visual-state-heading"><span className="visual-state-icon">{status === "checking" ? <LoaderCircle size={18} className="spin" /> : status === "passed" ? <CircleCheck size={18} /> : status === "blocked" || status === "failed" ? <ShieldAlert size={18} /> : <CircleAlert size={18} />}</span><div><strong>{stateCopy[0]}</strong><span>{stateCopy[1]}</span></div></div>{summary && <div className="visual-summary"><span>硬门禁 <b>{summary.hardGatePassedCount}/{summary.hardGateCount}</b></span><span>判官 <b>{summary.judgeModels.join("、") || "未运行"}</b></span><span>问题 <b>{summary.issues.length}</b></span>{reviewProof && <span title={reviewProof.proofPath}>人工证明 <b>{reviewProof.reviewer.display_name}</b></span>}</div>}</div>
    {summary && (summary.issues.length > 0 || summary.reasons.length > 0) && <div className="visual-findings"><strong>报告摘要</strong><ul>{[...summary.issues, ...summary.reasons].slice(0, 8).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
    {summary && status !== "blocked" && status !== "failed" && summary.scenes.length > 0 && <div className="visual-review">
      <div className="visual-review-toolbar">
        <div><strong>逐场景人工复核</strong><span>{confirmedScenes.size}/{summary.scenes.length} 已确认</span></div>
        <div className="visual-review-nav">
          <button className="icon-button" title="上一个场景" disabled={selectedIndex <= 0} onClick={() => onSelectScene(summary.scenes[selectedIndex - 1].sampleId)}><ChevronLeft size={16} /></button>
          <select aria-label="复核场景" value={selectedSceneId} onChange={(event) => onSelectScene(event.target.value)}>{summary.scenes.map((scene) => <option key={scene.sampleId} value={scene.sampleId}>{scene.sampleId}</option>)}</select>
          <button className="icon-button" title="下一个场景" disabled={selectedIndex < 0 || selectedIndex >= summary.scenes.length - 1} onClick={() => onSelectScene(summary.scenes[selectedIndex + 1].sampleId)}><ChevronRight size={16} /></button>
        </div>
      </div>
      <div className="visual-pair">
        <figure><figcaption>原文参考</figcaption>{imagePair?.sampleId === selectedSceneId ? <img src={imagePair.referenceDataUrl} alt={`${selectedSceneId} 原文参考`} /> : <div className="visual-image-loading">{imageLoading ? <LoaderCircle size={18} className="spin" /> : <CircleAlert size={18} />}</div>}</figure>
        <figure><figcaption>中文候选</figcaption>{imagePair?.sampleId === selectedSceneId ? <img src={imagePair.candidateDataUrl} alt={`${selectedSceneId} 中文候选`} /> : <div className="visual-image-loading">{imageLoading ? <LoaderCircle size={18} className="spin" /> : <CircleAlert size={18} />}</div>}</figure>
      </div>
      <div className="visual-review-actions">
        <label><input type="checkbox" checked={confirmedScenes.has(selectedSceneId)} disabled={Boolean(reviewProof) || proofSaving || !selectedSceneId || imagePair?.sampleId !== selectedSceneId} onChange={(event) => onConfirmScene(selectedSceneId, event.target.checked)} /><span>{reviewProof ? "该场景已写入人工复核证明" : "已检查该场景，未发现阻断发布的问题"}</span></label>
        {status === "review" && <button className="primary-button" disabled={!reviewComplete || proofSaving} onClick={onCompleteReview}>{proofSaving ? <LoaderCircle size={15} className="spin" /> : <ShieldCheck size={15} />}{proofSaving ? "保存证明中" : "确认人工验收"}</button>}
      </div>
    </div>}
  </section>;
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
      <div><strong>{ready ? "可以执行一键汉化" : "当前项目仅允许检测"}</strong><span>{ready ? `HanGuard 已允许：${capability.filter((item) => item !== "detect").join("、") || "结构化构建"}` : (candidate?.limitations?.join("；") || "适配器能力或 HanGuard 路由不足，已禁用提取和构建。")}</span>{candidate?.capability_matrix && <small className="capability-matrix-summary">{capabilityMatrixLabel(candidate.capability_matrix)}</small>}</div>
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
