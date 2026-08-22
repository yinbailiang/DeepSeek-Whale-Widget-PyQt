"""峰谷定价与今日已用换算（与原版 lib/index.js 完全一致）。

DeepSeek CNY 定价（每百万 token）：[空闲时段价, 高峰时段价]。
高峰时段：工作日 9:00–12:00 和 14:00–18:00（北京时间）；
2026-08-23 起周末全天按谷价。DeepSeek 调价时改这里。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# 高峰时段 [开始小时, 结束小时)，北京时间
PEAK_HOURS: List[Tuple[int, int]] = [
    (9, 12),
    (14, 18),
]

# 基础价：缓存命中=输入价；未命中=输入；输出+推理=输出
BASE_PRICE: Dict[str, List[float]] = {"hit": [0.05, 0.1], "miss": [1.5, 3.0], "out": [4.5, 9.0]}
# deepseek-v4-pro 为 flash 的 3 倍价（官方 2026-08-17 生效）；vision-exp 与 flash 同价
PRO_PRICE: Dict[str, List[float]] = {"hit": [0.15, 0.3], "miss": [4.5, 9.0], "out": [13.5, 27.0]}

PRICING: Dict[str, Dict[str, List[float]]] = {
    "deepseek-v4-flash-vision-exp": BASE_PRICE,
    "deepseek-v4-flash": BASE_PRICE,
    "deepseek-v4-pro": PRO_PRICE,
    "deepseek-chat": BASE_PRICE,
    "deepseek-reasoner": BASE_PRICE,
    "_default": BASE_PRICE,
}

# 周末谷价生效时刻：UTC 2026-08-22 16:00 == 北京时间 2026-08-23 00:00
WEEKEND_VALLEY_FROM: datetime = datetime(2026, 8, 22, 16, 0, 0, tzinfo=timezone.utc)
WEEKEND_VALLEY_FROM_SEC: float = WEEKEND_VALLEY_FROM.timestamp()

BJ_TZ = timezone(timedelta(hours=8))


def price_for(model: Optional[str]) -> Dict[str, List[float]]:
    """按模型名匹配定价表（子串匹配，与原版一致）。"""
    m = str(model or "").lower()
    for key, price in PRICING.items():
        if key == "_default":
            continue
        if m.find(key) != -1:
            return price
    return PRICING["_default"]


def is_peak_time(time_sec: Any) -> bool:
    """判断某个 epoch 秒是否处于高峰时段（北京时间）。

    2026-08-23 起周末（周六/周日）全天按谷价；生效时刻之前的历史
    分桶仍按旧规则计价，所以周末判定带生效分界。
    """
    try:
        n = float(time_sec)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(n):
        return False
    bj = datetime.fromtimestamp(n, tz=BJ_TZ)
    if n >= WEEKEND_VALLEY_FROM_SEC:
        # 生效时刻起，周末全天谷价
        if bj.weekday() >= 5:  # 5=周六 6=周日
            return False
    hour = bj.hour
    for start, end in PEAK_HOURS:
        if start <= hour < end:
            return True
    return False


def _num(v: Any) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_today_usage(data: Any) -> Optional[Dict[str, float]]:
    """把平台用量接口返回换算成今日金额。

    data.data.biz_data.series[]: [{model, buckets:[{time, usage:{RESPONSE_TOKEN,
    PROMPT_CACHE_HIT_TOKEN, PROMPT_CACHE_MISS_TOKEN}}]}]
    """
    d = data
    if d and isinstance(d, dict):
        dd = d.get("data")
        if dd and isinstance(dd, dict) and dd.get("biz_data") and isinstance(dd["biz_data"], dict):
            d = dd["biz_data"]
        elif dd and isinstance(dd, dict) and isinstance(dd.get("series"), list):
            d = dd
    if not isinstance(d, dict):
        return None
    series = d.get("series")
    if not isinstance(series, list) or len(series) == 0:
        return None
    cost = 0.0
    tokens = 0.0
    found = False
    for s in series:
        if not isinstance(s, dict):
            continue
        p = price_for(s.get("model"))
        buckets = s.get("buckets")
        if not isinstance(buckets, list):
            continue
        for b in buckets:
            if not isinstance(b, dict):
                continue
            u = b.get("usage")
            if not isinstance(u, dict):
                continue
            hit = _num(u.get("PROMPT_CACHE_HIT_TOKEN"))
            miss = _num(u.get("PROMPT_CACHE_MISS_TOKEN"))
            out = _num(u.get("RESPONSE_TOKEN"))
            if hit + miss + out == 0:
                continue
            found = True
            tokens += hit + miss + out
            pi = 1 if is_peak_time(b.get("time")) else 0
            cost += (hit / 1e6) * p["hit"][pi] + (miss / 1e6) * p["miss"][pi] + (out / 1e6) * p["out"][pi]
    return {"amount": cost, "tokens": tokens} if found else None


def fmt_amount(balance: Any, currency: str = "CNY") -> str:
    """金额显示，与原版 fmt() 一致。"""
    try:
        num = float(balance)
        fixed = f"{num:.2f}" if math.isfinite(num) else "--"
    except (TypeError, ValueError):
        fixed = "--"
    return f"¥ {fixed}" if currency == "CNY" else f"{fixed} {currency}"
