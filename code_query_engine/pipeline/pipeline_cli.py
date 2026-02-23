# code_query_engine/pipeline/pipeline_cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .loader import PipelineLoader
from .lockfile import generate_lockfile, lockfile_path_for_yaml, write_lockfile


def _cmd_lock(args: argparse.Namespace) -> int:
    yaml_path = Path(args.pipeline).resolve()
    if not yaml_path.exists() or not yaml_path.is_file():
        raise FileNotFoundError(f"pipeline YAML not found: {yaml_path}")

    pipelines_root = yaml_path.parent
    loader = PipelineLoader(pipelines_root=str(pipelines_root))
    pipeline = loader.load_from_path(str(yaml_path), pipeline_name=args.pipeline_name)

    lockfile = generate_lockfile(pipeline)
    out_path = Path(args.out).resolve() if args.out else lockfile_path_for_yaml(yaml_path)
    write_lockfile(lockfile=lockfile, path=out_path)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline_cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    lock_p = sub.add_parser("lock", help="Generate lockfile for a pipeline YAML")
    lock_p.add_argument("pipeline", help="Path to pipeline YAML")
    lock_p.add_argument("--name", dest="pipeline_name", help="Pipeline name (for multi-pipeline files)")
    lock_p.add_argument("--out", help="Optional output path for lockfile")
    lock_p.set_defaults(func=_cmd_lock)

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
