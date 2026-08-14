const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hanengine", {
  authStatus: () => ipcRenderer.invoke("auth:status"),
  register: (credentials) => ipcRenderer.invoke("auth:register", credentials),
  login: (credentials) => ipcRenderer.invoke("auth:login", credentials),
  logout: () => ipcRenderer.invoke("auth:logout"),
  selectFile: (options = {}) => ipcRenderer.invoke("dialog:select-file", options),
  selectDirectory: (options = {}) => ipcRenderer.invoke("dialog:select-directory", options),
  saveFile: (options = {}) => ipcRenderer.invoke("dialog:save-file", options),
  launchGame: (executablePath, language) => ipcRenderer.invoke("game:launch", executablePath, language),
  scanProject: (rootPath) => ipcRenderer.invoke("project:scan", rootPath),
  readCatalog: (filePath) => ipcRenderer.invoke("catalog:read", filePath),
  writeCatalog: (filePath, updates) => ipcRenderer.invoke("catalog:write", filePath, updates),
  readVisualReport: (filePath) => ipcRenderer.invoke("visual:read-report", filePath),
  readVisualImagePair: (filePath, sampleId) => ipcRenderer.invoke("visual:read-image-pair", filePath, sampleId),
  readVisualReviewProof: (filePath) => ipcRenderer.invoke("visual:read-review-proof", filePath),
  createVisualReviewProof: (filePath, confirmedSampleIds) => ipcRenderer.invoke("visual:create-review-proof", filePath, confirmedSampleIds),
  runPython: (taskId, args) => ipcRenderer.invoke("python:run", taskId, args),
  listTasks: (stateRoot) => ipcRenderer.invoke("tasks:list", stateRoot),
  showTask: (taskId, stateRoot) => ipcRenderer.invoke("tasks:show", taskId, stateRoot),
  retryTask: (taskId, stateRoot) => ipcRenderer.invoke("tasks:retry", taskId, stateRoot),
  cancelTask: (taskId, stateRoot) => ipcRenderer.invoke("tasks:cancel", taskId, stateRoot),
  cancelPython: (taskId) => ipcRenderer.invoke("python:cancel", taskId),
  onPythonEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("python:event", listener);
    return () => ipcRenderer.removeListener("python:event", listener);
  },
});
