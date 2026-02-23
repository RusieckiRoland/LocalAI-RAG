#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Server entrypoint with optional .env loading.
Use:
    python start_AI_server.py --env
"""

import argparse
import json
import os
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(__file__)
RUNTIME_CONFIG_DEFAULT_PATH = os.path.join(PROJECT_ROOT, "config.json")
RUNTIME_CONFIG_DEV_PATH = os.path.join(PROJECT_ROOT, "config.dev.json")
RUNTIME_CONFIG_PROD_PATH = os.path.join(PROJECT_ROOT, "config.prod.json")

# --- Optional --env flag ---
parser = argparse.ArgumentParser()
parser.add_argument("--env", action="store_true", help="Load environment variables from .env file")
args, unknown = parser.parse_known_args()

if args.env:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        print(f"📄 Loading environment from {env_path}")
        load_dotenv(env_path)
    else:
        print("⚠️  .env file not found, skipping.")


def _get_primary_ipv4() -> str:
    # English comments only.
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are actually sent; this picks the primary interface IP.
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _print_start_banner(host: str, port: int) -> None:
    # English comments only.
    ip = _get_primary_ipv4()
    development = _is_development_enabled()
    mode_label = "dev" if development else "prod"

    print("")
    print("🚀 LocalAI-RAG UI")
    print(f"🧭 Mode: {mode_label}")
    print(f"➜  Local:   http://127.0.0.1:{port}/")
    print(f"➜  Network: http://{ip}:{port}/")
    print("")
    print("🔎 Health / config")
    print(f"➜  /health:     http://127.0.0.1:{port}/health")
    if development:
        print(f"➜  /app-config/dev:  http://127.0.0.1:{port}/app-config/dev")
    print(f"➜  /app-config/prod: http://127.0.0.1:{port}/app-config/prod")
    print("")
    print("🔐 Prod auth check")
    print(f"➜  /auth-check/prod: http://127.0.0.1:{port}/auth-check/prod")
    if development:
        print(f"➜  /search/dev (POST):  http://127.0.0.1:{port}/search/dev")
    print(f"➜  /search/prod (POST): http://127.0.0.1:{port}/search/prod")
    print("")


def _parse_env_bool(raw: str | None) -> bool | None:
    val = str(raw or "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return None


def _resolve_runtime_config_path() -> str:
    explicit = str(os.getenv("APP_CONFIG_PATH") or "").strip()
    if explicit:
        return explicit if os.path.isabs(explicit) else os.path.join(PROJECT_ROOT, explicit)

    profile = str(os.getenv("APP_CONFIG_PROFILE") or "").strip().lower()
    if profile in ("dev", "development"):
        return RUNTIME_CONFIG_DEV_PATH
    if profile in ("prod", "production"):
        return RUNTIME_CONFIG_PROD_PATH

    env_dev = _parse_env_bool(os.getenv("APP_DEVELOPMENT"))
    if env_dev is True:
        return RUNTIME_CONFIG_DEV_PATH
    if env_dev is False:
        return RUNTIME_CONFIG_PROD_PATH

    if os.path.exists(RUNTIME_CONFIG_DEV_PATH):
        return RUNTIME_CONFIG_DEV_PATH
    return RUNTIME_CONFIG_DEFAULT_PATH


def _is_development_enabled() -> bool:
    env_val = _parse_env_bool(os.getenv("APP_DEVELOPMENT"))
    if env_val is not None:
        return env_val

    cfg_path = _resolve_runtime_config_path()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:
        if cfg_path != RUNTIME_CONFIG_DEFAULT_PATH:
            try:
                with open(RUNTIME_CONFIG_DEFAULT_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
            except Exception:
                return True
        else:
            return True

    return bool(cfg.get("development", True))


if __name__ == "__main__":
    # Import the Flask app ONLY inside __main__.
    # This is required when semantic search uses multiprocessing "spawn":
    # child processes re-import the main module, and importing the server at top-level
    # would start new processes during bootstrap (crash / recursion).
    from code_query_engine.query_server_dynamic import app  # noqa: E402

    host = "0.0.0.0"
    port = 5000
    development = _is_development_enabled()

    _print_start_banner(host=host, port=port)

    app.run(host=host, port=port, debug=development, use_reloader=False)
