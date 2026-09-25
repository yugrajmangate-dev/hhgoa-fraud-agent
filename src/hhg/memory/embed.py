"""Deterministic lexical embedding: hashed unigram+bigram TF-IDF, L2-normalised.

Honestly a lexical (bag-of-words) embedding, not a neural one: offline, reproducible,
and adequate for the templated closed-case narratives. Hashing uses SHA-1 so it is
stable across processes (Python's hash() is salted).
"""

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

DIM = 512
_TOKEN = re.compile(r"[a-z]+|\$?\d+(?:\.\d+)?")


def tokens(text: str) -> list:
    words = _TOKEN.findall(text.lower())
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def bucket(tok: str) -> int:
    return int.from_bytes(hashlib.sha1(tok.encode("utf-8")).digest()[:4], "big") % DIM


def fit_idf(corpus: list) -> np.ndarray:
    df = np.zeros(DIM)
    for text in corpus:
        for b in {bucket(t) for t in tokens(text)}:
            df[b] += 1
    return np.log((1 + len(corpus)) / (1 + df)) + 1.0


def embed(text: str, idf: np.ndarray) -> np.ndarray:
    v = np.zeros(DIM)
    for t in tokens(text):
        v[bucket(t)] += 1.0
    v = np.where(v > 0, 1.0 + np.log(np.maximum(v, 1.0)), 0.0) * idf
    norm = math.sqrt(float(v @ v))
    return v / norm if norm else v


def save_idf(idf: np.ndarray, path: Path):
    path.write_text(json.dumps({"dim": DIM, "idf": [round(float(x), 6) for x in idf]}), encoding="utf-8")


def load_idf(path: Path) -> np.ndarray:
    return np.array(json.loads(path.read_text(encoding="utf-8"))["idf"])


def to_field(v: np.ndarray) -> str:
    """Serialise for a TigerGraph LIST<DOUBLE> loaded with SPLIT(..., ';')."""
    return ";".join(f"{x:.6f}" for x in v)
