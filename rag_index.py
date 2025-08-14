# rag_index.py
from __future__ import annotations
import math
import os
import re
from dataclasses import dataclass
from typing import List, Tuple, Dict, Iterable, Optional

_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_PUNCT_RE = re.compile(r"[^\w@#\-/]+")

def _strip_html(s: str) -> str:
    return _TAG_RE.sub(" ", s)

def _normalize(s: str) -> str:
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    return _WHITESPACE_RE.sub(" ", s).strip()

def _sentences(text: str) -> List[str]:
    # simple sentence splitter
    parts = re.split(r"(?<=[\.\!\?])\s+(?=[A-Z0-9])", text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) > 0:
            out.append(p)
    return out

@dataclass
class DocChunk:
    doc_id: int
    chunk_id: int
    title: str
    text: str
    url: Optional[str] = None

class BM25Lite:
    """
    Lightweight BM25 (k1,b tuned conservatively).
    """
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: Dict[int, int] = {}
        self.avgdl: float = 0.0
        self.df: Dict[str, int] = {}
        self.postings: Dict[str, Dict[int, int]] = {}  # term -> {chunk_id -> tf}
        self.chunks: Dict[int, DocChunk] = {}
        self._built = False

    def add(self, chunk: DocChunk):
        cid = chunk.chunk_id
        self.chunks[cid] = chunk
        terms = _normalize(chunk.text).split()
        self.doc_len[cid] = len(terms)
        seen = set()
        tf: Dict[str, int] = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1
        for t, c in tf.items():
            if t not in self.postings:
                self.postings[t] = {}
            self.postings[t][cid] = c
            if t not in seen:
                self.df[t] = self.df.get(t, 0) + 1
                seen.add(t)

    def build(self):
        if not self.doc_len:
            self.avgdl = 0.0
        else:
            self.avgdl = sum(self.doc_len.values()) / len(self.doc_len)
        self._built = True

    def _idf(self, term: str) -> float:
        N = max(1, len(self.doc_len))
        df = self.df.get(term, 0)
        return math.log(1 + (N - df + 0.5) / (df + 0.5))

    def score(self, query: str, top_k: int = 3) -> List[Tuple[float, int]]:
        assert self._built, "Call build() before score()"
        q_terms = _normalize(query).split()
        scores: Dict[int, float] = {}
        for qt in q_terms:
            plist = self.postings.get(qt)
            if not plist:
                continue
            idf = self._idf(qt)
            for cid, tf in plist.items():
                dl = self.doc_len[cid] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1)))
                s = idf * (tf * (self.k1 + 1) / denom)
                scores[cid] = scores.get(cid, 0.0) + s
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(s, cid) for cid, s in ranked[:top_k]]

def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _read_any(path: str) -> str:
    raw = _read_text_file(path)
    if path.lower().endswith(".html"):
        return _strip_html(raw)
    return raw

def _chunk_by_sentences(text: str, max_chars: int = 600) -> List[str]:
    sents = _sentences(text)
    chunks, buf = [], ""
    for s in sents:
        if len(buf) + 1 + len(s) <= max_chars:
            buf = f"{buf} {s}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = s
    if buf:
        chunks.append(buf)
    return chunks

class LocalRAG:
    """
    Build a tiny local index over one or more files.
    """
    def __init__(self):
        self.idx = BM25Lite()
        self._next_doc_id = 1
        self._next_chunk_id = 1

    def add_file(self, path: str, title: Optional[str] = None, url: Optional[str] = None, max_chars: int = 600):
        if not os.path.exists(path):
            return
        doc_id = self._next_doc_id
        self._next_doc_id += 1
        title = title or os.path.basename(path)

        text = _read_any(path)
        for chunk_text in _chunk_by_sentences(text, max_chars=max_chars):
            cid = self._next_chunk_id
            self._next_chunk_id += 1
            self.idx.add(DocChunk(doc_id=doc_id, chunk_id=cid, title=title, text=chunk_text, url=url))

    def add_snippet(self, title: str, text: str, url: Optional[str] = None):
        doc_id = self._next_doc_id
        self._next_doc_id += 1
        cid = self._next_chunk_id
        self._next_chunk_id += 1
        self.idx.add(DocChunk(doc_id=doc_id, chunk_id=cid, title=title, text=text, url=url))

    def build(self):
        self.idx.build()

    def search(self, query: str, top_k: int = 3) -> List[DocChunk]:
        pairs = self.idx.score(query, top_k=top_k)
        out: List[DocChunk] = []
        for _, cid in pairs:
            ch = self.idx.chunks.get(cid)
            if ch:
                out.append(ch)
        return out
