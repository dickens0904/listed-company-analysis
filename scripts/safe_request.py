# -*- coding: utf-8 -*-
"""
通用工具：统一HTTP请求 + 降级处理

所有模块统一使用 safe_get() 替代 requests.get()，
自动处理：超时、重试、空数据、API变更。

2026-10-16 审计修复（P0）：
    旧版所有失败均静默 return None，上游无法区分
    "网络失败" / "该公司确实无此项数据" / "数据为0"，
    下游又用默认值顶替 → 错误无声扩散成结论。
    本次新增：
      - DataSourceError 异常 + strict 模式：关键维度失败即抛，异常即停。
      - safe_get_checked()：返回带 status(ok/empty/failed) 的结构，
        杜绝 None 的歧义。
"""
import requests
import time
import sys

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class DataSourceError(Exception):
    """
    数据源失败异常（P0 新增）。

    用途：关键维度（财务报表/股权结构/估值）在 strict 模式下
    数据源失败时上抛，让调用方"异常即停"，
    而不是静默降级为 None 后由下游编造默认值。
    """
    def __init__(self, url: str, reason: str, dim: str = None):
        self.url = url
        self.reason = reason
        self.dim = dim
        super().__init__(f"数据源失败[{dim or 'unknown'}]: {reason} | {url[:80]}")


# 默认请求头
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/html, */*',
}

# 默认超时（秒）
DEFAULT_TIMEOUT = 20

# 最大重试次数
MAX_RETRIES = 2

# 重试间隔（秒）
RETRY_DELAY = 1.5


def safe_get(url, params=None, headers=None, timeout=None,
             retries=MAX_RETRIES, retry_delay=RETRY_DELAY,
             backoff=None, expect_json=True, encoding='utf-8',
             strict=False, dim=None):
    """
    安全的HTTP GET请求，带重试和降级处理

    Args:
        url: 请求URL
        params: 查询参数
        headers: 自定义请求头（合并DEFAULT_HEADERS）
        timeout: 超时秒数
        retries: 重试次数
        retry_delay: 重试间隔
        backoff: 兼容参数，传了用作retry_delay
        expect_json: 是否期望JSON响应
        encoding: 响应编码
        strict: True 时最终失败抛 DataSourceError 而非返回 None（P0）
        dim: 维度名，用于异常信息定位（P0）

    Returns:
        dict/list/str: 解析后的响应数据
        None: 请求失败（strict=False 时）

    Raises:
        DataSourceError: strict=True 且所有重试均失败时
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    timeout = timeout or DEFAULT_TIMEOUT
    # backoff 兼容：如果传了backoff，用作retry_delay
    if backoff is not None:
        retry_delay = backoff

    last_reason = 'unknown'

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=merged_headers,
                           timeout=timeout)
            r.encoding = encoding

            if r.status_code != 200:
                last_reason = f'HTTP {r.status_code}'
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
                break

            if expect_json:
                try:
                    return r.json()
                except ValueError:
                    # 不是JSON，可能API变更
                    last_reason = '响应非JSON（API可能已变更）'
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    break
            else:
                return r.text

        except requests.Timeout:
            last_reason = '请求超时'
            print(f"  ⚠️ 请求超时: {url[:60]}...")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            break

        except requests.ConnectionError:
            last_reason = '连接失败'
            print(f"  ⚠️ 连接失败: {url[:60]}...")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            break

        except Exception as e:
            last_reason = f'请求异常: {e}'
            print(f"  ⚠️ 请求异常: {e}")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            break

    # 所有重试均失败（P0：strict 模式异常即停）
    if strict:
        raise DataSourceError(url, last_reason, dim=dim)
    return None


def safe_get_checked(url, params=None, dim=None, **kwargs) -> dict:
    """
    带状态标记的 GET（P0 新增）：让调用方能区分三种结果，
    不再面对含义模糊的 None。

    Returns:
        {
          'status': 'ok' | 'empty' | 'failed',
          'data': <解析后的数据 or None>,
          'error': <失败原因 or None>,
          'source': 'T3-API',
          '_meta': {'status': ..., 'url': ..., 'fetched_at': ...}
        }
    """
    from datetime import datetime
    try:
        data = safe_get(url, params=params, dim=dim, **kwargs)
    except DataSourceError as e:
        return _checked_result('failed', None, str(e), url)

    if data is None:
        return _checked_result('failed', None, '请求失败或响应不可解析', url)

    # 判断是否"查到了但无数据"（常见空结构）
    if isinstance(data, dict):
        if data.get('error'):
            return _checked_result('failed', None, str(data.get('error')), url)
        if data.get('result') is None or (
                isinstance(data.get('result'), dict)
                and not data['result'].get('data')):
            return _checked_result('empty', None, None, url)
    if isinstance(data, list) and len(data) == 0:
        return _checked_result('empty', None, None, url)

    return _checked_result('ok', data, None, url)


def _checked_result(status, data, error, url):
    from datetime import datetime
    return {
        'status': status,
        'data': data,
        'error': error,
        'source': 'T3-API',
        '_meta': {
            'status': status,
            'url': url[:120],
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        },
    }


def safe_extract(data, path, default=None):
    """
    安全地从嵌套dict/list中提取值

    Args:
        data: 嵌套数据结构
        path: 路径列表，如 ['result', 'data', 0, 'name']
        default: 找不到时的默认值

    Returns:
        找到的值或default
    """
    current = data
    for key in path:
        if current is None:
            return default
        if isinstance(key, int) and isinstance(current, list):
            if key < len(current):
                current = current[key]
            else:
                return default
        elif isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current if current is not None else default


def safe_float(value, default=None):
    """安全转换为float"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=None):
    """安全转换为int"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_post(url, json=None, data=None, headers=None, timeout=None,
              retries=MAX_RETRIES, retry_delay=RETRY_DELAY,
              expect_json=True, encoding='utf-8'):
    """
    安全的HTTP POST请求，带重试和降级处理

    Args:
        url: 请求URL
        json: JSON请求体
        data: 表单数据（dict或str）
        headers: 自定义请求头
        timeout: 超时秒数
        retries: 重试次数
        retry_delay: 重试间隔
        expect_json: 是否期望JSON响应
        encoding: 响应编码

    Returns:
        requests.Response 对象（调用方自行处理）
        None: 请求失败
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    timeout = timeout or DEFAULT_TIMEOUT

    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=json, data=data,
                            headers=merged_headers, timeout=timeout)
            r.encoding = encoding
            return r
        except requests.Timeout:
            print(f"  ⚠️ POST超时: {url[:60]}...")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            return None
        except requests.ConnectionError:
            print(f"  ⚠️ POST连接失败: {url[:60]}...")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            return None
        except Exception as e:
            print(f"  ⚠️ POST异常: {e}")
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            return None
    return None
