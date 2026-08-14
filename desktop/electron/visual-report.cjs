const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const REPORT_SCHEMA = "hanengine.visual-evidence-report/v2";
const REVIEW_PROOF_SCHEMA = "hanengine.visual-review-proof/v1";
const DECISIONS = new Set(["pass", "blocked", "escalate"]);
const MAX_REPORT_BYTES = 10 * 1024 * 1024;
const MAX_PROOF_BYTES = 1024 * 1024;
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const REVIEWED_AT_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

function object(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name} 必须是对象`);
  return value;
}

function strings(value, name) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new Error(`${name} 必须是字符串数组`);
  return value;
}

function exactKeys(value, expected, name) {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new Error(`${name} 字段无效`);
  }
}

function text(value, name, maximum = 500) {
  if (typeof value !== "string" || !value || value.length > maximum || [...value].some((character) => character.charCodeAt(0) < 32)) {
    throw new Error(`${name} 无效`);
  }
  return value;
}

function imageEvidence(value, index) {
  const image = object(value, `images[${index}]`);
  const fields = ["sample_id", "reference_image", "candidate_image", "reference_image_sha256", "candidate_image_sha256"];
  for (const field of fields) {
    if (typeof image[field] !== "string" || !image[field]) throw new Error(`视觉报告 ${field} 无效`);
  }
  if (!SHA256_PATTERN.test(image.reference_image_sha256) || !SHA256_PATTERN.test(image.candidate_image_sha256)) {
    throw new Error("视觉报告图片哈希无效");
  }
  if (!Number.isInteger(image.width) || image.width < 1 || !Number.isInteger(image.height) || image.height < 1) {
    throw new Error("视觉报告图片尺寸无效");
  }
  return image;
}

function summarizeVisualReport(payload) {
  const report = object(payload, "视觉报告");
  if (report.schema_version !== REPORT_SCHEMA) throw new Error("视觉报告版本不受支持");
  const gate = object(report.gate, "gate");
  if (!DECISIONS.has(gate.decision)) throw new Error("视觉报告决策无效");
  const hardGate = object(gate.hard_gate, "gate.hard_gate");
  if (typeof hardGate.passed !== "boolean" || !Array.isArray(hardGate.checks)) throw new Error("视觉报告硬门禁无效");
  const hardGatePassedCount = hardGate.checks.reduce((count, item, index) => {
    const check = object(item, `gate.hard_gate.checks[${index}]`);
    if (typeof check.passed !== "boolean") throw new Error("视觉报告检查状态无效");
    return count + (check.passed ? 1 : 0);
  }, 0);
  if (!Array.isArray(gate.judge_results)) throw new Error("视觉报告判官结果无效");
  const judgeModels = [];
  const issues = [];
  for (const [index, item] of gate.judge_results.entries()) {
    const result = object(item, `gate.judge_results[${index}]`);
    if (typeof result.model !== "string" || !result.model) throw new Error("视觉报告模型名称无效");
    if (!judgeModels.includes(result.model)) judgeModels.push(result.model);
    for (const issue of strings(result.issues, `gate.judge_results[${index}].issues`)) {
      if (!issues.includes(issue)) issues.push(issue.slice(0, 500));
    }
  }
  if (report.judge_provider !== null && typeof report.judge_provider !== "string") throw new Error("视觉报告判官提供方无效");
  if (!Array.isArray(report.images) || !report.images.length) throw new Error("视觉报告场景无效");
  const scenes = report.images.map((item, index) => {
    const image = imageEvidence(item, index);
    return { sampleId: image.sample_id, width: image.width, height: image.height };
  });
  if (new Set(scenes.map((scene) => scene.sampleId)).size !== scenes.length) throw new Error("视觉报告场景 ID 重复");
  return {
    decision: gate.decision,
    hardGatePassed: hardGate.passed,
    hardGatePassedCount,
    hardGateCount: hardGate.checks.length,
    judgeProvider: report.judge_provider,
    judgeModels: judgeModels.slice(0, 10),
    reasons: strings(gate.reasons, "gate.reasons").map((reason) => reason.slice(0, 500)).slice(0, 50),
    issues: issues.slice(0, 50),
    scenes,
  };
}

async function loadVisualReport(filePath) {
  if (typeof filePath !== "string" || !filePath.trim()) throw new TypeError("报告路径不能为空");
  const resolved = path.resolve(filePath);
  if (path.extname(resolved).toLowerCase() !== ".json") throw new Error("视觉报告必须是 JSON 文件");
  const details = await fs.lstat(resolved);
  if (!details.isFile() || details.isSymbolicLink() || details.size > MAX_REPORT_BYTES) throw new Error("视觉报告文件无效或过大");
  const bytes = await fs.readFile(resolved);
  return {
    payload: JSON.parse(bytes.toString("utf8")),
    reportSha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    resolved,
  };
}

async function readVisualReport(filePath) {
  const { payload } = await loadVisualReport(filePath);
  return summarizeVisualReport(payload);
}

function resolveEvidencePath(root, relativePath) {
  if (typeof relativePath !== "string" || !relativePath || path.isAbsolute(relativePath)) throw new Error("视觉证据路径无效");
  const resolved = path.resolve(root, relativePath);
  const relation = path.relative(root, resolved);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) throw new Error("视觉证据路径越界");
  return resolved;
}

async function verifiedImageBytes(root, relativePath, expectedHash) {
  const resolved = resolveEvidencePath(root, relativePath);
  const realRoot = await fs.realpath(root);
  const realImage = await fs.realpath(resolved);
  const relation = path.relative(realRoot, realImage);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) throw new Error("视觉证据路径越界");
  const details = await fs.lstat(realImage);
  if (!details.isFile() || details.isSymbolicLink() || details.size > MAX_IMAGE_BYTES) throw new Error("视觉证据图片无效或过大");
  const bytes = await fs.readFile(realImage);
  if (!bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) throw new Error("视觉证据图片不是 PNG");
  if (crypto.createHash("sha256").update(bytes).digest("hex") !== expectedHash.toLowerCase()) throw new Error("视觉证据图片哈希不匹配");
  return bytes;
}

async function verifiedImageDataUrl(root, relativePath, expectedHash) {
  const bytes = await verifiedImageBytes(root, relativePath, expectedHash);
  return `data:image/png;base64,${bytes.toString("base64")}`;
}

async function readVisualImagePair(filePath, sampleId) {
  if (typeof sampleId !== "string" || !sampleId) throw new TypeError("场景 ID 不能为空");
  const { payload, resolved } = await loadVisualReport(filePath);
  summarizeVisualReport(payload);
  const image = payload.images.find((item, index) => imageEvidence(item, index).sample_id === sampleId);
  if (!image) throw new Error("视觉报告中不存在该场景");
  const root = path.dirname(resolved);
  const [referenceDataUrl, candidateDataUrl] = await Promise.all([
    verifiedImageDataUrl(root, image.reference_image, image.reference_image_sha256),
    verifiedImageDataUrl(root, image.candidate_image, image.candidate_image_sha256),
  ]);
  return { sampleId, width: image.width, height: image.height, referenceDataUrl, candidateDataUrl };
}

function reviewProofPath(reportPath, reportSha256) {
  const extension = path.extname(reportPath);
  const stem = path.basename(reportPath, extension);
  return path.join(path.dirname(reportPath), `${stem}.human-review.${reportSha256}.json`);
}

function reviewScene(image) {
  return {
    sample_id: image.sample_id,
    reference_image_sha256: image.reference_image_sha256.toLowerCase(),
    candidate_image_sha256: image.candidate_image_sha256.toLowerCase(),
    width: image.width,
    height: image.height,
  };
}

async function verifyAllImages(payload, reportPath) {
  const root = path.dirname(reportPath);
  for (const [index, item] of payload.images.entries()) {
    const image = imageEvidence(item, index);
    await Promise.all([
      verifiedImageBytes(root, image.reference_image, image.reference_image_sha256),
      verifiedImageBytes(root, image.candidate_image, image.candidate_image_sha256),
    ]);
  }
}

function reviewerIdentity(value) {
  const reviewer = object(value, "复核人");
  exactKeys(reviewer, ["user_id", "username", "display_name"], "复核人");
  return {
    user_id: text(reviewer.user_id, "复核人 ID", 128),
    username: text(reviewer.username, "复核人用户名", 64),
    display_name: text(reviewer.display_name, "复核人显示名称", 80),
  };
}

function summarizeReviewProof(payload, proofPath) {
  return {
    schemaVersion: payload.schema_version,
    proofPath,
    reviewedAt: payload.reviewed_at,
    reviewer: payload.reviewer,
    reportSha256: payload.report_sha256,
    sceneCount: payload.scenes.length,
    decision: payload.decision,
  };
}

function validateReviewProof(payload, proofPath, report, reportSha256) {
  const proof = object(payload, "人工复核证明");
  exactKeys(proof, ["schema_version", "reviewed_at", "decision", "report_sha256", "report_schema_version", "machine_decision", "reviewer", "scenes"], "人工复核证明");
  if (proof.schema_version !== REVIEW_PROOF_SCHEMA) throw new Error("人工复核证明版本不受支持");
  if (!REVIEWED_AT_PATTERN.test(proof.reviewed_at) || Number.isNaN(Date.parse(proof.reviewed_at))) throw new Error("人工复核时间无效");
  if (proof.decision !== "pass") throw new Error("人工复核结论无效");
  if (proof.report_sha256 !== reportSha256) throw new Error("人工复核证明与视觉报告不匹配");
  if (proof.report_schema_version !== REPORT_SCHEMA || proof.machine_decision !== report.gate.decision) {
    throw new Error("人工复核证明的机器报告信息无效");
  }
  const reviewer = reviewerIdentity(proof.reviewer);
  if (!Array.isArray(proof.scenes) || proof.scenes.length !== report.images.length) throw new Error("人工复核场景不完整");
  const expectedScenes = report.images.map((item, index) => reviewScene(imageEvidence(item, index)));
  const scenes = proof.scenes.map((item, index) => {
    const scene = object(item, `人工复核场景[${index}]`);
    exactKeys(scene, ["sample_id", "reference_image_sha256", "candidate_image_sha256", "width", "height"], `人工复核场景[${index}]`);
    return scene;
  });
  if (JSON.stringify(scenes) !== JSON.stringify(expectedScenes)) throw new Error("人工复核场景与视觉证据不匹配");
  return summarizeReviewProof({ ...proof, reviewer }, proofPath);
}

async function readVisualReviewProof(filePath) {
  const { payload: report, reportSha256, resolved } = await loadVisualReport(filePath);
  const summary = summarizeVisualReport(report);
  if (!summary.hardGatePassed || summary.hardGatePassedCount !== summary.hardGateCount || summary.decision === "blocked") return null;
  const proofPath = reviewProofPath(resolved, reportSha256);
  let details;
  try {
    details = await fs.lstat(proofPath);
  } catch (error) {
    if (error && error.code === "ENOENT") return null;
    throw error;
  }
  if (!details.isFile() || details.isSymbolicLink() || details.size > MAX_PROOF_BYTES) throw new Error("人工复核证明文件无效或过大");
  const proof = JSON.parse(await fs.readFile(proofPath, "utf8"));
  const result = validateReviewProof(proof, proofPath, report, reportSha256);
  await verifyAllImages(report, resolved);
  const current = await loadVisualReport(resolved);
  if (current.reportSha256 !== reportSha256) throw new Error("视觉报告在人工复核验证期间发生变化");
  return result;
}

async function createVisualReviewProof(filePath, confirmedSampleIds, reviewer) {
  if (!Array.isArray(confirmedSampleIds) || confirmedSampleIds.some((sampleId) => typeof sampleId !== "string" || !sampleId)) {
    throw new TypeError("已确认场景必须是非空字符串数组");
  }
  const { payload: report, reportSha256, resolved } = await loadVisualReport(filePath);
  const summary = summarizeVisualReport(report);
  if (!summary.hardGatePassed || summary.hardGatePassedCount !== summary.hardGateCount || summary.decision === "blocked") {
    throw new Error("硬门禁未通过，不能生成人工复核证明");
  }
  const expectedIds = report.images.map((item, index) => imageEvidence(item, index).sample_id);
  if (new Set(confirmedSampleIds).size !== confirmedSampleIds.length || expectedIds.length !== confirmedSampleIds.length || expectedIds.some((sampleId) => !confirmedSampleIds.includes(sampleId))) {
    throw new Error("必须确认视觉报告中的全部场景");
  }
  const identity = reviewerIdentity(reviewer);
  await verifyAllImages(report, resolved);
  const proofPath = reviewProofPath(resolved, reportSha256);
  try {
    const existing = await readVisualReviewProof(resolved);
    if (existing) return existing;
  } catch (error) {
    if (!error || error.code !== "ENOENT") throw error;
  }
  const proof = {
    schema_version: REVIEW_PROOF_SCHEMA,
    reviewed_at: new Date().toISOString(),
    decision: "pass",
    report_sha256: reportSha256,
    report_schema_version: REPORT_SCHEMA,
    machine_decision: summary.decision,
    reviewer: identity,
    scenes: report.images.map((item, index) => reviewScene(imageEvidence(item, index))),
  };
  const temporaryPath = `${proofPath}.tmp-${process.pid}-${crypto.randomBytes(6).toString("hex")}`;
  try {
    await fs.writeFile(temporaryPath, `${JSON.stringify(proof, null, 2)}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
    await fs.link(temporaryPath, proofPath);
    await fs.unlink(temporaryPath);
  } catch (error) {
    await fs.unlink(temporaryPath).catch(() => {});
    if (error && error.code === "EEXIST") {
      const concurrent = await readVisualReviewProof(resolved);
      if (concurrent) return concurrent;
      throw new Error("现有人工复核证明与视觉报告不匹配");
    }
    throw error;
  }
  const persisted = await readVisualReviewProof(resolved);
  if (!persisted) throw new Error("人工复核证明写入后未能通过校验");
  return persisted;
}

module.exports = {
  createVisualReviewProof,
  readVisualImagePair,
  readVisualReport,
  readVisualReviewProof,
  summarizeVisualReport,
};
