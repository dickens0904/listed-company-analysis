# -*- coding: utf-8 -*-
"""
测试：维度调度器（dispatcher.py）
"""
import unittest
from scripts.dispatcher import infer_source_from_dim


class TestInferSourceFromDim(unittest.TestCase):

    def test_announcements_returns_em_announce(self):
        """公告维度应推断为 em_announce"""
        self.assertEqual(infer_source_from_dim('announcements', {}), 'em_announce')

    def test_financial_returns_none_for_unknown(self):
        """financial 维度无已知映射时应返回 None"""
        self.assertIsNone(infer_source_from_dim('financial', {}))

    def test_risk_returns_composite(self):
        """风险维度应推断为 composite"""
        self.assertEqual(infer_source_from_dim('risk', {}), 'composite')

    def test_annual_pdf_returns_cninfo_pdf(self):
        """年报PDF维度应推断为 cninfo_pdf"""
        self.assertEqual(infer_source_from_dim('annual_pdf', {}), 'cninfo_pdf')

    def test_meta_source_takes_priority(self):
        """result 中的 _meta.source 应优先于推断"""
        result = {'_meta': {'source': 'akshare'}}
        self.assertEqual(infer_source_from_dim('announcements', result), 'akshare')

    def test_top_level_source_takes_priority(self):
        """result 中的顶层 source 应优先于推断"""
        result = {'source': 'tushare'}
        self.assertEqual(infer_source_from_dim('announcements', result), 'tushare')

    def test_meta_source_over_top_level(self):
        """_meta.source 应优先于顶层 source"""
        result = {'_meta': {'source': 'akshare'}, 'source': 'tushare'}
        self.assertEqual(infer_source_from_dim('announcements', result), 'akshare')

    def test_none_result_returns_none(self):
        """非 dict result 应走推断逻辑"""
        self.assertEqual(infer_source_from_dim('announcements', None), 'em_announce')

    def test_industry_returns_csrc_ak(self):
        """行业维度应推断为 csrc_ak"""
        self.assertEqual(infer_source_from_dim('industry', {}), 'csrc_ak')

    def test_governance_returns_cninfo_api(self):
        """治理维度应推断为 cninfo_api"""
        self.assertEqual(infer_source_from_dim('governance', {}), 'cninfo_api')

    def test_unknown_dim_returns_none(self):
        """完全未知的维度应返回 None"""
        self.assertIsNone(infer_source_from_dim('nonexistent_dim', {}))


if __name__ == "__main__":
    unittest.main()
