"""埋め込み。1024次元（multilingual-e5-large 既定）。

次元数を config で固定しているのは、モデルを差し替えても
既存の soul.db が読めなくならないようにするため。次元を変える＝全再埋め込み。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

import httpx

from . import vectors


class Embedder(Protocol):
    dim: int

    @property
    def identity(self) -> str:
        """このベクトル空間の名前。`<モデル名>@<次元数>`。

        異なるモデルで作ったベクトルを同じ空間で比べても意味は無い。
        魂にこの文字列を記録しておき、起動時に照合する。
        これが無いと、モデルを差し替えた瞬間に記憶が静かに壊れる。
        """
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass
class ServerEmbedder:
    """OpenAI 互換 /embeddings。llama-server --embedding などを想定。"""

    base_url: str
    model: str = "multilingual-e5-large"
    dim: int = 1024
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    api_key: str = ""
    timeout_s: float = 120.0
    batch_size: int = 16

    def __post_init__(self) -> None:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers=headers,
            timeout=self.timeout_s,
            # HTTP_PROXY などの環境変数を読みに行かせない。相手は自分のマシン
            # （か、せいぜい家の LAN）なので、プロキシを通す理由が無い。
            # 通してしまうと、会社支給のマシンなどで localhost 宛てまでプロキシに
            # 回され、「llama-server に繋がらない」という嘘のエラーになる（実測）。
            trust_env=False,
        )

    @property
    def identity(self) -> str:
        return f"{self.model}@{self.dim}"

    def close(self) -> None:
        self._client.close()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([self.passage_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.query_prefix + text])[0]

    def _embed(self, inputs: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(inputs), self.batch_size):
            batch = list(inputs[start : start + self.batch_size])
            try:
                response = self._client.post(
                    "/embeddings", json={"model": self.model, "input": batch}
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"cannot reach embedder at {self.base_url}: {exc}") from exc
            items = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
            for item in items:
                vector = item["embedding"]
                if len(vector) != self.dim:
                    raise RuntimeError(
                        f"embedding dim mismatch: got {len(vector)}, config says {self.dim}. "
                        "次元を変えるなら既存ノートの再埋め込みが必要です。"
                    )
                out.append(vectors.normalize(vector))
        return out


@dataclass
class HashEmbedder:
    """外部サーバー無しで動く決定的な埋め込み（文字n-gramのハッシュ化）。

    テストとオフライン開発のためのもの。意味の理解はしないが、
    文字の重なりに応じた妥当な類似度を返すので、記憶パイプラインの
    配線を検証するには十分。本番では ServerEmbedder に差し替える。
    """

    dim: int = 1024
    query_prefix: str = ""
    passage_prefix: str = ""

    @property
    def identity(self) -> str:
        # 実機の埋め込みと混ざらないよう、はっきり別の名前を名乗る
        return f"hash@{self.dim}"

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        normalized = " ".join(text.lower().split())
        grams = [normalized[i : i + n] for n in (2, 3) for i in range(len(normalized) - n + 1)]
        grams += normalized.split()
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        return vectors.normalize(vector)


def build_embedder(config) -> Embedder:
    """config.embed から実体を作る。base_url が空なら offline 扱い。"""
    if not config.base_url:
        return HashEmbedder(dim=config.dim)
    return ServerEmbedder(
        base_url=config.base_url,
        model=config.model,
        dim=config.dim,
        query_prefix=config.query_prefix,
        passage_prefix=config.passage_prefix,
        timeout_s=config.timeout_s,
    )
