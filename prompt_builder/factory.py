from pathlib import Path
from .base import BasePromptBuilder

def get_prompt_builder(model_path: str) -> BasePromptBuilder:
    """
    Fabryka rozpoznająca typ modelu na podstawie ścieżki.
    Obsługuje ścieżki w formacie:
    - .../codeLlama[_\-]... → CodellamaPromptBuilder
    - .../deepseek[_\-]... → DeepSeekPromptBuilder
    """
    # Normalizacja ścieżki (zamiana \ na / i lowercase)
    normalized_path = str(model_path).lower().replace('\\', '/')
    
    # Rozpoznawanie modelu
    if 'codellama' in normalized_path or 'llama' in normalized_path:
        from .codellama import CodellamaPromptBuilder
        return CodellamaPromptBuilder()
    
    if 'deepseek' in normalized_path:
        from .deepseek import DeepSeekPromptBuilder
        return DeepSeekPromptBuilder()
    
    # Domyślny builder z ostrzeżeniem
    import warnings
    warnings.warn(
        f"Unrecognized model path: {model_path}. Defaulting to CodeLlama builder.",
        RuntimeWarning
    )
    from .codellama import CodellamaPromptBuilder
    return CodellamaPromptBuilder()