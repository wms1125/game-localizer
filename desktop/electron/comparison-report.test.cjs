const assert = require("node:assert/strict");
const test = require("node:test");

const { readComparisonReport } = require("./comparison-report.cjs");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

function report() {
  return {
    schema_version: "hanengine.translation-comparison/v1",
    engine_id: "unity",
    project_fingerprint: "f".repeat(64),
    entry_count: 3,
    entries: [
      {
        segment_id: "unity:1",
        table_name: "Menu Labels",
        entry_id: 1,
        source_text: "Play",
        official_zh: "开始",
        candidate_zh: "开始",
        category: "match",
        severity: "none",
        reasons: [],
      },
      {
        segment_id: "unity:2",
        table_name: "Item Labels",
        entry_id: 2,
        source_text: "Clownfish",
        official_zh: "小丑鱼",
        candidate_zh: "clown鱼",
        category: "difference",
        severity: "review",
        reasons: ["candidate_differs_from_official", "residual_english"],
        recommended_text: "小丑鱼",
      },
      {
        segment_id: "unity:3",
        table_name: "NPC Labels",
        entry_id: 3,
        source_text: "hello there",
        official_zh: "你好。",
        candidate_zh: null,
        category: "missing_target",
        severity: "error",
        reasons: ["missing_target_text"],
      },
    ],
  };
}

test("trims the comparison report to renderer-safe rows", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-comparison-"));
  const reportPath = path.join(directory, "comparison.json");
  await fs.writeFile(reportPath, JSON.stringify(report()), "utf8");
  const summary = await readComparisonReport(reportPath);
  assert.equal(summary.kind, "comparison");
  assert.equal(summary.engineId, "unity");
  assert.equal(summary.summary.entryCount, 3);
  assert.equal(summary.summary.matchCount, 1);
  assert.equal(summary.summary.differenceCount, 1);
  assert.equal(summary.summary.missingTargetCount, 1);
  assert.equal(summary.entries[1].segmentId, "unity:2");
  assert.equal(summary.entries[1].recommendedText, "小丑鱼");
  assert.deepEqual(summary.entries[1].reasons, ["candidate_differs_from_official", "residual_english"]);
});

test("rejects unsupported schemas and missing files", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-comparison-"));
  const bad = path.join(directory, "bad.json");
  await fs.writeFile(bad, JSON.stringify({ ...report(), schema_version: "other/v9" }), "utf8");
  await assert.rejects(() => readComparisonReport(bad), /schema/);
  await assert.rejects(() => readComparisonReport(path.join(directory, "missing.json")), /不存在/);
});

test("caps oversized text fields and drops unknown categories", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-comparison-"));
  const payload = report();
  payload.entries = [
    {
      segment_id: "unity:x",
      source_text: "x".repeat(5000),
      official_zh: "官",
      candidate_zh: "机",
      category: "mystery",
      severity: "bogus",
    },
  ];
  const reportPath = path.join(directory, "big.json");
  await fs.writeFile(reportPath, JSON.stringify(payload), "utf8");
  const summary = await readComparisonReport(reportPath);
  assert.equal(summary.entries[0].sourceText.length, 2000);
  assert.equal(summary.entries[0].category, "difference");
  assert.equal(summary.entries[0].severity, "review");
});
