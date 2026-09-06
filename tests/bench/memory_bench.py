"""記憶ベンチ — 記憶の品質を数字にする。

重みや半減期をいじると、体感では良くなったのか悪くなったのか分からなくなる。
そこで合成した会話を流し込み、時間を進めながら質問して測る。

測るのは2つ。どちらか片方だけでは不十分:
  1. 想起率  — 覚えているべきことを、後から思い出せるか
  2. 忘却率  — 忘れていいことを、ちゃんと忘れているか（＝ただの全部保存になっていないか）

    python tests/bench/memory_bench.py            # オフラインのスタブで
    python tests/bench/memory_bench.py --online   # 実際のローカルLLM/埋め込みで
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from nano.app import App  # noqa: E402
from nano.config import Config, PathsConfig, load_config  # noqa: E402
from nano.memory.retrieve import recall  # noqa: E402
from nano.store import events as events_store  # noqa: E402
from nano.store import notes as notes_store  # noqa: E402

DAY = 86400.0

# 覚えているべきこと。会話の中に自然に埋めてある。
FACTS: list[tuple[str, str, str]] = [
    ("妹の名前はミオで、高校2年生", "妹の名前は？", "ミオ"),
    ("ミオは吹奏楽部でトランペットを吹いている", "妹は何の楽器？", "トランペット"),
    ("飼っている猫の名前はクロ、今年で12歳になる", "猫の名前は？", "クロ"),
    ("クロは黒猫ではなくキジトラ", "クロはどんな柄の猫？", "キジトラ"),
    ("父は札幌に住んでいて、年に二回だけ会う", "父はどこに住んでいる？", "札幌"),
    ("好きな作家は伊坂幸太郎で、特にラッシュライフが好き", "好きな作家は？", "伊坂"),
    ("コーヒーは苦手で、飲むのはいつも紅茶", "コーヒーは好き？", "紅茶"),
    ("来月の12日に引っ越しをする予定", "引っ越しはいつ？", "12日"),
    ("職場は代々木で、家からは電車で25分かかる", "職場はどこ？", "代々木"),
    ("学生のときは弓道をやっていた", "学生時代の部活は？", "弓道"),
    ("いちばん苦手なのは電話をかけること", "苦手なことは？", "電話"),
    ("母の誕生日は3月8日", "母の誕生日は？", "3月8日"),
]

# 忘れていいこと。30日後にも全部残っているなら、それは忘却が働いていない。
TRIVIA = [
    "今日の昼は冷やし中華にした",
    "electron の更新が来ていたので入れた",
    "コンビニでレシートをもらい忘れた",
    "帰り道で信号にちょうど引っかかった",
    "ペンのインクが切れたので替えた",
    "テレビをつけたけどすぐ消した",
    "冷蔵庫の製氷皿を洗った",
    "靴紐がほどけたので結び直した",
]


@dataclass
class BenchResult:
    at_days: int
    hits: int = 0
    total: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


@dataclass
class BenchReport:
    recall_results: list[BenchResult]
    trivia_active: int
    trivia_total: int
    facts_active: int
    facts_total: int
    notes_total: int

    @property
    def forgetting_rate(self) -> float:
        """雑事のうち能動インデックスから外れた割合。高いほど「忘れられている」。"""
        if not self.trivia_total:
            return 0.0
        return 1.0 - self.trivia_active / self.trivia_total

    def render(self) -> str:
        lines = ["=== 記憶ベンチ ===", f"ノート総数: {self.notes_total}", ""]
        lines.append("想起率（覚えているべきことを思い出せるか）")
        for result in self.recall_results:
            lines.append(f"  {result.at_days:>3}日後: {result.rate:5.1%} ({result.hits}/{result.total})")
            for miss in result.misses:
                lines.append(f"        × {miss}")
        lines.append("")
        lines.append("忘却（忘れていいことを忘れているか）")
        lines.append(
            f"  雑事: {self.trivia_total - self.trivia_active}/{self.trivia_total} が非アクティブ "
            f"= 忘却率 {self.forgetting_rate:.1%}"
        )
        lines.append(
            f"  重要: {self.facts_active}/{self.facts_total} がアクティブのまま "
            "（こちらは高いままであってほしい）"
        )
        return "\n".join(lines)


def seed_conversation(app: App, base_ts: float) -> None:
    """会話を過去に遡って流し込む。エピソードは記録された時刻で作られる。"""
    session = "bench"
    ts = base_ts
    statements = [statement for statement, _, _ in FACTS]
    # 事実と雑事を混ぜる。実際の会話も大事な話だけでは進まない。
    interleaved: list[str] = []
    for index, statement in enumerate(statements):
        interleaved.append(statement)
        if index < len(TRIVIA):
            interleaved.append(TRIVIA[index])

    for text in interleaved:
        events_store.append(app.db, session, events_store.ROLE_USER, text, ts=ts)
        events_store.append(app.db, session, events_store.ROLE_COMPANION, "そうなんだ", ts=ts + 1)
        ts += 300.0  # 5分おき


def measure_recall(app: App, at: float, days: int) -> BenchResult:
    result = BenchResult(at_days=days, total=len(FACTS))
    for _, question, answer in FACTS:
        found = recall(
            app.db,
            app.index,
            app.embedder,
            question,
            app.config.retrieval,
            app.config.decay,
            at=at,
            touch=False,
        )
        if any(answer in item.note.content for item in found.items):
            result.hits += 1
        else:
            result.misses.append(f"{question} → {answer}")
    return result


def run(app: App, base_ts: float, checkpoints: tuple[int, ...] = (0, 7, 30, 90)) -> BenchReport:
    seed_conversation(app, base_ts)
    app.ingest()

    results = []
    for days in checkpoints:
        at = base_ts + days * DAY
        # 時間を進めるたびに忘却処理を通す（実運用の日次ジョブに相当）
        app.run_decay(at=at)
        results.append(measure_recall(app, at, days))

    active = notes_store.iter_notes(app.db, states=(notes_store.STATE_ACTIVE,))
    all_notes = notes_store.iter_notes(
        app.db,
        states=(notes_store.STATE_ACTIVE, notes_store.STATE_COLD, notes_store.STATE_MERGED),
    )

    def contains_any(note, phrases) -> bool:
        return any(phrase[:8] in note.content for phrase in phrases)

    trivia_notes = [note for note in all_notes if contains_any(note, TRIVIA)]
    fact_notes = [note for note in all_notes if contains_any(note, [f for f, _, _ in FACTS])]

    return BenchReport(
        recall_results=results,
        trivia_active=sum(1 for note in trivia_notes if note.state == notes_store.STATE_ACTIVE),
        trivia_total=len(trivia_notes),
        facts_active=sum(1 for note in fact_notes if note.state == notes_store.STATE_ACTIVE),
        facts_total=len(fact_notes),
        notes_total=len(all_notes),
    )


def build_app(tmp_dir: Path, online: bool, config_path: str | None) -> App:
    if online:
        config = load_config(config_path)
        config.paths.soul_dir = str(tmp_dir / "soul")
        return App.build(config, offline=False)
    config = Config(root=tmp_dir, paths=PathsConfig(soul_dir="soul"))
    return App.build(config, offline=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="記憶ベンチ")
    parser.add_argument("--online", action="store_true", help="実際のローカルLLM/埋め込みを使う")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    import tempfile
    import time

    with tempfile.TemporaryDirectory() as tmp:
        app = build_app(Path(tmp), args.online, args.config)
        try:
            report = run(app, base_ts=time.time() - 120 * DAY)
            print(report.render())
        finally:
            app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
