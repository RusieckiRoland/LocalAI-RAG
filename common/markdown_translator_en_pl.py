# File: common/markdown_translator_en_pl.py
from __future__ import annotations

import os
import re
import json
import torch
import tempfile
import logging
from typing import Dict
from transformers import MarianMTModel, MarianTokenizer
from mdpo.md2po import Md2Po
from mdpo.po2md import Po2Md
import polib

# Precompiled patterns (module-level, compiled once)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`]+?)`(?!`)")      # inline `code` (not fenced)
URL_RE         = re.compile(r"https?://[^\s<>\)]+")        # bare http(s)
PH_FIX_RE      = re.compile(r"<\s*([A-Z]+)_\s*(\d+)\s*>")  # < IC_1> -> <IC_1>

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class MarkdownTranslator:
    """
    Translate Markdown EN → PL using a local MarianMT model, preserving structure:
    - Extract to PO (mdpo),
    - Translate strings with placeholder protection for inline code and URLs,
    - Convert back to Markdown.

    Notes:
    - Model files must be present under `model_path` (config.json, pytorch_model.bin, tokenizer_config.json).
    - Device is auto-selected (CUDA if available, otherwise CPU).
    """

    def __init__(self, model_path: str):
        # Attach global regexes (explicit for readability and testability)
        self._inline_code_re = INLINE_CODE_RE
        self._url_re = URL_RE
        self._ph_fix_re = PH_FIX_RE

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logging.info(f"Loading MarianMT model from {model_path}...")

        # Validate model files
        required_files = ["config.json", "pytorch_model.bin", "tokenizer_config.json"]
        for file in required_files:
            if not os.path.exists(os.path.join(model_path, file)):
                raise FileNotFoundError(f"Missing model file: {file}")

        # Load model
        self.tokenizer = MarianTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = MarianMTModel.from_pretrained(model_path, local_files_only=True).to(self.device)
        logging.info("MarianMT model loaded successfully")

    # --- Placeholder protection / restoration ---------------------------------

    def _protect_inline_code(self, text: str, mapping: Dict[str, str]) -> str:
        """Replace single-backtick fragments `...` with placeholders <IC_n> (n = insertion order)."""
        def repl(m):
            key = f"<IC_{len(mapping)}>"
            mapping[key] = m.group(0)   # keep the backticks
            return key
        return self._inline_code_re.sub(repl, text)

    def _protect_urls(self, text: str, mapping: Dict[str, str]) -> str:
        """Replace bare URLs with placeholders <URL_n> (n continues the same mapping counter)."""
        def repl(m):
            key = f"<URL_{len(mapping)}>"
            mapping[key] = m.group(0)
            return key
        return self._url_re.sub(repl, text)

    def _restore_placeholders(self, text: str, mapping: Dict[str, str]) -> str:
        """Restore all placeholders from the mapping."""
        for k, v in mapping.items():
            text = text.replace(k, v)
        return text

    # --- Translation -----------------------------------------------------------

    def translate_text(self, text: str) -> str:
        """Translate EN → PL using MarianMT."""
        if not text.strip():
            return text
        try:
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(self.device)
            generated_tokens = self.model.generate(
                **inputs,
                max_length=512,
                num_beams=4,
                early_stopping=True
            )
            return self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
        except Exception as e:
            logging.error(f"Translation error: {str(e)}")
            return text

    def translate_markdown(self, markdown_content: str) -> str:
        """
        Translate Markdown content EN → PL while preserving structure and code blocks.

        Steps:
        1) Extract messages to PO (mdpo).
        2) For each message:
           - Skip fenced code blocks (leave as-is).
           - Protect inline code and URLs via placeholders.
           - Translate text.
           - Normalize placeholder spacing (< IC_1> -> <IC_1>).
           - Restore placeholders.
        3) Save PO to a temp file, convert back to Markdown (Po2Md), cleanup temp file.
        """
        if not markdown_content.strip():
            logging.warning("Empty markdown content, returning original")
            return markdown_content

        # 1) Extract to PO
        md2po = Md2Po(markdown_content)
        mdpo_entries = md2po.extract()

        pofile = polib.POFile()
        for msg in mdpo_entries:
            entry = polib.POEntry(
                msgid=msg.msgid,
                msgstr=msg.msgstr or "",
                msgctxt=getattr(msg, "msgctxt", None),
                occurrences=getattr(msg, "occurrences", []),
                comment=getattr(msg, "comment", "") or "",
                obsolete=getattr(msg, "obsolete", False),
            )
            pofile.append(entry)

        # 2) Translate with protection
        logging.info("Translating content...")
        for msg in pofile:
            if not msg.msgid or msg.obsolete:
                continue

            src = msg.msgid

            # Preserve fenced code blocks (``` ... ```)
            if "```" in src:
                msg.msgstr = src
                continue

            # Protect placeholders
            mapping: Dict[str, str] = {}
            protected = self._protect_inline_code(src, mapping)
            protected = self._protect_urls(protected, mapping)

            # Translate
            translated = self.translate_text(protected)

            # Normalize placeholder spacing: "< IC_1>" -> "<IC_1>"
            translated = self._ph_fix_re.sub(r"<\1_\2>", translated)

            # Restore placeholders
            msg.msgstr = self._restore_placeholders(translated, mapping)

        # 3) Persist PO and convert back to Markdown
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".po", prefix="mdpo_")
        tmp_path = tmp_file.name
        tmp_file.close()
        try:
            pofile.save(tmp_path)
            po2md = Po2Md(tmp_path)
            translated_content = po2md.translate(markdown_content)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                logging.warning(f"Could not remove temp file {tmp_path}")

        return translated_content
