function normalizeAuthStatus(status) {
  return {
    authenticated: false,
    needsSetup: Boolean(status.needsSetup ?? status.needs_setup),
    userCount: status.userCount ?? status.user_count,
    user: null,
  };
}

module.exports = { normalizeAuthStatus };
