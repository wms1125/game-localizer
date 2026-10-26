const fs = require("node:fs/promises");

const REPORT_SCHEMA = "hanengine.translation-comparison/v1";
const MAX_REPORT_BYTES = 4 * 1024 * 1024;
const MAX_ENTRIES = 2000;
const MAX_TEXT = 2000;
const CATEGORIES = new Set(["match", "difference", "untranslated", "missing_target", "source_mismatch", "corrupt_output", "format_error", "candidate_only"]);
const SEVERITIES = new Set(["none", "review", "warning", "error"]);

function object(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name} 必须是对象`);
  return value;
}

function text(value, name, maximum = MAX_TEXT) {
  if (typeof value !== "string" || value.length > maximum) throw new Error(`${name} 无效`);
  return value;
}

function count(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${name} 必须是非负整数`);
  return value;
}

function summarizeEntry(value, index) {
  const entry = object(value, `entries[${index}]`);
  const segmentId = text(entry.segment_id, `entries[${index}].segment_id`, 200);
  const category = typeof entry.category === "string" && CATEGORIES.has(entry.category) ? entry.category : "difference";
  const severity = typeof entry.severity === "string" && SEVERITIES.has(entry.severity) ? entry.severity : "review";
  return {
    segmentId,
    tableName: typeof entry.table_name === "string" ? entry.table_name.slice(0, 120) : "",
    entryId: Number.isSafeInteger(entry.entry_id) ? entry.entry_id : null,
    sourceText: typeof entry.source_text === "string" ? entry.source_text.slice(0, MAX_TEXT) : "",
    officialZh: typeof entry.official_zh === "string" ? entry.official_zh.slice(0, MAX_TEXT) : "",
    candidateZh: typeof entry.candidate_zh === "string" ? entry.candidate_zh.slice(0, MAX_TEXT) : "",
    recommendedText: typeof entry.recommended_text === "string" ? entry.recommended_text.slice(0, MAX_TEXT) : "",
    category,
    severity,
    reasons: Array.isArray(entry.reasons)
      ? entry.reasons.filter((reason) => typeof reason === "string" && reason.length <= 120).slice(0, 10)
      : [],
  };
}

async function readComparisonReport(filePath) {
  const resolved = require("node:path").resolve(filePath);
  const stat = await fs.stat(resolved).catch(() => null);
  if (!stat || !stat.isFile()) throw new Error("对比报告文件不存在");
  if (stat.size > MAX_REPORT_BYTES) throw new Error("对比报告超过 4MB 大小限制");
  const payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  const report = object(payload, "对比报告");
  if (report.schema_version !== REPORT_SCHEMA) throw new Error("对比报告 schema 版本不受支持");
  if (!Array.isArray(report.entries)) throw new Error("对比报告 entries 必须是数组");
  if (report.entries.length > MAX_ENTRIES) throw new Error("对比报告条目超过上限");
  const entries = report.entries.map(summarizeEntry);
  const counts = {};
  for (const entry of entries) counts[entry.category] = (counts[entry.category] || 0) + 1;
  return {
    kind: "comparison",
    reportPath: resolved,
    engineId: typeof report.engine_id === "string" ? report.engine_id : "unity",
    projectFingerprint: typeof report.project_fingerprint === "string" ? report.project_fingerprint : "",
    summary: {
      entryCount: count(entries.length, "entry_count"),
      matchCount: count(counts.match || 0, "match_count"),
      differenceCount: count(counts.difference || 0, "difference_count"),
      untranslatedCount: count(counts.untranslated || 0, "untranslated_count"),
      missingTargetCount: count(counts.missing_target || 0, "missing_target_count"),
      categories: counts,
    },
    entries,
  };
}

module.exports = { readComparisonReport };
