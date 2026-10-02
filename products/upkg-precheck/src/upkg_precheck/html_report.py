"""report.html: the same results as report.txt, laid out for reading in a browser.

Self-contained (inline CSS, no scripts, no external files) so it works offline and sends nothing.
Like report.txt it names input files only, never full paths.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from . import classify as cl
from .archive import InputRecord
from .checks import GREEN, RED, YELLOW, Analysis, Finding, human_size, kinds_text, verdict
from .known import ORDER, KnownAssets
from .report import header

VISIBLE_EXAMPLES = 3
_SECTIONS = ((RED, "red", "出す前に直すもの"), (YELLOW, "yellow", "確認するもの"), (GREEN, "green", "情報"))

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2129;--muted:#5c6470;--line:#dde1e7;
--red:#c62828;--red-bg:#fdecec;--yellow:#a15c00;--yellow-bg:#fff4dc;--green:#2e7d32;--green-bg:#e8f5e9;
--code:#eef0f3}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--card:#20242a;--text:#e6e8eb;--muted:#a0a7b1;--line:#343a42;
--red:#ff8a80;--red-bg:#3a1f1f;--yellow:#ffcc66;--yellow-bg:#3a3020;--green:#81c784;--green-bg:#1f3322;--code:#2b3038}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.7 "Yu Gothic UI","Meiryo","Hiragino Sans",system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
header p{margin:0;color:var(--muted);font-size:13px}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:17px;margin:32px 0 12px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.verdict{margin:20px 0;padding:18px 20px;border-radius:10px;border:2px solid;font-size:19px;font-weight:700}
.verdict.red{border-color:var(--red);background:var(--red-bg);color:var(--red)}
.verdict.yellow{border-color:var(--yellow);background:var(--yellow-bg);color:var(--yellow)}
.verdict.green{border-color:var(--green);background:var(--green-bg);color:var(--green)}
.counts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;font-size:14px;font-weight:400}
.pill{padding:2px 12px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--text)}
.card{background:var(--card);border:1px solid var(--line);border-left:6px solid;border-radius:8px;
padding:12px 16px;margin:10px 0}
.card.red{border-left-color:var(--red)}.card.yellow{border-left-color:var(--yellow)}.card.green{border-left-color:var(--green)}
.title{font-weight:700;overflow-wrap:anywhere}
.tag{display:inline-block;min-width:2.2em;text-align:center;border-radius:4px;padding:0 6px;margin-right:6px;
font-size:13px;font-weight:700;color:#fff}
.tag.red{background:var(--red)}.tag.yellow{background:var(--yellow)}.tag.green{background:var(--green)}
@media (prefers-color-scheme:dark){.tag{color:#16181c}}
.code{color:var(--muted);font-size:13px;margin-right:6px}
.advice{margin:6px 0 0;padding-left:1.4em}
.advice li{list-style:"→ "}
ul.ex{margin:6px 0 0;padding-left:1.4em;font-family:Consolas,"BIZ UDGothic",monospace;font-size:13px}
ul.ex li{overflow-wrap:anywhere}
details{margin-top:4px}
summary{cursor:pointer;color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:14px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--code)}
.scroll{overflow-x:auto}
.mono{font-family:Consolas,"BIZ UDGothic",monospace;font-size:13px}
footer{margin-top:40px;color:var(--muted);font-size:13px}
a{color:inherit}
"""


def _examples(f: Finding) -> str:
    if not f.examples:
        return ""
    shown, rest = f.examples[:VISIBLE_EXAMPLES], f.examples[VISIBLE_EXAMPLES:]
    out = '<ul class="ex">' + "".join(f"<li>{escape(e)}</li>" for e in shown) + "</ul>"
    if rest:
        out += (f"<details><summary>ほか {len(rest)} 件を表示</summary><ul class=\"ex\">"
                + "".join(f"<li>{escape(e)}</li>" for e in rest) + "</ul></details>")
    return out


def _card(f: Finding, cls: str) -> str:
    advice = "".join(f"<li>{escape(a)}</li>" for a in f.advice)
    return (f'<section class="card {cls}"><div class="title"><span class="tag {cls}">{escape(f.severity)}</span>'
            f'<span class="code">{escape(f.code)}</span>{escape(f.title)}</div>'
            + (f'<ul class="advice">{advice}</ul>' if advice else "") + _examples(f) + "</section>")


def render_html(inputs: list[InputRecord], analysis: Analysis, known: KnownAssets, now: datetime,
                max_referrers: int) -> str:
    findings = analysis.findings
    counts = {sev: sum(f.severity == sev for f in findings) for sev, _, _ in _SECTIONS}
    level = "red" if counts[RED] else "yellow" if counts[YELLOW] else "green"
    title = inputs[0].name if inputs else ""
    H: list[str] = [
        "<!doctype html>", '<html lang="ja"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>検品結果 - {escape(title)}</title><style>{_CSS}</style></head><body><main>",
        f"<header><h1>検品結果</h1><p>{escape(header(known))}　実行日時 {now:%Y-%m-%d %H:%M:%S}</p>",
        "<p>調べたファイル: " + "、".join(escape(f"{r.name}（{human_size(r.size)}）") for r in inputs) + "</p></header>",
        f'<div class="verdict {level}">{escape(verdict(findings))}<div class="counts">'
        + "".join(f'<span class="pill">{sev} {counts[sev]}</span>' for sev, _, _ in _SECTIONS) + "</div></div>",
    ]
    for sev, cls, label in _SECTIONS:
        group = [f for f in findings if f.severity == sev]
        if group:
            H.append(f"<h2>{label}（{sev} {len(group)}）</h2>")
            H += [_card(f, cls) for f in group]

    H.append("<h2>パッケージごとの同梱物</h2><div class=\"scroll\"><table><tr><th>パッケージ</th><th>中身</th>"
             "<th>ファイル</th><th>合計</th><th>Assets/ 直下</th></tr>")
    for s in analysis.summaries.values():
        H.append(f"<tr><td>{escape(s.name)}</td><td>{escape(kinds_text(s))}</td><td>{s.files}</td>"
                 f"<td>{escape(human_size(s.total_size))}</td><td>{escape(', '.join(s.top_folders))}</td></tr>")
    H.append("</table></div>")

    H.append("<h2>外部参照の一覧</h2><p>パッケージの外にあるファイルへの参照です（パッケージ内部と Unity 組み込みは除いています）。</p>")
    for pr in analysis.refs:
        rows = sorted(pr.external.values(), key=lambda x: (cl.CATEGORY_LABELS[x.category], x.guid))
        H.append(f"<details{' open' if rows and len(rows) <= 10 else ''}><summary>{escape(pr.package)}"
                 f"（外部 {len(rows)} 種類、内部 {pr.internal} か所、Unity 組み込み {pr.builtin} か所）</summary>")
        if rows:
            H.append('<div class="scroll"><table><tr><th>種類</th><th>識別番号（GUID）</th><th>参照数</th><th>参照元</th></tr>')
            for x in rows:
                label = cl.CATEGORY_LABELS[x.category]
                if x.known_id:
                    label += f"（{known.name(x.known_id)}）"
                elif x.kind:
                    label += f"（{x.kind}）"
                refs = ", ".join(x.referrers[:max_referrers])
                more = len(x.referrers) - max_referrers
                H.append(f'<tr><td>{escape(label)}</td><td class="mono">{escape(x.guid)}</td><td>{x.count}</td>'
                         f"<td>{escape(refs)}{f' ほか {more} 件' if more > 0 else ''}</td></tr>")
            H.append("</table></div>")
        H.append("</details>")

    H.append("<h2>既知アセットの検出</h2>")
    for pname, pm in analysis.matches.items():
        exact: dict[str, int] = {}
        prefix: dict[str, int] = {}
        for m in pm.values():
            if m is not None:
                d = exact if m.exact else prefix
                d[m.id] = d.get(m.id, 0) + 1
        if not exact and not prefix:
            H.append(f"<p>{escape(pname)}: なし</p>")
            continue
        H.append(f"<p>{escape(pname)}</p><ul>")
        for kid in ORDER:
            if kid in exact or kid in prefix:
                H.append(f"<li>{escape(known.name(kid))}: ID 一致 {exact.get(kid, 0)} 個 / "
                         f"フォルダ名だけの一致 {prefix.get(kid, 0)} 個</li>")
        H.append("</ul>")

    H.append('<footer>このページは手元の PC で作ったファイルです。インターネットには何も送信していません。'
             '同じ内容のテキスト版は <a href="report.txt">report.txt</a>、説明書の下書きは '
             '<a href="readme-draft.md">readme-draft.md</a> です（保存しなかった場合は開けません）。</footer>')
    H.append("</main></body></html>")
    return "\n".join(H) + "\n"
