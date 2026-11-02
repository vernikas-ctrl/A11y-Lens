"""Shared test setup.

`app.main` validates configuration at import, so the environment has to be
populated before any test module imports it. conftest.py is imported before
test modules, which makes this the right place.

These values are fake and exist only so the app can start. The real ones live
in backend/.env, which is git-ignored and deliberately not read here -- a test
suite that depends on a developer's personal .env passes or fails for reasons
that have nothing to do with the code.
"""

import os

TEST_ENVIRONMENT = {
    "ANTHROPIC_API_KEY": "sk-ant-not-a-real-key-for-tests-only",
    "ACCESS_CODE": "test-access-code-not-secret",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "SCAN_TIMEOUT_MS": "30000",
    "DAILY_SCAN_LIMIT": "50",
    "ENVIRONMENT": "development",
}

# setdefault, not assignment: CI may want to override one of these, and this
# should not fight it.
for _key, _value in TEST_ENVIRONMENT.items():
    os.environ.setdefault(_key, _value)
