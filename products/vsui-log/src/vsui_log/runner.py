"""The resident loop behind ``vsui-log run``. ``step(now)`` is the unit tests drive."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from .achievements import ACHIEVEMENTS
from .config import DetectParams, save_self_name
from .engine import Engine, Outputs
from .logparse import LogParser
from .logtail import LogTailer
from .oscio import Handlers, OscReceiver, OscSender, build_dispatcher
from .paths import AppPaths
from .report import fmt_duration
from .store import NightRecord, Store

log = logging.getLogger(__name__)

CHECKPOINT_EVERY = timedelta(seconds=60)
POSE_MISSING_AFTER = timedelta(minutes=5)
OSC_FRESH = timedelta(seconds=60)

MSG_FORMAT = "VRChat のログ形式が変わった可能性があります。V睡ログの更新を確認するか、設定の [log.patterns] を見直してください。"
MSG_NO_POSE = (
    "VRChat から頭の動きが届いていません。VRChat の OSC 設定で追加の同意（トラッキングデータの送信）が"
    "必要な場合があります。README の「頭の動きが届かないとき」を参照してください。"
)


class Runner:
    def __init__(
        self,
        cfg: dict[str, Any],
        paths: AppPaths,
        clock: Callable[[], datetime] = datetime.now,
        receiver_factory: Callable[[Any], OscReceiver] | None = None,
        outputs: Outputs | None = None,
        notify: Callable[[str], None] = print,
    ) -> None:
        self.cfg = cfg
        self.paths = paths
        self.clock = clock
        self.notify = notify
        self.started_at = clock()
        self.store = Store(paths.db_path)
        if self.store.recovered_from is not None:
            notify(f"データベースが壊れていたため、{self.store.recovered_from.name} に退避して新しく作りました。")
        osc = cfg["osc"]
        self.outputs = outputs or OscSender(osc["send_host"], osc["send_port"], osc["send_parameters"])
        oy = cfg["oyasumi"]
        self.engine = Engine(
            DetectParams.from_config(cfg),
            self.store,
            self.outputs,
            self_name=cfg["self"]["display_name"],
            on_self_confirmed=self._self_confirmed,
            chatbox_enabled=cfg["chatbox"]["enabled"],
            sleep_text=cfg["chatbox"]["sleep_text"],
            wake_text=cfg["chatbox"]["wake_text"],
            oyasumi_address=oy["address"] if oy["enabled"] else None,
            started_at=self.started_at,
            on_night_saved=self._night_saved,
            keep_samples_days=cfg["output"]["keep_samples_days"],
        )
        self.tailer = LogTailer(paths.log_dir, LogParser(cfg["log"]["patterns"]))
        handlers = Handlers(
            pose=self.engine.on_pose, afk=self.engine.on_afk, vrmode=self.engine.on_vrmode,
            oyasumi=self.engine.on_oyasumi if oy["enabled"] else None,
            oyasumi_address=oy["address"] if oy["enabled"] else None,
        )
        dispatcher = build_dispatcher(handlers, clock)
        if receiver_factory is not None:
            self.receiver = receiver_factory(dispatcher)
        else:
            self.receiver = OscReceiver(
                dispatcher, osc["mode"], osc["listen_port"], osc["direct_port"], on_warning=notify
            )
        self._last_checkpoint: datetime | None = None
        self._warned_pose = False

    # ------------------------------------------------------------------ callbacks

    def _self_confirmed(self, name: str) -> None:
        try:
            save_self_name(self.paths.config_path, name)
        except OSError as e:  # pragma: no cover
            log.warning("could not save self name: %s", e)
        self.notify(f"あなたの表示名を「{name}」と判定し、設定に保存しました（違う場合は設定の [self] を書き換えてください）。")

    def _night_saved(self, night: NightRecord, unlocked: list[str]) -> None:
        if night.sleep_minutes is not None:
            self.notify(f"記録しました: {night.night_date} 睡眠 {fmt_duration(night.sleep_minutes)}")
        else:
            self.notify(f"記録しました: {night.night_date}（睡眠時間なし）")
        for k in unlocked:
            self.notify(f"実績解除: {ACHIEVEMENTS[k]}")

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        now = self.clock()
        rec = self.engine.recover(now)
        if rec is not None:
            self.notify("前回の終了時に記録中だった夜を保存しました。")
        self.receiver.start()  # warnings arrive through on_warning, possibly later (mDNS)
        if not self.paths.log_dir.is_dir():
            self.notify(f"VRChat のログフォルダが見つかりません（{self.paths.log_dir}）。`vsui-log doctor` で確認してください。")

    def step(self, now: datetime | None = None) -> None:
        now = now or self.clock()
        for ev in self.tailer.poll(now):
            self.engine.on_log_event(ev)
        self.engine.tick(now)
        if self._last_checkpoint is None or now - self._last_checkpoint >= CHECKPOINT_EVERY:
            self.engine.checkpoint(now)
            self._last_checkpoint = now
        if self.tailer.format_warning_due(now):
            self.notify(MSG_FORMAT)
        self._check_pose(now)

    def _check_pose(self, now: datetime) -> None:
        e = self.engine
        if self._warned_pose or e.last_pose_at is not None or e.vrmode == 0 or e.last_osc_at is None:
            return
        if now - self.started_at >= POSE_MISSING_AFTER:
            self._warned_pose = True
            self.notify(MSG_NO_POSE)

    def stop(self, now: datetime | None = None) -> None:
        self.engine.shutdown(now or self.clock())
        self.receiver.stop()
        self.store.close()

    # ------------------------------------------------------------------ status

    def status_line(self, now: datetime | None = None) -> str:
        now = now or self.clock()
        s = self.engine.status()
        mode = "デスクトップ" if s["mode"] == "desktop" else "VR"
        state = "睡眠中" if s["asleep"] else "起床中"
        motion = f"{s['motion']:.2f}" if s["motion"] is not None else "―"
        fresh = self.engine.last_osc_at is not None and now - self.engine.last_osc_at <= OSC_FRESH
        osc = "OK" if fresh else "待機中"
        if self.receiver.active_mode == "fixed":
            osc += "(固定ポート)"
        logs = "OK" if self.tailer.current else "なし"
        world = s["world"] or "VRChat 待機中"
        return f"[{mode}] {state} / 動き {motion} / {world} / {s['people']}人 / OSC: {osc} / ログ: {logs}"
