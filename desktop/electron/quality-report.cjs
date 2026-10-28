const fs = require("node:fs/promises");
const path = require("node:path");

const REPORT_SCHEMA = "hanengine.quality-report/v1";
const STATUSES = new Set(["passed", "review_required", "failed"]);
const MAX_REPORT_BYTES = 2 * 1024 * 1024;
const MAX_ISSUES = 50;

function object(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name} 必须是对象`);
  return value;
}

function text(value, name, maximum = 500) {
  if (typeof value !== "string" || !value || value.length > maximum || [...value].some((character) => character.charCodeAt(0) < 32)) {
    throw new Error(`${name} 无效`);
  }
  return value;
}

function nullableText(value, name, maximum = 500) {
  if (value === null) return null;
  return text(value, name, maximum);
}

function count(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${name} 必须是非负整数`);
  return value;
}

function strings(value, name) {
  if (!Array.isArray(value)) throw new Error(`${name} 必须是字符串数组`);
  return value.map((item, index) => text(item, `${name}[${index}]`)).slice(0, MAX_ISSUES);
}

function summarizeIssue(value, name) {
  const issue = object(value, name);
  if (typeof issue.automatically_recoverable !== "boolean") throw new Error(`${name}.automatically_recoverable 无效`);
  return {
    code: text(issue.code, `${name}.code`, 120),
    severity: text(issue.severity, `${name}.severity`, 32),
    segmentId: nullableText(issue.segment_id, `${name}.segment_id`, 300),
    relativePath: nullableText(issue.relative_path, `${name}.relative_path`, 600),
    message: text(issue.message, `${name}.message`),
    automaticallyRecoverable: issue.automatically_recoverable,
    suggestedAction: nullableText(issue.suggested_action, `${name}.suggested_action`),
  };
}

function summarizeIssues(value, name) {
  if (!Array.isArray(value)) throw new Error(`${name} 必须是数组`);
  return value.slice(0, MAX_ISSUES).map((item, index) => summarizeIssue(item, `${name}[${index}]`));
}

function summarizeQualityReport(payload, reportPath = "") {
  const report = object(payload, "质量报告");
  if (report.schema_version !== REPORT_SCHEMA) throw new Error("质量报告版本不受支持");
  if (!STATUSES.has(report.status)) throw new Error("质量报告状态无效");

  const summary = object(report.summary, "质量报告 summary");
  const review = object(report.review, "质量报告 review");
  const validation = object(report.validation, "质量报告 validation");
  const verification = object(report.verification, "质量报告 verification");
  if (typeof review.required !== "boolean") throw new Error("质量报告 review.required 无效");
  if (validation.valid !== null && typeof validation.valid !== "boolean") throw new Error("质量报告 validation.valid 无效");
  if (verification.passed !== null && typeof verification.passed !== "boolean") throw new Error("质量报告 verification.passed 无效");

  return {
    reportPath,
    status: report.status,
    engineId: text(report.engine_id, "质量报告 engine_id", 120),
    sourceLanguage: text(report.source_language, "质量报告 source_language", 64),
    targetLanguage: text(report.target_language, "质量报告 target_language", 64),
    summary: {
      segmentCount: count(summary.segment_count, "summary.segment_count"),
      translatedCount: count(summary.translated_count, "summary.translated_count"),
      resumedCount: count(summary.resumed_count, "summary.resumed_count"),
      untranslatedCount: count(summary.untranslated_count, "summary.untranslated_count"),
      unhandledCount: count(summary.unhandled_count, "summary.unhandled_count"),
      validationIssueCount: count(summary.validation_issue_count, "summary.validation_issue_count"),
      validationBlockingCount: count(summary.validation_blocking_count, "summary.validation_blocking_count"),
      validationWarningCount: count(summary.validation_warning_count, "summary.validation_warning_count"),
      verificationIssueCount: count(summary.verification_issue_count, "summary.verification_issue_count"),
    },
    validationPassed: validation.valid,
    verificationPassed: verification.passed,
    review: { required: review.required, reasons: strings(review.reasons, "review.reasons") },
    issues: [
      ...summarizeIssues(validation.issues, "validation.issues"),
      ...summarizeIssues(verification.issues, "verification.issues"),
    ].slice(0, MAX_ISSUES),
  };
}

async function readQualityReport(filePath) {
  if (typeof filePath !== "string" || !filePath.trim()) throw new TypeError("质量报告路径不能为空");
  const resolved = path.resolve(filePath);
  if (path.extname(resolved).toLowerCase() !== ".json") throw new Error("质量报告必须是 JSON 文件");
  const details = await fs.lstat(resolved);
  if (!details.isFile() || details.isSymbolicLink() || details.size > MAX_REPORT_BYTES) throw new Error("质量报告文件无效或过大");
  const payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  return summarizeQualityReport(payload, resolved);
}

module.exports = { readQualityReport, summarizeQualityReport };
