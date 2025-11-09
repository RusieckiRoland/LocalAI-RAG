from .base import BasePromptBuilder
import constants

class CodellamaPromptBuilder(BasePromptBuilder):
    """
    CodeLlama-specific builder with proper constants injection
    """

    B_INST = "[INST]"
    E_INST = "[/INST]"
    B_SYS = "<<SYS>>\n"
    E_SYS = "\n<</SYS>>\n\n"

    @property 
    def PROFILE_SUFFIX(self) -> str:
        return ""  # Brak suffixu

    def build_prompt(self, context: str, question: str, profile: str = "turing") -> str:
        # Wczytanie i podstawienie stałych
        system_prompt = self._load_and_prepare_profile(profile)
        system_prompt = (
            system_prompt
            .replace("{ANSWER_PREFIX}", constants.ANSWER_PREFIX)
            .replace("{FOLLOWUP_PREFIX}", constants.FOLLOWUP_PREFIX)
        )
        
        sys_block = self.B_SYS + system_prompt + self.E_SYS
        user_content = (
            f"### Context:\n{context.strip() or '(none)'}\n\n"
            f"### User:\n{question.strip()}\n"
        )

        return f"{self.B_INST}{sys_block}{user_content}{self.E_INST}"
