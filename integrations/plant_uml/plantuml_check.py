from __future__ import annotations
import zlib
import re
import json
import os

from common.utils import sanitize_uml_answer
from constants import UML_CONSULTANT

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

# Repo root is assumed to be three levels up from this file.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _cfg = json.load(f)
else:
    _cfg = {}

# If missing in config.json, PLANTUML_SERVER will be None.
PLANTUML_SERVER: str | None = (_cfg.get("plantuml_server") or None)


# ---------------------------------------------------------------------------
# PlantUML encoding helpers
# ---------------------------------------------------------------------------

def encode_plantuml(text: str) -> str:
    """
    Compress and encode PlantUML text to the URL-safe format expected by the server.

    Implementation follows PlantUML's "deflate raw" + custom 64 alphabet approach:
    - zlib-compress,
    - strip the first 2 bytes (zlib header) and the last 4 bytes (Adler32),
    - encode with PlantUML's base64-like alphabet.
    """
    data = text.encode("utf-8")
    compressed = zlib.compress(data)[2:-4]  # raw DEFLATE payload
    return _encode_base64_plantuml(compressed)


def _encode_base64_plantuml(data: bytes) -> str:
    """
    PlantUML custom base64 encoder (0-9A-Za-z-_), 6 bits per character.
    """
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
    res = []
    buffer = 0
    bits_left = 0

    for b in data:
        buffer = (buffer << 8) | b
        bits_left += 8
        while bits_left >= 6:
            bits_left -= 6
            res.append(alphabet[(buffer >> bits_left) & 0x3F])

    if bits_left > 0:
        res.append(alphabet[(buffer << (6 - bits_left)) & 0x3F])

    return "".join(res)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_plant_link(final_answer: str, consultant: str) -> str:
    """
    Append a link to an online PlantUML rendering of the FIRST diagram found.

    Conditions:
    - `consultant` must match `UML_CONSULTANT` (case-insensitive).
    - The text must contain an '@startuml ... @enduml' diagram (case-insensitive).
    - `plantuml_server` must be specified in config.json.

    Behavior:
    - Extract the first diagram via regex (non-greedy).
    - Build a canonical Markdown answer with `sanitize_uml_answer(...)`.
    - Append an HTML link (<a target="_blank">) pointing to '{server}/uml/{encoded}'.

    Returns the original `final_answer` if any condition is not met.
    """
    if not isinstance(final_answer, str) or not final_answer.strip():
        return final_answer

    # Consultant gate (case-insensitive)
    if not isinstance(consultant, str) or consultant.lower() != str(UML_CONSULTANT).lower():
        return final_answer

    if not PLANTUML_SERVER:
        # No server configured → keep original
        return final_answer

    # Find the first diagram block, case-insensitive, DOTALL
    match = re.search(r"@startuml.*?@enduml", final_answer, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return final_answer

    diagram = match.group(0)

    # Encode for server
    encoded = encode_plantuml(diagram)

    # Normalize/clean the answer (canonical fenced block etc.)
    normalized = sanitize_uml_answer(final_answer)

    # Ensure we don't end up with a double slash
    server = PLANTUML_SERVER.rstrip("/")
    link = f"{server}/uml/{encoded}"

    # HTML anchor for target=_blank (Markdown link syntax has no target attribute)
    return f'{normalized}\n\n<a href="{link}" target="_blank">Open UML Diagram</a>'


# ---------------------------------------------------------------------------
# Local smoke test (kept minimal and side-effect free for library use)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = """
    ### Diagram
    ```plantuml
    @startuml
    Bob -> Alice : hello
    Alice -> Bob : reply
    @enduml
    ```
    """
    # Example: only adds link if constants.UML_CONSULTANT == "escher"
    out = add_plant_link(sample, "escher")
    print(out)
