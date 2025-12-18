from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import List

from constants import ANSWER_PREFIX, FOLLOWUP_PREFIX


class BasePromptBuilder(ABC):
    def __init__(self):
        self._init_profiles_dir()

    @property
    @abstractmethod
    def PROFILE_SUFFIX(self) -> str:
        """Optional profile suffix (e.g. '_deep' for DeepSeek)."""
        raise NotImplementedError

    def _init_profiles_dir(self) -> None:
        """Initialize prompt profiles directory."""
        self.SCRIPT_DIR = Path(__file__).parent
        self.PROFILE_DIR = self.SCRIPT_DIR.parent / "prompts"

        if not self.PROFILE_DIR.exists():
            raise FileNotFoundError(f"Missing prompts directory: {self.PROFILE_DIR}")

    def _iter_prompt_files(self) -> List[Path]:
        # Include subfolders to avoid a flat, messy prompts directory.
        return sorted(self.PROFILE_DIR.glob("**/*.txt"))

    def _normalize_profile_relpath(self, profile: str) -> PurePosixPath:
        """Normalize 'profile' to a safe relative path (supports subfolders)."""
        raw = (profile or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("Profile name is empty.")

        rel = PurePosixPath(raw)

        # Safety: disallow absolute paths or traversal.
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Invalid profile path: '{profile}'")

        return rel

    def _load_profile_content(self, profile: str) -> str:
        """Load profile content, applying optional class suffix."""
        suffix = getattr(self, "PROFILE_SUFFIX", None) or ""
        rel = self._normalize_profile_relpath(profile)

        # File name with optional suffix, placed in the same relative directory.
        stem = rel.name
        filename = f"{stem}_{suffix}.txt" if suffix else f"{stem}.txt"
        profile_path = (self.PROFILE_DIR / rel.parent / filename).resolve()

        # Ensure the resolved path stays inside prompts directory.
        try:
            profile_path.relative_to(self.PROFILE_DIR.resolve())
        except Exception as ex:
            raise ValueError(f"Invalid profile path: '{profile}'") from ex

        if not profile_path.exists():
            available = []
            for f in self._iter_prompt_files():
                # Rel path without extension.
                rel_stem = f.relative_to(self.PROFILE_DIR).with_suffix("").as_posix()

                # Strip suffix only if it matches, so users see usable profile keys.
                if suffix and rel_stem.endswith(f"_{suffix}"):
                    rel_stem = rel_stem[: -len(f"_{suffix}")]

                available.append(rel_stem)

            available_sorted = ", ".join(sorted(set(available)))
            raise FileNotFoundError(f"Missing prompt '{profile}'. Available: {available_sorted}")

        return profile_path.read_text(encoding="utf-8")

    def _load_and_prepare_profile(self, profile: str) -> str:
        """Load profile and inject constants placeholders."""
        content = self._load_profile_content(profile)
        return (
            content
            .replace("{ANSWER_PREFIX}", ANSWER_PREFIX)
            .replace("{FOLLOWUP_PREFIX}", FOLLOWUP_PREFIX)
        )
