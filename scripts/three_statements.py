# -*- coding: utf-8 -*-
"""
three_statements.py - 三表(资产负债表、利润表、现金流量表)提取

用途:从年报PDF中提取完整的财务三表数据,
      生成投行标准的多年度横向对比表。

依赖:PyMuPDF (fitz)
用法:
    python three_statements.py --pdf report.pdf --output output/
"""

import os
import re
import sys
import json
try:
    import fitz
    _HAS_FITZ = True
except ImportError:
    fitz = None
    _HAS_FITZ = False

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class ThreeStatementsExtractor:
    """三表提取器(支持中文年报)"""

    # 关键财务科目(用于定位表格)
    BALANCE_SHEET_KEYWORDS = [
        '合并资产负债表', '资产负债表',
        '流动资产', '货币资金', '应收账款', '存货', '固定资产',
        '流动负债', '非流动负债', '所有者权益'
    ]

    INCOME_STATEMENT_KEYWORDS = [
        '合并利润表', '利润表',
        '营业收入', '营业成本', '营业利润', '利润总额', '净利润'
    ]

    CASH_FLOW_KEYWORDS = [
        '合并现金流量表', '现金流量表',
        '经营活动产生的现金流量', '投资活动产生的现金流量', '筹资活动产生的现金流量'
    ]

    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        if not _HAS_FITZ:
            self.doc = None
            self.total_pages = 0
            raise ImportError("PyMuPDF 未安装，三表提取不可用（pip install pymupdf）")
        self.doc = fitz.open(pdf_path)
        self.total_pages = len(self.doc)

    def find_statement_pages(self):
        """定位三表所在页码"""
        pages = {
            'balance_sheet': [],
            'income_statement': [],
            'cash_flow': []
        }

        for pn in range(self.total_pages):
            text = self.doc[pn].get_text('text')

            # 资产负债表
            if any(kw in text for kw in self.BALANCE_SHEET_KEYWORDS):
                # 排除母公司资产负债表(只要合并)
                if '合并资产负债表' in text or ('资产负债表' in text and '合并' not in text and '母公司' not in text):
                    pages['balance_sheet'].append(pn)

            # 利润表
            if any(kw in text for kw in self.INCOME_STATEMENT_KEYWORDS):
                if '合并利润表' in text or ('利润表' in text and '合并' not in text and '母公司' not in text):
                    pages['income_statement'].append(pn)

            # 现金流量表
            if any(kw in text for kw in self.CASH_FLOW_KEYWORDS):
                if '合并现金流量表' in text or ('现金流量表' in text and '合并' not in text and '母公司' not in text):
                    pages['cash_flow'].append(pn)

        return pages

    def extract_tables_from_pages(self, pages, max_rows=200):
        """从指定页提取所有表格"""
        all_rows = []
        for pn in pages:
            page = self.doc[pn]
            tables = page.find_tables()
            for tbl in tables:
                data = tbl.extract()
                if data and len(data) >= 2:
                    # 跳过表头重复
                    for row in data:
                        if row and any(cell and str(cell).strip() for cell in row):
                            all_rows.append(row)

        # 去重(同一科目可能跨页重复)
        seen = set()
        unique_rows = []
        for row in all_rows:
            key = str(row[0]) if row else ''
            if key and key not in seen:
                seen.add(key)
                unique_rows.append(row)

        return unique_rows[:max_rows]

    def parse_balance_sheet(self, rows):
        """解析资产负债表"""
        result = {
            'assets': {},
            'liabilities': {},
            'equity': {},
            'total_assets': None,
            'total_liabilities': None,
            'total_equity': None
        }

        current_section = 'assets'

        for row in rows:
            if not row or len(row) < 2:
                continue

            item = str(row[0]).strip() if row[0] else ''
            if not item or item in ['项目', '期末余额', '期初余额', '---']:
                continue

            # 解析数值
            val_current = self._parse_value(row[1]) if len(row) > 1 else None
            val_prev = self._parse_value(row[2]) if len(row) > 2 else None

            # 分区判断
            if '流动资产' in item:
                current_section = 'assets'
                continue
            elif '非流动资产' in item:
                current_section = 'assets'
                continue
            elif '资产总计' in item:
                result['total_assets'] = (val_current, val_prev)
                current_section = 'liabilities'
                continue
            elif '流动负债' in item:
                current_section = 'liabilities'
                continue
            elif '非流动负债' in item:
                current_section = 'liabilities'
                continue
            elif '负债合计' in item or '负债总计' in item:
                result['total_liabilities'] = (val_current, val_prev)
                current_section = 'equity'
                continue
            elif '所有者权益' in item or '股东权益' in item:
                current_section = 'equity'
                continue
            elif '权益合计' in item or '权益总计' in item:
                result['total_equity'] = (val_current, val_prev)
                continue

            # 存储科目
            if val_current is not None:
                key = item.replace(':', '').strip()
                if current_section == 'assets':
                    result['assets'][key] = (val_current, val_prev)
                elif current_section == 'liabilities':
                    result['liabilities'][key] = (val_current, val_prev)
                elif current_section == 'equity':
                    result['equity'][key] = (val_current, val_prev)

        return result

    def parse_income_statement(self, rows):
        """解析利润表"""
        result = {
            'revenue': None,
            'operating_cost': None,
            'gross_profit': None,
            'operating_profit': None,
            'profit_before_tax': None,
            'net_profit': None,
            'net_profit_attr_parent': None,
            'items': {}
        }

        for row in rows:
            if not row or len(row) < 2:
                continue

            item = str(row[0]).strip() if row[0] else ''
            if not item or item in ['项目', '本期金额', '上期金额', '---']:
                continue

            val_current = self._parse_value(row[1]) if len(row) > 1 else None
            val_prev = self._parse_value(row[2]) if len(row) > 2 else None

            # 关键科目提取
            if '营业收入' in item and '成本' not in item:
                result['revenue'] = (val_current, val_prev)
            elif '营业成本' in item:
                result['operating_cost'] = (val_current, val_prev)
            elif '毛利' in item and '率' not in item and '额' not in item:
                result['gross_profit'] = (val_current, val_prev)
            elif '营业利润' in item and '总额' not in item:
                result['operating_profit'] = (val_current, val_prev)
            elif '利润总额' in item:
                result['profit_before_tax'] = (val_current, val_prev)
            elif '净利润' in item and '母公司' not in item and '少数' not in item:
                if '归属于母公司' in item or '归属于母' in item:
                    result['net_profit_attr_parent'] = (val_current, val_prev)
                else:
                    result['net_profit'] = (val_current, val_prev)

            # 存储所有科目
            if val_current is not None:
                key = item.replace('：', '').strip()
                result['items'][key] = (val_current, val_prev)

        # 计算回退：gross_profit（API未直接返回时用 revenue - operating_cost）
        if result['gross_profit'] is None and result['revenue'] is not None and result['operating_cost'] is not None:
            rev_curr, rev_prev = result['revenue']
            cost_curr, cost_prev = result['operating_cost']
            curr = (rev_curr - cost_curr) if rev_curr is not None and cost_curr is not None else None
            prev = (rev_prev - cost_prev) if rev_prev is not None and cost_prev is not None else None
            if curr is not None or prev is not None:
                result['gross_profit'] = (curr, prev)

        return result

    def parse_cash_flow(self, rows):
        """解析现金流量表"""
        result = {
            'operating_cf': None,
            'investing_cf': None,
            'financing_cf': None,
            'net_cash_increase': None,
            'items': {}
        }

        for row in rows:
            if not row or len(row) < 2:
                continue

            item = str(row[0]).strip() if row[0] else ''
            if not item or item in ['项目', '本期金额', '上期金额', '---']:
                continue

            val_current = self._parse_value(row[1]) if len(row) > 1 else None
            val_prev = self._parse_value(row[2]) if len(row) > 2 else None

            # 关键科目提取
            if '经营活动产生的现金流量净额' in item:
                result['operating_cf'] = (val_current, val_prev)
            elif '投资活动产生的现金流量净额' in item:
                result['investing_cf'] = (val_current, val_prev)
            elif '筹资活动产生的现金流量净额' in item:
                result['financing_cf'] = (val_current, val_prev)
            elif '现金及现金等价物净增加额' in item:
                result['net_cash_increase'] = (val_current, val_prev)

            # 存储所有科目
            if val_current is not None:
                key = item.replace(':', '').strip()
                result['items'][key] = (val_current, val_prev)

        return result

    def _parse_value(self, val):
        """解析数值(支持中文格式)"""
        if val is None:
            return None
        s = str(val).strip().replace(',', '').replace(',', '')
        if not s or s == '-' or s == '0.00':
            return 0.0
        try:
            return float(s)
        except:
            return None

    def extract_all(self):
        """提取全部三表"""
        pages = self.find_statement_pages()

        result = {
            'balance_sheet': None,
            'income_statement': None,
            'cash_flow': None,
            'pages': {k: [p+1 for p in v] for k, v in pages.items()}
        }

        # 资产负债表
        if pages['balance_sheet']:
            rows = self.extract_tables_from_pages(pages['balance_sheet'])
            result['balance_sheet'] = self.parse_balance_sheet(rows)
            result['balance_sheet']['rows'] = rows[:50]  # 保留原始数据

        # 利润表
        if pages['income_statement']:
            rows = self.extract_tables_from_pages(pages['income_statement'])
            result['income_statement'] = self.parse_income_statement(rows)
            result['income_statement']['rows'] = rows[:50]

        # 现金流量表
        if pages['cash_flow']:
            rows = self.extract_tables_from_pages(pages['cash_flow'])
            result['cash_flow'] = self.parse_cash_flow(rows)
            result['cash_flow']['rows'] = rows[:50]

        return result

    def generate_comparison_table(self, data, years):
        """生成多年度对比表(Markdown格式)"""
        lines = []

        # 资产负债表关键科目
        if data.get('balance_sheet'):
            bs = data['balance_sheet']
            lines.append('## 资产负债表关键科目(单位:亿元)')
            lines.append(f'| 科目 | {years[0]} | {years[1]} | 变动 |')
            lines.append('|------|------|------|------|')

            # 关键科目
            key_items = [
                ('货币资金', 'assets', '货币资金'),
                ('应收账款', 'assets', '应收账款'),
                ('存货', 'assets', '存货'),
                ('固定资产', 'assets', '固定资产'),
                ('资产总计', 'total_assets', None),
            ]

            for name, section, key in key_items:
                if section == 'total_assets':
                    vals = bs.get('total_assets')
                else:
                    vals = bs.get(section, {}).get(key)

                if vals and vals[0] is not None:
                    v0 = vals[0] / 1e8 if vals[0] else 0
                    v1 = vals[1] / 1e8 if vals[1] else 0
                    change = '' if not v1 else f'{(v0-v1)/v1*100:.1f}%' if v1 != 0 else 'N/A'
                    lines.append(f'| {name} | {v0:.2f} | {v1:.2f} | {change} |')

            lines.append('')

        # 利润表关键科目
        if data.get('income_statement'):
            inc = data['income_statement']
            lines.append('## 利润表关键科目(单位:亿元)')
            lines.append(f'| 科目 | {years[0]} | {years[1]} | 同比 |')
            lines.append('|------|------|------|------|')

            items = [
                ('营业收入', 'revenue'),
                ('营业成本', 'operating_cost'),
                ('营业利润', 'operating_profit'),
                ('净利润', 'net_profit'),
                ('归母净利润', 'net_profit_attr_parent'),
            ]

            for name, key in items:
                vals = inc.get(key)
                if vals and vals[0] is not None:
                    v0 = vals[0] / 1e8 if vals[0] else 0
                    v1 = vals[1] / 1e8 if vals[1] else 0
                    change = '' if not v1 else f'{(v0-v1)/abs(v1)*100:.1f}%' if v1 != 0 else 'N/A'
                    lines.append(f'| {name} | {v0:.2f} | {v1:.2f} | {change} |')

            lines.append('')

        # 现金流量表
        if data.get('cash_flow'):
            cf = data['cash_flow']
            lines.append('## 现金流量表关键科目(单位:亿元)')
            lines.append(f'| 科目 | {years[0]} | {years[1]} | 变动 |')
            lines.append('|------|------|------|------|')

            items = [
                ('经营活动现金流', 'operating_cf'),
                ('投资活动现金流', 'investing_cf'),
                ('筹资活动现金流', 'financing_cf'),
            ]

            for name, key in items:
                vals = cf.get(key)
                if vals and vals[0] is not None:
                    v0 = vals[0] / 1e8 if vals[0] else 0
                    v1 = vals[1] / 1e8 if vals[1] else 0
                    lines.append(f'| {name} | {v0:.2f} | {v1:.2f} | - |')

            lines.append('')

        return '\n'.join(lines)

    def save_results(self, output_dir):
        """保存提取结果"""
        os.makedirs(output_dir, exist_ok=True)

        data = self.extract_all()

        # JSON格式
        json_path = os.path.join(output_dir, 'three_statements.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Markdown对比表
        md_path = os.path.join(output_dir, 'three_statements.md')
        table = self.generate_comparison_table(data, ['2025', '2024'])
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('# 财务三表提取结果\n\n')
            f.write(f'PDF页数: {self.total_pages}\n\n')
            f.write(f'三表所在页: {data["pages"]}\n\n')
            f.write(table)

        return json_path, md_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='三表提取')
    parser.add_argument('--pdf', required=True, help='PDF文件路径')
    parser.add_argument('--output', '-o', default='output', help='输出目录')

    args = parser.parse_args()

    extractor = ThreeStatementsExtractor(args.pdf)
    json_path, md_path = extractor.save_results(args.output)

    print(f'提取完成:')
    print(f'  JSON: {json_path}')
    print(f'  Markdown: {md_path}')
