import os
from typing import Any, Dict, List, Optional

import yaml  # pip install pyyaml

from common.hybrid_search import HybridSearch
from common.utils import extract_followup
from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator
import constants
from history.history_manager import HistoryManager
from dotnet_sumarizer.code_compressor import compress_chunks
from .model import Model
from .log_utils import InteractionLogger


class PipelineContext:
    """Holds the state of a single dynamic pipeline execution."""

    def __init__(
        self,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str,
        *,
        translate_chat: bool,
        main_model: Model,
        searcher: HybridSearch,
        markdown_translator: MarkdownTranslator,
        translator_pl_en: Translator,
        history_manager: HistoryManager,
        settings: Dict[str, Any],
    ) -> None:
        self.user_query = user_query
        self.session_id = session_id
        self.consultant = consultant
        self.branch = branch
        self.translate_chat = translate_chat
        self.main_model = main_model
        self.searcher = searcher
        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.history_manager = history_manager
        self.settings = settings

        # Dynamic state
        self.user_language = "pl" if translate_chat else "en"
        self.model_input_en: Optional[str] = None
        self.context_blocks: List[str] = history_manager.get_context_blocks()
        self.last_response: Optional[str] = None
        self.answer_en: Optional[str] = None
        self.answer_pl: Optional[str] = None
        self.query_type: str = "unknown"
        self.steps_used: int = 0



class DynamicPipelineRunner:
    """Executes YAML-defined pipeline for a given consultant."""

    def __init__(
        self,
        pipelines_dir: str,
        main_model: Model,
        searcher: HybridSearch,
        markdown_translator: MarkdownTranslator,
        translator_pl_en: Translator,
        logger: InteractionLogger,
    ) -> None:
        self.pipelines_dir = pipelines_dir
        self.main_model = main_model
        self.searcher = searcher
        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

    def _load_pipeline_yaml(self, consultant: str) -> Dict[str, Any]:
        """Loads YAML pipeline for given consultant id."""
        file_name = f"{consultant}.yaml"
        path = os.path.join(self.pipelines_dir, file_name)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Pipeline YAML not found for consultant='{consultant}': {path}"
            )
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def run(
        self,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str,
        *,
        translate_chat: bool,
        mock_redis: Any,
    ):
        """High-level entry point used by Flask endpoint."""
        pipeline_def = self._load_pipeline_yaml(consultant)
        pipeline_root = pipeline_def.get("pipeline") or {}
        settings = pipeline_root.get("settings") or {}
        steps = pipeline_root.get("steps") or []
        steps_by_id = {s["id"]: s for s in steps}

        history_manager = HistoryManager(mock_redis, session_id)

        ctx = PipelineContext(
            user_query=user_query,
            session_id=session_id,
            consultant=consultant,
            branch=branch,
            translate_chat=translate_chat,
            main_model=self.main_model,
            searcher=self.searcher,
            markdown_translator=self.markdown_translator,
            translator_pl_en=self.translator_pl_en,
            history_manager=history_manager,
            settings=settings,
        )

        # Historia: chcemy zachować to samo zachowanie co w search_logic:
        # - przy translate_chat=True: w polu "en" trzymamy angielskie tłumaczenie,
        #   a w "pl" oryginalne pytanie użytkownika,
        # - przy translate_chat=False: pytanie traktujemy jako EN i zapisujemy je w obu polach.
        if translate_chat:
            model_input_en_for_history = self.translator_pl_en.translate(user_query)
        else:
            model_input_en_for_history = user_query

        ctx.history_manager.start_user_query(model_input_en_for_history, user_query)

        current_step_id = steps[0]["id"] if steps else None
        max_steps = len(steps) + 5  # simple safety limit

        for i in range(max_steps):
            if not current_step_id:
                break
            ctx.steps_used = i + 1
            step = steps_by_id.get(current_step_id)
            if not step:
                break

            next_step_id = self._execute_step(step, ctx)

            if step.get("end"):
                break
            current_step_id = next_step_id

        final_answer = ctx.answer_pl or ctx.answer_en or "Error: No valid response generated."
        self._log_final(ctx)
        return final_answer, ctx.query_type, ctx.steps_used, ctx.model_input_en or ctx.user_query

   
    # ---------- STEP DISPATCH ----------

    def _execute_step(self, step: Dict[str, Any], ctx: PipelineContext) -> Optional[str]:
        """Executes a single step and returns next step id."""
        action = step.get("action")

        if action == "detect_language":
            self._step_detect_language(ctx)
        elif action == "translate_in_if_needed":
            self._step_translate_in(ctx)
        elif action == "call_model":
            # per-step prompt_key
            self._step_call_model(step, ctx)
        elif action == "handle_prefix":
            return self._step_handle_prefix(step, ctx)
        elif action == "fetch_more_context":
            # per-step search_mode
            self._step_fetch_more_context(step, ctx)
        elif action == "finalize":
            self._step_finalize(ctx)
        elif action == "finalize_heuristic":
            self._step_finalize_heuristic(ctx)
        else:
            # Unknown action → ignore
            pass

        return step.get("next")



    # ---------- ACTIONS ----------

    def _step_detect_language(self, ctx: PipelineContext) -> None:
        """For now: use translate_chat flag as language hint."""
        ctx.user_language = "pl" if ctx.translate_chat else "en"

    def _step_translate_in(self, ctx: PipelineContext) -> None:
        """Translate user question to English if needed."""
        if ctx.user_language == "pl":
            ctx.model_input_en = ctx.translator_pl_en.translate(ctx.user_query)
        else:
            ctx.model_input_en = ctx.user_query

    def _build_context_str(self, ctx: PipelineContext) -> str:
        return "\n---\n".join(ctx.context_blocks or [])

    def _step_call_model(self, step: Dict[str, Any], ctx: PipelineContext) -> None:
        """Call main model with current context + question."""
        context_str = self._build_context_str(ctx)
        question = ctx.model_input_en or ctx.user_query

        # Prompt key resolution:
        # 1) step["prompt_key"]              – per-step configuration in YAML
        # 2) ctx.settings["default_prompt_key"] – optional pipeline-level default
        # 3) ctx.consultant                  – legacy fallback (old behavior)
        prompt_key = (
            step.get("prompt_key")
            or ctx.settings.get("default_prompt_key")
            or ctx.consultant
        )

        print(
            f"[Dynamic] Step {ctx.steps_used} - Prompt key: {prompt_key}, "
            f"question: {question[:200]}..."
        )
        response = ctx.main_model.ask(context_str, question, prompt_key)
        print(f"[Dynamic] Step {ctx.steps_used} - LLM: {response[:200]}...")

        ctx.last_response = response
                # Classification prompts:
        if prompt_key in ("classifier_user", "classifier_followup"):
            self._apply_classification(ctx)



    def _step_handle_prefix(self, step: Dict[str, Any], ctx: PipelineContext) -> Optional[str]:
        """Decide what to do after model response based on prefix."""
        resp = ctx.last_response or ""
        ans_pref = ctx.settings.get("answer_prefix", constants.ANSWER_PREFIX)
        foll_pref = ctx.settings.get("followup_prefix", constants.FOLLOWUP_PREFIX)

        if resp.startswith(ans_pref):
            ctx.answer_en = resp.replace(ans_pref, "").strip()
            ctx.query_type = "direct answer"
            return step.get("on_answer")
        elif resp.startswith(foll_pref):
            return step.get("on_followup")
        else:
            cleaned = resp.strip()
            if len(cleaned) > 20:
                ctx.answer_en = cleaned
                ctx.query_type = "direct answer (heuristic)"
                return step.get("on_other")
            ctx.answer_en = "Unrecognized response from model."
            ctx.query_type = "fallback error"
            return step.get("on_other")
    
    def _step_fetch_more_context(self, step: Dict[str, Any], ctx):
        """
        Fetch context using (1) search_mode priority: step → settings → default,
        (2) filters based on ctx.query_type,
        (3) fake search results for tests or real searcher in production.
        """
        resp = ctx.last_response or ""
        follow_pref = ctx.settings.get("followup_prefix", constants.FOLLOWUP_PREFIX)
        followup = extract_followup(resp, followup_prefix=follow_pref)
        if not followup:
            return

        # --- 1) determine search_mode ---
        search_mode = (
            step.get("search_mode")
            or ctx.settings.get("search_mode")
            or "hybrid"
        ).lower()

        if search_mode == "none":
            return

        # --- 2) determine query_type ---
        qtype = (ctx.query_type or "OTHER").upper()

        # --- 3) resolve filters from YAML ---
        filters_map = ctx.settings.get("filters", {})
        active_filters = filters_map.get(qtype, {})

        # --- 4) choose actual search engine ---
        if search_mode == "vector":
            results = ctx.searcher.search(
                followup,
                top_k=5,
                alpha=1.0,
                beta=0.0,
                filters=active_filters,
            )
        else:
            # default = hybrid
            results = ctx.searcher.search(
                followup,
                top_k=5,
                filters=active_filters,
            )

        # --- 5) compress chunks (tests rely on this existing) ---
        chunks = []
        for r in results or []:
            chunks.append({
                "path": r.get("File") or r.get("path"),
                "content": r.get("Content") or r.get("content"),
                "member": r.get("Member") or r.get("member"),
                "namespace": r.get("Namespace") or r.get("namespace"),
                "class": r.get("Class") or r.get("class"),
                "hit_lines": r.get("HitLines") or r.get("hit_lines"),
            })

        compressed = compress_chunks(
            chunks,
            token_budget=1200,
        )
        ctx.context_blocks.append(compressed)
        ctx.query_type = "vector query"

    def _apply_classification(self, ctx: PipelineContext):
        """
        Reads last_response and extracts query_type from ANSWER_PREFIX.
        Example:
            "###ANSWER: SQL"  -> ctx.query_type = "SQL"
        """
        raw = ctx.last_response or ""
        prefix = ctx.settings.get("answer_prefix", constants.ANSWER_PREFIX)

        if raw.startswith(prefix):
            value = raw.replace(prefix, "").strip()
            # Normalize
            ctx.query_type = value.upper()
        else:
            # classification failed → leave old value or set OTHER
            if ctx.query_type == "unknown":
                ctx.query_type = "OTHER"
                # Classification prompts:
        
