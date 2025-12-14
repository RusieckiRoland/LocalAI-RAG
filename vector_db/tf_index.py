# File: vector_db/tf_index.py

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Any

import numpy as np

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

def _split_camel(token: str) -> List[str]:
    # Split CamelCase identifiers into sub-tokens.
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", token)
    parts = spaced.split()
    return parts if parts else [token]

def tokenize_for_tf(text: str) -> List[str]:
    # Tokenizer tuned for code + SQL identifiers.
    if not text:
        return []
    raw = _TOKEN_RE.findall(text)
    out: List[str] = []
    for t in raw:
        out.append(t.lower())
        for p in _split_camel(t):
            pl = p.lower()
            if pl != out[-1]:
                out.append(pl)
    return [t for t in out if len(t) >= 2]


def build_tf_index(texts: List[str], out_dir: str) -> None:
    """
    Build a portable inverted index aligned with FAISS row order:
    doc_id == row index in texts/metadata/FAISS.
    """
    os.makedirs(out_dir, exist_ok=True)

    postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)  # term -> [(doc_id, tf), ...]
    df: Dict[str, int] = defaultdict(int)
    doc_len = np.zeros((len(texts),), dtype=np.int32)

    for doc_id, text in enumerate(texts):
        toks = tokenize_for_tf(text)
        doc_len[doc_id] = len(toks)
        if not toks:
            continue

        counts = Counter(toks)
        for term, tf in counts.items():
            postings[term].append((doc_id, int(tf)))
            df[term] += 1

    terms = sorted(postings.keys())  # deterministic
    vocab = {t: i for i, t in enumerate(terms)}
    V = len(terms)

    offsets = np.zeros((V + 1,), dtype=np.int64)
    total_postings = 0
    for i, t in enumerate(terms):
        offsets[i] = total_postings
        total_postings += len(postings[t])
    offsets[V] = total_postings

    doc_ids = np.zeros((total_postings,), dtype=np.int32)
    tfs = np.zeros((total_postings,), dtype=np.int16)
    df_arr = np.zeros((V,), dtype=np.int32)

    p = 0
    for i, t in enumerate(terms):
        plist = postings[t]
        df_arr[i] = int(df[t])
        for (d, tf) in plist:
            doc_ids[p] = d
            tfs[p] = tf if tf <= 32767 else 32767
            p += 1

    avgdl = float(doc_len.mean()) if len(doc_len) else 0.0

    with open(os.path.join(out_dir, "tf_vocab.json"), "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)

    np.save(os.path.join(out_dir, "tf_offsets.npy"), offsets)
    np.save(os.path.join(out_dir, "tf_doc_ids.npy"), doc_ids)
    np.save(os.path.join(out_dir, "tf_tfs.npy"), tfs)
    np.save(os.path.join(out_dir, "tf_df.npy"), df_arr)
    np.save(os.path.join(out_dir, "tf_doc_len.npy"), doc_len)

    meta = {
        "format": "tf_inverted_index_v1",
        "tokenizer": "regex_camel_v1",
        "doc_count": int(len(texts)),
        "vocab_size": int(V),
        "avgdl": avgdl,
    }
    with open(os.path.join(out_dir, "tf_index_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_tf_index(index_dir: str) -> Dict[str, Any]:
    with open(os.path.join(index_dir, "tf_vocab.json"), "r", encoding="utf-8") as f:
        vocab = json.load(f)

    offsets = np.load(os.path.join(index_dir, "tf_offsets.npy"))
    doc_ids = np.load(os.path.join(index_dir, "tf_doc_ids.npy"))
    tfs = np.load(os.path.join(index_dir, "tf_tfs.npy"))
    df_arr = np.load(os.path.join(index_dir, "tf_df.npy"))
    doc_len = np.load(os.path.join(index_dir, "tf_doc_len.npy"))

    with open(os.path.join(index_dir, "tf_index_meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)

    return {
        "vocab": vocab,
        "offsets": offsets,
        "doc_ids": doc_ids,
        "tfs": tfs,
        "df": df_arr,
        "doc_len": doc_len,
        "meta": meta,
    }


def bm25_search(tf_index: Dict[str, Any], query: str, top_k: int = 20, *, k1: float = 1.2, b: float = 0.75) -> List[Tuple[int, float]]:
    """
    Returns: list of (doc_id, score) sorted desc.
    doc_id is FAISS row index => maps 1:1 to unified_metadata[doc_id].
    """
    vocab = tf_index["vocab"]
    offsets = tf_index["offsets"]
    doc_ids = tf_index["doc_ids"]
    tfs = tf_index["tfs"].astype(np.float32)
    df_arr = tf_index["df"]
    doc_len = tf_index["doc_len"].astype(np.float32)

    N = int(tf_index["meta"]["doc_count"])
    avgdl = float(tf_index["meta"]["avgdl"]) or 1.0

    q_terms = tokenize_for_tf(query)
    if not q_terms or N <= 0:
        return []

    # Use unique terms to avoid double-work (classic BM25 sums terms anyway;
    # if you want query term frequency impact, you can multiply by q_tf).
    q_counts = Counter(q_terms)

    scores = np.zeros((N,), dtype=np.float32)

    for term, q_tf in q_counts.items():
        tid = vocab.get(term)
        if tid is None:
            continue

        df = float(df_arr[int(tid)])
        # Common BM25 idf variant
        idf = np.log(1.0 + (N - df + 0.5) / (df + 0.5))

        start = int(offsets[int(tid)])
        end = int(offsets[int(tid) + 1])
        if end <= start:
            continue

        docs = doc_ids[start:end]
        tf = tfs[start:end]

        dl = doc_len[docs]
        denom = tf + k1 * (1.0 - b + b * (dl / avgdl))
        contrib = idf * (tf * (k1 + 1.0) / denom)

        # Optional: apply query term frequency
        if q_tf > 1:
            contrib = contrib * float(q_tf)

        np.add.at(scores, docs, contrib)

    if top_k <= 0:
        top_k = 1
    top_k = min(int(top_k), N)

    # Fast top-k
    idx = np.argpartition(scores, -top_k)[-top_k:]
    idx = idx[np.argsort(scores[idx])[::-1]]

    return [(int(i), float(scores[i])) for i in idx if scores[i] > 0.0]
