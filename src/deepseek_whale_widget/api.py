"""DeepSeek API 访问层：余额拉取、平台实时用量、凭据解析。"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from . import storage
from .pricing import compute_today_usage

BALANCE_URL = "https://api.deepseek.com/user/balance"
PLATFORM_USAGE_URL = "https://platform.deepseek.com/api/v0/usage/by_api_key/amount"
HTTP_TIMEOUT = 20


# ---------- 凭据 ----------

def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """极简 YAML 子集解析：支持缩进嵌套与 key: value。

    只用于 DSH 凭据文件这种简单场景，足够容错。
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip("\"'")
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if value == "":
            node: dict[str, Any] = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            # 去掉常见引号
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            parent[key] = value
    return root


def _find_key(node: Any, key: str) -> str | None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str) and v:
                return v
            found = _find_key(v, key)
            if found:
                return found
    return None


def resolve_credentials() -> dict[str, str | None]:
    """按优先级解析凭据：环境变量 > DSH 凭据 yaml > PyQt 本地凭据文件。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    platform_token = os.environ.get("DEEPSEEK_PLATFORM_TOKEN")

    # DSH 凭据文件（~/.dsh/.credentials.yaml 及 profiles/web 下）
    for path in (
        storage.dsh_home() / ".credentials.yaml",
        storage.dsh_home() / "profiles" / "web" / ".credentials.yaml",
    ):
        try:
            if path.is_file():
                tree = _parse_simple_yaml(path.read_text(encoding="utf-8", errors="ignore"))
                api_key = api_key or _find_key(tree, "DEEPSEEK_API_KEY")
                platform_token = platform_token or _find_key(tree, "DEEPSEEK_PLATFORM_TOKEN")
        except Exception:
            pass

    # PyQt 本地凭据文件（菜单里填写的）
    local = storage.read_credentials()
    api_key = api_key or local.get("DEEPSEEK_API_KEY")
    platform_token = platform_token or local.get("DEEPSEEK_PLATFORM_TOKEN")

    def clean(tok: str | None) -> str | None:
        if not tok:
            return None
        tok = tok.strip()
        return re.sub(r"^Bearer\s+", "", tok, flags=re.IGNORECASE) if tok else None

    return {"api_key": clean(api_key), "platform_token": clean(platform_token)}


# ---------- HTTP ----------

def _http_json(url: str, headers: dict[str, str], timeout: int = HTTP_TIMEOUT) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_balance(api_key: str) -> dict[str, Any]:
    """拉取余额。返回与原版一致的 payload 结构。"""
    if not api_key:
        return {"ok": False, "code": "NO_KEY", "error": "未配置 DEEPSEEK_API_KEY（可设环境变量或在菜单→API 设置里填）"}
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            data = _http_json(
                BALANCE_URL,
                {"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code < 500:
                break
        except Exception as e:
            last_err = e
        else:
            info = _pick_balance_info(data.get("balance_infos"))
            if not info or info.get("total_balance") is None:
                return {"ok": False, "code": "SHAPE", "error": "余额接口返回结构异常"}
            return {
                "ok": True,
                "totalBalance": float(info["total_balance"]),
                "currency": str(info.get("currency") or "CNY"),
                "updatedAt": __import__("datetime").datetime.now().astimezone().isoformat(),
            }
        if attempt == 0:
            import time

            time.sleep(0.5)
    if isinstance(last_err, urllib.error.HTTPError):
        code = "HTTP"
        transient = last_err.code >= 500
        msg = f"余额接口请求失败: HTTP {last_err.code}"
    else:
        code = "HTTP"
        transient = True
        msg = f"余额接口请求失败: {last_err}"
    return {"ok": False, "code": code, "transient": transient, "error": msg}


def _pick_balance_info(infos: Any) -> dict[str, Any] | None:
    if not isinstance(infos, list) or len(infos) == 0:
        return None

    def num(x: Any) -> float:
        try:
            return float(x.get("total_balance"))
        except (AttributeError, TypeError, ValueError):
            return float("nan")

    cny_positive = next((x for x in infos if isinstance(x, dict) and x.get("currency") == "CNY" and num(x) > 0), None)
    if cny_positive:
        return cny_positive
    any_positive = next((x for x in infos if isinstance(x, dict) and num(x) > 0), None)
    if any_positive:
        return any_positive
    cny = next((x for x in infos if isinstance(x, dict) and x.get("currency") == "CNY"), None)
    if cny:
        return cny
    return infos[0] if isinstance(infos[0], dict) else None


def fetch_usage(platform_token: str) -> dict[str, Any]:
    """实时·令牌模式：调用平台用量接口，换算今日金额。"""
    if not platform_token:
        return {"error": "no platform token"}
    try:
        import datetime as dt

        now = dt.datetime.now(dt.timezone.utc).astimezone()
        tz = -(now.utcoffset() or dt.timedelta()).total_seconds()
        start = int(dt.datetime(now.year, now.month, now.day, tzinfo=now.tzinfo).timestamp())
        end = start + 86400
        url = f"{PLATFORM_USAGE_URL}?start={start}&end={end}&tz={int(tz)}"
        data = _http_json(url, {"Authorization": f"Bearer {platform_token}"}, timeout=15)
        u = compute_today_usage(data)
        if u and u["amount"] is not None and u["amount"] == u["amount"]:  # not NaN
            return {"amount": u["amount"], "tokens": u["tokens"]}
        return {"error": "no usage"}
    except Exception as e:
        return {"error": str(e)}
