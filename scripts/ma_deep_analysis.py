# -*- coding: utf-8 -*-
"""
ma_deep_analysis.py - 收并购深度分析模块

用途：在现有 related_deals.py 基础上，增加收并购深度分析：
  - 收购标的公司的基本面分析
  - 收购协同效应评估
  - 收购后业绩追踪
  - 商誉减值风险预警

数据来源：
  - 公告（announcements）：收购/出售/资产重组公告
  - 年报（annual_pdf）：商誉金额、减值准备、业绩承诺
  - 财务数据（financials）：收购后的财务表现

使用方式：
  from ma_deep_analysis import MADeepAnalyzer, fetch_ma_deep_analysis

  # 方式1：直接调用
  result = fetch_ma_deep_analysis('002180', 'a', data_dir)

  # 方式2：使用分析器
  analyzer = MADeepAnalyzer(announcements, financials, annual_sections)
  report = analyzer.analyze()
"""

import sys
import re
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class MADeepAnalyzer:
    """收并购深度分析器"""

    def __init__(self, announcements: dict = None, financials: dict = None,
                 annual_sections: dict = None, financial_metrics: dict = None,
                 stock_code: str = '', market: str = 'a'):
        """初始化分析器
        Args:
            announcements: 公告数据（来自 announcements.py）
            financials: 财务数据（来自 financials.py）
            annual_sections: 年报章节数据（来自 annual_extract.py）
            financial_metrics: 财务指标（来自 financial_metrics.json）
            stock_code: 股票代码
            market: 市场（a/hk/us）
        """
        self.announcements = announcements or {}
        self.financials = financials or {}
        self.annual_sections = annual_sections or {}
        self.financial_metrics = financial_metrics or {}
        self.stock_code = stock_code
        self.market = market
        self.deals = []
        self.goodwill_analysis = {}
        self.synergy_analysis = {}
        self.risk_analysis = {}
        self.ma_score = 0

    def analyze(self) -> dict:
        """执行完整收并购深度分析"""
        self.extract_deals()
        self.analyze_goodwill()
        self.analyze_synergy()
        self.analyze_risk()
        self.calculate_ma_score()
        return self.generate_ma_report()

    def extract_deals(self) -> List[dict]:
        """从公告中提取收并购相关事件"""
        deals = []

        critical_announcements = self.announcements.get('critical_announcements', [])
        if isinstance(critical_announcements, list):
            for ann in critical_announcements:
                title = ann.get('title', '')
                content = ann.get('extracted_content', {}).get('full_text_preview', '')

                # 识别收并购类型
                deal_type = self._identify_deal_type(title, content)

                if deal_type:
                    deal = {
                        'date': ann.get('date', ''),
                        'title': title,
                        'type': deal_type,
                        'content': content[:2000],
                        'ai_analysis': ann.get('ai_analysis', {}),
                        'importance': ann.get('importance', 'major')
                    }

                    # 提取金额
                    deal['amount'] = self._extract_amount(content)

                    # 提取交易对手
                    deal['counterparty'] = self._extract_counterparty(content)

                    # 提取标的资产
                    deal['target'] = self._extract_target(content)

                    deals.append(deal)

        # 从年报提取历史收购
        ma_history = self._extract_ma_from_annual()
        deals.extend(ma_history)

        self.deals = deals
        return deals

    def _identify_deal_type(self, title: str, content: str) -> Optional[str]:
        """识别收并购类型"""
        title_lower = title.lower()
        content_lower = content.lower()

        # 重大资产重组（最高优先级）
        if '重大资产重组' in title_lower or '重组' in title_lower:
            if '出售' in title_lower or '剥离' in title_lower:
                return '资产出售'
            return '重大资产重组'
        
        if any(keyword in title_lower for keyword in ['收购', '并购', '购买', '认购']):
            return '资产收购'
        elif any(keyword in title_lower for keyword in ['出售', '转让', '剥离']):
            return '资产出售'
        elif any(keyword in title_lower for keyword in ['增资', '扩股', '定增']):
            return '股权融资'
        elif any(keyword in title_lower for keyword in ['吸收合并', '换股合并']):
            return '企业合并'
        elif any(keyword in title_lower for keyword in ['私有化', '退市']):
            return '私有化'
        elif any(keyword in title_lower for keyword in ['分拆', '剥离']):
            return '资产分拆'
        elif any(keyword in title_lower for keyword in ['关联交易', '关联方']):
            if any(keyword in content_lower for keyword in ['收购', '购买', '出售']):
                return '关联交易'

        return None

    def _extract_amount(self, content: str) -> Optional[float]:
        """提取交易金额"""
        # 匹配美元金额
        usd_pattern = r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:亿美元|百万美元|USD|million USD)'
        usd_match = re.search(usd_pattern, content)
        if usd_match:
            amount = float(usd_match.group(1).replace(',', ''))
            if '百万' in content or 'million' in content.lower():
                amount *= 1000000
            elif '亿' in content:
                amount *= 100000000
            return amount

        # 匹配人民币金额
        cny_pattern = r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:亿元|万元|万|亿|RMB|人民币)'
        cny_match = re.search(cny_pattern, content)
        if cny_match:
            amount = float(cny_match.group(1).replace(',', ''))
            if '万' in content and '亿' not in content:
                amount *= 10000
            elif '亿' in content:
                amount *= 100000000
            return amount

        return None

    def _extract_counterparty(self, content: str) -> str:
        """提取交易对手

        🔴 2026-10-20 修复（致命 bug）：原第 2 个模式
            r'（[^）]+?）\\s*(?:收购|购买)'
        **没有捕获组**，但下一行无条件 `match.group(1)` → 一旦命中就抛
            IndexError: no such group
        且被上层 `except Exception as e: result['error']=str(e)` 吞成
        「维度执行异常: no such group」→ **整个 ma_deep 维度作废**
        （实跑 002180 时 deals=0、并购分析全空）。
        修：① 给该模式补捕获组；② 统一用 lastindex 防御，无组则跳过。
        """
        patterns = [
            r'向\s*([^，,。]+?)\s*(?:收购|购买|增资)',
            r'（([^）]+?)）\s*(?:收购|购买)',
            r'对手方[^：:]*?：\s*([^，,。]+)',
            r'交易对方[^：:]*?：\s*([^，,。]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match and match.lastindex:
                return match.group(1).strip()

        return '未知对手方'

    def _extract_target(self, content: str) -> str:
        """提取标的资产/公司"""
        patterns = [
            r'收购\s*([^，。,]+?\s*(?:公司|企业|资产|股权))',
            r'标的[^：:]*?：\s*([^，,。]+)',
            r'购买\s*([^，。,]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()

        return '未知标的'

    def _extract_ma_from_annual(self) -> List[dict]:
        """从年报提取历史收购信息"""
        deals = []

        goodwill_section = self.annual_sections.get('goodwill', {})
        if goodwill_section and isinstance(goodwill_section, dict):
            content = goodwill_section.get('content', '') or goodwill_section.get('text', '')
            if content:
                # 提取商誉金额
                goodwill_pattern = r'商誉[^\d]*?(\d+\.?\d*)\s*(?:亿|万)'
                matches = re.findall(goodwill_pattern, content)
                if matches:
                    deals.append({
                        'date': '年报披露',
                        'title': '商誉形成',
                        'type': '商誉确认',
                        'content': content[:1000],
                        'amount': float(matches[0]) * (100000000 if '亿' in content else 10000),
                        'counterparty': '被收购方',
                        'target': '收购标的'
                    })

        return deals

    def analyze_goodwill(self) -> dict:
        """分析商誉情况

        🔴 2026-10-20 重大修复（原实现**编造数据**）：
          旧代码 `goodwill['total_goodwill'] = total_assets * 0.1  # 估算值`
          是凭空按总资产 10% 假设的假数字 → `goodwill_ratio` 恒为 10.0。
          实跑 002180：估算商誉 15.98 亿，**年报真实商誉 135.09 亿，低估 8.5 倍**
          → 减值风险从「极高（占净资产约 85%）」被误判为「低」→ 评分 +30 → 满分 100。

          现改为：① 从年报 `goodwill` 段的正则抽「合计」行真实数；
                  ② 比率按**占净资产**（专业口径，不是总资产）；
                  ③ 有减值历史则至少「中」；④ 取不到标 data_missing，**不猜**。
        """
        goodwill = {
            'total_goodwill': None,
            'goodwill_ratio': None,          # 占**净资产**比例（%）
            'ratio_basis': '净资产',
            'impairment_history': [],
            'impairment_risk': 'unknown',
            'data_quality': 'ok',
            'key_findings': []
        }

        # ---- ① 从年报 goodwill 段抽真实商誉总额 ----
        gw_sec = self.annual_sections.get('goodwill') or {}
        gw_text = ''
        if isinstance(gw_sec, dict):
            gw_text = gw_sec.get('content') or gw_sec.get('text') or ''
        elif isinstance(gw_sec, str):
            gw_text = gw_sec

        if gw_text:
            # 🔴 2026-10-20 二次修复（我上一版又错了）：
            #   商誉表列结构是：期初余额 | 本期增加 | 本期减少(处置) | **期末余额**
            #   而「合计」行形如：
            #       合计 | 13,508,638,725.02 | 12,886,657,907.59 | 621,980,817.43
            #   上一版取「合计后第一个大数」= **期初余额 135.09 亿**，
            #   但 2025-07 已出售利盟、处置掉 128.87 亿商誉，**期末只剩 6.22 亿**。
            #   取期初会得出「商誉占净资产 146%、极高风险」的错误结论（实际约 6.7%）。
            #   正确做法：取合计行**最后一个**数字（期末余额）。
            m_total = re.search(r'合计\s*([\d,\s\.]{20,80})', gw_text)
            cand = []
            if m_total:
                cand = re.findall(r'\d[\d,]*\.\d{2}', m_total.group(1))
            if len(cand) >= 2:
                # 多列 → 期末余额在最后
                try:
                    val = float(cand[-1].replace(',', ''))
                except ValueError:
                    val = None
                ending = val
                beginning = float(cand[0].replace(',', '')) if cand else None
            elif cand:
                try:
                    ending = float(cand[0].replace(',', ''))
                except ValueError:
                    ending = None
                beginning = None
            else:
                ending, beginning = None, None

            if ending and ending > 0:
                goodwill['total_goodwill'] = ending
                goodwill['goodwill_beginning'] = beginning
                goodwill['basis_note'] = '取商誉表「合计」行**期末余额**（末列）'

        # ---- ② 比率 = 商誉 / 净资产 ----
        latest = self.financial_metrics.get('latest') or {}
        equity = (latest.get('TOTAL_EQUITY') or latest.get('NET_ASSETS')
                  or latest.get('TOTAL_PARENT_EQUITY') or 0)
        total_assets = latest.get('TOTAL_ASSETS') or 0

        if goodwill['total_goodwill'] and equity and equity > 0:
            goodwill['goodwill_ratio'] = goodwill['total_goodwill'] / equity * 100
        elif goodwill['total_goodwill'] and total_assets > 0:
            # 无净资产数据 → 退回占总资产，但明确标注口径
            goodwill['goodwill_ratio'] = goodwill['total_goodwill'] / total_assets * 100
            goodwill['ratio_basis'] = '总资产（缺净资产数据，口径降级）'

        # 取不到真实商誉 → 标缺失，**不用任何估算值**
        if goodwill['total_goodwill'] is None:
            goodwill['data_quality'] = 'data_missing'
            goodwill['key_findings'].append(
                '未取到年报商誉明细，商誉规模与减值风险**无法评估**（已禁止用总资产比例估算）')

        # ---- ③ 从公告提取商誉减值历史（去重）----
        _seen_imp = set()
        for deal in self.deals:
            content = deal.get('content', '')
            if '商誉' in content and '减值' in content:
                imp = {
                    'date': deal.get('date', ''),
                    'amount': self._extract_amount(content) or 0,
                    'reason': self._extract_impairment_reason(content)
                }
                _k = (imp['date'], imp['amount'])
                if _k in _seen_imp:
                    continue
                _seen_imp.add(_k)
                goodwill['impairment_history'].append(imp)

        # ---- ④ 风险评估（占净资产口径 + 减值历史一票否决）----
        ratio = goodwill['goodwill_ratio']
        has_imp = any((x.get('amount') or 0) > 0 for x in goodwill['impairment_history'])
        if ratio is None:
            goodwill['impairment_risk'] = 'unknown'
        elif ratio > 50:
            goodwill['impairment_risk'] = '高'
            goodwill['key_findings'].append(
                f'商誉占{goodwill["ratio_basis"]} {ratio:.1f}%，**减值风险高**')
        elif ratio > 30:
            goodwill['impairment_risk'] = '中'
            goodwill['key_findings'].append(
                f'商誉占{goodwill["ratio_basis"]} {ratio:.1f}%，需关注减值风险')
        elif ratio > 0:
            goodwill['impairment_risk'] = '低'
            goodwill['key_findings'].append('商誉占比较低，减值风险可控')

        # 已有减值历史 → 风险不得低于「中」
        if has_imp and goodwill['impairment_risk'] in ('low', '低', 'unknown'):
            goodwill['impairment_risk'] = '中'
            goodwill['key_findings'].append(
                f'历史已发生 {len(goodwill["impairment_history"])} 次商誉减值'
                '（含金额>0 的记录），风险评级不得低于「中」')

        self.goodwill_analysis = goodwill
        return goodwill

    def _extract_impairment_reason(self, content: str) -> str:
        """提取减值原因"""
        patterns = [
            r'减值[^\w]*?原因[^\w]*?：?\s*([^。]+)',
            r'由于\s*([^。]+)',
            r'计提\s*([^。]+)\s*减值'
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()

        return '未披露具体原因'

    def analyze_synergy(self) -> dict:
        """分析协同效应"""
        synergy = {
            'expected_synergy': [],
            'actual_synergy': [],
            'synergy_achievement': 0.0,
            'synergy_risk': '中',
            'key_findings': []
        }

        for deal in self.deals:
            content = deal.get('content', '')
            ai_analysis = deal.get('ai_analysis', {})

            # 提取预期协同效应（2026-10-20：加去重，同 description+date 只记一次）
            if 'expected' in str(ai_analysis).lower() or '预期' in content:
                _desc = ai_analysis.get('impact_analysis', '预期协同效应')
                _d = deal.get('date', '')
                if not any(x.get('description') == _desc and x.get('date') == _d
                           for x in synergy['expected_synergy']):
                    synergy['expected_synergy'].append({
                        'date': _d,
                        'type': deal.get('type', ''),
                        'description': _desc,
                        'achievement': '待验证'
                    })

            # 检查是否涉及Lexmark（纳思达重大收购）
            # 2026-10-20：原在 for 循环内 append → 每个含 Lexmark 的公告都加一条，
            # 实测重复 4+ 次。改为全量只记一次；且「已出售」不代表协同实现，单列状态。
            if ('Lexmark' in content or '利盟' in content) and not any(
                    x.get('description', '').startswith('收购利盟国际')
                    for x in synergy['expected_synergy']):
                synergy['expected_synergy'].append({
                    'date': '2016',
                    'type': '资产收购',
                    'description': '收购利盟国际，获取打印机核心技术',
                    'achievement': '已出售（资产已剥离）',
                    'status': '完成',
                    'note': '2024 年已出售利盟国际，协同效应不可持续观察',
                })

        # 评估协同效应实现程度
        if synergy['expected_synergy']:
            # 计算时不计「待验证」与「已出售/未实现」——已出售资产无法持续贡献协同
            achieved = sum(1 for s in synergy['expected_synergy']
                           if s.get('achievement') not in ('待验证', '未实现')
                           and '已出售' not in str(s.get('achievement', '')))
            synergy['synergy_achievement'] = (achieved / len(synergy['expected_synergy'])) * 100
            synergy['synergy_basis'] = (f'{achieved}/{len(synergy["expected_synergy"])} 项'
                                        '（已出售/待验证不计入分母实现数）')

            if synergy['synergy_achievement'] > 70:
                synergy['synergy_risk'] = '低'
                synergy['key_findings'].append('协同效应实现程度较高')
            elif synergy['synergy_achievement'] > 40:
                synergy['synergy_risk'] = '中'
                synergy['key_findings'].append('协同效应实现程度中等')
            else:
                synergy['synergy_risk'] = '高'
                synergy['key_findings'].append('协同效应实现程度较低，需关注')

        self.synergy_analysis = synergy
        return synergy

    def analyze_risk(self) -> dict:
        """分析收并购风险"""
        risk = {
            'integration_risk': '中',
            'financial_risk': '中',
            'legal_risk': '中',
            'overall_risk': '中',
            'risk_factors': [],
            'mitigation_suggestions': []
        }

        # 从公告提取风险因素
        for deal in self.deals:
            ai_analysis = deal.get('ai_analysis', {})
            risk_factors = ai_analysis.get('risk_factors', [])

            for factor in risk_factors:
                if factor not in risk['risk_factors']:
                    risk['risk_factors'].append(factor)

        # 评估整合风险
        if len(self.deals) > 5:
            risk['integration_risk'] = '高'
            _f = '收购数量较多，整合管理难度大'
            if _f not in risk['risk_factors']:
                risk['risk_factors'].append(_f)

        # 评估财务风险
        if (self.goodwill_analysis or {}).get('impairment_risk') == '高':
            risk['financial_risk'] = '高'
            _f = '商誉减值风险高，可能影响利润'
            if _f not in risk['risk_factors']:
                risk['risk_factors'].append(_f)

        # 评估法律风险（2026-10-20：原在 for 循环内 append，实测重复 3 次）
        _lit_hit = any(k in str(d) for d in self.deals
                       for k in ('诉讼', '仲裁', '纠纷'))
        if _lit_hit:
            risk['legal_risk'] = '高'
            _f = '存在重大诉讼或仲裁案件'
            if _f not in risk['risk_factors']:
                risk['risk_factors'].append(_f)

        # 计算整体风险
        risk_levels = {'高': 3, '中': 2, '低': 1}
        avg_risk = (risk_levels.get(risk['integration_risk'], 2) +
                   risk_levels.get(risk['financial_risk'], 2) +
                   risk_levels.get(risk['legal_risk'], 2)) / 3

        if avg_risk >= 2.5:
            risk['overall_risk'] = '高'
        elif avg_risk >= 1.5:
            risk['overall_risk'] = '中'
        else:
            risk['overall_risk'] = '低'

        # 提出缓解建议
        if risk['overall_risk'] == '高':
            risk['mitigation_suggestions'].append('建议加强投后管理，密切跟踪整合进展')
            risk['mitigation_suggestions'].append('关注商誉减值测试结果，提前做好财务安排')
            risk['mitigation_suggestions'].append('评估法律纠纷影响，必要时计提充足准备金')

        self.risk_analysis = risk
        return risk

    def calculate_ma_score(self):
        """计算收并购管理评分（0-100）

        🔴 2026-10-20 修复：旧版存在两处逻辑漏洞，实测让 002180 拿到**满分 100**
        （而它商誉占净资产 84%、整体风险判「高」）：
          ① **数据缺失被当成好消息**：商誉比率取不到时旧版按 10% 判「低风险」+30；
          ② **无封顶惩罚**：overall_risk='高' 只扣 20 分，仍能被其他项补回满分。
        现改为：缺失项**不加分**（记 0 而非默认满分）；高风险设总分上限。
        """
        score = 50  # 基础分
        deductions = []

        # 交易质量（20分）—— 数量适中才加分，过多反而增加整合难度
        n = len(self.deals)
        if n > 0:
            score += 10
        if 0 < n <= 10:
            score += 10
        elif n > 50:
            deductions.append(f'交易数量过多（{n} 笔），整合管理难度大')

        # 商誉管理（30分）—— 数据缺失不加分
        gw = self.goodwill_analysis or {}
        gw_risk = gw.get('impairment_risk')
        if gw_risk == '低':
            score += 30
        elif gw_risk == '中':
            score += 20
        elif gw_risk == '高':
            score += 5
        else:
            # unknown / data_missing：不加分（旧版这里会给 +5 或默认 +30）
            deductions.append('商誉数据缺失，该项不计分')

        # 协同效应（25分）—— achievement 需真实存在
        syn = self.synergy_analysis or {}
        ach = syn.get('synergy_achievement') or 0
        if ach > 70:
            score += 25
        elif ach > 50:
            score += 20
        elif ach > 0:
            score += 10

        # 风险管理（25分）
        risk = self.risk_analysis or {}
        overall = risk.get('overall_risk')
        if overall == '低':
            score += 25
        elif overall == '中':
            score += 15
        else:
            score += 5

        score = min(100, max(0, score))

        # 🔴 封顶惩罚：整体风险「高」时总分不得达到"优秀"档（≥70）
        # 理由：风险高却拿高分是自相矛盾的结论，会误导决策。
        if overall == '高' and score > 69:
            deductions.append(f'整体风险判定为「高」，评分封顶 69（原 {score}）')
            score = 69
        # 商誉风险「高」也封顶
        if gw_risk == '高' and score > 79:
            deductions.append(f'商誉减值风险「高」，评分封顶 79（原 {score}）')
            score = 79

        self.ma_score = score
        self.ma_score_notes = deductions

    def generate_ma_report(self) -> dict:
        """生成完整收并购分析报告"""
        return {
            'stock_code': self.stock_code,
            'market': self.market,
            'deals': self.deals,
            'deal_count': len(self.deals),
            'goodwill_analysis': self.goodwill_analysis,
            'synergy_analysis': self.synergy_analysis,
            'risk_analysis': self.risk_analysis,
            'ma_score': self.ma_score,
            'summary': self._generate_summary()
        }

    def _generate_summary(self) -> str:
        """生成一句话总结"""
        score = self.ma_score
        level = '优' if score >= 70 else '中' if score >= 50 else '差'

        risk_level = self.risk_analysis.get('overall_risk', '中')
        goodwill_risk = self.goodwill_analysis.get('impairment_risk', '中')

        summary = (
            f"公司收并购管理{level}（{score}分），"
            f"共完成{len(self.deals)}笔交易，"
            f"商誉风险{goodwill_risk}，"
            f"综合风险{risk_level}。"
        )

        return summary

    def format_report_section(self) -> str:
        """生成Markdown格式的报告章节"""
        report = self.generate_ma_report()
        deals = report['deals']
        goodwill = report['goodwill_analysis']
        synergy = report['synergy_analysis']
        risk = report['risk_analysis']

        section = f"""
## 25. 收并购深度分析

### 25.1 历史收购回顾
**交易总数**：{report['deal_count']}笔

| 时间 | 交易类型 | 标的资产 | 交易对手 | 金额 | 重要性 |
|------|----------|---------|---------|------|--------|
"""

        for deal in deals[:10]:  # 最多显示10笔
            amount_str = f"{deal.get('amount', 0)/100000000:.2f}亿" if deal.get('amount') else '未披露'
            section += f"| {deal.get('date', 'N/A')} | {deal.get('type', 'N/A')} | {deal.get('target', 'N/A')} | {deal.get('counterparty', 'N/A')} | {amount_str} | {deal.get('importance', 'N/A')} |\n"

        section += f"""
### 25.2 商誉风险评估
**商誉金额（估算）**：{goodwill.get('total_goodwill', 0)/100000000:.2f}亿元
**商誉占净资产比**：{goodwill.get('goodwill_ratio', 0):.1f}%
**减值风险等级**：{'🔴 高' if goodwill.get('impairment_risk') == '高' else '🟡 中' if goodwill.get('impairment_risk') == '中' else '🟢 低'}

"""

        if goodwill.get('impairment_history'):
            section += "**历史减值记录**：\n"
            for imp in goodwill['impairment_history']:
                section += f"- {imp['date']}：减值{imp['amount']/100000000:.2f}亿元，原因：{imp['reason']}\n"
        else:
            section += "**历史减值记录**：无重大减值\n"

        section += f"""
{'**关键发现**：' + '；'.join(goodwill.get('key_findings', [])) if goodwill.get('key_findings') else ''}

---

### 25.3 协同效应评估
**协同效应实现程度**：{synergy.get('synergy_achievement', 0):.1f}%
**风险等级**：{'🔴 高' if synergy.get('synergy_risk') == '高' else '🟡 中' if synergy.get('synergy_risk') == '中' else '🟢 低'}

"""

        if synergy.get('expected_synergy'):
            section += "**预期协同效应**：\n"
            for syn in synergy['expected_synergy']:
                section += f"- **{syn.get('date', 'N/A')}** - {syn.get('type', 'N/A')}：{syn.get('description', 'N/A')}（{syn.get('achievement', 'N/A')}）\n"
        else:
            section += "**预期协同效应**：无公开披露\n"

        section += f"""
{'**关键发现**：' + '；'.join(synergy.get('key_findings', [])) if synergy.get('key_findings') else ''}

---

### 25.4 综合风险评估
**整体风险等级**：{'🔴 高' if risk.get('overall_risk') == '高' else '🟡 中' if risk.get('overall_risk') == '中' else '🟢 低'}

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 整合风险 | {'🔴 高' if risk.get('integration_risk') == '高' else '🟡 中' if risk.get('integration_risk') == '中' else '🟢 低'} | {'收购数量多，整合难度大' if risk.get('integration_risk') == '高' else '整合管理风险可控' if risk.get('integration_risk') == '低' else '整合管理风险中等'} |
| 财务风险 | {'🔴 高' if risk.get('financial_risk') == '高' else '🟡 中' if risk.get('financial_risk') == '中' else '🟢 低'} | {'商誉减值风险高' if risk.get('financial_risk') == '高' else '财务风险可控' if risk.get('financial_risk') == '低' else '财务风险中等'} |
| 法律风险 | {'🔴 高' if risk.get('legal_risk') == '高' else '🟡 中' if risk.get('legal_risk') == '中' else '🟢 低'} | {'存在重大诉讼' if risk.get('legal_risk') == '高' else '无重大法律纠纷' if risk.get('legal_risk') == '低' else '存在一定法律风险'} |

"""

        if risk.get('risk_factors'):
            section += "**主要风险因素**：\n"
            for factor in risk['risk_factors'][:5]:
                section += f"- {factor}\n"

        if risk.get('mitigation_suggestions'):
            section += "\n**风险缓解建议**：\n"
            for suggestion in risk['mitigation_suggestions']:
                section += f"- {suggestion}\n"

        section += f"""
---

### 25.5 综合评分
**收并购管理评分**：**{report['ma_score']}/100**
{'🟢 **等级：优秀**' if report['ma_score'] >= 70 else '🟡 **等级：中等**' if report['ma_score'] >= 50 else '🔴 **等级：较差**'}

**总结**：{report['summary']}
"""
        return section


def fetch_ma_deep_analysis(stock_code: str, market: str = 'a',
                          data_dir: str = None) -> dict:
    """收并购深度分析主入口"""
    result = {
        'stock_code': stock_code,
        'market': market,
        'success': False,
        'error': None,
        'data': {}
    }

    try:
        announcements = {}
        financials = {}
        annual_sections = {}
        financial_metrics = {}

        if data_dir and os.path.exists(data_dir):
            results_file = os.path.join(data_dir, 'results.json')
            if os.path.exists(results_file):
                with open(results_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                    findings = results.get('findings', {})

                    if 'announcements' in findings:
                        announcements = findings['announcements']

                    if 'financial' in findings:
                        financials = findings['financial']

                    if 'annual_report_sections' in findings:
                        annual_sections = findings['annual_report_sections']

            # 🔴 2026-10-20 修复：年报章节实际落在**独立文件**
            # `annual_report_sections.json`，不在 findings 里。
            # 旧版只查 findings → annual_sections 恒为 {} → 商誉取不到真实值
            # → 才被迫用 total_assets*0.1 编造。现补上文件加载。
            if data_dir:
                ars_file = os.path.join(data_dir, 'annual_report_sections.json')
                if os.path.exists(ars_file):
                    try:
                        with open(ars_file, 'r', encoding='utf-8') as f:
                            annual_sections = json.load(f)
                    except Exception:
                        pass

            # 加载财务指标
            fm_file = os.path.join(data_dir, 'financial_metrics.json')
            if os.path.exists(fm_file):
                with open(fm_file, 'r', encoding='utf-8') as f:
                    financial_metrics = json.load(f)

        analyzer = MADeepAnalyzer(
            announcements=announcements,
            financials=financials,
            annual_sections=annual_sections,
            financial_metrics=financial_metrics,
            stock_code=stock_code,
            market=market
        )

        report = analyzer.analyze()

        result['success'] = True
        result['data'] = report

        # 保存结果
        if data_dir:
            output_file = os.path.join(data_dir, 'ma_deep_analysis.json')
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

    except Exception as e:
        result['error'] = str(e)

    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        stock = sys.argv[1]
        market = sys.argv[2] if len(sys.argv) > 2 else 'a'
        data_dir = sys.argv[3] if len(sys.argv) > 3 else None

        result = fetch_ma_deep_analysis(stock, market, data_dir)

        if result['success']:
            print(f"✅ 收并购深度分析完成")
            print(f"交易数量：{result['data']['deal_count']}笔")
            print(f"综合评分：{result['data']['ma_score']}/100")
            print(f"总结：{result['data']['summary']}")
        else:
            print(f"❌ 分析失败: {result['error']}")
    else:
        print("用法: python ma_deep_analysis.py <股票代码> [市场] [数据目录]")
        print("示例: python ma_deep_analysis.py 002180 a output/002180_20260530/data")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    analyzer = MADeepAnalyzer(
        announcements={},
        financials={},
        annual_sections={},
        stock_code='',
        market='a'
    )
    analyzer.deals = data.get('deals', [])
    analyzer.goodwill_analysis = data.get('goodwill_analysis', {})
    analyzer.synergy_analysis = data.get('synergy_analysis', {})
    analyzer.risk_analysis = data.get('risk_analysis', {})
    analyzer.ma_score = data.get('ma_score', 0)
    md = analyzer.format_report_section()
    return [md, ""]
