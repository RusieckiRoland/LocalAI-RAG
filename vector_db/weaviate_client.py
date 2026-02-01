from __future__ import annotations

"""
Production Weaviate client utilities.

- Reads connection settings from config.json (commit-safe) and environment variables.
- Supports optional loading of a local ".env" file when explicitly requested by CLI (--env).
- Works both with API key auth and without auth (dev).
- Fail-fast (raises on invalid config/env).
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import weaviate


@dataclass(frozen=True)
class WeaviateConnSettings:
    host: str = "localhost"
    http_port: int = 18080
    grpc_port: int = 15005
    api_key: str = ""
    ready_timeout_seconds: int = 30


def load_dotenv(dotenv_path: Path, *, override: bool = False) -> bool:
    """
    Load KEY=VALUE pairs from a .env file into os.environ.

    - Does NOT override existing env vars unless override=True.
    - Returns True if file existed and was parsed, False if file doesn't exist.
    - Raises on IO errors (read failure), but ignores malformed lines safely.
    """
    if not dotenv_path.is_file():
        return False

    text = dotenv_path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # allow: export KEY=VALUE
        if line.startswith("export "):
            line = line[len("export "):].lstrip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()

        # strip surrounding quotes if present
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        if not override and key in os.environ:
            continue

        os.environ[key] = value

    return True


def _project_root_from_here() -> Path:
    # vector_db/weaviate_client.py -> project root is one level up
    return Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise RuntimeError(f"Failed to load/parse JSON config: {path}") from e


def load_config(*, project_root: Optional[Path] = None, config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path is not None:
        return _read_json(config_path)

    env_cfg_path = (os.getenv("WEAVIATE_CONFIG_PATH") or "").strip()
    if env_cfg_path:
        return _read_json(Path(env_cfg_path))

    root = project_root or _project_root_from_here()
    return _read_json(root / "config.json")


def _get_cfg(cfg: Dict[str, Any], *path: str) -> Any:
    cur: Any = cfg
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _pick_str(env_key: str, cfg: Dict[str, Any], cfg_path: tuple[str, ...], default: str) -> str:
    v = (os.getenv(env_key) or "").strip()
    if v:
        return v
    raw = _get_cfg(cfg, *cfg_path)
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


def _pick_int(env_key: str, cfg: Dict[str, Any], cfg_path: tuple[str, ...], default: int) -> int:
    v = (os.getenv(env_key) or "").strip()
    if v:
        try:
            return int(v)
        except Exception as e:
            raise RuntimeError(f"Invalid int in env {env_key}={v!r}") from e

    raw = _get_cfg(cfg, *cfg_path)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception as e:
        raise RuntimeError(f"Invalid int in config at {'.'.join(cfg_path)}={raw!r}") from e


def get_settings(
    *,
    project_root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> WeaviateConnSettings:
    cfg = load_config(project_root=project_root, config_path=config_path)

    # config supports: weaviate.host/http_port/grpc_port/api_key/ready_timeout_seconds
    host = _pick_str("WEAVIATE_HOST", cfg, ("weaviate", "host"), "localhost")
    http_port = _pick_int("WEAVIATE_HTTP_PORT", cfg, ("weaviate", "http_port"), 18080)
    grpc_port = _pick_int("WEAVIATE_GRPC_PORT", cfg, ("weaviate", "grpc_port"), 15005)
    api_key = _pick_str("WEAVIATE_API_KEY", cfg, ("weaviate", "api_key"), "")
    ready_timeout = _pick_int("WEAVIATE_READY_TIMEOUT", cfg, ("weaviate", "ready_timeout_seconds"), 30)

    ov = overrides or {}
    if ov.get("host"):
        host = str(ov["host"]).strip()
    if ov.get("http_port"):
        http_port = int(ov["http_port"])
    if ov.get("grpc_port"):
        grpc_port = int(ov["grpc_port"])
    if ov.get("api_key") is not None and str(ov.get("api_key") or "").strip():
        api_key = str(ov["api_key"]).strip()

    return WeaviateConnSettings(
        host=host,
        http_port=http_port,
        grpc_port=grpc_port,
        api_key=api_key,
        ready_timeout_seconds=ready_timeout,
    )


def _build_auth(api_key: str):
    key = (api_key or "").strip()
    if not key:
        return None

    try:
        from weaviate.auth import AuthApiKey  # type: ignore
        return AuthApiKey(key)
    except Exception:
        try:
            from weaviate.classes.init import Auth  # type: ignore
            return Auth.api_key(key)
        except Exception as e:
            raise RuntimeError("Cannot construct Weaviate API key auth; check weaviate-client version") from e


def create_client(settings: WeaviateConnSettings) -> "weaviate.WeaviateClient":
    auth = _build_auth(settings.api_key)

    client = weaviate.connect_to_local(
        host=settings.host,
        port=settings.http_port,
        grpc_port=settings.grpc_port,
        auth_credentials=auth,
    )

    if not client.is_ready():
        client.close()
        raise RuntimeError(
            "Weaviate is not ready. "
            f"host={settings.host} http_port={settings.http_port} grpc_port={settings.grpc_port}"
        )

    return client
