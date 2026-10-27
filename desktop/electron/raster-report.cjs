const fs = require("node:fs/promises");
const path = require("node:path");

const MANIFEST_SCHEMA = "hanengine.raster-manifest/v1";
const VERIFICATION_SCHEMA = "hanengine.raster-verification-report/v1";
const MAX_FILE_BYTES = 4 * 1024 * 1024;
const MAX_ASSETS = 5000;
const MAX_TEXT = 1000;
const STATUSES = new Set(["detected", "translated", "approved", "manual_review"]);
const KINDS = new Set(["image", "video"]);

function object(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name} 必须是对象`);
  return value;
}

function text(value, name, maximum = MAX_TEXT) {
  if (typeof value !== "string") throw new Error(`${name} 无效`);
  return value.slice(0, maximum);
}

function statusCounts(segments) {
  const counts = { detected: 0, translated: 0, approved: 0, manual_review: 0, other: 0 };
  for (const segment of segments) {
    if (STATUSES.has(segment.status)) counts[segment.status] += 1;
    else counts.other += 1;
  }
  return counts;
}

async function readRasterManifest(filePath) {
  const resolved = path.resolve(filePath);
  const stat = await fs.stat(resolved).catch(() => null);
  if (!stat || !stat.isFile()) throw new Error("栅格清单文件不存在");
  if (stat.size > MAX_FILE_BYTES) throw new Error("栅格清单超过 4MB 大小限制");
  const payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  const manifest = object(payload, "栅格清单");
  if (manifest.schema_version !== MANIFEST_SCHEMA) throw new Error("栅格清单 schema 版本不受支持");
  if (!Array.isArray(manifest.assets)) throw new Error("栅格清单 assets 必须是数组");
  if (manifest.assets.length > MAX_ASSETS) throw new Error("栅格清单资产超过上限");
  const totals = { detected: 0, translated: 0, approved: 0, manual_review: 0, other: 0 };
  const assets = manifest.assets.map((value, index) => {
    const asset = object(value, `assets[${index}]`);
    const kind = KINDS.has(asset.kind) ? asset.kind : "image";
    const segments = Array.isArray(asset.segments) ? asset.segments : [];
    const counts = statusCounts(
      segments.map((segment, sIndex) => ({
        status: object(segment, `assets[${index}].segments[${sIndex}]`).status,
      })),
    );
    for (const key of Object.keys(totals)) totals[key] += counts[key];
    return {
      relativePath: text(asset.relative_path, `assets[${index}].relative_path`),
      kind,
      segmentCount: segments.length,
      statusCounts: counts,
      approved: counts.approved > 0 && counts.detected === 0 && counts.manual_review === 0,
      localizedArtifactPath: typeof asset.localized_artifact_path === "string" ? asset.localized_artifact_path : "",
      reviewReason: typeof asset.review_reason === "string" ? asset.review_reason.slice(0, 300) : "",
    };
  });
  return {
    kind: "raster-manifest",
    manifestPath: resolved,
    sourceLanguage: typeof manifest.source_language === "string" ? manifest.source_language : "en",
    targetLanguage: typeof manifest.target_language === "string" ? manifest.target_language : "zh-CN",
    summary: {
      assetCount: assets.length,
      imageCount: assets.filter((asset) => asset.kind === "image").length,
      videoCount: assets.filter((asset) => asset.kind === "video").length,
      totals,
    },
    assets,
  };
}

async function readRasterVerificationReport(filePath) {
  const resolved = path.resolve(filePath);
  const payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  const report = object(payload, "栅格验证报告");
  if (report.schema_version !== VERIFICATION_SCHEMA) throw new Error("栅格验证报告 schema 版本不受支持");
  const issues = Array.isArray(report.issues)
    ? report.issues.slice(0, 50).map((value, index) => {
        const issue = object(value, `issues[${index}]`);
        return {
          code: text(issue.code, `issues[${index}].code`, 120),
          message: text(issue.message, `issues[${index}].message`, 500),
        };
      })
    : [];
  return {
    kind: "raster-verification",
    reportPath: resolved,
    passed: report.passed === true,
    artifactCount: Array.isArray(report.artifact_hashes) ? report.artifact_hashes.length : 0,
    issues,
  };
}

module.exports = { readRasterManifest, readRasterVerificationReport };
