# -*- coding: utf-8 -*-
"""
utils.py — 共享工具函数
消除跨模块重复代码（_secucode、_safe_float、em_get 等）。
"""
import time
import random
import json
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def secucode(stock_code: str) -> str:
    """把 6 位股票代码转成东财格式（600519 → 600519.SH）"""
    code = stock_code.strip().split(".")[0]
    if code.startswith(("00", "30")):
        return f"{code}.SZ"
    if code.startswith(("60", "68")):
        return f"{code}.SH"
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def safe_float(val, default=None):
    """安全转 float，空值/None 返回 default"""
    if val is None or val == "" or val == "N/A":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=None):
    """安全转 int"""
    if val is None or val == "" or val == "N/A":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ── 东财防封限流 ─────────────────────────────────────────────

_last_em_call = 0.0
EM_MIN_INTERVAL = 1.0


def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: int = 15) -> dict:
    """
    东财统一请求入口：内置节流（≥1s间隔+随机抖动）。
    返回解析后的 JSON dict。
    """
    global _last_em_call
    wait = EM_MIN_INTERVAL - (time.time() - _last_em_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))

    try:
        hdrs = {"User-Agent": UA}
        if headers:
            hdrs.update(headers)
        qs = ""
        if params:
            qs = "?" + "&".join(
                f"{k}={urllib.request.quote(str(v))}"
                for k, v in params.items())
        req = urllib.request.Request(url + qs, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        _last_em_call = time.time()


def http_get(url: str, timeout: int = 15, headers: dict = None) -> dict:
    """通用 HTTP GET，返回 JSON dict（非东财接口用）"""
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
