"""配置与账本持久化。

沿用原版 DSH 挂件的文件名（`.dshw-size.json` / `.dshw-usage.json`），
放在 DSH_HOME（默认 `~/.dsh`）下，这样 PyQt 桌面版与 Web 插件版可以
共享大小/音量/用量模式配置以及「小鲸鱼记账」账本数据。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

CONFIG_FIELDS = [
    "scale", "sound", "vol", "soundSet", "usageMode", "peakMode",
    "bubbleOn", "turnCostOn", "turnCostCloseMs", "scrollGapOn", "scrollGapPx",
    # 桌面版追加的位置字段（原版忽略未知字段）
    "left", "top",
]


def dsh_home() -> Path:
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env)
    return Path.home() / ".dsh"


def _candidates(relative: str) -> list[Path]:
    home = dsh_home()
    return [
        home / relative,
        home / "profiles" / "web" / relative,
        Path.home() / relative,
    ]


def _read_first(relative: str) -> dict[str, Any] | None:
    for p in _candidates(relative):
        try:
            if not p.is_file():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
        except Exception:
            continue
    return None


def _write_first(relative: str, data: dict[str, Any]) -> bool:
    for p in _candidates(relative):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception:
            continue
    return False


# ---------- 挂件配置 ----------

DEFAULT_CONFIG: dict[str, Any] = {
    "scale": 1.0,
    "sound": True,
    "vol": 0.9,
    "soundSet": "duck",          # duck | fx1
    "usageMode": "ledger",       # ledger | token
    "peakMode": "default",       # default | liangwen | qiangqiang
    "bubbleOn": True,
    "turnCostOn": True,
    "turnCostCloseMs": 5000,
    "scrollGapOn": False,
    "scrollGapPx": 17,
    "left": None,
    "top": None,
}


def normalize_mode(value: Any, kind: str) -> str:
    if kind == "usage":
        return "token" if value == "token" else "ledger"
    if kind == "peak":
        return value if value in ("liangwen", "qiangqiang") else "default"
    if kind == "soundSet":
        return "fx1" if value == "fx1" else "duck"
    return str(value or "")


def read_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    data = _read_first(".dshw-size.json")
    if data:
        if isinstance(data.get("scale"), (int, float)) and 0.5 <= float(data["scale"]) <= 2.6:
            cfg["scale"] = float(data["scale"])
        if isinstance(data.get("sound"), bool):
            cfg["sound"] = data["sound"]
        if isinstance(data.get("vol"), (int, float)):
            cfg["vol"] = max(0.0, min(1.0, float(data["vol"])))
        cfg["soundSet"] = normalize_mode(data.get("soundSet"), "soundSet")
        cfg["usageMode"] = normalize_mode(data.get("usageMode"), "usage")
        cfg["peakMode"] = normalize_mode(data.get("peakMode"), "peak")
        if isinstance(data.get("bubbleOn"), bool):
            cfg["bubbleOn"] = data["bubbleOn"]
        if isinstance(data.get("turnCostOn"), bool):
            cfg["turnCostOn"] = data["turnCostOn"]
        if isinstance(data.get("turnCostCloseMs"), (int, float)):
            cfg["turnCostCloseMs"] = max(0, int(data["turnCostCloseMs"]))
        if isinstance(data.get("scrollGapOn"), bool):
            cfg["scrollGapOn"] = data["scrollGapOn"]
        if isinstance(data.get("scrollGapPx"), (int, float)):
            cfg["scrollGapPx"] = max(0, int(data["scrollGapPx"]))
        for key in ("left", "top"):
            if isinstance(data.get(key), (int, float)):
                cfg[key] = int(data[key])
    return cfg


def write_config(cfg: dict[str, Any]) -> bool:
    body = {k: cfg.get(k, DEFAULT_CONFIG.get(k)) for k in CONFIG_FIELDS}
    body["updatedAt"] = __import__("datetime").datetime.now().astimezone().isoformat()
    return _write_first(".dshw-size.json", body)


# ---------- 小鲸鱼记账账本 ----------

def today_key() -> str:
    now = __import__("datetime").datetime.now()
    return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"


def read_ledger() -> dict[str, Any]:
    data = _read_first(".dshw-usage.json")
    if data and isinstance(data.get("date"), str):
        return data
    return {"date": today_key(), "lastBalance": None, "todayUsage": 0.0, "history": {}}


def write_ledger(led: dict[str, Any]) -> bool:
    return _write_first(".dshw-usage.json", led)


def record_ledger_usage(current_balance: float) -> dict[str, Any]:
    """记账模式：每次观测到余额后，用余额正差值累计当天用量（跨天自动归零并归档）。"""
    t = today_key()
    led = read_ledger()
    if led.get("date") != t:
        if led.get("date") and isinstance(led.get("todayUsage"), (int, float)):
            led.setdefault("history", {})[led["date"]] = led["todayUsage"]
        led["date"] = t
        led["lastBalance"] = current_balance
        led["todayUsage"] = 0.0
    else:
        prev = led.get("lastBalance")
        if prev is None or not isinstance(prev, (int, float)):
            prev = current_balance
        if current_balance < prev:
            led["todayUsage"] = float(led.get("todayUsage", 0.0)) + (prev - current_balance)
        led["lastBalance"] = current_balance
    # 归档保留 30 天
    keys = sorted(led.get("history", {}).keys())
    while len(keys) > 30:
        del led["history"][keys.pop(0)]
    write_ledger(led)
    return led


# ---------- 凭据（独立文件，不混入共享配置） ----------

def credentials_path() -> Path:
    return dsh_home() / ".dshw-pyqt-credentials.json"


def read_credentials() -> dict[str, str]:
    p = credentials_path()
    try:
        if p.is_file():
            data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
            return {k: str(v) for k, v in data.items() if v}
    except Exception:
        pass
    return {}


def write_credentials(creds: dict[str, str]) -> bool:
    try:
        p = credentials_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False
