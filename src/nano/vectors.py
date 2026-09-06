"""ベクトル演算とその永続表現。

numpy があれば使い、無ければ純Pythonで同じ結果を返す。
「10年後も動く」ために、numpy を必須依存にはしない。
埋め込みは float32 のリトルエンディアン列（= BLOB）として保存する。
これは numpy にも array モジュールにも読める、最も素朴で長寿な形式。
"""

from __future__ import annotations

import array
import math
from typing import Sequence

try:  # pragma: no cover - 環境依存の分岐
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

Vector = Sequence[float]


def pack(vector: Vector) -> bytes:
    buffer = array.array("f", vector)
    if array.array("f").itemsize != 4:  # pragma: no cover - 実質ありえない
        raise RuntimeError("float32 array unavailable on this platform")
    import sys

    if sys.byteorder == "big":  # pragma: no cover
        buffer.byteswap()
    return buffer.tobytes()


def unpack(blob: bytes) -> list[float]:
    buffer = array.array("f")
    buffer.frombytes(blob)
    import sys

    if sys.byteorder == "big":  # pragma: no cover
        buffer.byteswap()
    return list(buffer)


def normalize(vector: Vector) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return list(vector)
    return [value / norm for value in vector]


def cosine(a: Vector, b: Vector) -> float:
    """正規化済みベクトル同士なら内積と一致する。未正規化でも正しく動く。"""
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def similarities(query: Vector, matrix: Sequence[Vector]) -> list[float]:
    """1対多のコサイン類似度。行列は正規化済みを前提としない。"""
    if not matrix:
        return []
    if _np is not None:
        q = _np.asarray(query, dtype=_np.float32)
        m = _np.asarray(matrix, dtype=_np.float32)
        q_norm = float(_np.linalg.norm(q)) or 1.0
        m_norms = _np.linalg.norm(m, axis=1)
        m_norms[m_norms == 0.0] = 1.0
        return (m @ q / (m_norms * q_norm)).tolist()
    return [cosine(query, row) for row in matrix]


def centroid(vectors: Sequence[Vector]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    total = [0.0] * dim
    for vector in vectors:
        for index, value in enumerate(vector):
            total[index] += value
    return normalize([value / len(vectors) for value in total])
