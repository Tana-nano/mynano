"""デーモンのログ。

`print` のままでも動くが、常駐が長くなると2つ困る。

1. **日付でファイルを分けられない。** `deploy/windows/nano-unconscious.bat` は
   起動時に一度だけ日付を決めてリダイレクトしていた。3週間動き続けると、
   3週間ぶんが「起動日」の名前のファイルに入り、際限なく太る。
   ローテーションはデーモン自身が持たないと成立しない。
2. **重さの区別がつかない。** 「することなし」と「ジョブが3回失敗した」が
   同じ見た目で並ぶ。何か起きたか後から探せない。

依存は増やさない。`logging` は標準ライブラリ（禁則3）。
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from .config import Config

LOGGER_NAME = "nano.unconscious"
# 自分が付けたハンドラの目印。他所（pytest の capture など）が同じ logger に
# ハンドラを足していることがあるので、「設定済みか」は数ではなくこれで判定する。
_MARK = "_nano_handler"
_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup(config: Config, verbose: bool = False, to_stream: bool = True) -> logging.Logger:
    """`soul/log/unconscious.log` に日次ローテーションで書く logger を返す。

    二重に呼ばれてもハンドラは増やさない（`nano daemon` を同じプロセスで
    2回組み立てるテストがあるため）。
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    if own_handlers(logger):
        return logger

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    config.log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        config.log_dir / "unconscious.log",
        when="midnight",
        backupCount=config.unconscious.log_retain_days,
        # 常駐先は Windows。既定は cp932 なので、明示しないと
        # 日本語のログ1行で UnicodeEncodeError になって落ちる。
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(formatter)
    setattr(handler, _MARK, True)
    logger.addHandler(handler)

    if to_stream:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        setattr(stream, _MARK, True)
        logger.addHandler(stream)
    return logger


def own_handlers(logger: logging.Logger | None = None) -> list[logging.Handler]:
    logger = logger or logging.getLogger(LOGGER_NAME)
    return [handler for handler in logger.handlers if getattr(handler, _MARK, False)]


def reset() -> None:
    """自分が付けたハンドラだけ外す。テストが一時ディレクトリを掴んだままにしないため。"""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in own_handlers(logger):
        logger.removeHandler(handler)
        handler.close()
