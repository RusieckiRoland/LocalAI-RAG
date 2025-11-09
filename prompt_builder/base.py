from abc import ABC, abstractmethod
from pathlib import Path
import os

from constants import ANSWER_PREFIX, FOLLOWUP_PREFIX


class BasePromptBuilder(ABC):
    def __init__(self):
        self._init_profiles_dir()
        
    @property
    @abstractmethod
    def PROFILE_SUFFIX(self) -> str:
        """Suffix dla plików profilowych (np. '_deep' dla DeepSeek)"""
        pass

    def _init_profiles_dir(self):
        """Inicjalizacja ścieżek z wymuszeniem suffixu"""
        self.SCRIPT_DIR = Path(__file__).parent
        self.PROFILE_DIR = self.SCRIPT_DIR.parent / "prompts"
        
        # Wymuszenie istnienia folderu
        if not self.PROFILE_DIR.exists():
            raise FileNotFoundError(f"Brak folderu profili: {self.PROFILE_DIR}")

    def _load_profile_content(self, profile: str) -> str:
        """Ładuje treść profilu, stosując opcjonalny suffix klasy."""

        suffix = getattr(self, "PROFILE_SUFFIX", None)
        if suffix:
            filename = f"{profile}_{suffix}.txt"
        else:
            filename = f"{profile}.txt"

        profile_path = self.PROFILE_DIR / filename

        # Sprawdź czy plik istnieje
        if not profile_path.exists():
            # Lista dostępnych profili (usuwamy suffix tylko jeśli istnieje)
            available = []
            for f in self.PROFILE_DIR.glob("*.txt"):
                stem = f.stem
                if suffix and stem.endswith(f"_{suffix}"):
                    stem = stem[: -len(f"_" + suffix)]
                available.append(stem)

            available_sorted = ", ".join(sorted(set(available)))
            raise FileNotFoundError(
                f"Brak pliku '{filename}'. Dostępne profile: {available_sorted}"
            )

        return profile_path.read_text(encoding="utf-8")


    def _load_and_prepare_profile(self, profile: str) -> str:
        """
        Ładuje profil i wstrzykuje stałe {ANSWER_PREFIX}/{FOLLOWUP_PREFIX}.
        """
        content = self._load_profile_content(profile)

        return (
            content
            .replace("{ANSWER_PREFIX}", ANSWER_PREFIX)
            .replace("{FOLLOWUP_PREFIX}", FOLLOWUP_PREFIX)
        )
