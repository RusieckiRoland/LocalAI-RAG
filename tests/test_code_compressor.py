import re
import textwrap
import pytest

from dotnet_summarizer.code_compressor import compress_chunks

# NOTE: This is a fully FICTITIOUS sample log in a "FAISS-like" style.
# It does NOT reuse any of your code or names. Purely invented for tests.
FAISS_STYLE_LOG = textwrap.dedent(
    """
    [Context 1]
        * Rank 1 | File: QrScannerEngine.cs | ID: 5001 (Distance: 0.8421)
        // Namespace: AcmeApp.Devices.QrScanner.Core // Class: QrScannerEngine // Type: Method  

                #region Boot
                /// boots the engine
                public void Boot(object host)
                {
                    // prep internal state
                    Prepare();
                    var container = host as IHostSurface;
                    if (container != null)
                    {
                        container.AttachChild(ScannerControl);
                        ScannerControl.OnReady += HandleReady;
                        StartLoop();
                    }
                    this.ScannerControl.OnFrame += this.OnFrame;
                }

          * Dependencies:
            -> QrScannerEngine.cs | Prepare (Method)
               private void Prepare() { _buffer = null; }

            -> QrScannerEngine.cs | StartLoop (Method)
               public void StartLoop() { /* run loop */ }

        * Rank 2 | File: QrScannerUiSkin.cs | ID: 5002 (Distance: 0.8530)
        // Namespace: AcmeApp.Devices.QrScanner.UI // Class: UiSkin // Type: Method  
                public void DrawDefault()
                {
                    // fake drawing API
                    Ui.SetLayer(Layer.Background);
                    Ui.Clear();
                    Ui.SetLayer(Layer.Foreground);
                    Ui.DrawRect(10, 10, 200, 120);
                }

        * Rank 3 | File: QrScannerControl.cs | ID: 5003 (Distance: 0.8455)
        // Namespace: AcmeApp.Devices.QrScanner.Core // Class: QrScannerControl // Type: Constructor  
                [ImportingConstructor]
                public QrScannerControl(IBackend svc)
                {
                    View = new ScannerView();
                    Device = View.Model?.Device;
                    if (Device != null) { Device.LogSink = svc.LogSink; }
                }

        * Rank 4 | File: QrScannerEngine.cs | ID: 5004 (Distance: 0.8599)
        // Namespace: AcmeApp.Devices.QrScanner.Core // Class: QrScannerEngine // Type: Method  
                private void Stop()
                {
                    if (ScannerControl.Active) ScannerControl.Stop();
                    else { ScannerControl.DisableInput(); ScannerControl.Clear(); }
                    ClearHotspots();
                }
    """
)


def _parse_faiss_log_to_chunks(log: str):
    """Tiny parser for the invented FAISS-like log used in tests.
    Pulls path, namespace, class, first method name, and code block.
    It intentionally avoids any real project nomenclature.
    """
    chunks = []
    # Split on rank markers
    for block in re.split(r"\n\s*\*\s*Rank\s*\d+\s*\|", log):
        block = block.strip()
        if not block or block.startswith("[Context"):
            continue
        block = "File:" + block  # restore prefix for regex simplicity
        m = re.search(
            r"File:\s*([^|]+)\s*\|.*?\n\s*//\s*Namespace:\s*([^/]+)\s*//\s*Class:\s*([^/]+)",
            block,
        )
        if not m:
            continue
        path = m.group(1).strip()
        namespace = m.group(2).strip()
        cls = m.group(3).strip()

        code = block.split("\n", 2)[-1]
        code = re.split(r"\n\s*\*\s*Dependencies:\n", code)[0]  # drop deps

        mm = re.search(r"\b(public|private|internal|protected)\s+[^\(\)\n]+?\s+(\w+)\s*\(", code)
        member = mm.group(2) if mm else None

        lines = code.splitlines()
        hit = None
        if member:
            for i, ln in enumerate(lines, start=1):
                if member in ln:
                    hit = i
                    break

        chunks.append({
            "path": path,
            "namespace": namespace,
            "class": cls,
            "member": member,
            "start_line": 1,
            "end_line": len(lines),
            "content": code,
            "hit_lines": [hit] if hit else None,
        })
    return chunks


def test_metadata_compaction_is_short_and_includes_paths():
    chunks = _parse_faiss_log_to_chunks(FAISS_STYLE_LOG)
    out = compress_chunks(chunks, mode="metadata", token_budget=300, max_chunks=3)
    lines = [l for l in out.strip().splitlines() if l.strip()]
    # Only headers, no code fences in metadata mode
    assert all(not l.startswith("```") for l in lines)
    # Each header should contain a path and a symbol
    assert any("QrScannerEngine.cs" in l for l in lines)
    assert any("QrScannerUiSkin.cs" in l for l in lines)


def test_snippets_strip_comments_regions_and_usings():
    chunks = _parse_faiss_log_to_chunks(FAISS_STYLE_LOG)
    out = compress_chunks(chunks, mode="snippets", token_budget=600, window=10, max_chunks=1, language="csharp")
    assert "#region" not in out
    assert "///" not in out
    # Dependencies section should not leak into snippet
    assert "Dependencies:" not in out


def test_windowing_keeps_method_body_near_hits():
    chunks = _parse_faiss_log_to_chunks(FAISS_STYLE_LOG)
    out = compress_chunks(chunks, mode="snippets", token_budget=400, window=5, max_chunks=1)
    # Should still contain the Boot signature but be relatively short
    assert "public void Boot(" in out
    assert len(out.splitlines()) < 80


def test_token_budget_is_enforced():
    chunks = _parse_faiss_log_to_chunks(FAISS_STYLE_LOG)
    tiny = compress_chunks(chunks, mode="snippets", token_budget=120, window=8, max_chunks=2, per_chunk_hard_cap=40)
    # Very small output; must contain at least one header line
    assert "QrScannerEngine.cs" in tiny
    # And should not explode beyond budget (rough heuristic by length)
    assert len(tiny) < 120 * 6  # chars ≈ tokens*4, with some buffer


def test_dedup_by_path_and_member():
    chunks = _parse_faiss_log_to_chunks(FAISS_STYLE_LOG)
    if chunks:
        chunks.insert(1, dict(chunks[0]))  # duplicate first
    out = compress_chunks(chunks, mode="metadata", token_budget=500, max_chunks=10)
    first_path = chunks[0]["path"]
    count = sum(1 for l in out.splitlines() if first_path in l)
    assert count == 1  # appears once


def test_generic_language_cleanup_python():
    py_chunk = {
        "path": "module.py",
        "namespace": "",
        "class": "",
        "member": "foo",
        "start_line": 1,
        "end_line": 7,
        "content": """
# leading comment
# another

def foo(x):
    # inside
    return x+1
""",
        "hit_lines": [4],
    }
    out = compress_chunks([py_chunk], mode="snippets", token_budget=200, language="python")
    # Comments should be stripped inside snippet
    assert "# leading comment" not in out
    assert "another" not in out
    assert "# inside" not in out
    assert "def foo(" in out

def test_clean_python_keeps_hash_in_strings():
    """
    Ensure that the Python cleaner does NOT remove '#' that appear inside string literals.
    """
    py_chunk = {
        "path": "module2.py",
        "namespace": "",
        "class": "",
        "member": "bar",
        "start_line": 1,
        "end_line": 5,
        "content": '''
def bar():
    s = "print('# not a comment')"
    return s
''',
        "hit_lines": [2],
    }

    out = compress_chunks([py_chunk], mode="snippets", token_budget=200, language="python")

    # '#' inside a string literal must be preserved
    assert "# not a comment" in out

    # but no real comment lines should remain
    assert re.search(r"^\s*#", out, flags=re.MULTILINE) is None
