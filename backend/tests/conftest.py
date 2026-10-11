"""Test isolation for the database layer.

The backend's real configuration (backend/.env) points USE_MOCK_MONGO at the
Docker MongoDB. That is correct for the running app, but the test suite must
never touch a real server: it would require Docker to be up and would pollute
real data. Setting USE_MOCK_MONGO here (before any app import) keeps every test
hermetic and fast, regardless of what backend/.env contains.

load_dotenv() does not override variables that are already set, so this value
wins once app.main is imported by a test module.
"""

import os

os.environ["USE_MOCK_MONGO"] = "true"
