"""
Shared pytest setup for the FieldLine AGENT tests.

pytest loads this file BEFORE it imports any test file, which matters
because several agent modules do work the moment they are imported:

  - settings.py builds a Settings object that REQUIRES MOSS_PROJECT_ID,
    MOSS_PROJECT_KEY and FIELDLINE_JWT_SECRET, and crashes if any is
    missing. On your laptop those come from agent/.env.local; on a fresh
    GitHub Actions machine there is no .env.local at all. Setting harmless
    dummy values here makes the tests run identically in both places.
  - tracing.py tries to connect to an Arize Phoenix server when imported.
    OTEL_SDK_DISABLED=true turns OpenTelemetry into a no-op so tests never
    wait on (or spam errors about) a Phoenix server that isn't running.

None of these values are ever used to reach a real service -- every test
that touches Moss, the backend or the network replaces that piece with a
fake.
"""

import os
import sys

# Make agent/src importable (agent.py-style flat imports like `import audit_log`).
_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

os.environ.setdefault("MOSS_PROJECT_ID", "test-moss-project-id")
os.environ.setdefault("MOSS_PROJECT_KEY", "test-moss-project-key")
os.environ.setdefault("FIELDLINE_JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
