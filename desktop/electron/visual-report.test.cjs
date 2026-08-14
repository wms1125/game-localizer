const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  createVisualReviewProof,
  readVisualImagePair,
  readVisualReviewProof,
  summarizeVisualReport,
} = require("./visual-report.cjs");

function report(decision = "pass") {
  return {
    schema_version: "hanengine.visual-evidence-report/v2",
    judge_provider: "zhipu-glm-4.6v",
    images: [{
      sample_id: "scene-01", reference_image: "reference.png", candidate_image: "candidate.png",
      reference_image_sha256: "a".repeat(64), candidate_image_sha256: "b".repeat(64), width: 960, height: 540,
    }],
    gate: {
      decision,
      hard_gate: { passed: decision !== "blocked", checks: [{ passed: true }, { passed: decision !== "blocked" }] },
      judge_results: [{ model: "glm-4.6v", issues: decision === "pass" ? [] : ["clipped: 标题被截断"] }],
      reasons: decision === "pass" ? [] : ["scene-01 needs review"],
    },
  };
}

test("returns only the client visual summary", () => {
  assert.deepEqual(summarizeVisualReport(report()), {
    decision: "pass", hardGatePassed: true, hardGatePassedCount: 2, hardGateCount: 2,
    judgeProvider: "zhipu-glm-4.6v", judgeModels: ["glm-4.6v"], reasons: [], issues: [],
    scenes: [{ sampleId: "scene-01", width: 960, height: 540 }],
  });
});

test("preserves blocked and review evidence", () => {
  assert.equal(summarizeVisualReport(report("blocked")).decision, "blocked");
  const review = summarizeVisualReport(report("escalate"));
  assert.equal(review.decision, "escalate");
  assert.deepEqual(review.issues, ["clipped: 标题被截断"]);
});

test("rejects unrecognized report shapes", () => {
  assert.throws(() => summarizeVisualReport({ schema_version: "other" }), /版本不受支持/);
  const invalid = report();
  invalid.gate.hard_gate.checks[0].passed = "yes";
  assert.throws(() => summarizeVisualReport(invalid), /检查状态无效/);
});

test("reads only hash-matched PNG evidence named by the report", async (context) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-visual-report-"));
  context.after(() => fs.rm(root, { recursive: true, force: true }));
  const reference = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("reference")]);
  const candidate = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("candidate")]);
  await Promise.all([
    fs.writeFile(path.join(root, "reference.png"), reference),
    fs.writeFile(path.join(root, "candidate.png"), candidate),
  ]);
  const payload = report("escalate");
  payload.images[0].reference_image_sha256 = crypto.createHash("sha256").update(reference).digest("hex");
  payload.images[0].candidate_image_sha256 = crypto.createHash("sha256").update(candidate).digest("hex");
  const reportPath = path.join(root, "report.json");
  await fs.writeFile(reportPath, JSON.stringify(payload));

  const pair = await readVisualImagePair(reportPath, "scene-01");

  assert.equal(pair.sampleId, "scene-01");
  assert.match(pair.referenceDataUrl, /^data:image\/png;base64,/);
  assert.match(pair.candidateDataUrl, /^data:image\/png;base64,/);
});

test("rejects unknown scenes, traversal, and tampered evidence", async (context) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-visual-report-"));
  context.after(() => fs.rm(root, { recursive: true, force: true }));
  const png = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("evidence")]);
  await Promise.all([
    fs.writeFile(path.join(root, "reference.png"), png),
    fs.writeFile(path.join(root, "candidate.png"), png),
  ]);
  const payload = report("escalate");
  const digest = crypto.createHash("sha256").update(png).digest("hex");
  payload.images[0].reference_image_sha256 = digest;
  payload.images[0].candidate_image_sha256 = digest;
  const reportPath = path.join(root, "report.json");
  await fs.writeFile(reportPath, JSON.stringify(payload));

  await assert.rejects(readVisualImagePair(reportPath, "missing"), /不存在/);
  payload.images[0].candidate_image = "../outside.png";
  await fs.writeFile(reportPath, JSON.stringify(payload));
  await assert.rejects(readVisualImagePair(reportPath, "scene-01"), /越界/);
  payload.images[0].candidate_image = "candidate.png";
  payload.images[0].candidate_image_sha256 = "c".repeat(64);
  await fs.writeFile(reportPath, JSON.stringify(payload));
  await assert.rejects(readVisualImagePair(reportPath, "scene-01"), /哈希不匹配/);
});

async function reviewFixture(context, decision = "escalate") {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-visual-review-"));
  context.after(() => fs.rm(root, { recursive: true, force: true }));
  const reference = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("review-reference")]);
  const candidate = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("review-candidate")]);
  await Promise.all([
    fs.writeFile(path.join(root, "reference.png"), reference),
    fs.writeFile(path.join(root, "candidate.png"), candidate),
  ]);
  const payload = report(decision);
  payload.images[0].reference_image_sha256 = crypto.createHash("sha256").update(reference).digest("hex");
  payload.images[0].candidate_image_sha256 = crypto.createHash("sha256").update(candidate).digest("hex");
  const reportPath = path.join(root, "report.json");
  await fs.writeFile(reportPath, JSON.stringify(payload));
  return { candidate, payload, reportPath };
}

const reviewer = { user_id: "user-01", username: "reviewer", display_name: "本地复核员" };

test("creates and restores a report-bound human review proof", async (context) => {
  const { reportPath } = await reviewFixture(context);

  const created = await createVisualReviewProof(reportPath, ["scene-01"], reviewer);
  const repeated = await createVisualReviewProof(
    reportPath,
    ["scene-01"],
    { user_id: "user-02", username: "other", display_name: "另一位复核员" },
  );
  const restored = await readVisualReviewProof(reportPath);

  assert.equal(created.schemaVersion, "hanengine.visual-review-proof/v1");
  assert.equal(created.decision, "pass");
  assert.equal(created.sceneCount, 1);
  assert.deepEqual(created.reviewer, reviewer);
  assert.deepEqual(repeated, created);
  assert.deepEqual(restored, created);
  assert.match(path.basename(created.proofPath), /^report\.human-review\.[0-9a-f]{64}\.json$/);
});

test("requires every scene and a passing hard gate before writing proof", async (context) => {
  const review = await reviewFixture(context);
  await assert.rejects(createVisualReviewProof(review.reportPath, [], reviewer), /全部场景/);
  assert.equal(await readVisualReviewProof(review.reportPath), null);

  const blocked = await reviewFixture(context, "blocked");
  await assert.rejects(createVisualReviewProof(blocked.reportPath, ["scene-01"], reviewer), /硬门禁未通过/);
  assert.equal(await readVisualReviewProof(blocked.reportPath), null);
});

test("does not reuse proof after report changes and rejects tampered images", async (context) => {
  const changed = await reviewFixture(context);
  await createVisualReviewProof(changed.reportPath, ["scene-01"], reviewer);
  changed.payload.gate.reasons.push("report changed");
  await fs.writeFile(changed.reportPath, JSON.stringify(changed.payload));
  assert.equal(await readVisualReviewProof(changed.reportPath), null);

  const tampered = await reviewFixture(context);
  await createVisualReviewProof(tampered.reportPath, ["scene-01"], reviewer);
  await fs.writeFile(path.join(path.dirname(tampered.reportPath), "candidate.png"), Buffer.concat([tampered.candidate, Buffer.from("tampered")]));
  await assert.rejects(readVisualReviewProof(tampered.reportPath), /哈希不匹配/);
});
