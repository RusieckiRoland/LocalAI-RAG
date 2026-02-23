import re
from dotnet_summarizer.code_compressor import compress_chunks


# --- helpers ---

def mk_chunk(path: str, content: str, *, member: str | None = None, ns: str | None = None,
             cls: str | None = None, hit_lines: list[int] | None = None,
             start: int | None = None, end: int | None = None, rank: int | None = None):
    return {
        "path": path,
        "content": content,
        "member": member,
        "namespace": ns,
        "class": cls,
        "hit_lines": hit_lines,
        "start_line": start,
        "end_line": end,
        "rank": rank,
    }


SIMPLE_CS = (
    "using System;\n"
    "#region region\n#endregion\n"
    "#pragma warning disable\n"
    "[Obsolete]\n"
    "namespace Demo {\n"
    "  public class C {\n"
    "    /// xml doc\n"
    "    // line comment\n"
    "    public void Initialize() { /* block */ Console.WriteLine(\"x\"); }\n"
    "  }\n"
    "}\n"
)


def test_metadata_dedup_by_path():
    chunks = [
        mk_chunk("a/C.cs", SIMPLE_CS, member="Initialize"),
        mk_chunk("a/C.cs", SIMPLE_CS, member="Other"),  # same path, different member
    ]
    out = compress_chunks(chunks, mode="metadata", token_budget=2000)
    # path appears only once in headers
    assert out.splitlines().count(next(iter({c['path'] for c in chunks}))) == 0  # path is inside each header line, check by contains
    path = "a/C.cs"
    assert sum(1 for line in out.splitlines() if path in line) == 1
    # no code fences in metadata mode
    assert "```" not in out


def test_two_chunks_same_snippet_only_one_code_block():
    # Different paths but identical content → two headers, one code block
    chunks = [
        mk_chunk("a/C1.cs", SIMPLE_CS, member="Initialize", hit_lines=[8]),
        mk_chunk("b/C2.cs", SIMPLE_CS, member="Initialize", hit_lines=[8]),
    ]
    out = compress_chunks(chunks, mode="snippets", token_budget=5000)
    # two headers
    assert sum(1 for l in out.splitlines() if "a/C1.cs" in l) == 1
    assert sum(1 for l in out.splitlines() if "b/C2.cs" in l) == 1
    # only one fenced code block emitted (dedup by snippet hash)
    assert out.count("```") == 2  # one open + one close total


def test_token_budget_trims_snippet():
    big = "\n".join(f"// c{i}\npublic void M{i}() {{ }}" for i in range(200))
    chunks = [mk_chunk("big/C.cs", big, member="M1", hit_lines=[10])]
    # very small budget: we at least keep the header;
    # snippet may be dropped completely to stay within the token budget.
    out = compress_chunks(chunks, mode="snippets", token_budget=80)

    # We require non-empty output and preserved header line.
    assert out.strip() != ""
    assert out.startswith("- big/C.cs : M1")



def test_keep_http_urls_but_strip_line_comments():
    src = (
        "public class W {\n"
        "  // remove me\n"
        "  string u = \"http://example.com//path\"; // real comment\n"
        "  string s = \"https://x//y\"; // end\n"
        "}\n"
    )
    out = compress_chunks([mk_chunk("w.cs", src, member="W", hit_lines=[1, 3])], mode="snippets", token_budget=1000)
    code = out[out.find("```")+3: out.rfind("```")]
    assert "http://example.com//path" in code
    assert "https://x//y" in code
    assert "remove me" not in code
    assert "real comment" not in code


def test_strip_attrs_usings_regions_pragmas():
    out = compress_chunks([mk_chunk("c.cs", SIMPLE_CS, member="Initialize", hit_lines=[8])], mode="snippets", token_budget=1000)
    code = out[out.find("```")+3: out.rfind("```")]
    assert "using System;" not in code
    assert "#region" not in code and "#pragma" not in code
    assert "[Obsolete]" not in code
    assert "xml doc" not in code


def test_two_stage_headers_only():
    out = compress_chunks([mk_chunk("x.cs", SIMPLE_CS, member="Initialize")], mode="two_stage", token_budget=1000)
    assert "```" not in out
    assert "x.cs" in out


def test_empty_input_returns_empty_string():
    assert compress_chunks([], mode="metadata") == ""


def test_header_span_formatting():
    chunks = [mk_chunk("h.cs", "class H{}", ns="Acme.App", cls="H", member="M", start=10, end=20)]
    out = compress_chunks(chunks, mode="metadata")
    # Expect (L10-20) in header
    assert "(L10-20)" in out
