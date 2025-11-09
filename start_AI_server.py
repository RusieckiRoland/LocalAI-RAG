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

# --- Main app import and run ---
from code_query_engine.query_server import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
