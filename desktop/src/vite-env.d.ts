/// <reference types="vite/client" />

type ProjectNode = {
  name: string;
  relativePath: string;
  type: "directory" | "file";
  extension?: string;
  children?: ProjectNode[];
};

type TranslationRow = {
  id: string;
  context: string;
  source: string;
  target: string;
  status: "translated" | "pending" | "draft" | "warning";
  locator?: Record<string, unknown>;
};

type GameLanguage = "zh-CN" | "source";

type CatalogPayload = {
  kind: "catalog" | "dictionary";
  metadata: { engine: string; sourceLanguage: string; targetLanguage: string; fileCount: number };
  rows: TranslationRow[];
};

type DetectionCandidate = {
  engine_id: string;
  display_name: string;
  score: number;
  capability?: string | string[];
  maturity?: string;
  limitations?: string[];
  evidence?: Array<Record<string, unknown>>;
  capability_matrix?: CapabilityMatrix;
};

type CapabilityMatrix = {
  schema_version: "hanengine.adapter-capabilities/v1";
  capabilities: Array<{
    capability: "native_text_replace" | "dynamic_text" | "raster_text" | "detect_only";
    status: "implemented" | "verified" | "detect_only" | "unsupported";
    reason: string;
    evidence: string[];
  }>;
};

type DetectionReport = {
  status: string;
  selected_engine: string | null;
  candidates?: DetectionCandidate[];
  candidate?: DetectionCandidate;
  capabilities?: string[];
  capability_matrix?: CapabilityMatrix;
  allowed_operations?: string[];
  hanguard?: Record<string, unknown> | null;
  task_id?: string;
  state_root?: string;
};

type TaskProgress = { completed: number; total: number | null; current_item: string | null };
type TaskArtifact = {
  artifact_id: string;
  kind: string;
  relative_path: string | null;
  sha256: string | null;
  metadata: Record<string, unknown>;
};
type TaskStatus = {
  project_id: string;
  project_name: string;
  source_root: string;
  task_id: string;
  kind: string;
  state: string;
  stage: string;
  engine_id: string | null;
  progress: TaskProgress | null;
  failure_reason: string | null;
  latest_checkpoint: Record<string, unknown> | null;
  artifacts: TaskArtifact[];
  retryable: boolean;
  retry: Record<string, unknown> | null;
  parent_task_id: string | null;
  cancel_requested_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  hanguard: Record<string, unknown> | null;
};

type PythonEvent = { taskId: string; channel?: "workflow" | "control"; type: string; text?: string; code?: number; args?: string[] };
type AuthUser = { user_id: string; username: string; display_name: string };
type AuthStatus = { authenticated: boolean; needsSetup: boolean; user: AuthUser | null; user_count?: number };
type AuthCredentials = { username: string; password: string; display_name?: string };
type VisualReportSummary = {
  decision: "pass" | "blocked" | "escalate";
  hardGatePassed: boolean;
  hardGatePassedCount: number;
  hardGateCount: number;
  judgeProvider: string | null;
  judgeModels: string[];
  reasons: string[];
  issues: string[];
  scenes: Array<{ sampleId: string; width: number; height: number }>;
};
type VisualImagePair = {
  sampleId: string;
  width: number;
  height: number;
  referenceDataUrl: string;
  candidateDataUrl: string;
};
type VisualReviewProof = {
  schemaVersion: "hanengine.visual-review-proof/v1";
  proofPath: string;
  reviewedAt: string;
  reviewer: AuthUser;
  reportSha256: string;
  sceneCount: number;
  decision: "pass";
};

interface Window {
  hanengine: {
    authStatus: () => Promise<AuthStatus>;
    register: (credentials: AuthCredentials) => Promise<AuthStatus>;
    login: (credentials: AuthCredentials) => Promise<AuthStatus>;
    logout: () => Promise<{ authenticated: false }>;
    selectFile: (options?: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>;
    selectDirectory: (options?: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>;
    saveFile: (options?: Record<string, unknown>) => Promise<{ canceled: boolean; filePath?: string }>;
    launchGame: (executablePath: string, language: string) => Promise<{ pid: number | null }>;
    scanProject: (rootPath: string) => Promise<ProjectNode[]>;
    readCatalog: (filePath: string) => Promise<CatalogPayload>;
    writeCatalog: (filePath: string, updates: TranslationRow[]) => Promise<{ updated: number; path: string }>;
    readVisualReport: (filePath: string) => Promise<VisualReportSummary>;
    readVisualImagePair: (filePath: string, sampleId: string) => Promise<VisualImagePair>;
    readVisualReviewProof: (filePath: string) => Promise<VisualReviewProof | null>;
    createVisualReviewProof: (filePath: string, confirmedSampleIds: string[]) => Promise<VisualReviewProof>;
    runPython: (taskId: string, args: string[]) => Promise<{ code: number; stdout: string; stderr: string }>;
    listTasks: (stateRoot?: string) => Promise<{ code: number; stdout: string; stderr: string }>;
    showTask: (taskId: string, stateRoot?: string) => Promise<{ code: number; stdout: string; stderr: string }>;
    retryTask: (taskId: string, stateRoot?: string) => Promise<{ code: number; stdout: string; stderr: string }>;
    cancelTask: (taskId: string, stateRoot?: string) => Promise<{ code: number; stdout: string; stderr: string }>;
    cancelPython: (taskId: string) => Promise<boolean>;
    onPythonEvent: (callback: (event: PythonEvent) => void) => () => void;
  };
}
