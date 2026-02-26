from __future__ import annotations

from typing import Callable, Optional

from flask import jsonify, request

from code_query_engine.pipeline.cancellation import get_pipeline_cancel_registry
from .broker import get_work_callback_broker


AuthCheckFn = Callable[[str], Optional[object]]


def register_cancel_routes(
    app,
    *,
    require_bearer_fn: AuthCheckFn,
) -> None:
    @app.route("/pipeline/cancel", methods=["POST"])
    def pipeline_cancel():
        return _handle_cancel_request(require_bearer_fn=require_bearer_fn)


def _handle_cancel_request(*, require_bearer_fn: AuthCheckFn):
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = require_bearer_fn(auth_header)
    if auth_error is not None:
        return auth_error

    payload = request.get_json(silent=True) or {}
    run_id = (
        str(payload.get("pipeline_run_id") or payload.get("run_id") or request.headers.get("X-Run-ID") or "").strip()
    )
    if not run_id:
        return jsonify({"ok": False, "error": "missing run_id"}), 400

    registry = get_pipeline_cancel_registry()
    registry.request_cancel(run_id, reason="client_cancel")

    broker = get_work_callback_broker()
    broker.close(run_id, reason="cancelled")

    return jsonify({"ok": True, "run_id": run_id, "cancelled": True})
