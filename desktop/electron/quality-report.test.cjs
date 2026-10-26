const assert = require("node:assert/strict");
const test = require("node:test");

const { summarizeQualityReport } = require("./quality-report.cjs");

function report(status = "passed") {
  return {
    schema_version: "hanengine.quality-report/v1",
    status,
    engine_id: "godot",
    source_language: "en",
    target_language: "zh-CN",
    summary: {
      segment_count: 12,
      translated_count: 10,
      resumed_count: 2,
      untranslated_count: 0,
      unhandled_count: 1,
      validation_issue_count: 0,
      validation_blocking_count: 0,
      validation_warning_count: 0,
      verification_issue_count: 0,
    },
    review: { required: false, reasons: [] },
    validation: { valid: true, issues: [] },
    verification: { passed: true, issues: [] },
  };
}

test("returns only the quality information needed by the renderer", () => {
  const payload = report();
  payload.project_fingerprint = "must not be exposed";
  const summary = summarizeQualityReport(payload, "C:\\candidate.quality.json");

  assert.deepEqual(summary, {
    reportPath: "C:\\candidate.quality.json",
    status: "passed",
    engineId: "godot",
    sourceLanguage: "en",
    targetLanguage: "zh-CN",
    summary: {
      segmentCount: 12,
      translatedCount: 10,
      resumedCount: 2,
      untranslatedCount: 0,
      unhandledCount: 1,
      validationIssueCount: 0,
      validationBlockingCount: 0,
      validationWarningCount: 0,
      verificationIssueCount: 0,
    },
    validationPassed: true,
    verificationPassed: true,
    review: { required: false, reasons: [] },
    issues: [],
  });
});

test("keeps failed validation issues and their suggested action", () => {
  const payload = report("failed");
  payload.summary.untranslated_count = 1;
  payload.summary.validation_issue_count = 1;
  payload.summary.validation_blocking_count = 1;
  payload.review = { required: true, reasons: ["translation_incomplete"] };
  payload.validation = {
    valid: false,
    issues: [{
      code: "missing_target_text",
      severity: "error",
      segment_id: "segment-7",
      relative_path: "dialogue.json",
      message: "缺少译文",
      automatically_recoverable: false,
      suggested_action: "补充译文后重新构建",
    }],
  };

  const summary = summarizeQualityReport(payload);

  assert.equal(summary.status, "failed");
  assert.deepEqual(summary.review.reasons, ["translation_incomplete"]);
  assert.deepEqual(summary.issues, [{
    code: "missing_target_text",
    severity: "error",
    segmentId: "segment-7",
    relativePath: "dialogue.json",
    message: "缺少译文",
    automaticallyRecoverable: false,
    suggestedAction: "补充译文后重新构建",
  }]);
});

test("rejects unsupported reports and malformed counts", () => {
  const unsupported = report();
  unsupported.schema_version = "other";
  assert.throws(() => summarizeQualityReport(unsupported), /版本不受支持/);

  const malformed = report();
  malformed.summary.translated_count = -1;
  assert.throws(() => summarizeQualityReport(malformed), /translated_count/);
});
