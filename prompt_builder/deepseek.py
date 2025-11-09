from .base import BasePromptBuilder

class DeepSeekPromptBuilder(BasePromptBuilder):
    """Builder dla DeepSeek z własnym suffixem profili"""
    
    @property
    def PROFILE_SUFFIX(self) -> str:
        return "deep"  # Sufix dla plików deepseek

    def build_prompt(self, context: str, question: str, profile: str = "turing") -> str:
        system_prompt = self._load_and_prepare_profile(profile)
        return (
            f"{system_prompt}\n"
            f"### Context\n{context.strip() or '(no context)'}\n"
            f"### User Question\n{question.strip()}\n"
            f"### Response:"
        )