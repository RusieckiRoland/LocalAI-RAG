#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Server entrypoint with optional .env loading.
Use:
    python start_AI_server.py --env
"""

import argparse
import os
from dotenv import load_dotenv

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

    print("")
    print("🚀 LocalAI-RAG UI")
    print(f"➜  Local:   http://127.0.0.1:{port}/")
    print(f"➜  Network: http://{ip}:{port}/")
    print("")
    print("🔎 Health / config")
    print(f"➜  /health:     http://127.0.0.1:{port}/health")
    print(f"➜  /app-config: http://127.0.0.1:{port}/app-config")
    print("")


if __name__ == "__main__":
    # Import the Flask app ONLY inside __main__.
    # This is required when semantic search uses multiprocessing "spawn":
    # child processes re-import the main module, and importing the server at top-level
    # would start new processes during bootstrap (crash / recursion).
    from code_query_engine.query_server_dynamic import app  # noqa: E402

    host = "0.0.0.0"
    port = 5000

    _print_start_banner(host=host, port=port)

    app.run(host=host, port=port, debug=True)
