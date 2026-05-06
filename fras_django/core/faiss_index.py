"""
FAISS index management: build, save, load, search.
Ported from src/enroll.py and src/recognize.py.
Uses IndexFlatIP with L2-normalised float32 embeddings → inner product = cosine similarity.
"""

import os

import faiss
import numpy as np


def build_and_save(embeddings: list[np.ndarray], index_path: str) -> faiss.Index:
    """Build a new FAISS index from a list of 512-d embeddings and save to disk."""
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    matrix = np.stack(embeddings).astype(np.float32)
    index  = faiss.IndexFlatIP(512)
    index.add(matrix)
    faiss.write_index(index, index_path)
    return index


def load_index(index_path: str) -> faiss.Index | None:
    """Load an existing FAISS index from disk. Returns None if not found."""
    if not os.path.exists(index_path):
        return None
    return faiss.read_index(index_path)


def search(index: faiss.Index, embedding: np.ndarray, k: int = 1):
    """
    Search for the k nearest neighbours.
    Returns (similarities, faiss_indices) — both shape (k,).
    similarity is cosine similarity (higher = better match).
    """
    emb = embedding.astype(np.float32).reshape(1, -1)
    distances, indices = index.search(emb, k)
    return distances[0], indices[0]
