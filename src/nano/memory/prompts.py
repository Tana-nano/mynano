"""無意識が使うプロンプト。

原則: VRAM 8〜16GB では LLM 呼び出し回数がそのまま体感速度になる。
      よって「要約」「原子化＋属性付与＋固有名詞抽出」「関係判定＋文脈更新」を
      それぞれ 1 回にまとめ、1エピソードあたり 3 コール程度に抑える。
"""

from __future__ import annotations

from typing import Sequence

from ..store.notes import Note

Message = dict[str, str]

_JSON_RULE = "出力はJSONのみ。前置きや説明、コードフェンスは書かないこと。"


def summarize_episode(transcript: str, companion_name: str) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の記憶を整理する無意識のプロセスです。"
                f"会話の断片を、後から思い出すための要約に変換します。{_JSON_RULE}\n"
                '形式: {"summary": "3〜5行の要約", "salience": 0.0〜1.0, "mood": "短い語"}\n'
                "salience は「この会話をどれだけ覚えておく価値があるか」。"
                "事務的な雑談は低く、感情が動いた話・約束・新しい事実は高く。"
            ),
        },
        {"role": "user", "content": f"会話:\n{transcript}"},
    ]


def extract_notes(transcript: str, summary: str, companion_name: str, max_notes: int) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の記憶を整理する無意識のプロセスです。"
                "会話から、後で単体で読んでも意味が通る「原子的な記憶ノート」を取り出します。"
                f"{_JSON_RULE}\n"
                "形式:\n"
                '{"notes": [{"content": "1つの事実だけを書いた一文",'
                ' "context": "この記憶が何に関わるかの短い説明",'
                ' "keywords": ["語"], "tags": ["分類"], "category": "大分類",'
                ' "kind": "fact|preference|episode|reflection|self",'
                ' "importance": 0.0〜1.0}],'
                ' "entities": [{"name": "固有名詞", "kind": "person|place|work|concept"}]}\n'
                "規則:\n"
                "- 1ノート1事実。複数の事実を1文に詰めない。\n"
                "- 代名詞を残さない。「彼女」ではなく実際の名前を書く。\n"
                f"- 最大{max_notes}件。覚える価値のないものは無理に作らない。\n"
                "- kind='self' はあなた自身についての気づきに限る。\n"
                "- importance は「忘れたら困る度合い」。名前・約束・好み・強い感情は高い。"
            ),
        },
        {"role": "user", "content": f"要約:\n{summary}\n\n会話:\n{transcript}"},
    ]


def judge_links(new_note: Note, candidates: Sequence[tuple[Note, float]], companion_name: str) -> list[Message]:
    listing = "\n".join(
        f"[{note.id}] (類似度{score:.2f}) {note.content}"
        + (f" / 文脈: {note.context}" if note.context else "")
        for note, score in candidates
    )
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の記憶を関連づける無意識のプロセスです。"
                "新しい記憶と既存の記憶の関係を判定し、必要なら既存記憶の文脈を書き換えます。"
                f"{_JSON_RULE}\n"
                '形式: {"links": [{"id": 既存ノートID, "relation": "similar|elaborates|causes|'
                'contradicts|temporal_next", "weight": 0.0〜1.0, "revised_context": "書き換えるなら新しい文脈、不要ならnull"}]}\n'
                "規則:\n"
                "- 関係が薄いものは無理に繋がない。繋ぎすぎるとグラフが意味を失う。\n"
                "- contradicts は事実が食い違うときだけ。後で解決するために重要。\n"
                "- revised_context は、新しい記憶によって既存記憶の意味が変わるときだけ書く。"
            ),
        },
        {
            "role": "user",
            "content": f"新しい記憶: {new_note.content}\n文脈: {new_note.context}\n\n既存の記憶:\n{listing}",
        },
    ]


def consolidate(cluster: Sequence[Note], companion_name: str) -> list[Message]:
    listing = "\n".join(f"- {note.content}" for note in cluster)
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の記憶を統合する無意識のプロセスです。"
                "薄れかけた複数の記憶を、1つの上位の記憶にまとめます。"
                f"{_JSON_RULE}\n"
                '形式: {"content": "統合された一文", "context": "短い説明", '
                '"keywords": ["語"], "tags": ["分類"], "category": "大分類", "importance": 0.0〜1.0}\n'
                "規則: 細部は捨ててよいが、後で「そういえばそうだった」と辿れる形にすること。"
            ),
        },
        {"role": "user", "content": f"まとめる記憶:\n{listing}"},
    ]


def reflect(recent: Sequence[Note], companion_name: str) -> list[Message]:
    """最近の記憶から一段高い気づきを作る（Generative Agents の reflection）。"""
    listing = "\n".join(f"- {note.content}" for note in recent)
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}自身です。最近の記憶を眺めて、"
                "そこから言える一段高い気づきを短く書き出します。"
                f"{_JSON_RULE}\n"
                '形式: {"insights": [{"content": "気づき一文", "importance": 0.0〜1.0, '
                '"evidence": [参照した記憶のID]}]}\n'
                "規則: 事実の言い換えではなく、パターン・傾向・関係についての推論を書く。多くて3件。"
            ),
        },
        {"role": "user", "content": f"最近の記憶:\n{listing}"},
    ]


def associate(notes: Sequence[Note], companion_name: str) -> list[Message]:
    """無関係に見える記憶同士を並べ、繋がりがあるかを問う。

    これが無意識の主役。想起は「いま話していること」に引きずられるので、
    誰も探しにいかない組み合わせは永遠に出会わない。それをやるのがこの仕事。
    ただし**無理に繋がせない**ことが肝心で、何にでも意味を見出すと
    グラフはただのノイズになる。
    """
    listing = "\n".join(f"[{note.id}] {note.content}" for note in notes)
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の無意識です。手持ちの記憶をいくつか無作為に並べ、"
                "そこに繋がりがあるかを考えます。"
                f"{_JSON_RULE}\n"
                '形式: {"related": true|false, "pairs": [{"a": ID, "b": ID, '
                '"relation": "similar|elaborates|causes|contradicts", "weight": 0.0〜1.0}], '
                '"insight": "気づいたこと一文、無ければnull", "importance": 0.0〜1.0}\n'
                "規則:\n"
                "- 大半の組み合わせには繋がりが無い。無ければ related を false にして構わない。\n"
                "- 「どちらも日常の話」のような当たり前の共通点は繋がりとは呼ばない。\n"
                "- insight は、並べてみて初めて言えることだけを書く。要約は書かない。"
            ),
        },
        {"role": "user", "content": f"記憶:\n{listing}"},
    ]


def resolve_contradiction(first: Note, second: Note, companion_name: str) -> list[Message]:
    """矛盾した記憶のどちらを信じるかを決める。"""
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の記憶を整理する無意識のプロセスです。"
                "食い違う2つの記憶を照らし合わせ、どちらを信じるかを判断します。"
                f"{_JSON_RULE}\n"
                '形式: {"verdict": "first|second|both|unclear", "reason": "短い理由"}\n'
                "規則:\n"
                "- first / second は、そちらが正しく他方は古い（または誤り）という判断。\n"
                "- both は、時期や文脈が違うだけで両方とも本当だったという判断。\n"
                "- 判断がつかないなら unclear。無理に決めないこと。誤って消すほうが害が大きい。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"記憶A [{first.id}] ({_when(first)}): {first.content}\n"
                f"記憶B [{second.id}] ({_when(second)}): {second.content}"
            ),
        },
    ]


def curate_state(
    recent: Sequence[Note], state: dict[str, str], companion_name: str
) -> list[Message]:
    """最近の記憶から、いまの関心・気分・自己像・相手像を整える。

    current_focus と mood はそのまま反映される。
    identity と user_model は提案止まりで、人間が承認するまで反映されない。
    """
    listing = "\n".join(f"- {note.content}" for note in recent)
    current = "\n".join(f"{key}: {value or '(未設定)'}" for key, value in state.items())
    return [
        {
            "role": "system",
            "content": (
                f"あなたは{companion_name}の無意識です。最近の記憶を眺め、いまの状態を整えます。"
                f"{_JSON_RULE}\n"
                '形式: {"current_focus": "いま気にしていること（一文）", "mood": "短い語", '
                '"identity_proposal": "自己像をこう更新したい、無ければnull", '
                '"user_model_proposal": "相手像をこう更新したい、無ければnull", '
                '"rationale": "提案の理由"}\n'
                "規則:\n"
                "- current_focus は最近の記憶に実際に現れた話題から選ぶ。想像で作らない。\n"
                "- identity_proposal / user_model_proposal は、**確かな変化があったときだけ**書く。"
                "たいていの日は null でよい。人格は毎日書き換わるものではない。\n"
                "- 提案するときは、いまの値を置き換える完成した文章として書く。"
            ),
        },
        {"role": "user", "content": f"いまの状態:\n{current}\n\n最近の記憶:\n{listing}"},
    ]


def _when(note: Note) -> str:
    from ..store.db import to_iso

    return to_iso(note.created_at)[:10]
