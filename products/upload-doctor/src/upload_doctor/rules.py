"""Rule table (rules.json): load, validate, expose typed rules.

The table is data so that it can follow SDK changes without code changes (--rules to swap it).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from .versions import parse_version

LEVELS = ("ng", "warn", "info")
CONFIDENCES = ("high", "mid", "low")
COMPILE_GROUPS = ("file", "line", "col", "code", "msg")
MAX_SCAN_DEPTH = 2
SCHEMA = 1


class RulesError(ValueError):
    """The rule table is broken. The message names the offending place."""


@dataclass(frozen=True)
class FolderRule:
    id: str
    under: str
    name_glob: str
    max_depth: int
    level: str
    confidence: str
    title: str
    advice: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class LogRule:
    id: str
    regex: re.Pattern[str]
    near: re.Pattern[str] | None
    near_lines: int
    level: str
    confidence: str
    title: str
    advice: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class TypeHint:
    match: tuple[str, ...]
    exact: tuple[str, ...]
    hint: str
    confidence: str
    source: str

    def matches(self, name: str) -> bool:
        n = name.casefold()
        return any(n == e.casefold() for e in self.exact) or any(n.startswith(p.casefold()) for p in self.match)


@dataclass(frozen=True)
class Rules:
    checked_on: date
    unity_supported: tuple[str, ...]
    unity_source: str
    sdk_min_avatars: str
    sdk_confidence: str
    sdk_source: str
    compile_error: re.Pattern[str]
    folder_rules: tuple[FolderRule, ...]
    log_rules: tuple[LogRule, ...]
    type_hints: tuple[TypeHint, ...]
    overrides: dict[str, dict[str, str]]
    origin: str

    @property
    def recommended_unity(self) -> str:
        return self.unity_supported[0]

    def hint_for(self, name: str) -> TypeHint | None:
        return next((h for h in self.type_hints if h.matches(name)), None)


def _bundled_text() -> str:
    try:
        return resources.files(__package__).joinpath("rules.json").read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError, TypeError, AttributeError):
        # Fallback for frozen builds whose importer lacks resource support (checked by the CI smoke run).
        return (Path(__file__).resolve().parent / "rules.json").read_text(encoding="utf-8")


def load(path: str | Path | None = None) -> Rules:
    if path is None:
        text = _bundled_text()
        origin = "同梱"
    else:
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except OSError as e:
            raise RulesError(f"{path}: 読めません（{e.strerror or e}）") from None
        origin = str(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RulesError(f"JSON として読めません（{e.lineno} 行目 {e.colno} 列目: {e.msg}）") from None
    return parse(data, origin)


# --- validation helpers -------------------------------------------------------------


def _obj(v: Any, where: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise RulesError(f"{where}: オブジェクト（{{…}}）である必要があります")
    return v


def _str(d: dict[str, Any], key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise RulesError(f"{where}.{key}: 空でない文字列が必要です")
    return v


def _choice(d: dict[str, Any], key: str, where: str, choices: tuple[str, ...]) -> str:
    v = d.get(key)
    if v not in choices:
        raise RulesError(f"{where}.{key}: {' / '.join(choices)} のどれかが必要です（{v!r}）")
    return v


def _strlist(d: dict[str, Any], key: str, where: str, required: bool = True) -> tuple[str, ...]:
    v = d.get(key)
    if v is None and not required:
        return ()
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        raise RulesError(f"{where}.{key}: 空でない文字列のリストが必要です")
    return tuple(v)


def _regex(d: dict[str, Any], key: str, where: str) -> re.Pattern[str]:
    src = _str(d, key, where)
    try:
        return re.compile(src, re.IGNORECASE)
    except re.error as e:
        raise RulesError(f"{where}.{key}: 正規表現として不正です（{e}）") from None


def _int(d: dict[str, Any], key: str, where: str, lo: int, hi: int) -> int:
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise RulesError(f"{where}.{key}: {lo}〜{hi} の整数が必要です（{v!r}）")
    return v


def _ids_unique(items: list[Any], where: str) -> None:
    seen: set[str] = set()
    for i, it in enumerate(items):
        rid = it.id
        if rid in seen:
            raise RulesError(f"{where}[{i}].id: 重複しています（{rid}）")
        seen.add(rid)


def parse(data: Any, origin: str = "") -> Rules:
    root = _obj(data, "rules")
    if root.get("schema") != SCHEMA:
        raise RulesError(f"rules.schema: {SCHEMA} が必要です（{root.get('schema')!r}）")
    try:
        checked_on = date.fromisoformat(_str(root, "checked_on", "rules"))
    except ValueError:
        raise RulesError("rules.checked_on: YYYY-MM-DD の日付が必要です") from None

    unity = _obj(root.get("unity"), "unity")
    supported = _strlist(unity, "supported", "unity")
    unity_source = _str(unity, "source", "unity")

    sdk = _obj(root.get("sdk"), "sdk")
    sdk_min = _str(sdk, "min_avatars_for_new_upload", "sdk")
    if parse_version(sdk_min) is None:
        raise RulesError(f"sdk.min_avatars_for_new_upload: バージョンとして読めません（{sdk_min!r}）")
    sdk_conf = _choice(sdk, "confidence", "sdk", CONFIDENCES)
    sdk_source = _str(sdk, "source", "sdk")

    compile_error = _regex(root, "compile_error_regex", "rules")
    missing = [g for g in COMPILE_GROUPS if g not in compile_error.groupindex]
    if missing:
        raise RulesError(f"rules.compile_error_regex: 名前付きグループ {', '.join(missing)} が必要です")

    folder_rules = []
    raw = root.get("folder_rules", [])
    if not isinstance(raw, list):
        raise RulesError("rules.folder_rules: リストが必要です")
    for i, r in enumerate(raw):
        w = f"folder_rules[{i}]"
        r = _obj(r, w)
        if r.get("under") != "Assets":
            raise RulesError(f"{w}.under: \"Assets\" だけが使えます（{r.get('under')!r}）")
        folder_rules.append(
            FolderRule(
                id=_str(r, "id", w),
                under="Assets",
                name_glob=_str(r, "name_glob", w),
                max_depth=_int(r, "max_depth", w, 1, MAX_SCAN_DEPTH),
                level=_choice(r, "level", w, LEVELS),
                confidence=_choice(r, "confidence", w, CONFIDENCES),
                title=_str(r, "title", w),
                advice=_strlist(r, "advice", w),
                source=_str(r, "source", w),
            )
        )
    _ids_unique(folder_rules, "folder_rules")

    log_rules = []
    raw = root.get("log_rules", [])
    if not isinstance(raw, list):
        raise RulesError("rules.log_rules: リストが必要です")
    for i, r in enumerate(raw):
        w = f"log_rules[{i}]"
        r = _obj(r, w)
        near = _regex(r, "near_regex", w) if "near_regex" in r else None
        log_rules.append(
            LogRule(
                id=_str(r, "id", w),
                regex=_regex(r, "regex", w),
                near=near,
                near_lines=_int(r, "near_lines", w, 1, 50) if near else 0,
                level=_choice(r, "level", w, LEVELS),
                confidence=_choice(r, "confidence", w, CONFIDENCES),
                title=_str(r, "title", w),
                advice=_strlist(r, "advice", w),
                source=_str(r, "source", w),
            )
        )
    _ids_unique(log_rules, "log_rules")

    hints = []
    raw = root.get("missing_type_hints", [])
    if not isinstance(raw, list):
        raise RulesError("rules.missing_type_hints: リストが必要です")
    for i, r in enumerate(raw):
        w = f"missing_type_hints[{i}]"
        r = _obj(r, w)
        hints.append(
            TypeHint(
                match=_strlist(r, "match", w),
                exact=_strlist(r, "exact", w, required=False),
                hint=_str(r, "hint", w),
                confidence=_choice(r, "confidence", w, CONFIDENCES),
                source=_str(r, "source", w),
            )
        )

    overrides: dict[str, dict[str, str]] = {}
    for fid, ov in _obj(root.get("overrides", {}), "overrides").items():
        w = f"overrides.{fid}"
        ov = _obj(ov, w)
        unknown = set(ov) - {"level", "confidence"}
        if unknown:
            raise RulesError(f"{w}: level / confidence 以外は指定できません（{', '.join(sorted(unknown))}）")
        clean: dict[str, str] = {}
        if "level" in ov:
            clean["level"] = _choice(ov, "level", w, LEVELS)
        if "confidence" in ov:
            clean["confidence"] = _choice(ov, "confidence", w, CONFIDENCES)
        overrides[fid] = clean

    return Rules(
        checked_on=checked_on,
        unity_supported=supported,
        unity_source=unity_source,
        sdk_min_avatars=sdk_min,
        sdk_confidence=sdk_conf,
        sdk_source=sdk_source,
        compile_error=compile_error,
        folder_rules=tuple(folder_rules),
        log_rules=tuple(log_rules),
        type_hints=tuple(hints),
        overrides=overrides,
        origin=origin,
    )
