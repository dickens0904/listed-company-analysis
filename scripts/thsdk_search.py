try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result
# -*- coding: utf-8 -*-
"""
thsdk_search.py — THSDK（同花顺Python SDK）轻量封装 v2

功能：
    1. 自然语言选股（wencai_nlp）
    2. 证券模糊搜索（search_symbols）
    3. A股实时行情（market_data_cn 汇总，30+字段）
    4. 港股实时行情（market_data_hk 基础数据+财务指标）
    5. 美股实时行情（market_data_us 基础数据+财务指标）
    6. K线数据（日/周/月/1分/5分/15分/30分/60分）
    7. 板块数据（行业/概念板块列表 + 成分股）
    8. 权息资料（分红送转历史）
    9. DDE大单流向（逐笔成交+买卖方向）
    10. 五档盘口（depth）
    11. 分时数据（intraday_data）
    12. 集合竞价（个股竞价数据）
    13. 竞价异动（涨停试盘/跌停试盘）
    14. IPO排队（待上市新股）
    15. 资讯快讯（7x24新闻）

用法（CLI）：
    python thsdk_search.py nlp "人工智能概念股"
    python thsdk_search.py search "腾讯"
    python thsdk_search.py quote 300033
    python thsdk_search.py quote_hk 00700
    python thsdk_search.py quote_us AAPL
    python thsdk_search.py kline 300033 --interval day --count 10
    python thsdk_search.py block --type industry
    python thsdk_search.py block --type concept --name AI
    python thsdk_search.py constituents 885779
    python thsdk_search.py dividend 600519
    python thsdk_search.py dde 300033 --max 50
    python thsdk_search.py depth 300033
    python thsdk_search.py intraday 300033
    python thsdk_search.py call_auction 300033
    python thsdk_search.py auction USZA
    python thsdk_search.py ipo
    python thsdk_search.py news

用法（模块导入）：
    from thsdk_search import ThsdkSearch
    ts = ThsdkSearch()
    r = ts.quote("300033")       # A股30+字段
    r = ts.quote_hk("00700")     # 港股实时行情
    r = ts.quote_us("AAPL")      # 美股实时行情
    r = ts.dde("300033")         # DDE大单
    ts.close()

THS代码规则：
    沪A: USHA + 6位代码 (如 USHA600519)
    深A: USZA + 6位代码 (如 USZA300033)
    北交: USZA + 6位代码 (如 USZA920262)
    港股: UHKMHK + 4位代码 (如 UHKMHK0700 = 腾讯, UHKMHK9988 = 阿里)
          注意：港股代码为4位数字，不是5位！00700→0700, 09988→9988
    行业: URFI + 6位代码 (如 URFI881165)
    概念: URFI + 6位代码 (如 URFI885779)

依赖：pip install --upgrade thsdk
"""
import sys
import json
import re
import time
import logging
import argparse
from typing import Optional, Dict, List, Any
from datetime import datetime

# ─── 常量 ───────────────────────────────────────────────

# A股代码 → THS代码 前缀映射
A_SHARE_PREFIX = {
    '60': 'USHA',   # 沪市主板
    '68': 'USHA',   # 科创板
    '00': 'USZA',   # 深市主板
    '30': 'USZA',   # 创业板
    '92': 'USZA',   # 北交所
}

# THS代码前缀 → 市场标签
MARKET_LABEL = {
    'USHA': '沪A',
    'USZA': '深A',
    'UHKM': '港股',
    'USHK': '港股',
    'URFI': '同花顺板块',
    'USHI': '沪指',
    'USZJ': '深基',
    'USHD': '沪债',
}

# K线周期映射
KLINE_INTERVALS = {
    '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '60m': '60m',
    'day': 'day', 'week': 'week', 'month': 'month',
}

logger = logging.getLogger(__name__)


# ─── 工具函数 ───────────────────────────────────────────

def code_to_ths(code: str) -> str:
    """A股/港股代码 → THS代码
    
    A股：6位代码 → USHA/USZA + 6位（如 600519 → USHA600519）
    港股：4~5位代码 → UHKMHK + 4位（如 00700 → UHKMHK0700, 9988 → UHKMHK9988）
    
    注意：港股THS代码格式是4位数字，不是5位！
    - 00700 → UHKMHK0700（去掉前导零只保留4位）
    - 09988 → UHKMHK9988
    - 00005 → UHKMHK0005
    """
    code = code.strip().upper()
    # 已经是THS代码
    if code.startswith(('USHA', 'USZA', 'UHKM', 'URFI', 'USHI', 'USZJ', 'USHD')):
        return code
    # 纯数字6位 → A股
    if len(code) == 6 and code.isdigit():
        prefix = code[:2]
        ths_prefix = A_SHARE_PREFIX.get(prefix)
        if ths_prefix:
            return f'{ths_prefix}{code}'
    # 纯数字4~5位 → 港股（转为4位THS格式）
    if code.isdigit() and 4 <= len(code) <= 5:
        # 港股代码：去掉前导零后补齐4位
        num = int(code)  # 去掉前导零
        return f'UHKMHK{num:04d}'
    return code


def ths_to_code(ths_code: str) -> tuple:
    """THS代码 → (纯数字代码, 市场标签)"""
    for prefix in ['USHA', 'USZA', 'USHI', 'URFI', 'USZJ', 'USHD']:
        if ths_code.startswith(prefix):
            return ths_code[len(prefix):], MARKET_LABEL.get(prefix, prefix)
    if ths_code.startswith('UHKMHK'):
        # UHKMHK0700 → 0700
        raw = ths_code[6:]
        return raw, '港股'
    if ths_code.startswith('UHKMK'):
        return ths_code[5:], '港股R'
    if ths_code.startswith('UHKW'):
        return ths_code[4:], '港股窝轮'
    return ths_code, ''


def df_to_records(df, max_rows: int = 100) -> List[Dict]:
    """DataFrame → 记录列表，自动处理NaN/无效值，时间戳转ISO格式"""
    import pandas as pd
    import numpy as np
    if df is None or df.empty:
        return []
    df = df.head(max_rows)
    
    for col in df.columns:
        # 时间戳列转ISO格式
        if '时间' in col:
            try:
                df[col] = pd.to_datetime(df[col], unit='s', errors='coerce')
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
            except Exception:
                try:
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                    df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                except Exception as _sexc:
                    record(__name__, 'df_to_records', _sexc, note='静默降级')
                    pass
    
    # 替换NaN和uint32最大值(4294967295 = 游客无权限标记)
    df = df.replace([4294967295, 4294967295.0], None)
    df = df.where(pd.notnull(df), None)
    
    # 转为记录，处理特殊类型
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col in df.columns:
            val = row[col]
            if isinstance(val, (np.integer,)):
                val = int(val)
            elif isinstance(val, (np.floating,)):
                if np.isnan(val):
                    val = None
                else:
                    val = float(val)
            elif isinstance(val, (np.bool_,)):
                val = bool(val)
            elif isinstance(val, pd.Timestamp):
                val = val.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(val, (int, float, np.integer, np.floating)):
                try:
                    if pd.isna(val):
                        val = None
                except (ValueError, TypeError):
                    pass
            elif val is None or (isinstance(val, float) and val != val):
                val = None
            rec[col] = val
        records.append(rec)
    return records


# ─── 核心封装 ───────────────────────────────────────────

class ThsdkSearch:
    """THSDK轻量封装，支持上下文管理器"""

    def __init__(self, ops: Optional[Dict] = None):
        self.ops = ops or {}
        self._ths = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def connect(self):
        from thsdk import THS
        self._ths = THS(self.ops)
        r = self._ths.connect(max_retries=3)
        if not r.success:
            raise ConnectionError(f'THSDK连接失败: {r.error}')
        return r

    def close(self):
        if self._ths:
            self._ths.disconnect()
            self._ths = None

    def _ensure_connected(self):
        if not self._ths:
            self.connect()

    # ── 1. 自然语言选股 ──

    def nlp(self, query: str, max_rows: int = 50) -> Dict:
        """
        自然语言选股（问财）
        
        示例：
            "人工智能概念股"
            "PE<20且市值>100亿的半导体股"
            "最近一年涨幅前10"
            "连续3天涨停"
        """
        self._ensure_connected()
        r = self._ths.wencai_nlp(query)
        if not r.success:
            return {'success': False, 'error': r.error, 'query': query}

        df = r.df
        # 精简输出：只保留核心字段
        core_cols = ['股票代码', '股票简称', '所属概念', '最新价', '最新涨跌幅']
        keep_cols = [c for c in core_cols if c in df.columns]
        if keep_cols:
            result_df = df[keep_cols].head(max_rows)
        else:
            result_df = df.head(max_rows)

        return {
            'success': True,
            'query': query,
            'total': len(df),
            'returned': len(result_df),
            'data': df_to_records(result_df),
        }

    # ── 2. 证券搜索 ──

    def search(self, keyword: str) -> Dict:
        """
        证券模糊搜索（支持A股/港股/指数/板块/窝轮）
        """
        self._ensure_connected()
        r = self._ths.search_symbols(keyword)
        if not r.success:
            return {'success': False, 'error': r.error, 'keyword': keyword}

        df = r.df
        if 'MarketStr' in df.columns:
            main_df = df[~df['MarketStr'].isin(['UHKW'])].head(20)
        else:
            main_df = df.head(20)

        records = df_to_records(main_df)
        for rec in records:
            market = rec.get('MarketStr', '')
            rec['market_label'] = MARKET_LABEL.get(market, market)

        return {
            'success': True,
            'keyword': keyword,
            'total': len(df),
            'data': records,
        }

    # ── 3. A股实时行情（汇总，30+字段） ──

    def quote(self, code: str) -> Dict:
        """
        A股实时行情（汇总模式，30+字段）
        
        包含：价格/涨跌幅/市盈率TTM/换手率/量比/委比/主力净流入/
              流通市值/总市值/涨停价/跌停价/振幅/5日涨幅等
        
        参数：6位代码（如 300033）或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        
        # 先尝试汇总（最丰富），失败则回退基础数据
        r = self._ths.market_data_cn(ths_code, '汇总')
        if not r.success:
            # 回退到基础数据
            r = self._ths.market_data_cn(ths_code, '基础数据')
            if not r.success:
                return {'success': False, 'error': r.error, 'code': code}
        
        # 合并两行数据（汇总返回2行，取第一行）
        if len(r.df) > 1:
            # 第二行可能有额外字段，合并
            row1 = r.df.iloc[0]
            row2 = r.df.iloc[1]
            merged = row1.combine_first(row2)
            records = [merged.to_dict()]
        else:
            records = df_to_records(r.df)
        
        # 计算涨跌幅（如果没有的话）
        rec = records[0] if records else {}
        price = rec.get('价格', 0)
        prev = rec.get('昨收价', 0)
        if prev and price and not rec.get('涨幅'):
            try:
                rec['涨跌幅'] = round((float(price) - float(prev)) / float(prev) * 100, 2)
            except (ValueError, ZeroDivisionError):
                rec['涨跌幅'] = None

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'data': rec,
        }

    # ── 4. 港股实时行情 ──

    def quote_hk(self, code: str) -> Dict:
        """
        港股实时行情（基础数据+财务指标）
        
        包含：价格/涨跌幅/市盈率TTM/市净率/总市值
        
        参数：4~5位港股代码（如 00700, 9988）或完整THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        
        # 基础数据
        r1 = self._ths.market_data_hk(ths_code, '基础数据')
        if not r1.success:
            return {'success': False, 'error': r1.error, 'code': code}
        
        # 财务指标
        time.sleep(0.05)
        r2 = self._ths.market_data_hk(ths_code, '财务指标')
        
        # 合并
        base = df_to_records(r1.df)[0] if r1.success and len(r1.df) > 0 else {}
        fin = df_to_records(r2.df)[0] if r2.success and len(r2.df) > 0 else {}
        
        # 去重（代码字段可能重复）
        fin_clean = {k: v for k, v in fin.items() if k not in base or k == '代码'}
        merged = {**base, **fin_clean}
        
        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'data': merged,
        }

    # ── 5. 美股实时行情 ──

    def quote_us(self, symbol: str) -> Dict:
        """
        美股实时行情（基础数据+财务指标）
        
        包含：价格/涨跌幅/市盈率TTM/市净率/总市值/52周高低点
        
        参数：美股代码（如 AAPL, TSLA, NVDA, MSFT, JPM）
        
        注意：
            - 纳斯达克: UNQQ + symbol (如 UNQQAAPL)
            - 纽交所:  UNYN + symbol (如 UNYNJPM)
            - K线/盘口/资金流不可用（THS代码格式不兼容）
            - 买1/卖1价量在游客模式下无效（返回int32最大值）
        """
        self._ensure_connected()
        # 先搜索获取正确的THS代码
        r_search = self._ths.search_symbols(symbol)
        if not r_search.success or r_search.df.empty:
            return {'success': False, 'error': f'未找到美股: {symbol}', 'symbol': symbol}
        
        # 找到第一个美股结果
        us_stock = None
        for _, row in r_search.df.iterrows():
            market = str(row.get('MarketStr', ''))
            if market in ('UNQQ', 'UNYN', 'UNQA', 'UNYS'):
                us_stock = row
                break
        if us_stock is None:
            us_stock = r_search.df.iloc[0]
        
        ths_code = str(us_stock.get('THSCODE', us_stock.get('Code', '')))
        name = str(us_stock.get('Name', ''))
        
        # 基础数据
        r1 = self._ths.market_data_us(ths_code, '基础数据')
        if not r1.success:
            return {'success': False, 'error': r1.error, 'symbol': symbol}
        
        # 财务指标
        time.sleep(0.05)
        r2 = self._ths.market_data_us(ths_code, '财务指标')
        
        # 合并
        base = df_to_records(r1.df)[0] if r1.success and len(r1.df) > 0 else {}
        fin = df_to_records(r2.df)[0] if r2.success and len(r2.df) > 0 else {}
        
        # 过滤无效值（int32最大值=游客无权限）
        for d in [base, fin]:
            for k, v in list(d.items()):
                if isinstance(v, (int, float)) and v >= 2147483647:
                    d[k] = None
        
        fin_clean = {k: v for k, v in fin.items() if k not in base or k in ('代码', '总市值')}
        merged = {**base, **fin_clean}
        
        # 补充symbol信息
        merged['symbol'] = symbol
        merged['名称'] = name
        
        return {
            'success': True,
            'symbol': symbol,
            'ths_code': ths_code,
            'data': merged,
        }

    # ── 6. K线数据 ──

    def kline(self, code: str, interval: str = 'day', count: int = 30,
              adjust: str = '') -> Dict:
        """
        K线数据（支持分钟级）
        
        参数：
            code: 6位代码或THS代码
            interval: 1m/5m/15m/30m/60m/day/week/month
            count: 返回条数
            adjust: ''不复权 / 'qfq'前复权 / 'hfq'后复权
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.klines(ths_code, interval=interval, count=count, adjust=adjust)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'interval': interval,
            'count': len(r.df),
            'data': df_to_records(r.df),
        }

    # ── 7. 板块数据 ──

    def industry_list(self) -> Dict:
        """同花顺行业板块列表"""
        self._ensure_connected()
        r = self._ths.ths_industry()
        if not r.success:
            return {'success': False, 'error': r.error}

        return {
            'success': True,
            'total': len(r.df),
            'data': df_to_records(r.df),
        }

    def concept_list(self, keyword: Optional[str] = None) -> Dict:
        """
        同花顺概念板块列表
        
        参数：keyword 过滤关键词（如 "AI"、"华为"、"新能源"）
        """
        self._ensure_connected()
        r = self._ths.ths_concept()
        if not r.success:
            return {'success': False, 'error': r.error}

        df = r.df
        if keyword:
            mask = df['名称'].str.contains(keyword, case=False, na=False)
            df = df[mask]

        return {
            'success': True,
            'keyword': keyword,
            'total': len(df),
            'data': df_to_records(df),
        }

    def block_constituents(self, block_code: str) -> Dict:
        """
        板块成分股
        
        参数：板块代码（如 885779 = 腾讯概念）或完整URFI代码
        """
        self._ensure_connected()
        if not block_code.startswith('URFI'):
            block_code = f'URFI{block_code}'
        r = self._ths.block_constituents(block_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'block_code': block_code}

        return {
            'success': True,
            'block_code': block_code,
            'total': len(r.df),
            'data': df_to_records(r.df, max_rows=200),
        }

    # ── 8. 权息资料 ──

    def dividend(self, code: str, max_rows: int = 20) -> Dict:
        """
        分红送转历史
        
        参数：6位代码或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.corporate_action(ths_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        df = r.df.head(max_rows)
        records = []
        for _, row in df.iterrows():
            info = str(row.get('权息资料', ''))
            m = re.match(r'(\d{4}-\d{2}-\d{2})', info)
            date = m.group(1) if m else str(row.get('时间', ''))
            content = re.sub(r'^\d{4}-\d{2}-\d{2}\(', '', info).rstrip('$)')
            records.append({'日期': date, '内容': content})

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'total': len(r.df),
            'data': records,
        }

    # ── 9. DDE大单流向 ──

    def dde(self, code: str, max_rows: int = 100) -> Dict:
        """
        DDE大单流向（逐笔成交数据）
        
        包含：时间/成交方向/成交量/总金额/委托买入价/委托卖出价
        成交方向：2=买入, 1=卖出
        
        参数：6位代码或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.big_order_flow(ths_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        df = r.df.head(max_rows)
        # 成交方向映射
        dir_map = {2: '买入', 1: '卖出', 0: '中性'}
        if '成交方向' in df.columns:
            df['成交方向'] = df['成交方向'].map(lambda x: dir_map.get(x, x))

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'total': len(r.df),
            'returned': len(df),
            'data': df_to_records(df),
        }

    # ── 10. 五档盘口 ──

    def depth(self, code: str) -> Dict:
        """
        五档盘口数据
        
        包含：买1~5价/量 + 卖1~5价/量 + 昨收价
        
        参数：6位代码或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.depth(ths_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        rec = df_to_records(r.df)[0] if len(r.df) > 0 else {}
        
        # 整理为买卖盘结构
        bids = []
        asks = []
        for i in range(1, 6):
            bp = rec.get(f'买{i}价')
            bv = rec.get(f'买{i}量')
            sp = rec.get(f'卖{i}价')
            sv = rec.get(f'卖{i}量')
            if bp is not None:
                bids.append({'level': i, 'price': bp, 'volume': bv})
            if sp is not None:
                asks.append({'level': i, 'price': sp, 'volume': sv})

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'last_close': rec.get('昨收价'),
            'bids': bids,
            'asks': asks,
        }

    # ── 11. 分时数据 ──

    def intraday(self, code: str, max_rows: int = 241) -> Dict:
        """
        分时数据（当日分钟级走势）
        
        包含：时间/价格/成交量/总金额/领先指标
        
        参数：6位代码或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.intraday_data(ths_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'total': len(r.df),
            'data': df_to_records(r.df, max_rows=max_rows),
        }

    # ── 12. 集合竞价 ──

    def call_auction(self, code: str) -> Dict:
        """
        个股集合竞价数据
        
        包含：时间/价格/买2量/卖2量/当前量
        
        参数：6位代码或THS代码
        """
        self._ensure_connected()
        ths_code = code_to_ths(code)
        r = self._ths.call_auction(ths_code)
        if not r.success:
            return {'success': False, 'error': r.error, 'code': code}

        return {
            'success': True,
            'code': code,
            'ths_code': ths_code,
            'total': len(r.df),
            'data': df_to_records(r.df),
        }

    # ── 13. 竞价异动 ──

    def auction(self, market: str = 'USZA') -> Dict:
        """
        竞价异动（涨停试盘/跌停试盘）
        
        参数：market = USHA(沪A) / USZA(深A)
        """
        self._ensure_connected()
        r = self._ths.call_auction_anomaly(market)
        if not r.success:
            return {'success': False, 'error': r.error, 'market': market}

        return {
            'success': True,
            'market': market,
            'total': len(r.df),
            'data': df_to_records(r.df, max_rows=50),
        }

    # ── 14. IPO排队 ──

    def ipo(self) -> Dict:
        """IPO排队列表（待上市新股）"""
        self._ensure_connected()
        r = self._ths.ipo_wait()
        if not r.success:
            return {'success': False, 'error': r.error}

        return {
            'success': True,
            'total': len(r.df),
            'data': df_to_records(r.df, max_rows=50),
        }

    # ── 15. 资讯快讯 ──

    def news(self, max_rows: int = 20) -> Dict:
        """7x24资讯快讯"""
        self._ensure_connected()
        r = self._ths.news()
        if not r.success:
            return {'success': False, 'error': r.error}

        df = r.df
        records = []
        for _, row in df.head(max_rows).iterrows():
            props = row.get('Properties', '')
            summary = ''
            source = ''
            if isinstance(props, str):
                for line in props.split('\n'):
                    if line.startswith('summ='):
                        summary = line[5:]
                    elif line.startswith('source='):
                        source = line[7:]
            records.append({
                'time': row.get('Time', ''),
                'title': row.get('Title', ''),
                'summary': summary,
                'source': source,
            })

        return {
            'success': True,
            'total': len(df),
            'data': records,
        }


# ─── CLI 入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='THSDK 证券数据搜索工具 v2')
    sub = parser.add_subparsers(dest='command')

    # nlp
    p = sub.add_parser('nlp', help='自然语言选股')
    p.add_argument('query', help='自然语言查询')
    p.add_argument('--max', type=int, default=20, help='最大返回条数')

    # search
    p = sub.add_parser('search', help='证券模糊搜索')
    p.add_argument('keyword', help='搜索关键词')

    # quote (升级：30+字段)
    p = sub.add_parser('quote', help='A股实时行情（30+字段）')
    p.add_argument('code', help='6位代码（如 300033）')

    # quote_hk
    p = sub.add_parser('quote_hk', help='港股实时行情')
    p.add_argument('code', help='港股代码（如 00700, 9988）')

    # quote_us (新增)
    p = sub.add_parser('quote_us', help='美股实时行情')
    p.add_argument('symbol', help='美股代码（如 AAPL, TSLA, NVDA）')

    # kline (升级：支持分钟级)
    p = sub.add_parser('kline', help='K线数据')
    p.add_argument('code', help='6位代码')
    p.add_argument('--interval', default='day',
                   choices=['1m', '5m', '15m', '30m', '60m', 'day', 'week', 'month'])
    p.add_argument('--count', type=int, default=30)
    p.add_argument('--adjust', default='', choices=['', 'qfq', 'hfq'])

    # block
    p = sub.add_parser('block', help='板块列表')
    p.add_argument('--type', default='concept', choices=['industry', 'concept'])
    p.add_argument('--name', default=None, help='过滤关键词')

    # constituents
    p = sub.add_parser('constituents', help='板块成分股')
    p.add_argument('block_code', help='板块代码（如 885779）')

    # dividend
    p = sub.add_parser('dividend', help='分红送转历史')
    p.add_argument('code', help='6位代码')

    # dde (新增)
    p = sub.add_parser('dde', help='DDE大单流向')
    p.add_argument('code', help='6位代码')
    p.add_argument('--max', type=int, default=50, help='最大返回条数')

    # depth (新增)
    p = sub.add_parser('depth', help='五档盘口')
    p.add_argument('code', help='6位代码')

    # intraday (新增)
    p = sub.add_parser('intraday', help='分时数据')
    p.add_argument('code', help='6位代码')

    # call_auction (新增)
    p = sub.add_parser('call_auction', help='个股集合竞价')
    p.add_argument('code', help='6位代码')

    # auction (竞价异动)
    p = sub.add_parser('auction', help='竞价异动')
    p.add_argument('--market', default='USZA', choices=['USHA', 'USZA'])

    # ipo (新增)
    p = sub.add_parser('ipo', help='IPO排队列表')

    # news
    p = sub.add_parser('news', help='7x24资讯快讯')
    p.add_argument('--max', type=int, default=20)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    logging.getLogger('thsdk').setLevel(logging.WARNING)

    with ThsdkSearch() as ts:
        cmd_map = {
            'nlp': lambda: ts.nlp(args.query, max_rows=args.max),
            'search': lambda: ts.search(args.keyword),
            'quote': lambda: ts.quote(args.code),
            'quote_hk': lambda: ts.quote_hk(args.code),
            'quote_us': lambda: ts.quote_us(args.symbol),
            'kline': lambda: ts.kline(args.code, interval=args.interval,
                                      count=args.count, adjust=args.adjust),
            'block': lambda: ts.industry_list() if args.type == 'industry'
                             else ts.concept_list(keyword=args.name),
            'constituents': lambda: ts.block_constituents(args.block_code),
            'dividend': lambda: ts.dividend(args.code),
            'dde': lambda: ts.dde(args.code, max_rows=args.max),
            'depth': lambda: ts.depth(args.code),
            'intraday': lambda: ts.intraday(args.code),
            'call_auction': lambda: ts.call_auction(args.code),
            'auction': lambda: ts.auction(market=args.market),
            'ipo': lambda: ts.ipo(),
            'news': lambda: ts.news(max_rows=args.max),
        }
        handler = cmd_map.get(args.command)
        result = handler() if handler else {'error': f'未知命令: {args.command}'}

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
