from __future__ import annotations

import json
from queue import Empty
from typing import Callable, Optional

from flask import Response, abort, jsonify, request, stream_with_context

from .broker import get_work_callback_broker


AuthCheckFn = Callable[[str], Optional[object]]
DevEnabledFn = Callable[[], bool]


def register_work_callback_routes(
    app,
    *,
    dev_enabled_fn: DevEnabledFn,
    require_prod_bearer_fn: AuthCheckFn,
) -> None:
    @app.route("/pipeline/stream/dev", methods=["GET"])
    def pipeline_stream_dev():
        if not dev_enabled_fn():
            abort(404)
        return _handle_trace_stream(require_bearer_auth=False, require_prod_bearer_fn=require_prod_bearer_fn)

    @app.route("/pipeline/stream/prod", methods=["GET"])
    def pipeline_stream_prod():
        return _handle_trace_stream(require_bearer_auth=True, require_prod_bearer_fn=require_prod_bearer_fn)


def _handle_trace_stream(*, require_bearer_auth: bool, require_prod_bearer_fn: AuthCheckFn):
    auth_header = (request.headers.get("Authorization") or "").strip()
    if require_bearer_auth:
        auth_error = require_prod_bearer_fn(auth_header)
        if auth_error is not None:
            return auth_error

    run_id = (request.args.get("run_id") or request.headers.get("X-Run-ID") or "").strip()
    if not run_id:
        return jsonify({"ok": False, "error": "missing run_id"}), 400

    broker = get_work_callback_broker()
    q, snapshot, closed, reason = broker.open_stream(run_id)

    def _stream():
        try:
            for ev in snapshot:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if closed:
                yield f"data: {json.dumps({'type': 'done', 'reason': reason}, ensure_ascii=False)}\n\n"
                return

            while True:
                try:
                    ev = q.get(timeout=10)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                if isinstance(ev, dict) and ev.get("type") == "done":
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            broker.remove_stream(run_id, q)

    resp = Response(stream_with_context(_stream()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

