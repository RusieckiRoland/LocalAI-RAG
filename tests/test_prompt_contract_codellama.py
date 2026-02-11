import pytest

from prompt_builder.codellama import CodellamaPromptBuilder

def _pairs_to_dialog(pairs):
    dialog = []
    for u, a in pairs:
        dialog.append({"role": "user", "content": u})
        dialog.append({"role": "assistant", "content": a})
    return dialog



def _compose_model_formatted_text(*, context: str, question: str) -> str:
    ctx = context.strip() if str(context or "").strip() else "(none)"
    # This mimics "pipeline composed text" (builder must not invent sections).
    return (
        "### Context:\n"
        f"{ctx}\n\n"
        "### User:\n"
        f"{question}\n\n"
        "### Answer:"
    )


@pytest.mark.parametrize(
    "context,history_pairs,question,expected",
    [
        # 1) no context, no history -> SYS is attached to the current user message
        (
            "",
            [],
            "Where is the entry point?",
            "[INST]\n"
            "<<SYS>>\nSYS\n<</SYS>>\n\n"
            "### Context:\n(none)\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 2) context present, no history (braces must be escaped in user payload)
        (
            "File: Program.cs\nstatic void Main() {}",
            [],
            "Where is the entry point?",
            "[INST]\n"
            "<<SYS>>\nSYS\n<</SYS>>\n\n"
            "### Context:\nFile: Program.cs\nstatic void Main() {}\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 3) no context, history present -> SYS goes into the FIRST history user turn
        (
            "",
            [("hi", "hello")],
            "Where is the entry point?",
            "[INST] <<SYS>>\nSYS\n<</SYS>>\n\nhi [/INST] hello\n"
            "[INST]\n"
            "### Context:\n(none)\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 4) context + history present
        (
            "File: Program.cs\nstatic void Main() {}",
            [("hi", "hello")],
            "Where is the entry point?",
            "[INST] <<SYS>>\nSYS\n<</SYS>>\n\nhi [/INST] hello\n"
            "[INST]\n"
            "### Context:\nFile: Program.cs\nstatic void Main() {}\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
    ],
)
def test_codellama_prompt_contract_variants(context, history_pairs, question, expected):
    b = CodellamaPromptBuilder()

    model_formatted_text = _compose_model_formatted_text(context=context, question=question)

    prompt = b.build_prompt(
        modelFormatedText=model_formatted_text,
        history=_pairs_to_dialog(history_pairs),
        system_prompt="SYS",
)


    assert prompt == expected

    # Extra guard: absolutely forbid bound-method leakage into the prompt
    assert "<bound method" not in prompt
