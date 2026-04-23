import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class HelloDevOpsAppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.create_app().test_client()

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "Hello DevOps")

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "OK")

    def test_version_endpoint_uses_env_defaults(self):
        with patch.dict(os.environ, {"GIT_COMMIT": "abc123", "BUILD_TIMESTAMP": "2026-01-01T00:00:00Z"}, clear=False):
            with patch.object(app, "BUILD_INFO_FILE", Path("/non/existent/build_info.json")):
                response = self.client.get("/version")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode("utf-8"))
        self.assertEqual(payload["git_commit"], "abc123")
        self.assertEqual(payload["build_timestamp"], "2026-01-01T00:00:00Z")

    def test_version_endpoint_prefers_build_info_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_info_path = Path(tmpdir) / "build_info.json"
            build_info_path.write_text(
                json.dumps({"git_commit": "file-commit", "build_timestamp": "2026-02-02T00:00:00+00:00"}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GIT_COMMIT": "env-commit", "BUILD_TIMESTAMP": "env-time"}, clear=False):
                with patch.object(app, "BUILD_INFO_FILE", build_info_path):
                    response = self.client.get("/version")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode("utf-8"))
        self.assertEqual(payload["git_commit"], "file-commit")
        self.assertEqual(payload["build_timestamp"], "2026-02-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
