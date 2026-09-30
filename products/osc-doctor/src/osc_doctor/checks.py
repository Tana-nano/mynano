"""Turn collected facts into findings. Pure functions: no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .cache import CacheSummary
from .oscquery import VrcQuery
from .sysinfo import VRCHAT_EXE, LaunchOsc, PortState

OK = "OK"
INFO = "情報"
WARN = "注意"
NG = "NG"

DEFAULT_IN = 9000
DEFAULT_OUT = 9001
TRACKING_SETTING = "Allow Sending Head and Wrist VR Tracking OSC Data"


@dataclass(frozen=True)
class Finding:
    id: str
    status: str
    label: str
    message: str
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class RxSummary:
    total: int = 0
    fixed: int = 0
    oscquery: int = 0
    addresses: int = 0
    avatar_params: int = 0
    tracking_oscquery: int = 0
    tracking_rate: float | None = None  # messages/s for head pose (or any tracking address)
    vrmode: int | None = None


@dataclass
class Facts:
    vrc_running: bool = False
    launch: LaunchOsc | None = None
    installer_running: bool = False
    vr_runtime: bool = False
    explicit_in: int | None = None
    explicit_out: int | None = None
    ports: dict[int, PortState] = field(default_factory=dict)
    fixed_bound: bool = False
    discovery_vrc: VrcQuery | None = None
    mdns_ok: bool = True
    rx: RxSummary = field(default_factory=RxSummary)
    extended: bool = False
    cache: CacheSummary | None = None

    # --- derived ports ----------------------------------------------------

    @property
    def nominal_in(self) -> int:
        """In-port without asking VRChat: --in-port > launch arg > 9000."""
        if self.explicit_in:
            return self.explicit_in
        if self.launch:
            return self.launch.in_port
        return DEFAULT_IN

    @property
    def vrc_in(self) -> int:
        """VRChat's receive port: HOST_INFO first (VRChat may pick another free port)."""
        if self.discovery_vrc is not None:
            return self.discovery_vrc.osc_port
        return self.nominal_in

    @property
    def out_port(self) -> int:
        if self.explicit_out:
            return self.explicit_out
        if self.launch:
            return self.launch.out_port
        return DEFAULT_OUT

    def port(self, p: int) -> PortState:
        return self.ports.get(p, PortState(False))


def resolve_oscquery_port(explicit: int | None, launch: LaunchOsc | None) -> int:
    # UNVERIFIED: VRChat serves OSCQuery on TCP <outPort> (vrc-oscquery-lib Readme says 9001 or the launch-arg port).
    if explicit:
        return explicit
    if launch:
        return launch.out_port
    return DEFAULT_OUT


def _owner(st: PortState) -> str:
    return st.owner or "他のアプリ（名前は取得できませんでした）"


def judge(f: Facts) -> list[Finding]:
    out: list[Finding] = []
    add = out.append

    # VRChat process
    if not f.vrc_running:
        add(Finding("VRC_NOT_RUNNING", NG, "VRChat", "起動していません",
                    ("VRChat を起動してから、もう一度実行してください",)))
    else:
        arg = f"起動引数 --osc={f.launch.in_port}:{f.launch.sender_ip}:{f.launch.out_port}" if f.launch else "起動引数 --osc なし"
        add(Finding("VRC_RUNNING", OK, "VRChat", f"起動しています（{arg}）"))

    if f.installer_running:
        add(Finding("INSTALLER_LEFT", WARN, "install.exe", "VRChat のインストーラが残っています（OSC のポートを使い続けることがあります）",
                    ("タスクマネージャーで install.exe を終了するか、PC を再起動してください",)))

    oq = f.discovery_vrc
    if f.vrc_running:
        # VRChat's receive port
        port = f.vrc_in
        st = f.port(port)
        nominal = f.nominal_in
        if oq is not None and port != nominal:
            nst = f.port(nominal)
            if nst.in_use and not nst.owned_by(VRCHAT_EXE):
                add(Finding("IN_PORT_ROUTED", INFO, f"ポート {nominal}", f"{_owner(nst)} が使っています。VRChat 本体はポート {port} で受信しています（ルーター構成）",
                            (f"固定ポートで送るアプリは {nominal} の {_owner(nst)} へ送れば VRChat に届きます",)))
        if st.in_use and st.owned_by(VRCHAT_EXE):
            add(Finding("IN_PORT_VRC", OK, f"ポート {port}", "VRChat.exe が受信に使っています"))
        elif st.in_use and st.owner:
            add(Finding("IN_PORT_OTHER", NG, f"ポート {port}", f"{st.owner} が使っていて、VRChat が受信できません",
                        (f"{st.owner} を閉じるか、VRChat の起動引数 --osc で受信ポートを変えてください",)))
        elif st.in_use:
            add(Finding("IN_PORT_UNKNOWN", INFO, f"ポート {port}", "使用中です（アプリ名は取得できませんでした）"))
        elif oq is not None:
            add(Finding("IN_PORT_STALE", WARN, f"ポート {port}", "VRChat は受信中と言っていますが、ポートが空いています",
                        ("VRChat を再起動してください",)))
        else:
            add(Finding("IN_PORT_FREE", NG, f"ポート {port}", "VRChat が受信していません（OSC が OFF の可能性）",
                        ("VRChat のアクションメニュー → Options → OSC → Enabled にしてください",)))

    # Fixed out port
    ost = f.port(f.out_port)
    if ost.in_use and not f.fixed_bound:
        add(Finding("OUT_PORT_OTHER", INFO, f"ポート {f.out_port}", f"{_owner(ost)} が使っています（OSCドクターは OSCQuery で受信します）",
                    ("固定ポートで受信するアプリは同時に 1 つしか動きません。OSCQuery 対応のアプリは影響を受けません",)))

    if f.vrc_running:
        # VRChat's OSCQuery
        if oq is not None and oq.via == "mdns":
            extra = f"（設定・起動引数では {f.nominal_in}）" if oq.osc_port != f.nominal_in else ""
            add(Finding("OQ_FOUND", OK, "OSCQuery", f"VRChat を見つけました（{oq.name}、受信ポート {oq.osc_port}{extra}）"))
        elif oq is not None:
            why = "mDNS が使えない環境です" if not f.mdns_ok else "mDNS では見つかりませんでした"
            add(Finding("OQ_FOUND_DIRECT", WARN, "OSCQuery", f"VRChat の OSC は ON ですが、{why}（直接確認で受信ポート {oq.osc_port}）",
                        ("ファイアウォールや他の mDNS ソフトが通信を止めている可能性があります。OSCQuery 対応アプリが VRChat を見つけられないことがあります",
                         "固定ポートで動くアプリは影響を受けません")))
        elif not f.mdns_ok:
            add(Finding("OQ_UNAVAILABLE", INFO, "OSCQuery", "確認できませんでした（mDNS が使えません）"))
        else:
            add(Finding("OQ_NOT_FOUND", WARN, "OSCQuery", "VRChat の OSCQuery が見つかりません",
                        ("OSC が OFF の可能性が高いです。アクションメニュー → Options → OSC → Enabled にして再実行してください",)))
        if oq is not None and not oq.has_avatar:
            add(Finding("OQ_NO_AVATAR", WARN, "アバター", "VRChat がアバターの情報を公開していません",
                        ("アバターを読み込み直してください（着替え直す・リセット）",)))

        # Reception
        rx = f.rx
        if rx.total:
            routes = []
            if rx.oscquery:
                routes.append("OSCQuery")
            if rx.fixed:
                routes.append(f"固定ポート {f.out_port}")
            add(Finding("RX_OK", OK, "受信", f"VRChat から {rx.addresses} 種類・{rx.total} 件届きました（{' と '.join(routes)} 経由）"))
            if rx.fixed and not rx.oscquery and oq is not None:
                add(Finding("RX_ONLY_FIXED", WARN, "受信", "固定ポートには届きましたが、OSCQuery 経由では届きませんでした",
                            ("OSCQuery 対応アプリが受信できない状態です。VRChat を再起動してください",)))
        elif oq is not None:
            add(Finding("RX_NONE_OQ", NG, "受信", "VRChat から何も届きませんでした",
                        ("ゲーム内で OSC を OFF→ON すると、OSCQuery のアプリへ送られなくなる不具合があります。VRChat を再起動してください",
                         "アバターの読み込み中でないかも確認してください")))
        else:
            add(Finding("RX_NONE", NG, "受信", "VRChat から何も届きませんでした",
                        ("VRChat のアクションメニュー → Options → OSC → Enabled にしてください",
                         f"ポート {f.out_port} を使っている他のアプリがあれば閉じてください")))

        # Tracking: only sent to OSCQuery apps exposing /tracking/vrsystem.
        if rx.oscquery:
            if rx.tracking_oscquery:
                rate = f"、約 {rx.tracking_rate:.0f} 件/秒" if rx.tracking_rate else ""
                add(Finding("TRACKING_OK", OK, "トラッキング", f"頭・手首の位置が届いています（{rx.tracking_oscquery} 件{rate}）"))
            elif rx.vrmode == 0:
                add(Finding("TRACKING_DESKTOP", INFO, "トラッキング", "デスクトップモードのため対象外です"))
            elif rx.vrmode == 1 or f.vr_runtime:
                add(Finding("TRACKING_MISSING", WARN, "トラッキング", "頭・手首の位置が届いていません",
                            (f"VRChat の設定で「{TRACKING_SETTING}」を ON にしてください",)))
            else:
                add(Finding("TRACKING_UNKNOWN", INFO, "トラッキング", "頭・手首の位置は届いていません（デスクトップなら対象外です）",
                            (f"VR で使っている場合は、VRChat の設定で「{TRACKING_SETTING}」を ON にしてください",)))

    # Avatar config cache
    if f.cache is None:
        add(Finding("CACHE_NONE", INFO, "キャッシュ", "アバター設定のキャッシュはありません"))
    else:
        newest = f"、最新 {f.cache.newest:%Y-%m-%d %H:%M}" if f.cache.newest else ""
        actions: tuple[str, ...] = ()
        if f.vrc_running and f.rx.total and not f.rx.avatar_params:
            actions = ("アバターのパラメータが届いていません。`--fix-cache` でキャッシュを退避してから、アバターを着替え直してください",)
        add(Finding("CACHE_INFO", INFO, "キャッシュ", f"アバター設定 {f.cache.files} 件{newest}", actions))

    return out


def summary(findings: list[Finding]) -> str:
    ng = sum(1 for x in findings if x.status == NG)
    warn = sum(1 for x in findings if x.status == WARN)
    if not ng and not warn:
        return "問題は見つかりませんでした"
    parts = []
    if ng:
        parts.append(f"NG {ng} 件")
    if warn:
        parts.append(f"注意 {warn} 件")
    return "、".join(parts)


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(x.status == NG for x in findings) else 0


def stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")
