"""train/masking.py — completion-only loss の境界計算。

train/ は nano の外（別 venv、torch 前提）だが、この境界計算だけは標準ライブラリで書いてあり、
ここから検査する。理由は docs/finetune.md §5(b): **マスクの間違いは静かに通る。**
学習は普通に走って loss も下がり、あとで「妹の名前」を重みが覚えている。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TRAIN = Path(__file__).resolve().parents[1] / "train"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TRAIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass が from __future__ annotations を解決するのに要る
    spec.loader.exec_module(module)
    return module


masking = _load("masking")


def test_prompt_tokens_are_ignored_and_answer_tokens_are_kept():
    prompt = [1, 2, 3, 4]
    full = [1, 2, 3, 4, 10, 11, 12]
    encoded = masking.split_prompt_and_answer(prompt, full)
    assert encoded.input_ids == full
    assert encoded.labels == [masking.IGNORE] * 4 + [10, 11, 12]
    assert encoded.answer_tokens == 3


def test_a_prompt_that_is_not_a_prefix_is_refused():
    """テンプレートの境界がずれていたら止める。黙って通すと記憶側に loss が乗る。"""
    with pytest.raises(masking.MaskError, match="食い違って"):
        masking.split_prompt_and_answer([1, 2, 9], [1, 2, 3, 4, 5])


def test_an_empty_answer_is_refused():
    with pytest.raises(masking.MaskError):
        masking.split_prompt_and_answer([1, 2, 3], [1, 2, 3])


def test_too_long_rows_are_dropped_not_truncated():
    encoded = masking.split_prompt_and_answer([1, 2], [1, 2, 3, 4, 5])
    assert masking.fits(encoded, 5)
    assert not masking.fits(encoded, 4)


def test_generation_matches_the_dataset_rule():
    """dataset.py の Sample.generation と同じ規則で世代を読むこと。"""
    assert masking.generation_of({"model": "local", "adapter": ""}) == "local"
    assert masking.generation_of({"model": "local", "adapter": "nano-v1@0.7"}) == "local+nano-v1@0.7"
    assert masking.generation_of({}) == ""


class _FakeTokenizer:
    """1文字=1トークン。chat template は role ごとに [role]…[/role] を挟む。"""

    def apply_chat_template(self, messages, add_generation_prompt=False, tokenize=True):
        text = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in messages)
        if add_generation_prompt:
            text += "<assistant>"
        return [ord(ch) for ch in text] if tokenize else text

    def __call__(self, text):
        return {"input_ids": [ord(ch) for ch in text]}


def test_prepare_drops_by_length_and_reports_generations(tmp_path, monkeypatch, capsys):
    """prepare.py の落とし方。切らずに行ごと落とし、落とした数と世代の内訳を出す。"""
    prepare = _load("prepare")
    monkeypatch.setattr(prepare, "load_tokenizer", lambda name: _FakeTokenizer())

    source = tmp_path / "soul" / "export" / "train"
    source.mkdir(parents=True)
    rows = [
        {"messages": [{"role": "system", "content": "憲章"}, {"role": "user", "content": "q"},
                      {"role": "assistant", "content": "短い"}],
         "meta": {"model": "local", "adapter": ""}},
        {"messages": [{"role": "system", "content": "憲章 思い出したこと " * 20}, {"role": "user", "content": "q"},
                      {"role": "assistant", "content": "長い"}],
         "meta": {"model": "local", "adapter": "nano-v1"}},
    ]
    (source / "sft.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (source / "orpo.jsonl").write_text("", encoding="utf-8")

    out = tmp_path / "work"
    code = prepare.main(["--soul", str(tmp_path / "soul"), "--tokenizer", "fake", "--max-seq-len", "80", "--out", str(out)])
    assert code == 0
    stats = json.loads((out / "prepare.json").read_text(encoding="utf-8"))
    assert stats["sft"] == {"kept": 1, "dropped_too_long": 1, "dropped_no_answer": 0}
    assert stats["generations"] == {"local": 1, "local+nano-v1": 1}
    kept = [json.loads(l) for l in (out / "sft.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kept[0]["messages"][-1]["content"] == "短い", "落とすのは行ごと。残った行は無傷"
    printed = capsys.readouterr().out
    assert "世代内訳" in printed and "落とした 1 件" in printed
