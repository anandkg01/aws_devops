from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify

APP_DIR = Path(__file__).resolve().parent
BUILD_INFO_FILE = APP_DIR / "build_info.json"


def _load_build_info() -> dict[str, str]:
    build_info = {
        "git_commit": os.getenv("GIT_COMMIT", "unknown"),
        "build_timestamp": os.getenv("BUILD_TIMESTAMP", "unknown"),
    }

    if BUILD_INFO_FILE.exists():
        try:
            file_data = json.loads(BUILD_INFO_FILE.read_text(encoding="utf-8"))
            build_info["git_commit"] = file_data.get("git_commit", build_info["git_commit"])
            build_info["build_timestamp"] = file_data.get("build_timestamp", build_info["build_timestamp"])
        except (json.JSONDecodeError, OSError):
            pass

    return build_info


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def hello() -> str:
        return "Hello DevOps"

    @app.get("/health")
    def health() -> str:
        return "OK"

    @app.get("/version")
    def version():
        return jsonify(_load_build_info())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
