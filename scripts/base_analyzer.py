# -*- coding: utf-8 -*-
"""
统一基类 - 所有分析模块的标准化接口

每个模块实现时只需继承 BaseAnalyzer，实现 run() 方法即可。

接口规范：
  __init__(stock_code, market, findings, data_dir)
  run() -> dict

stock_code: str   - 股票代码（如 "301419"）
market: str       - 市场（"a"=A股，"hk"=港股，"us"=美股）
findings: dict    - 已有的分析结果（新模块可读取前辈数据，避免重复请求）
data_dir: str     - 数据输出目录
"""
import os, json
from datetime import datetime


class BaseAnalyzer:
    """所有分析模块的基类"""

    def __init__(self, stock_code, market='a', findings=None, data_dir=None):
        self.stock_code = stock_code
        self.market = market
        self.findings = findings or {}
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'output', f'{stock_code}_{datetime.now().strftime("%Y%m%d")}'
        )
        os.makedirs(self.data_dir, exist_ok=True)

        # 便捷访问 - 从前辈数据中快速读取
        self.quote = self.findings.get('quote', {})
        self.company_name = (self.quote.get('data') or {}).get('名称') or stock_code

        # 实时价格
        self.price = None
        if self.quote.get('success') and self.quote.get('data'):
            self.price = self.quote['data'].get('价格')

        # 流通市值
        self.mkt_cap = None
        if self.quote.get('data'):
            self.mkt_cap = self.quote['data'].get('流通市值') or self.quote['data'].get('总市值')

        # 年报PDF路径
        self.pdf_path = None
        ap = self.findings.get('annual_pdf', {})
        if isinstance(ap, dict):
            self.pdf_path = ap.get('pdf_path') or ap.get('pdf')
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            # 尝试从 data_dir 找
            for f in os.listdir(self.data_dir) if os.path.exists(self.data_dir) else []:
                if f.endswith('.pdf'):
                    self.pdf_path = os.path.join(self.data_dir, f)
                    break

        self._result = {}

    def run(self):
        """子类实现。返回分析结果字典。"""
        raise NotImplementedError

    def _save_result(self, key, data):
        """保存模块结果到 findings 并写入 data_dir/*.json"""
        self.findings[key] = data
        path = os.path.join(self.data_dir, f'{key}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return data

    def _to_yi(self, value):
        """自动检测单位，将数字转为亿元"""
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v > 1e12:       # 元 → 万亿
            return round(v / 1e12, 2)
        elif v > 1e8:      # 元 → 亿
            return round(v / 1e8, 2)
        elif v > 1e4:      # 万元 → 亿
            return round(v / 1e4, 2)
        else:
            return round(v, 2)  # 已是亿元

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.stock_code}>'