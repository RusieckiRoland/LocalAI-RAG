import pytest

from prompt_builder.codellama import CodellamaPromptBuilder


@pytest.mark.parametrize(
    "context,history,question,template,expected",
    [
        # 1) no context, no history
        (
            "",
            "",
            "Where is the entry point?",
            "### Context:\n{context}\n\n### User:\n{question}\n\n### Answer:\n",
            "[INST]<<SYS>>\n\nSYS\n\n<</SYS>>\n\n"
            "### Context:\n(none)\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 2) context present, no history
        (
            "File: Program.cs\nstatic void Main() {}",
            "",
            "Where is the entry point?",
            "### Context:\n{context}\n\n### User:\n{question}\n\n### Answer:\n",
            "[INST]<<SYS>>\n\nSYS\n\n<</SYS>>\n\n"
            "### Context:\nFile: Program.cs\nstatic void Main() {{}}\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 3) no context, history present
        (
            "",
            "User: hi\nAssistant: hello",
            "Where is the entry point?",
            "### Context:\n{context}\n\n### History:\n{history}\n\n### User:\n{question}\n\n### Answer:\n",
            "[INST]<<SYS>>\n\nSYS\n\n<</SYS>>\n\n"
            "### Context:\n(none)\n\n"
            "### History:\nUser: hi\nAssistant: hello\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
        # 4) context + history present
        (
            "File: Program.cs\nstatic void Main() {}",
            "User: hi\nAssistant: hello",
            "Where is the entry point?",
            "### Context:\n{context}\n\n### History:\n{history}\n\n### User:\n{question}\n\n### Answer:\n",
            "[INST]<<SYS>>\n\nSYS\n\n<</SYS>>\n\n"
            "### Context:\nFile: Program.cs\nstatic void Main() {{}}\n\n"
            "### History:\nUser: hi\nAssistant: hello\n\n"
            "### User:\nWhere is the entry point?\n\n"
            "### Answer:\n"
            "[/INST]",
        ),
    ],
)
def test_codellama_prompt_contract_variants(context, history, question, template, expected):
    b = CodellamaPromptBuilder()

    prompt = b.build_prompt(
        context=context,
        question=question,
        history=history,
        profile="irrelevant_for_test",
        system_prompt="SYS",
        template=template,
    )

    assert prompt == expected

    # Extra guard: absolutely forbid bound-method leakage into the prompt
    assert "<bound method" not in prompt
