# -*- coding: utf-8 -*-
"""
thsdk_provider.py - thsdk 同花顺SDK统一数据供给模块
单例模式，自动降级到 bse_price.py（腾讯行情）

已验证可用接口（2026-05-11 实测）：
- market_data_cn(code)          → 实时行情（名称/价格/开高低/成交量）
- market_data_cn(code, '汇总')    → 行情+财务指标+股本（市值在第2行，全NaN）
- market_data_cn(code, '扩展1')  → 资金面（换手率/量比/主力净流入）
- klines(code, count=N, interval='day') → K线（日/周/月）
- intraday_data(code)            → 1分钟分时
- depth(code)                    → 五档盘口
- corporate_action(code)         → 分红历史
- stock_bj_lists()               → 北交所全量股票（314只）
- ths_industry()                 → 申万行业（90个）
- ths_concept()                 → 概念板块（390个）
- block_constituents(link_code)  → 板块成分股
- wencai_nlp(query)              → NLP自然语言选股（支持北交所）
- news(count=N)                  → 7×24快讯
- complete_ths_code(partial)     → 代码补全
- ipo_wait()                    → IPO排队数据
- call_auction(code)             → 集合竞价

不支持北交所：
- klines interval=非day、big_order_flow

单例用法：
    from scripts.thsdk_provider import thsdkp
    r = thsdkp.quote('920262')
    k = thsdkp.klines('920262', count=60)       # 默认日K
    k = thsdkp.klines('920262', count=20, interval='week')
    divs = thsdkp.dividend_history('920262')
    ff = thsdkp.fund_flow('920262')              # 资金流向
    stocks = thsdkp.bj_all_stocks()              # 北交所全量
    nlp = thsdkp.nlp_search('净利润增长超过50%')   # NLP选股
"""
import sys, os, time, json, hashlib, re
from datetime import datetime, timedelta
from pathlib import Path
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# thsdk 路径（允许环境变量 THSDK_PATH 覆盖；默认为本机专属路径，换机须重设或留空）
# 2026-10-22 打包审计修复：仅当路径存在才插入 sys.path，避免换机 import 阶段写死路径污染
_THSDK_PATH = os.environ.get('THSDK_PATH', r'I:\QClaw\resources\openclaw\python\Lib\site-packages')
if _THSDK_PATH and os.path.isdir(_THSDK_PATH) and _THSDK_PATH not in sys.path:
    sys.path.insert(0, _THSDK_PATH)

# 缓存目录
_CACHE_DIR = Path(os.path.expanduser('~')) / '.qclaw' / 'cache' / 'thsdk'
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 全局单例
_thsdk_instance = None


def _get_thsdk():
    """获取thsdk单例（进程内复用）"""
    global _thsdk_instance
    if _thsdk_instance is None:
        import thsdk as _thsdk_mod
        _thsdk_instance = _thsdk_mod.THS({})
        r = _thsdk_instance.connect(max_retries=2)
        if not r.success:
            raise RuntimeError(f"thsdk连接失败: {r.error}")
    return _thsdk_instance


# 频率限制
_last_call = 0
def _rate_limited():
    global _last_call
    now = time.time()
    wait = 0.35 - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _call_thsdk(fn, *args, **kwargs):
    """带≥0.35s频率限制的thsdk调用，失败重试1次"""
    _rate_limited()
    try:
        result = fn(*args, **kwargs)
        if not getattr(result, 'success', False):
            time.sleep(0.5)
            result = fn(*args, **kwargs)
        return result
    except Exception:
        time.sleep(1)
        return fn(*args, **kwargs)


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _to_ths_prefix(code: str, market: str = 'a') -> str:
    """股票代码 → thsdk前缀格式

    规则（实测验证）：
    - 92xxx/83xxx → USTM（北交所）
    - 其他A股    → USHA
    """
    c = code.strip().upper()
    if re.match(r'^9[238]\d+$', c):
        return f'USTM{c}'
    return f'USHA{c}'


def _load_cache(key: str, ttl_seconds: int) -> dict | None:
    """读取缓存（TTL秒内有效）"""
    cache_file = _CACHE_DIR / f'{key}.json'
    if not cache_file.exists():
        return None
    try:
        if time.time() - cache_file.stat().st_mtime > ttl_seconds:
            return None
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(key: str, data: dict | list) -> None:
    """保存缓存"""
    cache_file = _CACHE_DIR / f'{key}.json'
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception as _sexc:
        record(__name__, '_save_cache', _sexc, note='静默降级')
        pass


def _df_to_dict(df) -> list[dict]:
    """DataFrame → list[dict]"""
    if df is None or df.empty:
        return []
    records = []
    for _, row in df.iterrows():
        rec = {}
        for k, v in row.items():
            s = str(v)
            if s not in ('nan', 'None', '', 'NaN') and v is not None:
                try:
                    rec[str(k)] = float(v)
                except (TypeError, ValueError):
                    rec[str(k)] = str(v)
        records.append(rec)
    return records


# ── 主要接口 ─────────────────────────────────────────────────────────────────

class ThsdkProvider:
    """thsdk 数据供给类（单例模式）"""

    @property
    def ths(self):
        return _get_thsdk()

    def _fallback_price(self, code: str, market: str = 'a') -> dict:
        """降级到 bse_price.py（腾讯行情）"""
        try:
            # 相对导入，从 scripts 目录加载
            from scripts.bse_price import fetch_price as _fp
            return _fp(code, market)
        except ImportError:
            return {'stock_code': code, 'status': 'error', 'message': '无数据源'}

    # ── 1. 实时行情 ─────────────────────────────────────────────────────────

    def quote(self, code: str, market: str = 'a') -> dict:
        """获取实时行情

        返回字段：name, price, chg, pct, open, prev_close, high, low,
                  vol_hands, pe, market_cap, datetime, status, source
        """
        cache_key = f'quote_{code}'
        cached = _load_cache(cache_key, 300)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)

        # 用默认 query_key（基础行情，无query_key参数）
        r = _call_thsdk(self.ths.market_data_cn, ths_code)
        result = self._parse_quote(r, code)

        if result.get('status') == 'trading' and result.get('name'):
            # 补充涨跌额/涨跌幅/PE/市值（从扩展1获取）
            if result.get('price') and result.get('prev_close'):
                result['chg'] = round(result['price'] - result['prev_close'], 2)
                if result['prev_close'] > 0:
                    result['pct'] = round((result['chg'] / result['prev_close']) * 100, 2)
            # 尝试从fund_flow获取PE-TTM和市值
            try:
                ff = self.fund_flow(code, market)
                if ff:
                    if not result.get('pe'):
                        result['pe'] = ff.get('市盈率TTM') or ff.get('市盈率')
                    # 注意：扩展1没有总市值/流通市值，市值需从'汇总'query_key单独获取
                    # 这里补充涨幅和振幅
                    if not result.get('pct'):
                        result['pct'] = ff.get('涨幅')  # 扩展1的"涨幅"字段
                    result['pb'] = ff.get('市净率1')
                    result['turnover_rate'] = ff.get('换手率')
                    result['amplitude'] = ff.get('振幅')
                    result['volume_ratio'] = ff.get('量比')
                    result['main_net_inflow'] = ff.get('主力净流入')
            except Exception as _sexc:
                record(__name__, 'quote', _sexc, note='静默降级')
                pass  # fund_flow失败不影响基本行情

            # 补充市值（从'汇总'获取，返回2行，第2行含总市值）
            if not result.get('market_cap'):
                try:
                    r2 = _call_thsdk(self.ths.market_data_cn, ths_code, '汇总')
                    if r2.success and r2.data and len(r2.data) >= 2:
                        row0 = r2.data[0] if isinstance(r2.data, list) else r2.data.iloc[0].to_dict()
                        # 汇总第1行可能含'总市值'字段（thsdk单位：元）
                        total_cap = row0.get('总市值')
                        if total_cap and float(total_cap) > 0:
                            total_cap = float(total_cap)
                            # thsdk总市值单位为元，转换为亿/万亿
                            total_cap_yi = total_cap / 1e8  # 元 → 亿
                            if total_cap_yi >= 10000:
                                result['market_cap'] = f'{total_cap_yi/10000:.2f}万亿'
                            elif total_cap_yi >= 1:
                                result['market_cap'] = f'{total_cap_yi:.2f}亿'
                            else:
                                result['market_cap'] = f'{total_cap*1e4:.2f}万'
                except Exception as _sexc:
                    record(__name__, 'quote', _sexc, note='静默降级')
                    pass

            _save_cache(cache_key, result)
            return result

        # 降级到腾讯行情
        return self._fallback_price(code, market)

    def _parse_quote(self, r, code: str) -> dict:
        """解析默认行情数据（使用位置索引，字段顺序已通过实测验证）

        字段顺序（13个字段）：
          idx0=现价,  idx1=外盘,  idx2=成交量(手),
          idx3=外盘,  idx4=内盘,  idx5=成交额,
          idx6=今开,  idx7=股票代码, idx8=名称,
          idx9=昨收, idx10=今开(重复), idx11=最高, idx12=最低

        注意：字段名称因控制台编码会显示为乱码，以位置为准。
        """
        if not r.success or r.df is None or r.df.empty:
            return {'stock_code': code, 'status': 'no_data'}

        df = r.df
        vals = list(df.iloc[0].values)

        def safe_float(v, default=None):
            if v is None: return default
            try:
                f = float(v)
                if str(v) in ('nan', 'NaN', '') or (f != f):  # NaN check
                    return default
                return f
            except (TypeError, ValueError):
                return default

        def cap_str(v):
            try:
                val = float(v)
                if val >= 1e4: return f'{val/1e4:.2f}万亿'
                elif val >= 1: return f'{val:.2f}亿'
                else: return f'{val*1e4:.2f}万'
            except:
                return None

        # 位置索引（13字段顺序已实测确认）
        # idx0=价格, idx2=成交量, idx4=总金额, idx9=昨收价,
        # idx10=开盘价, idx11=最高价, idx12=最低价
        price     = safe_float(vals[0]) if len(vals) > 0 else None
        vol_hands = safe_float(vals[2]) if len(vals) > 2 else None  # 成交量(手)
        amount    = safe_float(vals[4]) if len(vals) > 4 else None  # 总金额(成交额)
        prev      = safe_float(vals[9]) if len(vals) > 9 else None  # 昨收价
        open_     = safe_float(vals[10]) if len(vals) > 10 else None  # 开盘价
        high      = safe_float(vals[11]) if len(vals) > 11 else None  # 最高价
        low       = safe_float(vals[12]) if len(vals) > 12 else None  # 最低价
        ths_code  = str(vals[7]) if len(vals) > 7 else ''   # 股票代码
        name      = str(vals[8]) if len(vals) > 8 else ''   # 名称

        # 涨跌额/涨跌幅需要从扩展1获取，或从 汇总 query_key
        chg = None
        pct = None

        return {
            'stock_code': code,
            'name': name or None,
            'price': price,
            'chg': chg,
            'pct': pct,
            'open': open_,
            'prev_close': prev,
            'high': high,
            'low': low,
            'vol_hands': vol_hands,
            'amount': amount,       # 成交额（元）
            'pe': None,            # 基础数据不含PE
            'market_cap': None,    # 需从 汇总 query_key 获取
            'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'trading',
            'source': 'thsdk',
        }

    # ── 2. 分红历史 ─────────────────────────────────────────────────────────

    def dividend_history(self, code: str, market: str = 'a', years: int = 10) -> list[dict]:
        """分红历史（通过 corporate_action）"""
        cache_key = f'dividend_{code}'
        cached = _load_cache(cache_key, 86400)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.corporate_action, ths_code)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df.head(years))

        _save_cache(cache_key, records)
        return records

    # ── 3. K线数据 ─────────────────────────────────────────────────────────

    def klines(self, code: str, market: str = 'a', period: str = 'day',
               count: int = 60) -> list[dict]:
        """获取K线数据

        参数:
            code:  股票代码
            period: 'day' / 'week' / 'month' / 'quarter'（北交所仅支持day）
            count: 数量
        返回: [{时间, 开盘, 收盘, 最高, 最低, 成交量}, ...]
        """
        cache_key = f'kline_{code}_{period}_{count}'
        cached = _load_cache(cache_key, 3600)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.klines, ths_code, count=count, interval=period)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df)

        _save_cache(cache_key, records)
        return records

    # ── 4. 资金流向（扩展1）────────────────────────────────────────────────

    def fund_flow(self, code: str, market: str = 'a') -> dict:
        """资金流向数据（thsdk 扩展1）

        字段：涨跌幅, 换手率, 量比, 主力净流入, 成交额, 超大单净流入,
              市盈率TTM, 股票, 名称, 昨收, 净流入等
        """
        cache_key = f'fundflow_{code}'
        cached = _load_cache(cache_key, 1800)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.market_data_cn, ths_code, '扩展1')

        result = {}
        if r.success and r.df is not None and not r.df.empty:
            row = r.df.iloc[0]
            for k, v in row.items():
                s = str(v)
                if s not in ('nan', 'None', 'NaN', '') and v is not None:
                    try:
                        result[str(k)] = float(v)
                    except (TypeError, ValueError):
                        result[str(k)] = str(v)

        _save_cache(cache_key, result)
        return result

    # ── 5. 分时数据 ─────────────────────────────────────────────────────────

    def intraday(self, code: str, market: str = 'a') -> list[dict]:
        """获取1分钟分时数据"""
        cache_key = f'intraday_{code}'
        cached = _load_cache(cache_key, 300)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.intraday_data, ths_code)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df)

        _save_cache(cache_key, records)
        return records

    # ── 6. 五档盘口 ────────────────────────────────────────────────────────

    def depth(self, code: str, market: str = 'a') -> dict:
        """获取五档买卖盘"""
        cache_key = f'depth_{code}'
        cached = _load_cache(cache_key, 60)
        if cached:
            return cached

        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.depth, ths_code)

        result = {}
        if r.success and r.df is not None and not r.df.empty:
            result = _df_to_dict(r.df)

        _save_cache(cache_key, result)
        return result

    # ── 7. 集合竞价 ─────────────────────────────────────────────────────────

    def call_auction(self, code: str, market: str = 'a') -> list[dict]:
        """获取集合竞价数据"""
        ths_code = _to_ths_prefix(code, market)
        r = _call_thsdk(self.ths.call_auction, ths_code)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df)
        return records

    # ── 8. NLP选股（自然语言）───────────────────────────────────────────────

    def nlp_search(self, query: str, top_n: int = 20) -> list[dict]:
        """自然语言选股（wencai_nlp）"""
        cache_key = f'nlps_{hashlib.md5(query.encode()).hexdigest()}'
        cached = _load_cache(cache_key, 7200)
        if cached:
            return cached[:top_n]

        r = _call_thsdk(self.ths.wencai_nlp, query)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df)

        _save_cache(cache_key, records)
        return records[:top_n]

    # ── 9. 北交所全量股票 ───────────────────────────────────────────────────

    def bj_all_stocks(self) -> list[dict]:
        """全部北交所股票列表（314只）"""
        cache_key = 'bj_all_stocks'
        cached = _load_cache(cache_key, 86400)
        if cached:
            return cached

        r = _call_thsdk(self.ths.stock_bj_lists)

        records = []
        if r.success and r.df is not None and not r.df.empty:
            records = _df_to_dict(r.df)

        _save_cache(cache_key, records)
        return records

    # ── 10. 行业/概念板块 ──────────────────────────────────────────────────

    def industry_list(self) -> list[dict]:
        """申万行业列表（90个）"""
        cache_key = 'ths_industry'
        cached = _load_cache(cache_key, 86400)
        if cached:
            return cached
        r = _call_thsdk(self.ths.ths_industry)
        records = _df_to_dict(r.df) if r.success and r.df is not None else []
        _save_cache(cache_key, records)
        return records

    def concept_list(self) -> list[dict]:
        """概念板块列表（390个）"""
        cache_key = 'ths_concept'
        cached = _load_cache(cache_key, 86400)
        if cached:
            return cached
        r = _call_thsdk(self.ths.ths_concept)
        records = _df_to_dict(r.df) if r.success and r.df is not None else []
        _save_cache(cache_key, records)
        return records

    def block_members(self, link_code: str) -> list[dict]:
        """获取板块成分股"""
        r = _call_thsdk(self.ths.block_constituents, link_code)
        return _df_to_dict(r.df) if r.success and r.df is not None else []

    # ── 11. 7×24快讯 ───────────────────────────────────────────────────────

    def news(self, count: int = 20) -> list[dict]:
        """7×24快讯"""
        r = _call_thsdk(self.ths.news, count=count)
        return _df_to_dict(r.df) if r.success and r.df is not None else []

    # ── 12. 代码补全 ───────────────────────────────────────────────────────

    def complete_code(self, partial: str) -> list[str]:
        """代码补全"""
        r = _call_thsdk(self.ths.complete_ths_code, partial)
        codes = []
        if r.success and r.df is not None:
            for _, row in r.df.iterrows():
                for v in row.values:
                    s = str(v)
                    if s not in ('nan', 'None', 'NaN', '') and v is not None:
                        codes.append(str(v))
        return codes

    # ── 13. IPO排队 ────────────────────────────────────────────────────────

    def ipo_wait(self) -> list[dict]:
        """IPO排队企业"""
        cache_key = 'ipo_wait'
        cached = _load_cache(cache_key, 3600)
        if cached:
            return cached
        r = _call_thsdk(self.ths.ipo_wait)
        records = _df_to_dict(r.df) if r.success and r.df is not None else []
        _save_cache(cache_key, records)
        return records

    # ── 14. 批量行情 ───────────────────────────────────────────────────────

    def batch_quote(self, codes: list[str], market: str = 'a') -> list[dict]:
        """批量获取多只股票行情"""
        results = []
        for code in codes:
            try:
                results.append(self.quote(code, market))
            except Exception as e:
                results.append({'stock_code': code, 'status': 'error', 'message': str(e)[:50]})
        return results


# ── 全局单例 ────────────────────────────────────────────────────────────────
thsdkp = ThsdkProvider()