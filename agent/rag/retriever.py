import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9\+\#]+")

class EdTechRAGRetriever:
    """Fast hybrid TF-IDF cosine + keyword-boost retriever for sub-5ms voice RAG."""

    def __init__(self, kb_path: Path | None = None):
        self.kb_path = kb_path or Path(__file__).parent / "knowledge_base.json"
        self.docs: list[dict[str, Any]] = json.loads(self.kb_path.read_text(encoding="utf-8"))
        self.doc_tokens: list[Counter[str]] = []
        self.idf: dict[str, float] = {}
        self._build_index()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return TOKEN_RE.findall(text.lower())

    def _build_index(self) -> None:
        df: Counter[str] = Counter()
        for doc in self.docs:
            combined = f"{doc['title']} {' '.join(doc['keywords'])} {doc['content']}"
            counts = Counter(self._tokenize(combined))
            self.doc_tokens.append(counts)
            for term in counts:
                df[term] += 1
        n = len(self.docs)
        self.idf = {term: math.log((n + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

    def _tfidf_vec(self, counts: Counter[str]) -> dict[str, float]:
        total = sum(counts.values()) or 1
        return {t: (c / total) * self.idf.get(t, 1.0) for t, c in counts.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        norm_a = math.sqrt(sum(v * v for v in a.values())) or 1e-9
        norm_b = math.sqrt(sum(v * v for v in b.values())) or 1e-9
        return dot / (norm_a * norm_b)

    def search(self, query: str, top_k: int = 2) -> list[dict[str, Any]]:
        q_tokens = self._tokenize(query)
        q_vec = self._tfidf_vec(Counter(q_tokens))
        q_lower = query.lower()

        scored: list[tuple[float, dict[str, Any]]] = []
        for doc, d_counts in zip(self.docs, self.doc_tokens):
            d_vec = self._tfidf_vec(d_counts)
            cos_sim = self._cosine(q_vec, d_vec)
            kw_hits = sum(1 for kw in doc["keywords"] if kw in q_lower)
            score = cos_sim + (0.22 * kw_hits)
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": doc["id"],
                "title": doc["title"],
                "score": round(score, 3),
                "content": doc["content"],
            }
            for score, doc in scored[:top_k]
        ]
