"""実機に載せる前の点検。

実機で初めて動かすとき、詰まる順番はだいたい決まっている。
llama-server が立っていない → 次元が config と違う → キャリブレーションを飛ばした
→ ⭐ を集め始めてからベースラインが無いことに気づく。

これらを1回ずつエラーで踏むと、そのたびに調べ直すことになる。
まとめて見て、直す順番ごと出す。

ここでは**何も直さない**。直し方は書くが、実行はしない。
魂に触る操作（`nano reembed` など）を点検の副作用でやると、
一番壊れてほしくないものが、一番不注意な瞬間に壊れる。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import calibration as calibration_module
from .config import Config
from .embed import HashEmbedder, build_embedder
from .llm import LLMError, LlamaServerLLM
from .persona.drift import baseline_path, load_baseline, usable_baseline
from .store import identity as identity_store
from .store import jobs as jobs_store
from .store import stars as stars_store
from .store.db import Database, to_iso

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARKS = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Finding:
    status: str
    title: str
    detail: str = ""
    remedy: str = ""

    def render(self) -> str:
        lines = [f"{_MARKS[self.status]} {self.title}"]
        if self.detail:
            lines.append(f"    {self.detail}")
        if self.remedy:
            lines.append(f"    → {self.remedy}")
        return "\n".join(lines)


@dataclass
class Report:
    findings: list[Finding]

    @property
    def failed(self) -> int:
        return sum(1 for finding in self.findings if finding.status == FAIL)

    @property
    def warned(self) -> int:
        return sum(1 for finding in self.findings if finding.status == WARN)

    def render(self) -> str:
        body = "\n".join(finding.render() for finding in self.findings)
        if self.failed:
            tail = f"\n{self.failed} 件、先に直す必要があります。"
        elif self.warned:
            tail = f"\n{self.warned} 件、気に留めておくところがあります。動かすことはできます。"
        else:
            tail = "\n問題なし。`nano chat` を始められます。"
        return body + "\n" + tail


def run(config: Config) -> Report:
    findings = [_paths(config)]
    db = Database(config.db_path)
    try:
        findings.append(_soul(db))
        findings += _llm(config)
        embed_finding, live_identity = _embedder(config)
        findings.append(embed_finding)
        findings.append(_identity(db, live_identity))
        findings.append(_calibration(config, live_identity))
        findings.append(_baseline(config, live_identity))
        findings.append(_link_density(db))
        findings.append(_jobs(db))
        findings += _environment()
    finally:
        db.close()
    return Report(findings)


def _paths(config: Config) -> Finding:
    return Finding(OK, "設定", f"魂: {config.soul_dir}　憲章: {config.constitution_path}")


def _soul(db: Database) -> Finding:
    notes = db.scalar("SELECT COUNT(*) FROM notes") or 0
    events = db.scalar("SELECT COUNT(*) FROM events") or 0
    stars = stars_store.counts(db)
    return Finding(
        OK,
        "魂",
        f"生ログ {events} / 記憶 {notes} / ⭐ {stars['keep']}（✗ {stars['avoid']}）",
    )


def _llm(config: Config) -> list[Finding]:
    if not config.llm.base_url:
        return [Finding(WARN, "対話モデル", "base_url が空です（オフライン運用）")]
    client = LlamaServerLLM(
        base_url=config.llm.base_url,
        model=config.llm.model,
        api_key=config.llm.api_key,
        # 点検なので短く諦める。応答が遅いこと自体は別の話。
        timeout_s=min(config.llm.timeout_s, 30.0),
    )
    started = time.monotonic()
    try:
        answer = client.chat(
            [{"role": "user", "content": "「はい」とだけ答えてください。"}],
            task="doctor",
            temperature=0.0,
            max_tokens=16,
        )
    except LLMError as error:
        return [
            Finding(
                FAIL,
                "対話モデル",
                str(error)[:200],
                f"llama-server を {config.llm.base_url} で起動しているか確認する",
            )
        ]
    finally:
        client.close()
    elapsed = time.monotonic() - started
    return [
        Finding(
            OK,
            "対話モデル",
            f"{config.llm.base_url} 応答あり（{elapsed:.1f}秒 / {answer[:40]!r}）",
        )
    ]


def _embedder(config: Config) -> tuple[Finding, str]:
    embedder = build_embedder(config.embed)
    if isinstance(embedder, HashEmbedder):
        return (
            Finding(WARN, "埋め込みモデル", "base_url が空なのでハッシュ埋め込みです（オフライン運用）"),
            embedder.identity,
        )
    try:
        vector = embedder.embed_query("点検")
    except RuntimeError as error:
        message = str(error)
        if "dim mismatch" in message:
            return (
                Finding(
                    FAIL,
                    "埋め込みモデル",
                    message[:200],
                    "config.toml の [embed] dim をモデルに合わせる"
                    "（既に記憶があるなら nano reembed が要ります）",
                ),
                embedder.identity,
            )
        return (
            Finding(
                FAIL,
                "埋め込みモデル",
                message[:200],
                f"llama-server --embedding を {config.embed.base_url} で起動しているか確認する",
            ),
            embedder.identity,
        )
    finally:
        closer = getattr(embedder, "close", None)
        if callable(closer):
            closer()
    return (
        Finding(OK, "埋め込みモデル", f"{embedder.identity} 応答あり（{len(vector)}次元）"),
        embedder.identity,
    )


def _identity(db: Database, live_identity: str) -> Finding:
    recorded = identity_store.recorded(db)
    vectors = identity_store.vector_count(db)
    if not recorded:
        return Finding(OK, "埋め込み同一性", f"未記録（最初の記憶を書いた時点で {live_identity} が記録されます）")
    if recorded == live_identity:
        return Finding(OK, "埋め込み同一性", f"{recorded}（ベクトル {vectors} 件）")
    return Finding(
        FAIL,
        "埋め込み同一性",
        f"魂は {recorded} で作られていますが、いまの設定は {live_identity} です"
        f"（ベクトル {vectors} 件）",
        "nano reembed で埋め直すか、config.toml を元のモデルに戻す。"
        "混ぜると想起が静かに壊れます",
    )


def _calibration(config: Config, live_identity: str) -> Finding:
    measured = calibration_module.load(config, live_identity)
    if measured is None:
        return Finding(
            FAIL,
            "キャリブレーション",
            "未測定。しきい値が config.toml の絶対値のまま使われます",
            "nano calibrate（コサインの絶対値はモデルごとに帯が違うので、"
            "飛ばすと連想と統合が両方おかしくなります）",
        )
    return Finding(
        OK,
        "キャリブレーション",
        f"{to_iso(measured.measured_at)[:10]} 実測"
        f"（{measured.source} / {measured.similarity.n} ペア）",
    )


def _baseline(config: Config, live_identity: str) -> Finding:
    """基準が「在るか」ではなく「いまの構成で使えるか」を診る。

    `--offline` で一度でも probe を回すとハッシュ埋め込みの基準ができる。
    在ることだけを見ていると、それを持ったまま実機に載せて、
    別空間のベクトルどうしを比べた数字を人格のずれとして読むことになる。
    """
    baseline = load_baseline(config)
    if baseline is None:
        return Finding(
            WARN,
            "人格ベースライン",
            "未取得。ドリフトを測る基準がありません",
            "nano probe --save-baseline（これが無いと nano dataset が止まります）",
        )
    unusable = usable_baseline(config, live_identity) if live_identity else ""
    if unusable:
        return Finding(
            FAIL,
            "人格ベースライン",
            unusable.splitlines()[0],
            "nano probe --save-baseline（いまのモデルで取り直す）",
        )
    measured = baseline.conditions
    detail = f"{baseline.created[:10] or '取得日不明'} / 対話 {measured.llm or '不明'}"
    if measured.adapter:
        detail += f" + {measured.adapter}"
    return Finding(OK, "人格ベースライン", detail)


def _link_density(db: Database) -> Finding:
    notes = db.scalar("SELECT COUNT(*) FROM notes") or 0
    if not notes:
        return Finding(OK, "リンク密度", "まだ記憶がありません")
    links = db.scalar("SELECT COUNT(*) FROM links WHERE relation != 'temporal_next'") or 0
    per_note = links / notes
    if per_note > 10:
        return Finding(
            FAIL,
            "リンク密度",
            f"1記憶あたり {per_note:.1f} 本。繋がりすぎで、グラフが何も語らなくなっています",
            "config.toml の [pipeline] link_max_per_note を下げる（既定3）",
        )
    return Finding(OK, "リンク密度", f"1記憶あたり {per_note:.1f} 本")


def _jobs(db: Database) -> Finding:
    failures = jobs_store.recent_failures(db)
    if not failures:
        return Finding(OK, "無意識のジョブ", "最近の失敗はありません")
    latest = failures[0]
    return Finding(
        WARN,
        "無意識のジョブ",
        f"{len(failures)} 件失敗しています。直近: {latest['kind']} — {latest['last_error'][:80]}",
        "nano jobs で詳しく見る",
    )


def _environment() -> list[Finding]:
    proxies = [name for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY") if os.environ.get(name)]
    if not proxies:
        return []
    return [
        Finding(
            OK,
            "プロキシ設定",
            f"{', '.join(proxies)} が設定されていますが、nano は無視して直接繋ぎます",
        )
    ]
