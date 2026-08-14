const assert = require("node:assert/strict");
const test = require("node:test");

const { normalizeAuthStatus } = require("./auth-status.cjs");

test("maps Python snake-case auth status for the renderer", () => {
  assert.deepEqual(normalizeAuthStatus({ needs_setup: true, user_count: 0 }), {
    authenticated: false,
    needsSetup: true,
    userCount: 0,
    user: null,
  });
});
