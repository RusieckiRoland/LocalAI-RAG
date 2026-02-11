from __future__ import annotations

import logging
import os
from typing import Any, Optional

from code_query_engine.pipeline.providers.ports import IRetrievalBackend
import constants
from history.history_manager import HistoryManager
from integrations.plant_uml.plantuml_check import add_plant_link

from .pipeline.action_registry import build_default_action_registry
from .pipeline.engine import PipelineEngine, PipelineRuntime
from .pipeline.loader import PipelineLoader
from .pipeline.providers.retrieval import RetrievalDispatcher
from .pipeline.state import PipelineState
from .pipeline.validator import PipelineValidator

py_logger = logging.getLogger(__name__)



def _create_history_manager(*, mock_redis: Any, session_id: str, consultant: str, user_id: Optional[str]):
    """
    HistoryManager signature changed a few times; keep this tolerant for tests/mocks.
    """
    candidates = [
        lambda: HistoryManager(mock_redis=mock_redis, session_id=session_id, consultant=consultant, user_id=user_id),
        lambda: HistoryManager(mock_redis=mock_redis, session_id=session_id, consultant=consultant),
        lambda: HistoryManager(mock_redis, session_id=session_id, consultant=consultant, user_id=user_id),
        lambda: HistoryManager(mock_redis, session_id=session_id, user_id=user_id),
        lambda: HistoryManager(mock_redis, session_id=session_id),
        lambda: HistoryManager(mock_redis, session_id, user_id),
        lambda: HistoryManager(mock_redis, session_id),
    ]

    last_err: Optional[Exception] = None
    for ctor in candidates:
        try:
            return ctor()
        except TypeError as e:
            last_err = e

    # If we got here, no signature matched.
    raise last_err or TypeError("Unable to construct HistoryManager with provided arguments.")


class DynamicPipelineRunner:
    def __init__(
        self,
        *,
        pipelines_dir: Optional[str] = None,
        pipelines_root: Optional[str] = None,
        model: Any = None,
        retrieval_backend: IRetrievalBackend | None = None,
        markdown_translator: Any = None,
        translator_pl_en: Any = None,
        logger: Any = None,        
        semantic_rerank_searcher: Any = None,
        graph_provider: Any = None,
        token_counter: Any = None,
        allow_test_pipelines: bool = False,
        limits_policy: str | None = None,
    ) -> None:
        root = pipelines_root or pipelines_dir
        if not root:
            raise TypeError("DynamicPipelineRunner requires pipelines_root/pipelines_dir")

        self.pipelines_root = os.fspath(root)
        self.model = model       
        self.retrieval_backend = retrieval_backend       
        self.semantic_rerank_searcher = semantic_rerank_searcher

        if graph_provider is None:
            # No fallback: graph provider must be injected explicitly.
            graph_provider = None

        self.graph_provider = graph_provider
        self.token_counter = token_counter

        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

        self.allow_test_pipelines = bool(allow_test_pipelines)
        self.limits_policy = limits_policy

        self._loader = PipelineLoader(pipelines_root=self.pipelines_root)
        self._validator = PipelineValidator()

        # Engine needs an action registry (tests may override runner._engine anyway).
        self._engine = PipelineEngine(registry=build_default_action_registry())
        self._budget_contract_cache: dict[str, tuple[dict[str, float], dict[str, Any], PipelineDef]] = {}

    def run(
        self,
        *,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str = "",
        translate_chat: bool = False,
        user_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        repository: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        snapshot_id_b: Optional[str] = None,
        snapshot_set_id: Optional[str] = None,
        overrides: Optional[dict[str, Any]] = None,
        mock_redis: Any = None,
    ):
        pipe_name = pipeline_name or consultant

        # ✅ Correct loader API
        pipeline = self._loader.load_by_name(pipe_name)
        self._validator.validate(pipeline)

        # ✅ Block test pipelines unless explicitly allowed (required by E2E test)
        if bool((pipeline.settings or {}).get("test")) and not self.allow_test_pipelines:
            raise PermissionError("Test pipelines are blocked unless allow_test_pipelines=True")

        effective_settings = dict(pipeline.settings or {})
        if overrides:
            effective_settings.update(dict(overrides))

        # Budget contract requires some numeric settings to be present even for pipelines
        # with no call_model steps (e.g., unit-test pipelines). Provide safe defaults.
        if effective_settings.get("max_context_tokens") is None:
            effective_settings["max_context_tokens"] = 5000
        if effective_settings.get("max_history_tokens") is None:
            effective_settings["max_history_tokens"] = 0
        if effective_settings.get("budget_safety_margin_tokens") is None:
            effective_settings["budget_safety_margin_tokens"] = 128

        # Budget contract (mtime-cached, no file writes). May clamp settings/steps in-memory.
        try:
            from .pipeline.budget_contract import enforce_budget_contract, normalize_limits_policy

            policy = normalize_limits_policy(self.limits_policy) or "fail_fast"

            # Cache key: pipeline logical name (post-extends merge uses that name).
            cache_key = pipe_name

            # Fingerprint sources: YAML chain + prompt files (mtime-based; stat only).
            prompts_dir = str(effective_settings.get("prompts_dir") or "prompts")
            prompt_keys: set[str] = set()
            for s in pipeline.steps:
                if s.action != "call_model":
                    continue
                pk = str((s.raw or {}).get("prompt_key") or "").strip()
                if pk:
                    prompt_keys.add(pk)

            files: list[str] = []
            resolve_fn = getattr(self._loader, "resolve_files_by_name", None)
            if callable(resolve_fn):
                files = [os.fspath(p) for p in resolve_fn(pipe_name)]
            for pk in sorted(prompt_keys):
                files.append(os.path.join(prompts_dir, f"{pk}.txt"))

            fp: dict[str, float] = {}
            for path in files:
                try:
                    fp[path] = float(os.path.getmtime(path))
                except Exception:
                    fp[path] = -1.0

            cached = self._budget_contract_cache.get(cache_key)
            if cached and cached[0] == fp:
                effective_settings = cached[1]
                pipeline = cached[2]
            else:
                def _coerce_int(value: Any, *, default: int) -> int:
                    try:
                        v = value() if callable(value) else value
                        if v is None:
                            return default
                        return int(v)
                    except Exception:
                        return default

                model_n_ctx = _coerce_int(getattr(self.model, "n_ctx", 0), default=0)
                if model_n_ctx <= 0:
                    llm = getattr(self.model, "llm", None)
                    model_n_ctx = _coerce_int(getattr(llm, "n_ctx", None) if llm is not None else None, default=0)
                if model_n_ctx <= 0:
                    # Fallback for test stubs or model wrappers that don't expose n_ctx.
                    # Keep a conservative, positive default so budget_contract can run deterministically.
                    model_n_ctx = _coerce_int(effective_settings.get("model_context_window", None), default=4096)
                    if model_n_ctx <= 0:
                        model_n_ctx = 4096

                model_default_max = _coerce_int(getattr(self.model, "default_max_tokens", 1500), default=1500) or 1500

                pipe2, settings2, _res, fp2 = enforce_budget_contract(
                    loader=self._loader,
                    pipeline=pipeline,
                    effective_settings=effective_settings,
                    model_context_window=model_n_ctx,
                    model_default_max_tokens=model_default_max,
                    token_counter=self.token_counter,
                    policy=policy,
                )

                effective_settings = settings2
                pipeline = pipe2
                self._budget_contract_cache[cache_key] = (fp2, effective_settings, pipeline)
        except Exception:
            py_logger.exception("fatal: budget contract enforcement failed")
            raise

        state = PipelineState(
            user_query=user_query,
            session_id=session_id,
            consultant=consultant,
            branch=branch,
            translate_chat=bool(translate_chat),
            user_id=user_id,
            repository=repository,
            snapshot_id=snapshot_id,
            snapshot_id_b=snapshot_id_b,
            snapshot_set_id=snapshot_set_id,
        )

        if repository:
            state.repository = repository

        if overrides:
            # Common ad-hoc request fields used by UI (best-effort).
            if "branch_b" in overrides:
                setattr(state, "branch_b", overrides.get("branch_b"))
            if "snapshot_id" in overrides and not snapshot_id:
                setattr(state, "snapshot_id", overrides.get("snapshot_id"))
            if "snapshot_id_b" in overrides and not snapshot_id_b:
                setattr(state, "snapshot_id_b", overrides.get("snapshot_id_b"))
            if "snapshot_set_id" in overrides and not snapshot_set_id:
                setattr(state, "snapshot_set_id", overrides.get("snapshot_set_id"))
            if "allowed_commands" in overrides:
                raw_allowed = overrides.get("allowed_commands")
                if isinstance(raw_allowed, list):
                    state.allowed_commands = [str(x) for x in raw_allowed if str(x).strip()]
            # Optional retrieval filters (e.g., ACL tags) resolved by the server.
            retrieval_filters = overrides.get("retrieval_filters")
            if isinstance(retrieval_filters, dict):
                state.retrieval_filters.update(retrieval_filters)

        history_manager = _create_history_manager(
            mock_redis=mock_redis,
            session_id=session_id,
            consultant=consultant,
            user_id=user_id,
        )

        

        retrieval_backend = self.retrieval_backend
        if retrieval_backend is None:
            raise ValueError("DynamicPipelineRunner: retrieval_backend is required.")

        # ✅ Match PipelineRuntime signature (no action_registry kwarg here)
        runtime = PipelineRuntime(
            pipeline_settings=effective_settings,
            model=self.model,
            searcher=None,
            markdown_translator=self.markdown_translator,
            translator_pl_en=self.translator_pl_en,
            history_manager=history_manager,
            logger=self.logger,
            constants=constants,
            retrieval_backend=retrieval_backend,
            graph_provider=self.graph_provider,
            token_counter=self.token_counter,
            add_plant_link=add_plant_link,
        )

        self._engine.run(pipeline, state, runtime)

        final_answer = state.final_answer or state.answer_en or ""
        query_type = state.query_type or state.retrieval_mode or None
        steps_used = state.steps_used
        model_input_en = state.model_input_en_or_fallback()

        return final_answer, query_type, steps_used, model_input_en
