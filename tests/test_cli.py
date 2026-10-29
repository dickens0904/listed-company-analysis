# -*- coding: utf-8 -*-
"""
测试：CLI 工具函数（parse_args, dim_label, dim_summary）
"""
import unittest
from scripts.cli import parse_args, dim_label, dim_summary


class TestParseArgs(unittest.TestCase):

    def test_stock_basic(self):
        """基本的 --stock 参数解析"""
        args = parse_args(["--stock", "300501"])
        self.assertEqual(args.stock, "300501")
        self.assertEqual(args.market, "auto")
        self.assertFalse(args.full)
        self.assertEqual(args.dims, "all")

    def test_stock_with_full(self):
        """--stock + --full 组合"""
        args = parse_args(["--stock", "002180", "--full"])
        self.assertEqual(args.stock, "002180")
        self.assertTrue(args.full)

    def test_stock_with_market(self):
        """--stock + --market hk"""
        args = parse_args(["--stock", "00700", "--market", "hk"])
        self.assertEqual(args.stock, "00700")
        self.assertEqual(args.market, "hk")

    def test_stock_with_dims(self):
        """--stock + --dims 指定维度"""
        args = parse_args(["--stock", "300501", "--dims", "financial,announcements"])
        self.assertEqual(args.dims, "financial,announcements")

    def test_company_mode(self):
        """--company 模式（未上市公司）"""
        args = parse_args(["--company", "某科技公司"])
        self.assertEqual(args.company, "某科技公司")
        self.assertIsNone(args.stock)

    def test_name_mode(self):
        """--name 模式（中文公司名）"""
        args = parse_args(["--name", "贵州茅台"])
        self.assertEqual(args.name, "贵州茅台")

    def test_no_stock_or_company_raises(self):
        """不指定 --stock / --name / --company 应报错"""
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_stock_and_name_mutually_exclusive(self):
        """--stock 和 --name 不能同时使用"""
        with self.assertRaises(SystemExit):
            parse_args(["--stock", "300501", "--name", "海顺新材"])

    def test_no_pdf_flag(self):
        """--no-pdf 标志"""
        args = parse_args(["--stock", "300501", "--no-pdf"])
        self.assertTrue(args.no_pdf)

    def test_report_years_default(self):
        """--report-years 默认值应为 1"""
        args = parse_args(["--stock", "300501"])
        self.assertEqual(args.report_years, 1)


class TestDimLabel(unittest.TestCase):

    def test_known_dimensions(self):
        """所有已知维度应返回中文标签"""
        known = {
            'announcements': '公告全景',
            'financial': '财务报表',
            'risk': '综合风险',
            'quote': '实时行情',
            'valuation': '估值分析',
        }
        for dim, expected in known.items():
            self.assertEqual(dim_label(dim), expected, f"dim={dim}")

    def test_unknown_dimension_returns_self(self):
        """未知维度应返回原值"""
        self.assertEqual(dim_label("nonexistent"), "nonexistent")


class TestDimSummary(unittest.TestCase):

    def test_announcements_summary(self):
        """公告维度摘要应包含公告数和重要性统计"""
        result = {
            'count': 42,
            'importance_stats': {'critical': 5, 'major': 10, 'routine': 27},
            'event_chains': {'ev1': {}, 'ev2': {}},
        }
        summary = dim_summary('announcements', result)
        self.assertIn('42', summary)
        self.assertIn('CRITICAL:5', summary)

    def test_financial_summary(self):
        """财务维度摘要应包含审计意见"""
        result = {'audit_opinion': '标准无保留意见'}
        summary = dim_summary('financial', result)
        self.assertIn('标准无保留意见', summary)

    def test_risk_summary(self):
        """风险维度摘要应包含等级和得分"""
        result = {'level': '🟡 中风险', 'score': 57}
        summary = dim_summary('risk', result)
        self.assertIn('中风险', summary)
        self.assertIn('57', summary)

    def test_list_batch_quote(self):
        """批量行情模式摘要"""
        result = [{'status': 'trading'}, {'status': 'closed'}, {'status': 'trading'}]
        summary = dim_summary('quote', result)
        self.assertIn('3只', summary)
        self.assertIn('2只交易中', summary)

    def test_unknown_dimension_returns_empty(self):
        """未知维度应返回空字符串"""
        self.assertEqual(dim_summary('nonexistent', {}), '')

    def test_annual_pdf_error(self):
        """年报PDF获取失败时的摘要"""
        result = {'error': '下载失败'}
        summary = dim_summary('annual_pdf', result)
        self.assertIn('获取失败', summary)

    def test_annual_pdf_success(self):
        """年报PDF成功时的摘要"""
        result = {'year': 2025, 'page_count': 186}
        summary = dim_summary('annual_pdf', result)
        self.assertIn('2025', summary)
        self.assertIn('186', summary)


if __name__ == "__main__":
    unittest.main()
