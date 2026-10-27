const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { readRasterManifest, readRasterVerificationReport } = require("./raster-report.cjs");

function manifest() {
  return {
    schema_version: "hanengine.raster-manifest/v1",
    source_language: "en",
    target_language: "zh-CN",
    assets: [
      {
        relative_path: "Assets/UI/title.png",
        kind: "image",
        source_sha256: "a".repeat(64),
        localized_artifact_path: null,
        localized_sha256: null,
        review_reason: null,
        segments: [
          { status: "approved" },
          { status: "approved" },
          { status: "detected" },
        ],
      },
      {
        relative_path: "Assets/Video/intro.mp4",
        kind: "video",
        source_sha256: "b".repeat(64),
        localized_artifact_path: "artifacts/intro.mp4",
        localized_sha256: "c".repeat(64),
        review_reason: "frame timing needs manual confirmation",
        segments: [{ status: "manual_review" }],
      },
    ],
  };
}

test("summarizes raster manifest assets and status totals", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-raster-"));
  const manifestPath = path.join(directory, "raster-manifest.json");
  await fs.writeFile(manifestPath, JSON.stringify(manifest()), "utf8");
  const summary = await readRasterManifest(manifestPath);
  assert.equal(summary.kind, "raster-manifest");
  assert.equal(summary.summary.assetCount, 2);
  assert.equal(summary.summary.imageCount, 1);
  assert.equal(summary.summary.videoCount, 1);
  assert.deepEqual(summary.summary.totals, { detected: 1, translated: 0, approved: 2, manual_review: 1, other: 0 });
  assert.equal(summary.assets[0].approved, false);
  assert.equal(summary.assets[1].reviewReason, "frame timing needs manual confirmation");
});

test("rejects unsupported manifest schema and missing files", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-raster-"));
  const bad = path.join(directory, "bad.json");
  await fs.writeFile(bad, JSON.stringify({ ...manifest(), schema_version: "other/v1" }), "utf8");
  await assert.rejects(() => readRasterManifest(bad), /schema/);
  await assert.rejects(() => readRasterManifest(path.join(directory, "missing.json")), /不存在/);
});

test("trims verification report to passed flag artifact count and issues", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-raster-"));
  const reportPath = path.join(directory, "verify.json");
  await fs.writeFile(
    reportPath,
    JSON.stringify({
      schema_version: "hanengine.raster-verification-report/v1",
      passed: false,
      artifact_hashes: ["a".repeat(64), "b".repeat(64)],
      issues: [{ code: "hash_mismatch", message: "candidate artifact hash differs" }],
    }),
    "utf8",
  );
  const summary = await readRasterVerificationReport(reportPath);
  assert.equal(summary.passed, false);
  assert.equal(summary.artifactCount, 2);
  assert.equal(summary.issues[0].code, "hash_mismatch");
});
