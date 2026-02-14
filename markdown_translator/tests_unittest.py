import unittest


class _EchoTranslator:
    def translate(self, text: str) -> str:
        # Fake translator: marks translated regions without altering protected placeholders.
        return "PL(" + text + ")"


class MarkdownToPolishTranslatorTests(unittest.TestCase):
    def test_preserves_fenced_code_blocks(self):
        from markdown_translator.translator import MarkdownToPolishTranslator

        tr = MarkdownToPolishTranslator(translator=_EchoTranslator())
        md = "Hello\n```python\nprint('hi')\n```\nWorld\n"
        out = tr.translate_markdown(md)
        self.assertIn("```python\nprint('hi')\n```", out)

    def test_protects_inline_code_and_urls(self):
        from markdown_translator.translator import MarkdownToPolishTranslator

        tr = MarkdownToPolishTranslator(translator=_EchoTranslator())
        md = "Use `Class Foo` at https://example.com/x\n"
        out = tr.translate_markdown(md)
        self.assertIn("`Class Foo`", out)
        self.assertIn("https://example.com/x", out)

    def test_does_not_translate_markdown_link_urls(self):
        from markdown_translator.translator import MarkdownToPolishTranslator

        tr = MarkdownToPolishTranslator(translator=_EchoTranslator())
        md = "See [docs](https://example.com/docs)\n"
        out = tr.translate_markdown(md)
        self.assertIn("(https://example.com/docs)", out)

    def test_preserves_empty_lines_and_heading_prefix(self):
        from markdown_translator.translator import MarkdownToPolishTranslator

        tr = MarkdownToPolishTranslator(translator=_EchoTranslator())
        md = "Line1\n\n## Evidence\n\nLine2\n"
        out = tr.translate_markdown(md)
        self.assertIn("\n\n", out)
        self.assertIn("## ", out)

    def test_prefix_template_keeps_prefix_and_translates_remainder(self):
        from markdown_translator.translator import MarkdownToPolishTranslator
        from markdown_translator.templates import load_templates_config, default_templates_path

        tr = MarkdownToPolishTranslator(translator=_EchoTranslator())
        md = ">⚠️  Search-limit note: Hello world\n"
        out = tr.translate_markdown(md)
        # prefix is deterministic (from templates.json) and the remainder is translated via the translator.
        cfg = load_templates_config(default_templates_path())
        prefix_pl = cfg.templates[0].pl
        self.assertTrue(out.startswith(prefix_pl))
        self.assertIn("PL(Hello world)", out)


if __name__ == "__main__":
    unittest.main()
