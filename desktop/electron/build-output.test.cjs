const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("built renderer assets use paths compatible with Electron loadFile", () => {
  const config = fs.readFileSync(path.resolve(__dirname, "..", "vite.config.ts"), "utf8");

  assert.match(config, /\bbase:\s*["']\.\/["']/);
});
