"""Pages for the browser: the saved report.html, and the drop screen served by app.py.

report.html is self-contained (inline CSS, no scripts, no external files) so it works offline and
sends nothing. Like report.txt it names input files only, never full paths. The served pages add
a drop area and a small script that talks only to the local server (see app.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape

from . import DISPLAY_NAME, VERSION
from . import classify as cl
from .archive import InputRecord
from .checks import GREEN, RED, YELLOW, Analysis, Finding, human_size, kinds_text, verdict, zip_counts
from .known import ORDER, KnownAssets

VISIBLE_EXAMPLES = 3
# (severity, css class, section id, heading, sidebar label)
_SECTIONS = (
    (RED, "red", "fix", "出す前に直すもの", "直すもの"),
    (YELLOW, "yellow", "check", "確認するもの", "確認するもの"),
    (GREEN, "green", "info", "情報", "情報"),
)


@dataclass
class AppChrome:
    """What a page needs when it is served by the local app instead of saved to disk."""

    base: str  # "/<token>": every request goes below it
    result_id: str | None = None
    saved_label: str | None = None  # "ドキュメント\\UpkgPrecheck\\<folder>", never a full path


_CSS = """
:root{color-scheme:light dark;
--bg:#f5f6f8;--surface:#fff;--surface-2:#f1f3f5;--text:#1b1f24;--text-2:#57606a;--text-3:#7d858f;
--border:#d4d9df;--border-2:#e4e7eb;--dash:#aab3be;--accent:#1f62d0;--accent-soft:#e8f0fd;--on-accent:#fff;
--red:#c4262e;--red-soft:#fdf0f0;--red-line:#f0c4c6;--yellow:#946300;--yellow-soft:#fdf7e3;--yellow-line:#ecd9a0;
--green:#1d7a3b;--green-soft:#eef8f1;--green-line:#bfe0c9;
--mono:"Cascadia Mono",Consolas,"BIZ UDGothic",monospace}
@media (prefers-color-scheme:dark){:root{
--bg:#101216;--surface:#171a1f;--surface-2:#1e2228;--text:#e3e6ea;--text-2:#a2abb6;--text-3:#7a838e;
--border:#323840;--border-2:#262b32;--dash:#4f5863;--accent:#6ea2ff;--accent-soft:#1a2740;--on-accent:#0d1117;
--red:#ff8a83;--red-soft:#2a1719;--red-line:#5a2a2d;--yellow:#e8bd52;--yellow-soft:#2a2414;--yellow-line:#55451e;
--green:#5fcf7e;--green-soft:#15261b;--green-line:#24492f}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.65 "Segoe UI","Yu Gothic UI","Meiryo UI","Hiragino Sans",system-ui,sans-serif;
font-feature-settings:"palt" 0}
h1,h2,.lead,.note,.verdict,.row .t,.steps,.drop,.dropbar,footer{word-break:auto-phrase}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
svg.ic{width:16px;height:16px;flex:none;display:block}
.ic .b{fill:currentColor}.ic .k{fill:var(--surface)}.ic .ks{stroke:var(--surface);fill:none}
.topbar{background:var(--surface);border-bottom:1px solid var(--border)}
.topbar-in{max-width:1160px;margin:0 auto;padding:0 24px;height:52px;display:flex;align-items:center;gap:10px}
.brand{display:flex;align-items:center;gap:9px;font-weight:600;font-size:15px;color:var(--text)}
.brand:hover{text-decoration:none}
.mark{width:22px;height:22px;border-radius:5px;background:var(--accent);display:grid;place-items:center}
.mark svg{width:15px;height:15px;stroke:var(--on-accent);fill:none;stroke-width:1.5;stroke-linejoin:round}
.ver{color:var(--text-3);font-size:12px;font-weight:400}
.topbar .meta{margin-left:auto;color:var(--text-3);font-size:12px}
.layout{max-width:1160px;margin:0 auto;padding:32px 24px 72px;display:grid;
grid-template-columns:184px minmax(0,1fr);gap:48px}
.toc{position:sticky;top:24px;align-self:start;font-size:13px}
.toc p{margin:0 0 8px;color:var(--text-3);font-size:12px}
.toc ol{list-style:none;margin:0;padding:0;border-left:1px solid var(--border)}
.toc a{display:flex;justify-content:space-between;gap:8px;padding:4px 0 4px 12px;margin-left:-1px;
border-left:2px solid transparent;color:var(--text-2)}
.toc a:hover{color:var(--text);border-left-color:var(--text-3);text-decoration:none}
.toc .n{color:var(--text-3);font-variant-numeric:tabular-nums}
main{min-width:0}
.eyebrow{margin:0 0 4px;color:var(--text-2);font-size:13px}
h1{margin:0;font-size:22px;line-height:1.4;font-weight:600;overflow-wrap:anywhere}
h1 .more{color:var(--text-2);font-weight:400;font-size:16px;margin-left:8px}
h2{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-size:16px;font-weight:600}
h2 .n{min-width:22px;padding:0 7px;border-radius:10px;background:var(--surface-2);border:1px solid var(--border-2);
color:var(--text-2);font-size:12px;font-weight:600;text-align:center;font-variant-numeric:tabular-nums}
section.block{margin-top:40px;scroll-margin-top:16px}
.lead{margin:-4px 0 12px;color:var(--text-2)}
.verdict{display:flex;gap:12px;align-items:flex-start;margin:20px 0 0;padding:14px 16px;border-radius:8px;border:1px solid}
.verdict svg.ic{width:20px;height:20px;margin-top:1px}
.verdict strong{display:block;font-size:15px}
.verdict span{color:var(--text-2)}
.verdict.red{background:var(--red-soft);border-color:var(--red-line)}.verdict.red svg{color:var(--red)}
.verdict.yellow{background:var(--yellow-soft);border-color:var(--yellow-line)}.verdict.yellow svg{color:var(--yellow)}
.verdict.green{background:var(--green-soft);border-color:var(--green-line)}.verdict.green svg{color:var(--green)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);margin-top:16px;background:var(--surface);
border:1px solid var(--border);border-radius:8px;overflow:hidden}
.stat{display:block;padding:12px 16px;color:var(--text)}
.stat+.stat{border-left:1px solid var(--border-2)}
a.stat:hover{background:var(--surface-2);text-decoration:none}
.stat .v{display:block;font-size:24px;font-weight:600;line-height:1.3;font-variant-numeric:tabular-nums}
.stat .l{display:flex;align-items:center;gap:6px;color:var(--text-2);font-size:13px}
.stat.red .v{color:var(--red)}.stat.yellow .v{color:var(--yellow)}.stat.green .v{color:var(--green)}
.stat.zero .v{color:var(--text-3)}
.dot{width:8px;height:8px;border-radius:50%}
.dot.red{background:var(--red)}.dot.yellow{background:var(--yellow)}.dot.green{background:var(--green)}
.saved{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-top:12px;color:var(--text-2);font-size:13px}
.saved code{font-family:var(--mono);font-size:12px;color:var(--text)}
.list{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.item+.item{border-top:1px solid var(--border-2)}
.row{display:flex;align-items:flex-start;gap:10px;padding:11px 16px;list-style:none}
.row::-webkit-details-marker{display:none}
summary.row{cursor:pointer}summary.row:hover{background:var(--surface-2)}
.row svg.ic{margin-top:3px}
.row .t{flex:1;min-width:0;font-weight:600;overflow-wrap:anywhere}
.item.green .row .t{font-weight:500}
.row .code{flex:none;font-family:var(--mono);font-size:12px;color:var(--text-3);margin-top:2px}
.chev{width:14px;height:14px;flex:none;margin-top:4px;stroke:var(--text-3);fill:none;stroke-width:1.6;transition:transform .15s}
details[open]>summary .chev{transform:rotate(90deg)}
.sev-red{color:var(--red)}.sev-yellow{color:var(--yellow)}.sev-green{color:var(--green)}
.body{padding:0 16px 14px 42px}
.body p{margin:0 0 6px;color:var(--text-2)}
.ex{margin:8px 0 0;padding:8px 12px;list-style:none;background:var(--surface-2);border:1px solid var(--border-2);
border-radius:6px;font-family:var(--mono);font-size:12px;line-height:1.7}
.ex li{overflow-wrap:anywhere}
.more-ex>summary{display:inline-block;margin-top:6px;cursor:pointer;color:var(--accent);font-size:13px}
.empty{padding:14px 16px;color:var(--text-2)}
.tbl{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--surface-2);color:var(--text-2);font-weight:600;font-size:12px;border-bottom:1px solid var(--border);white-space:nowrap}
td{border-top:1px solid var(--border-2)}tr:first-child>td{border-top:0}
td.num,th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.mono{font-family:var(--mono);font-size:12px}
td.sub{color:var(--text-2)}
.disc{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.disc+.disc{margin-top:8px}
.disc>summary{display:flex;gap:10px;align-items:flex-start;padding:10px 16px;cursor:pointer;list-style:none}
.disc>summary::-webkit-details-marker{display:none}
.disc>summary:hover{background:var(--surface-2)}
.disc>summary .t{flex:1;min-width:0;font-weight:600;overflow-wrap:anywhere}
.disc>summary .s{color:var(--text-2);font-size:13px;white-space:nowrap}
.disc .tbl{border:0;border-top:1px solid var(--border);border-radius:0}
.disc>.row{border-bottom:1px solid var(--border-2)}.disc>.row:last-child{border-bottom:0}
.kv{margin:0;padding:0;list-style:none}
.kv li{display:flex;justify-content:space-between;gap:16px;padding:8px 16px;border-top:1px solid var(--border-2)}
.kv li:first-child{border-top:0}
.kv .s{color:var(--text-2);font-variant-numeric:tabular-nums;white-space:nowrap}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--border);color:var(--text-3);font-size:12px}
footer p{margin:0 0 4px}
.btn{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 14px;border-radius:6px;font:inherit;font-size:13px;
font-weight:600;cursor:pointer;border:1px solid var(--border);background:var(--surface);color:var(--text)}
.btn:hover{background:var(--surface-2)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn.primary:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.5;cursor:default}
.btn.sm{height:28px;padding:0 10px;font-weight:400}
.drop{display:flex;flex-direction:column;align-items:center;gap:6px;padding:52px 24px;text-align:center;
background:var(--surface);border:1.5px dashed var(--dash);border-radius:12px;transition:border-color .12s,background .12s}
.drop.over,.dropbar.over{border-color:var(--accent);background:var(--accent-soft)}
.drop .up{width:40px;height:40px;margin-bottom:6px;stroke:var(--text-3);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.drop strong{font-size:16px}
.drop .hint{color:var(--text-2);font-size:13px}
.btns{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:14px}
.dropbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;margin-bottom:28px;padding:10px 12px 10px 16px;
background:var(--surface);border:1.5px dashed var(--dash);border-radius:8px;font-size:13px;color:var(--text-2)}
.dropbar .up{width:18px;height:18px;stroke:var(--text-3);fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.dropbar .grow{flex:1;min-width:12em}
.note{margin:14px 0 0;color:var(--text-2);font-size:13px}
.home{max-width:720px;margin:0 auto;padding:56px 24px 72px}
.home h1{font-size:24px}
.home .lead{margin:6px 0 24px}
.steps{margin:40px 0 0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;font-size:13px}
.steps li{padding-top:10px;border-top:2px solid var(--border)}
.steps b{display:block;color:var(--text);font-size:13px}
.steps span{color:var(--text-2)}
.panel{margin-top:16px;padding:14px 16px;background:var(--surface);border:1px solid var(--border);border-radius:8px}
.panel[hidden]{display:none}
.panel .line{display:flex;justify-content:space-between;gap:12px;font-size:13px}
.panel.error .msg{color:var(--text)}
.panel .line span:last-child{color:var(--text-2);font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{height:4px;margin-top:10px;border-radius:2px;background:var(--surface-2);overflow:hidden}
.bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .2s}
.panel.busy .bar i{width:35%!important;animation:slide 1.1s ease-in-out infinite}
@keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(290%)}}
.dropbar+.panel{margin:-12px 0 28px}
.panel.error{background:var(--red-soft);border-color:var(--red-line)}
.panel.error .msg{white-space:pre-line}
.overlay{position:fixed;inset:0;z-index:10;display:none;padding:24px;background:color-mix(in srgb,var(--bg) 82%,transparent)}
.overlay.on{display:block}
.overlay>div{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
border:2px dashed var(--accent);border-radius:16px;background:var(--accent-soft);color:var(--accent);font-size:18px;font-weight:600}
.overlay .up{width:44px;height:44px;stroke:currentColor;fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.overlay span{font-size:13px;font-weight:400;color:var(--text-2)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
@media (max-width:960px){.layout{grid-template-columns:minmax(0,1fr);gap:0}.toc{display:none}}
@media (max-width:600px){.topbar-in,.layout,.home{padding-left:16px;padding-right:16px}
.topbar .meta{display:none}.stat{padding:10px 12px}.stat .v{font-size:20px}.body{padding-left:16px}
.steps{grid-template-columns:1fr}.drop{padding:36px 16px}
.tbl table{min-width:600px}.dropbar .grow{flex-basis:100%}.disc>summary{flex-wrap:wrap}.disc>summary .s{flex-basis:100%;padding-left:24px;white-space:normal}
.kv li{flex-direction:column;gap:0}}
.nowrap{white-space:nowrap}
@media print{body{background:#fff}.topbar,.toc,.dropbar,.overlay{display:none}.layout{display:block;padding:0}
details>*{display:block}}
"""

_MARK = ('<span class="mark"><svg viewBox="0 0 16 16"><path d="M8 1.8 13.6 5v6L8 14.2 2.4 11V5z"/>'
         '<path d="M2.6 5.1 8 8.2l5.4-3.1M8 8.2v5.8"/></svg></span>')
_CHEV = '<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5l4.5 4.5L6 12.5"/></svg>'
_UP = ('<svg class="up" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/>'
       '<path d="M4 14v4.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V14"/></svg>')
_ICONS = {
    "red": '<circle class="b" cx="8" cy="8" r="7.5"/><rect class="k" x="7.15" y="3.6" width="1.7" height="5.6" rx=".85"/>'
           '<circle class="k" cx="8" cy="11.6" r="1.05"/>',
    "yellow": '<path class="b" d="M8 .9c.55 0 1.05.3 1.32.77l6.2 11.1c.55.98-.16 2.2-1.3 2.2H1.78c-1.14 0-1.85-1.22-1.3-2.2'
              'l6.2-11.1C6.95 1.2 7.45.9 8 .9z"/><rect class="k" x="7.15" y="5" width="1.7" height="5" rx=".85"/>'
              '<circle class="k" cx="8" cy="12.25" r="1.05"/>',
    "green": '<circle class="b" cx="8" cy="8" r="7.5"/><circle class="k" cx="8" cy="4.75" r="1.05"/>'
             '<rect class="k" x="7.15" y="6.8" width="1.7" height="5.6" rx=".85"/>',
    "ok": '<circle class="b" cx="8" cy="8" r="7.5"/><path class="ks" d="M4.7 8.3l2.2 2.2 4.4-4.7" stroke-width="1.8" '
          'stroke-linecap="round" stroke-linejoin="round"/>',
}
_SEV_WORD = {"red": "赤", "yellow": "黄", "green": "緑"}


def _icon(kind: str, cls: str = "") -> str:
    return f'<svg class="ic {cls}" viewBox="0 0 16 16" aria-hidden="true">{_ICONS[kind]}</svg>'


def _topbar(known: KnownAssets, home: str | None) -> str:
    brand = f"{_MARK}{escape(DISPLAY_NAME)}<span class=\"ver\">{escape(VERSION)}</span>"
    brand = f'<a class="brand" href="{escape(home)}">{brand}</a>' if home else f'<span class="brand">{brand}</span>'
    return (f'<header class="topbar"><div class="topbar-in">{brand}'
            f'<span class="meta">既知アセットの辞書 {escape(known.built)}</span></div></header>')


def _shell(title: str, body: str, app: AppChrome | None) -> str:
    attrs = f' data-base="{escape(app.base)}"' if app else ""
    script = f"<script>{_JS}</script>" if app else ""
    return ("<!doctype html>\n"
            '<html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            + ('<link rel="icon" href="data:,">' if app else "")
            + f"<title>{escape(title)}</title><style>{_CSS}</style></head>"
            f"<body{attrs}>{body}{script}</body></html>\n")


def _example_list(items: list[str]) -> str:
    return '<ul class="ex">' + "".join(f"<li>{escape(e)}</li>" for e in items) + "</ul>"


def _item(f: Finding, cls: str) -> str:
    head = (f'{_icon(cls, "sev-" + cls)}<span class="t">{escape(f.title)}</span>'
            f'<span class="code">{escape(f.code)}</span>')
    body = "".join(f"<p>{escape(a)}</p>" for a in f.advice)
    if f.examples:
        shown, rest = f.examples[:VISIBLE_EXAMPLES], f.examples[VISIBLE_EXAMPLES:]
        body += _example_list(shown)
        if rest:
            body += (f'<details class="more-ex"><summary>ほか {len(rest)} 件を表示</summary>'
                     f"{_example_list(rest)}</details>")
    if not body:
        return f'<div class="item {cls}"><div class="row">{head}<span class="chev"></span></div></div>'
    # Things to fix or check start open; information starts folded.
    is_open = " open" if cls != "green" else ""
    return (f'<details class="item {cls}"{is_open}><summary class="row">{head}{_CHEV}</summary>'
            f'<div class="body">{body}</div></details>')


def _drop_parts(compact: bool) -> str:
    """Drop area, hidden file pickers, progress panel and the full-window overlay."""
    pickers = ('<input type="file" id="pick-files" class="sr" multiple accept=".zip,.unitypackage" tabindex="-1">'
               '<input type="file" id="pick-folder" class="sr" webkitdirectory tabindex="-1">')
    buttons = ('<button type="button" class="btn{p}" data-pick="pick-files">ファイルを選ぶ</button>'
               '<button type="button" class="btn{s}" data-pick="pick-folder">フォルダを選ぶ</button>')
    if compact:
        area = (f'<div class="dropbar" id="drop">{_UP}<span class="grow">別のファイルを調べるときは、'
                f'このページにドロップしてください。</span>{buttons.format(p=" sm", s=" sm")}</div>')
    else:
        area = (f'<div class="drop" id="drop">{_UP}<strong>ここにドロップ</strong>'
                '<span class="hint">zip・unitypackage、またはそれらが入ったフォルダ（いくつでもまとめて）</span>'
                f'<div class="btns">{buttons.format(p=" primary", s="")}</div></div>')
    panel = ('<div class="panel" id="status" hidden role="status" aria-live="polite">'
             '<div class="line"><span class="msg"></span><span class="pct"></span></div>'
             '<div class="bar"><i></i></div></div>')
    return pickers + area + panel + '<div class="overlay" id="overlay"><div>' + _UP + 'ドロップして検品<span>zip・unitypackage・フォルダ</span></div></div>'


def render_home(known: KnownAssets, app: AppChrome) -> str:
    """The first screen of the app: a drop area and three steps."""
    body = (_topbar(known, None)
            + '<main class="home"><h1>出品前の検品</h1>'
            '<p class="lead">Booth に出す zip や unitypackage を、Unity を開かずに調べます。'
            '入れ忘れ・入れすぎ・名前の問題を、出品前に見つけます。</p>'
            + _drop_parts(compact=False)
            + '<p class="note">ファイルはこのパソコンの中だけで調べます。インターネットには送信しません。'
            '結果は<span class="nowrap">「ドキュメント\\UpkgPrecheck」</span>にも保存されます。</p>'
            '<ol class="steps">'
            '<li><b>1. ドロップ</b><span>出品用の zip をそのまま。フォルダごとでも構いません。</span></li>'
            '<li><b>2. 結果を見る</b><span>赤は出す前に直すもの、黄は確認するもの、緑は情報です。</span></li>'
            '<li><b>3. 直して、もう一度</b><span>直した zip をまたドロップして、赤が消えたか確かめます。</span></li>'
            "</ol></main>")
    return _shell(DISPLAY_NAME, body, app)


def _overview(inputs: list[InputRecord], findings: list[Finding], now: datetime, app: AppChrome | None) -> str:
    counts = {sev: sum(f.severity == sev for f in findings) for sev, *_ in _SECTIONS}
    level = "red" if counts[RED] else "yellow" if counts[YELLOW] else "green"
    first = inputs[0].name if inputs else ""
    more = f'<span class="more">ほか {len(inputs) - 1} 件</span>' if len(inputs) > 1 else ""
    head, _, tail = verdict(findings).partition("。")
    icon = _icon("ok" if level == "green" else level)
    out = (f'<p class="eyebrow">検品結果　{now:%Y-%m-%d %H:%M}</p><h1>{escape(first)}{more}</h1>'
           f'<div class="verdict {level}">{icon}<div><strong>{escape(head)}。</strong>'
           + (f"<span>{escape(tail)}</span>" if tail else "") + "</div></div>"
           '<div class="stats">')
    for sev, cls, sid, _, label in _SECTIONS:
        n = counts[sev]
        tag = "a" if n else "div"
        href = f' href="#{sid}"' if n else ""
        out += (f'<{tag} class="stat {cls}{"" if n else " zero"}"{href}><span class="v">{n}</span>'
                f'<span class="l"><span class="dot {cls}"></span>{label}（{_SEV_WORD[cls]}）</span></{tag}>')
    out += "</div>"
    if app and app.saved_label:
        out += (f'<div class="saved"><span>保存先: <code>{escape(app.saved_label)}</code></span>'
                f'<button type="button" class="btn sm" id="open-folder" data-id="{escape(app.result_id or "")}">'
                "フォルダを開く</button></div>")
    return out


def _known_counts(pm: dict) -> tuple[dict[str, int], dict[str, int]]:
    exact: dict[str, int] = {}
    prefix: dict[str, int] = {}
    for m in pm.values():
        if m is not None:
            d = exact if m.exact else prefix
            d[m.id] = d.get(m.id, 0) + 1
    return exact, prefix


def render_html(inputs: list[InputRecord], analysis: Analysis, known: KnownAssets, now: datetime,
                max_referrers: int, app: AppChrome | None = None) -> str:
    findings = analysis.findings
    toc: list[tuple[str, str, int | None]] = [("overview", "概要", None)]
    B: list[str] = []
    if app:
        B.append(_drop_parts(compact=True))
    B.append(f'<section id="overview">{_overview(inputs, findings, now, app)}</section>')

    for sev, cls, sid, heading, label in _SECTIONS:
        group = [f for f in findings if f.severity == sev]
        if group:
            toc.append((sid, label, len(group)))
            B.append(f'<section class="block" id="{sid}"><h2>{heading}<span class="n">{len(group)}</span></h2>'
                     f'<div class="list">{"".join(_item(f, cls) for f in group)}</div></section>')

    toc.append(("files", "調べたファイル", len(inputs)))
    B.append('<section class="block" id="files"><h2>調べたファイル</h2><div class="tbl"><table>'
             '<tr><th>ファイル</th><th class="num">大きさ</th><th>中身</th></tr>')
    for r in inputs:
        what = zip_counts(r.zip) if r.zip is not None else "unitypackage"
        B.append(f"<tr><td>{escape(r.name)}</td><td class=\"num\">{escape(human_size(r.size))}</td>"
                 f'<td class="sub">{escape(what)}</td></tr>')
    B.append("</table></div></section>")

    toc.append(("contents", "同梱物", len(analysis.summaries)))
    B.append('<section class="block" id="contents"><h2>パッケージごとの同梱物</h2><div class="tbl"><table>'
             '<tr><th>パッケージ</th><th>中身</th><th class="num">ファイル</th><th class="num">合計</th>'
             "<th>Assets/ 直下</th></tr>")
    for s in analysis.summaries.values():
        B.append(f"<tr><td>{escape(s.name)}</td><td class=\"sub\">{escape(kinds_text(s))}</td>"
                 f'<td class="num">{s.files}</td><td class="num">{escape(human_size(s.total_size))}</td>'
                 f'<td class="sub">{escape(", ".join(s.top_folders))}</td></tr>')
    B.append("</table></div></section>")

    toc.append(("refs", "外部参照", None))
    B.append('<section class="block" id="refs"><h2>外部参照</h2><p class="lead">パッケージの外にあるファイルへの参照です'
             "（パッケージの中どうしの参照と、Unity 組み込みのものは除いています）。</p>")
    for pr in analysis.refs:
        rows = sorted(pr.external.values(), key=lambda x: (cl.CATEGORY_LABELS[x.category], x.guid))
        is_open = " open" if rows and len(rows) <= 10 else ""
        B.append(f'<details class="disc"{is_open}><summary>{_CHEV}<span class="t">{escape(pr.package)}</span>'
                 f'<span class="s">外部 {len(rows)} 種類・内部 {pr.internal} か所・組み込み {pr.builtin} か所</span></summary>')
        if rows:
            B.append('<div class="tbl"><table><tr><th>種類</th><th>識別番号（GUID）</th><th class="num">参照数</th>'
                     "<th>参照元</th></tr>")
            for x in rows:
                label = cl.CATEGORY_LABELS[x.category]
                if x.known_id:
                    label += f"（{known.name(x.known_id)}）"
                elif x.kind:
                    label += f"（{x.kind}）"
                refs = ", ".join(x.referrers[:max_referrers])
                more = len(x.referrers) - max_referrers
                B.append(f'<tr><td>{escape(label)}</td><td class="mono">{escape(x.guid)}</td>'
                         f'<td class="num">{x.count}</td>'
                         f"<td class=\"sub\">{escape(refs)}{f' ほか {more} 件' if more > 0 else ''}</td></tr>")
            B.append("</table></div>")
        else:
            B.append('<div class="empty">外部への参照はありません。</div>')
        B.append("</details>")
    B.append("</section>")

    toc.append(("known", "既知アセット", None))
    B.append('<section class="block" id="known"><h2>既知アセットの検出</h2><p class="lead">'
             "lilToon などの配布物と同じ識別番号（ID）か、同じフォルダ名のファイルの数です。</p>")
    for pname, pm in analysis.matches.items():
        exact, prefix = _known_counts(pm)
        B.append(f'<div class="disc"><div class="row"><span class="t">{escape(pname)}</span></div>')
        if not exact and not prefix:
            B.append('<div class="empty">見つかりませんでした。</div></div>')
            continue
        B.append('<ul class="kv">')
        for kid in ORDER:
            if kid in exact or kid in prefix:
                B.append(f"<li><span>{escape(known.name(kid))}</span><span class=\"s\">ID 一致 {exact.get(kid, 0)}"
                         f" ・ フォルダ名だけの一致 {prefix.get(kid, 0)}</span></li>")
        B.append("</ul></div>")
    B.append("</section>")

    if app:
        foot = ("<p>このページはチェッカーの窓を閉じると使えなくなります。結果は保存先の report.html で"
                "いつでも見られます。</p>")
    else:
        foot = ('<p>同じ内容のテキスト版は <a href="report.txt">report.txt</a>、説明書の下書きは '
                '<a href="readme-draft.md">readme-draft.md</a> です（保存しなかった場合は開けません）。</p>')
    foot += "<p>このページは手元のパソコンで作られました。インターネットには何も送信していません。</p>"
    B.append(f"<footer>{foot}</footer>")

    nav = '<nav class="toc" aria-label="目次"><p>目次</p><ol>' + "".join(
        f'<li><a href="#{sid}"><span>{label}</span>' + (f'<span class="n">{n}</span>' if n is not None else "")
        + "</a></li>" for sid, label, n in toc) + "</ol></nav>"
    body = _topbar(known, f"{app.base}/" if app else None) + f'<div class="layout">{nav}<main>{"".join(B)}</main></div>'
    title = f"検品結果 - {inputs[0].name}" if inputs else "検品結果"
    return _shell(title, body, app)


# The served pages only: collect dropped or picked files, upload them to the local server one by
# one (with progress), run the check, then show the result page. Folders keep their inner paths.
_JS = r"""
(() => {
const base = document.body.dataset.base;
const SUP = /\.(zip|unitypackage)$/i;
const $ = (id) => document.getElementById(id);
const panel = $("status"), drop = $("drop"), overlay = $("overlay");
let busy = false;

function show(kind, msg, pct) {
  panel.hidden = false;
  panel.className = "panel" + (kind ? " " + kind : "");
  panel.querySelector(".msg").textContent = msg;
  panel.querySelector(".pct").textContent = pct == null ? "" : pct + "%";
  panel.querySelector(".bar i").style.width = (pct || 0) + "%";
  panel.querySelector(".bar").hidden = kind === "error";
}
function size(n) {
  for (const [u, d] of [["GB", 1 << 30], ["MB", 1 << 20], ["KB", 1 << 10]]) if (n >= d) return (n / d).toFixed(1) + " " + u;
  return n + " B";
}
const GONE = "チェッカーの黒い窓が閉じられたため、調べられません。upkg-precheck.exe をもう一度起動してください。";

async function api(method, path, body) {
  let r;
  try {
    r = await fetch(base + path, {method, headers: {"Content-Type": "application/json", "X-Upkg": "1"},
                                  body: body == null ? null : JSON.stringify(body)});
  } catch (e) { throw new Error(GONE); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ("エラーが起きました（" + r.status + "）"));
  return j;
}
function put(path, file, onp) {
  return new Promise((ok, ng) => {
    const x = new XMLHttpRequest();
    x.open("PUT", base + path);
    x.setRequestHeader("X-Upkg", "1");
    x.upload.onprogress = (e) => onp(e.loaded);
    x.onload = () => {
      if (x.status < 300) return ok();
      let m; try { m = JSON.parse(x.responseText).error; } catch (e) {}
      ng(new Error(m || ("読み込めませんでした（" + x.status + "）")));
    };
    x.onerror = () => ng(new Error(GONE));
    x.send(file);
  });
}

function readDir(dir) {
  const reader = dir.createReader(), all = [];
  return new Promise((ok, ng) => {
    const next = () => reader.readEntries((batch) => {
      if (!batch.length) return ok(all);
      all.push(...batch); next();
    }, ng);
    next();
  });
}
async function walk(entry, prefix, out) {
  if (entry.isFile) {
    if (SUP.test(entry.name)) out.push({rel: prefix + entry.name, file: await new Promise((ok, ng) => entry.file(ok, ng))});
  } else if (entry.isDirectory) {
    for (const e of await readDir(entry)) await walk(e, prefix + entry.name + "/", out);
  }
}
async function fromDrop(dt) {
  // webkitGetAsEntry must be called before the first await: the item list empties afterwards.
  const picked = [...dt.items].filter((i) => i.kind === "file")
    .map((i) => ({entry: i.webkitGetAsEntry ? i.webkitGetAsEntry() : null, file: i.getAsFile()}));
  const roots = [];
  for (const p of picked) {
    if (p.entry && p.entry.isDirectory) {
      const files = [];
      for (const e of await readDir(p.entry)) await walk(e, "", files);
      roots.push({name: p.entry.name, dir: true, files});
    } else if (p.file) {
      roots.push({name: p.file.name, dir: false, files: [{rel: p.file.name, file: p.file}]});
    }
  }
  return roots;
}
function fromFolderPicker(list) {
  const byRoot = new Map();
  for (const f of list) {
    const parts = (f.webkitRelativePath || f.name).split("/");
    const root = parts.length > 1 ? parts.shift() : "";
    if (!byRoot.has(root)) byRoot.set(root, []);
    if (SUP.test(f.name)) byRoot.get(root).push({rel: parts.join("/"), file: f});
  }
  return [...byRoot].map(([name, files]) => ({name, dir: true, files}));
}

async function check(roots) {
  if (busy || !roots.length) return;
  busy = true;
  document.querySelectorAll("[data-pick]").forEach((b) => b.disabled = true);
  try {
    const all = roots.flatMap((r) => r.files.map((f) => f.file).filter((f) => !r.dir || SUP.test(f.name)));
    const total = all.reduce((s, f) => s + f.size, 0) || 1;
    const {job} = await api("POST", "/jobs");
    let done = 0;
    for (const [i, r] of roots.entries()) {
      for (const [j, f] of r.files.entries()) {
        if (!r.dir && !SUP.test(f.file.name)) continue;
        await put(`/jobs/${job}/${i}/${j}`, f.file, (n) =>
          show("", "読み込んでいます: " + (r.dir ? r.name + "\\" + f.rel.replace(/\//g, "\\") : f.rel) +
               "（" + size(f.file.size) + "）", Math.min(99, Math.floor((done + n) * 100 / total))));
        done += f.file.size;
      }
    }
    show("busy", "検品しています…");
    const res = await api("POST", `/jobs/${job}/run`,
      {roots: roots.map((r) => ({name: r.name, dir: r.dir, files: r.files.map((f) => ({rel: f.rel, size: f.file.size}))}))});
    location.href = res.url;
  } catch (e) {
    show("error", e.message);
  } finally {
    busy = false;
    document.querySelectorAll("[data-pick]").forEach((b) => b.disabled = false);
  }
}

document.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => $(b.dataset.pick).click()));
$("pick-files").addEventListener("change", (e) => {
  check([...e.target.files].map((f) => ({name: f.name, dir: false, files: [{rel: f.name, file: f}]})));
  e.target.value = "";
});
$("pick-folder").addEventListener("change", (e) => { check(fromFolderPicker(e.target.files)); e.target.value = ""; });

let depth = 0;
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  if (++depth === 1 && !busy) { overlay.classList.add("on"); drop.classList.add("over"); }
});
window.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  if (--depth <= 0) { depth = 0; overlay.classList.remove("on"); drop.classList.remove("over"); }
});
window.addEventListener("dragover", (e) => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = busy ? "none" : "copy"; } });
window.addEventListener("drop", async (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  depth = 0; overlay.classList.remove("on"); drop.classList.remove("over");
  if (busy) return;
  let roots;
  try { roots = await fromDrop(e.dataTransfer); } catch (err) { return show("error", "ドロップしたものを読めませんでした。"); }
  if (!roots.length) return show("error", "ファイルかフォルダをドロップしてください。");
  check(roots);
});

const of = $("open-folder");
if (of) of.addEventListener("click", async () => {
  try { await api("POST", `/results/${of.dataset.id}/open`); } catch (e) { show("error", e.message); }
});
})();
"""
