# -*- coding: utf-8 -*-
"""
test_regex_guards.py — 已知踩过的坑的回归测试（2026-10-20）

## 为什么需要

2026-10-20 一天内连踩 4 个"不报错的解析坑"：
  · ma_deep 正则无捕获组 → `match.group(1)` 抛 IndexError，被上层吞成
    "维度执行异常: no such group" → 整个维度作废（deals=0）
  · unlisted_company 同类问题 → 金额解析函数在特定输入下崩
  · 产品型号正则 `\\b` 在中文环境失效 → 漏抽 G32R430
  · 商誉表取「合计」行**第一个**数（期初 135.09 亿）而非**最后一个**（期末 6.22 亿）
    → 把"刚甩掉的包袱"当成"还背着的"，结论完全反了

这些坑的共同点：**不抛异常、不报警，只是安静地给出错数字**。
只靠"导入体检 + 跑批报错"是抓不到的（导入只查能否 import，跑批只查最终是否 success）。

## 用法

    python scripts/test_regex_guards.py          # 全部跑
    python scripts/test_regex_guards.py -v       # 详细

退出码 0 = 全过；非 0 = 有回归。
"""

from __future__ import annotations

import re
import sys
import unittest

sys.path.insert(0, 'scripts')
sys.path.insert(0, '.')


class TestCounterpartyRegex(unittest.TestCase):
    """ma_deep._extract_counterparty：曾因无捕获组抛 IndexError 导致整个维度作废"""

    def setUp(self):
        from scripts.ma_deep_analysis import MADeepAnalyzer
        self.a = MADeepAnalyzer(announcements={}, financials={},
                                annual_sections={}, financial_metrics={},
                                stock_code='000000', market='a')

    def test_all_patterns_have_capture_group(self):
        """核心：任何 pattern 匹配成功都必须有 group(1)，否则 IndexError"""
        cases = [
            '公司向珠海赛纳科技有限公司收购其持有的股权',
            '（纳思达股份有限公司）收购标的资产',
            '对手方：某某控股有限公司',
            '交易对方：珠海艾派克微电子有限公司',
            '本次交易不涉及对手方（无相关表述）',
        ]
        for c in cases:
            r = self.a._extract_counterparty(c)
            self.assertIsInstance(r, str, f'输入未返回字符串：{c[:20]}')
            self.assertTrue(len(r) > 0)
            self.assertNotEqual(r, 'None')

    def test_no_exception_on_pattern_without_group(self):
        """回归点：'（XXX）收购' 这个分支曾无捕获组 → 必须不崩且能抽到 XXX"""
        r = self.a._extract_counterparty('（珠海赛纳科技有限公司）收购利盟国际100%股权')
        self.assertIn('珠海赛纳', r, f'应抽到括号内主体，实际={r}')

    def test_fallback_when_no_match(self):
        """无匹配时返回兜底值，不得抛异常"""
        self.assertEqual(self.a._extract_counterparty('完全无关的一段文字'), '未知对手方')


class TestAmountParse(unittest.TestCase):
    """unlisted_company._parse_amount：曾因 ^[\\d.]+$ 无捕获组而崩"""

    def _fn(self):
        from scripts.unlisted_company import _parse_amount
        return _parse_amount

    def test_plain_number_no_crash(self):
        """回归点：纯数字串（无万/亿单位）曾在 group(1) 处崩"""
        f = self._fn()
        for s in ('120000000', '5000', '3.5'):
            v = f(s)
            self.assertIsInstance(v, (int, float), f'{s} 未返回数值，实际={v}')

    def test_units(self):
        f = self._fn()
        self.assertAlmostEqual(f('1.2亿'), 1.2, places=4)
        self.assertAlmostEqual(f('500万'), 0.05, places=4)

    def test_empty(self):
        self.assertIsNone(self._fn()(''))
        self.assertIsNone(self._fn()(None))


class TestProductModelRegex(unittest.TestCase):
    """产品型号抽取：\\b 在中文环境失效（Python 的 \\w 含中文）"""

    OLD = r'\b([A-Z]{1,4}\d{2,4}[A-Z]?\d{0,3})\b'                    # 旧：会漏
    NEW = r'(?<![A-Za-z0-9])([A-Z]{1,4}\d{2,4}[A-Z]?\d{0,3})(?![A-Za-z0-9])'  # 新

    def test_chinese_adjacent(self):
        """回归点：中文紧邻型号时，旧正则会漏抽"""
        text = '机械、G32R501 实时控制DSP、G32R430编码器专用MCU'
        old = re.findall(self.OLD, text)
        new = re.findall(self.NEW, text)
        self.assertIn('G32R501', new)
        self.assertIn('G32R430', new, f'中文相邻必须能抽到；旧={old} 新={new}')
        self.assertLess(len(old), len(new), '本用例应能暴露旧正则的缺陷')

    def test_not_match_inside_words(self):
        """不应把长标识符的片段当型号"""
        text = 'ABC123456789'
        self.assertEqual(re.findall(self.NEW, text), [])


class TestGoodwillColumn(unittest.TestCase):
    """商誉表：必须取「合计」行**期末余额**（末列），不是期初"""

    def test_takes_ending_balance(self):
        """回归点：002180 商誉表 期初135.09亿 | 处置128.87亿 | 期末6.22亿"""
        gw_text = ('被投资单位名称 期初余额 本期增加 本期减少 期末余额 '
                   '合计 13,508,638,725.02 12,886,657,907.59 621,980,817.43')
        m_total = re.search(r'合计\s*([\d,\s\.]{20,80})', gw_text)
        self.assertIsNotNone(m_total, '应能定位合计行')
        cand = re.findall(r'\d[\d,]*\.\d{2}', m_total.group(1))
        self.assertGreaterEqual(len(cand), 2, '合计行应至少两列（期初/期末）')
        ending = float(cand[-1].replace(',', ''))
        beginning = float(cand[0].replace(',', ''))
        self.assertAlmostEqual(ending / 1e8, 6.22, places=2, msg='期末应为 6.22 亿')
        self.assertAlmostEqual(beginning / 1e8, 135.09, places=2, msg='期初应为 135.09 亿')
        self.assertNotAlmostEqual(ending, beginning, msg='期初期末必须不同，取错列即失败')

    def test_self_consistency(self):
        """自洽校验：期初 - 处置 = 期末（容差 1%）"""
        begin, disposed, end = 13_508_638_725.02, 12_886_657_907.59, 621_980_817.43
        self.assertAlmostEqual(begin - disposed, end, delta=end * 0.01,
                               msg='期初 - 处置 应≈ 期末，否则列语义判断错了')


class TestCumulativeVsActive(unittest.TestCase):
    """质押/诉讼：必须区分「历史累计」与「当前在册」"""

    def test_pledge_split(self):
        from scripts.qcc_dimensions import parse_pledge
        payload = {'股权质押信息': [
            {'质押人': ['A'], '状态': '质押中', '股份总数': '100万'},
            {'质押人': ['A'], '状态': '已解除质押', '股份总数': '200万'},
            {'质押人': ['A'], '状态': '质押中', '股份总数': '300万'},
        ]}
        r = parse_pledge(payload, 'stock')
        self.assertEqual(r['total_records'], 3, '总记录 = 累计')
        self.assertEqual(r['active_count'], 2, '在押 = 仅状态为质押中')
        self.assertEqual(r['released_count'], 1)
        self.assertNotEqual(r['total_records'], r['active_count'],
                            '累计与在册必须分开，否则会高估')


class TestDCFNoFabrication(unittest.TestCase):
    """DCF：取不到营收/净利率时必须标缺失，不得用 100 亿/10% 兜底"""

    def test_missing_data_refuses(self):
        from scripts.valuation import _build_dcf
        r = _build_dcf([], {'market_cap_亿': 100})
        self.assertTrue(r.get('data_missing'), '空 records 必须标 data_missing')
        self.assertIsNone(r.get('dcf_value_亿'), '不得给出估值')
        self.assertIsNone(r.get('revenue_base_亿'), '不得返回默认 100 亿')

    def test_real_data_used(self):
        from scripts.valuation import _build_dcf
        records = [{'TOTAL_OPERATE_INCOME': 4_564_209_769.02,
                    'PARENT_NETPROFIT': 87_290_160.07,
                    'REPORTDATE': '2026-06-30', 'YSTZ': -22.3}]
        r = _build_dcf(records, {'market_cap_亿': 218.4})
        self.assertFalse(r.get('data_missing'))
        self.assertAlmostEqual(r['revenue_base_亿'], 45.64, places=2)
        self.assertAlmostEqual(r['net_margin_pct'], 1.91, places=1)


if __name__ == '__main__':
    # 用 unittest 主程序跑，退出码非 0 表示有回归
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules['__main__'])
    result = unittest.TextTestRunner(verbosity=2 if '-v' in sys.argv else 1).run(suite)
    n = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print('\n' + '=' * 62)
    print(f'正则/解析回归测试：{n} 项 ｜ 通过 {n - bad} ｜ 失败 {bad}')
    print('=' * 62)
    sys.exit(0 if bad == 0 else 1)
