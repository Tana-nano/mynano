"""readme-draft.md: "what you need / what's included" for the product's manual."""

from __future__ import annotations

from .archive import InputRecord
from .checks import Analysis, is_junk, kinds_text
from .known import KnownAssets

NONE = "（検出されませんでした）"
# ndmf is written as part of Modular Avatar when both are needed.
_MERGED_INTO = {"ndmf": "modular-avatar"}


def render_draft(inputs: list[InputRecord], analysis: Analysis, known: KnownAssets) -> str:
    L = ["# （商品名）導入に必要なもの・同梱物【下書き】", "",
         "> この下書きは出品前チェッカーが unitypackage の中身から作りました。内容を確認して書き直してから使ってください。", ""]

    need = [i for i in analysis.required if not (i in _MERGED_INTO and _MERGED_INTO[i] in analysis.required)]
    L.append("## 導入に必要なもの")
    L += [f"- {known.ids[i].draft}" for i in need] or [NONE]
    L.append("")

    packages = [p.name for r in inputs for p in r.packages]
    steps = []
    if need:
        steps.append("「導入に必要なもの」を先に入れてください（シェーダー → ツールの順）。")
    if analysis.common_packages:
        steps.append(f"先に共通のパッケージ（{'、'.join(analysis.common_packages)}）をインポートしてください。")
    rest = [n for n in packages if n not in analysis.common_packages]
    if len(rest) > 1:
        steps.append("お使いのアバターに対応した unitypackage をインポートしてください。")
    elif rest:
        steps.append(f"{rest[0]} をインポートしてください。")
    steps.append("（ここに着せ方を書いてください）")
    L.append("## 導入手順")
    L += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    L.append("")

    L += ["## 同梱物", "| ファイル | 内容 |", "|---|---|"]
    for r in inputs:
        if r.zip is None:
            for p in r.packages:
                L.append(f"| {p.name} | {kinds_text(analysis.summaries[p.name])} |")
            continue
        for p in r.packages:
            L.append(f"| {p.name} | {kinds_text(analysis.summaries[p.name])} |")
        for f in r.zip.files:
            if not is_junk(f.name):
                L.append(f"| {f.name} | |")
    L.append("")

    L.append("## 同梱していないもの")
    missing = [i for i in analysis.not_bundled if not (i in _MERGED_INTO and _MERGED_INTO[i] in analysis.not_bundled)]
    L += [f"- {known.name(i)} 本体（上の入手先から導入してください）" for i in missing] or [NONE]
    return "\n".join(L) + "\n"
