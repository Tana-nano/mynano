"""Configuration: defaults -> config.toml -> VSUILOG_<SECTION>_<KEY> env -> CLI."""

from __future__ import annotations

import copy
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULTS: dict[str, dict[str, Any]] = {
    "self": {"display_name": ""},
    "osc": {
        "mode": "auto",
        "listen_port": 9001,
        "direct_port": 9010,
        "send_host": "127.0.0.1",
        "send_port": 9000,
        "send_parameters": True,
    },
    "oyasumi": {"enabled": False, "address": "/avatar/parameters/VsuiLog/OyasumiSleep"},
    "chatbox": {"enabled": False, "sleep_text": "💤 おやすみなさい", "wake_text": "おはようございます"},
    "detect": {
        "sensitivity": "normal",
        "sleep_threshold": 0.03,
        "wake_threshold": 0.30,
        "angle_weight": 0.01,
        "sleep_minutes": 10,
        "wake_minutes": 3,
        "gap_minutes": 10,
        "afk_minutes": 2,
        "merge_minutes": 30,
        "min_samples": 5,
        "max_jump": 1.0,
        "frozen_samples": 20,
        "co_sleeper_minutes": 30,
    },
    "log": {"directory": "", "patterns": {}},
    "output": {"directory": "", "card_show_names": False, "keep_samples_days": 30},
}

DEFAULT_TOML = """\
# V睡ログ 設定ファイル
# 変更したら V睡ログ を再起動してください。

[self]
display_name = ""          # あなたの VRChat 表示名。空なら自動で判定します

[osc]
mode = "auto"              # auto（おすすめ） | oscquery | fixed
listen_port = 9001         # fixed モードの受信ポート
direct_port = 9010         # 外部ツール（OyasumiVR 等）からの直送用。0 で無効
send_host = "127.0.0.1"
send_port = 9000           # VRChat の受信ポート
send_parameters = true     # アバターに VsuiLog/Sleeping, VsuiLog/Visitors を送る

[oyasumi]
enabled = false            # OyasumiVR のスリープモードと同期する
address = "/avatar/parameters/VsuiLog/OyasumiSleep"

[chatbox]
enabled = false            # 入眠・起床時にチャットボックスへ送る
sleep_text = "💤 おやすみなさい"
wake_text = "おはようございます"

[detect]
sensitivity = "normal"     # low | normal | high（high ほど「寝た」と判定されやすい）
sleep_threshold = 0.03
wake_threshold = 0.30
angle_weight = 0.01
sleep_minutes = 10
wake_minutes = 3
gap_minutes = 10
afk_minutes = 2
merge_minutes = 30
min_samples = 5
max_jump = 1.0
frozen_samples = 20
co_sleeper_minutes = 30

[log]
directory = ""             # 空なら VRChat の既定の場所

[log.patterns]             # ログ形式が変わった時だけ設定します（通常は空のまま）

[output]
directory = ""             # 空なら ドキュメント\\VsuiLog
card_show_names = false    # true で共有カードを既定で名前入りにする
keep_samples_days = 30
"""

SENSITIVITY = {"low": 0.5, "normal": 1.0, "high": 2.0}
OSC_MODES = ("auto", "oscquery", "fixed")


class ConfigError(Exception):
    """User-facing configuration problem (message is Japanese)."""


@dataclass(frozen=True)
class DetectParams:
    sleep_threshold: float
    wake_threshold: float
    angle_weight: float
    sleep_minutes: int
    wake_minutes: int
    gap_minutes: int
    afk_minutes: int
    merge_minutes: int
    min_samples: int
    max_jump: float
    frozen_samples: int
    co_sleeper_minutes: int

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> "DetectParams":
        d = cfg["detect"]
        k = SENSITIVITY[d["sensitivity"]]
        return cls(
            sleep_threshold=d["sleep_threshold"] * k,
            wake_threshold=d["wake_threshold"] * k,
            angle_weight=d["angle_weight"],
            sleep_minutes=d["sleep_minutes"],
            wake_minutes=d["wake_minutes"],
            gap_minutes=d["gap_minutes"],
            afk_minutes=d["afk_minutes"],
            merge_minutes=d["merge_minutes"],
            min_samples=d["min_samples"],
            max_jump=d["max_jump"],
            frozen_samples=d["frozen_samples"],
            co_sleeper_minutes=d["co_sleeper_minutes"],
        )


def _merge(base: dict, override: Mapping, where: str = "") -> None:
    for key, value in override.items():
        if key not in base:
            raise ConfigError(f"設定に不明な項目があります: {where}{key}")
        if isinstance(base[key], dict):
            if not isinstance(value, Mapping):
                raise ConfigError(f"設定 {where}{key} は表（[{where}{key}]）で書いてください")
            if key == "patterns":
                base[key] = dict(value)
            else:
                _merge(base[key], value, f"{where}{key}.")
        else:
            base[key] = _coerce(base[key], value, f"{where}{key}")


def _coerce(default: Any, value: Any, name: str) -> Any:
    kind = type(default)
    try:
        if kind is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in ("true", "1", "yes", "on"):
                return True
            if isinstance(value, str) and value.lower() in ("false", "0", "no", "off"):
                return False
            raise ValueError
        if kind is int:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if kind is float:
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        return str(value)
    except (TypeError, ValueError):
        raise ConfigError(f"設定 {name} の値 {value!r} が正しくありません（{kind.__name__} で指定してください）") from None


def _validate(cfg: dict) -> None:
    if cfg["osc"]["mode"] not in OSC_MODES:
        raise ConfigError(f"osc.mode は {' / '.join(OSC_MODES)} のどれかにしてください")
    if cfg["detect"]["sensitivity"] not in SENSITIVITY:
        raise ConfigError("detect.sensitivity は low / normal / high のどれかにしてください")
    for key in ("listen_port", "send_port"):
        if not 1 <= cfg["osc"][key] <= 65535:
            raise ConfigError(f"osc.{key} は 1〜65535 にしてください")
    if not 0 <= cfg["osc"]["direct_port"] <= 65535:
        raise ConfigError("osc.direct_port は 0〜65535 にしてください（0 で無効）")
    d = cfg["detect"]
    for key in ("sleep_threshold", "wake_threshold", "angle_weight", "max_jump"):
        if d[key] < 0:
            raise ConfigError(f"detect.{key} は 0 以上にしてください")
    for key in ("sleep_minutes", "wake_minutes", "gap_minutes", "afk_minutes", "min_samples", "frozen_samples"):
        if d[key] < 1:
            raise ConfigError(f"detect.{key} は 1 以上にしてください")
    if d["wake_threshold"] < d["sleep_threshold"]:
        raise ConfigError("detect.wake_threshold は sleep_threshold 以上にしてください")
    for key, pattern in cfg["log"]["patterns"].items():
        try:
            re.compile(pattern)
        except re.error as e:
            raise ConfigError(f"log.patterns.{key} の正規表現が正しくありません: {e}") from None


def load_config(path: Path | None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    if path is not None and path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"設定ファイルの書き方に誤りがあります（{path}）: {e}") from None
        _merge(cfg, data)
    env = os.environ if env is None else env
    for section, values in DEFAULTS.items():
        for key, default in values.items():
            if isinstance(default, dict):
                continue
            name = f"VSUILOG_{section.upper()}_{key.upper()}"
            if name in env:
                cfg[section][key] = _coerce(default, env[name], f"{section}.{key}")
    _validate(cfg)
    return cfg


def ensure_config_file(path: Path) -> bool:
    """Write the commented default config if missing. Returns True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    return True


def save_self_name(path: Path, name: str) -> None:
    """Persist the auto-detected display name into [self].display_name."""
    ensure_config_file(path)
    text = path.read_text(encoding="utf-8")
    value = json.dumps(name, ensure_ascii=False)  # a valid TOML basic string
    new, n = re.subn(
        r'(?m)^(display_name\s*=\s*)"(?:[^"\\]|\\.)*"',
        lambda m: m.group(1) + value,
        text,
        count=1,
    )
    if n == 0:
        new = text.rstrip("\n") + f"\n\n[self]\ndisplay_name = {value}\n"
    path.write_text(new, encoding="utf-8")
