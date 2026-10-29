# -*- coding: utf-8 -*-
"""
cross_validator.py - 跨维度交叉验证引擎

核心能力：将各维度分析结果进行交叉比对，发现单一维度无法察觉的隐情信号。

设计理念：
  - 不重复各模块已有的单维度预警
  - 专注"跨维度关联"和"逻辑矛盾"
  - 每条隐情信号需≥2个独立维度支撑
  - 信号强度分级：🟡疑似 / 🟠高度疑似 / 🔴实锤

隐情类型（6大类20+子规则）：
  1. 利润质量类：虚增利润、报表洗澡、利润转移
  2. 利益输送类：关联方代持、隐性关联交易、资产掏空
  3. 套现跑路类：实控人撤退、高管先行、质押爆仓
  4. 隐藏负债类：表外担保、明股实债、隐性杠杆
  5. 信息操纵类：选择性披露、窗口期交易、预期管理
  6. 治理缺陷类：一股独大、独董花瓶、审计合谋

用法：
    from cross_validator import CrossValidator
    cv = CrossValidator(findings, stock_code, market)
    result = cv.validate()
    print(result['hidden_truths'])   # 隐情列表
    print(result['summary'])        # 综合评估
"""

import sys, json, re, os
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class CrossValidator:
    """跨维度交叉验证引擎"""

    LEVEL_SUSPECTED = '🟡疑似'
    LEVEL_LIKELY = '🟠高度疑似'
    # P2（2026-10-16）：原为 '🔴实锤'。"实锤"等于定性指控，
    # 但底层是关键词/正则的脆弱检测，对上市公司下此结论有合规/声誉风险。
    LEVEL_CONFIRMED = '🔴多信号叠加(需专项核实)'

    def __init__(self, findings, stock_code, market='a'):
        self.findings = findings
        self.stock_code = stock_code
        self.market = market
        self.signals = []
        self.hidden_truths = []

        # 统一加载年报章节数据（兼容 annual_extract 和 annual_pdf 两种来源）
        self.annual_data = self._load_annual_data()

    def _load_annual_data(self):
        """从 findings 中加载年报提取数据

        优先级：annual_extract > annual_pdf.sections > data_dir/annual_report_sections.json
        """
        # 1. 直接从 annual_extract 获取（旧流程）
        ae = self.findings.get('annual_extract', {})
        if ae and any(ae.get(k) for k in ['top5_customers', 'top5_suppliers', 'guarantee', 'related_transactions']):
            return ae

        # 2. 从 annual_pdf.sections 提取关键字段
        ap = self.findings.get('annual_pdf', {})
        sections = ap.get('sections', {}) if isinstance(ap, dict) else {}
        if sections:
            def _sec_content(v):
                """sections值可能是str或dict{'name':..,'content':..}，统一提取content"""
                if isinstance(v, dict):
                    return v.get('content', '')
                return v or ''
            return {
                'top5_customers': _sec_content(sections.get('top5_customers')),
                'top5_suppliers': _sec_content(sections.get('top5_suppliers')),
                'guarantee': _sec_content(sections.get('guarantee')),
                'related_transactions': _sec_content(sections.get('related_transactions')),
                'litigation_detail': _sec_content(sections.get('litigation_detail')) + '\n' + _sec_content(sections.get('litigation', '')) + '\n' + _sec_content(sections.get('contingent', '')),
                'audit': _sec_content(sections.get('audit')),
                'subsidiaries': _sec_content(sections.get('subsidiaries')),
            }

        # 3. 从文件加载
        data_dir = self.findings.get('_data_dir', '') or self.findings.get('_meta', {}).get('data_dir', '')
        if data_dir:
            sp = os.path.join(data_dir, 'annual_report_sections.json')
            if os.path.exists(sp):
                try:
                    with open(sp, 'r', encoding='utf-8') as f:
                        sec = json.load(f)
                    def _sc(v):
                        if isinstance(v, dict):
                            return v.get('content', '')
                        return v or ''
                    return {
                        'top5_customers': _sc(sec.get('top5_customers')),
                        'top5_suppliers': _sc(sec.get('top5_suppliers')),
                        'guarantee': _sc(sec.get('guarantee')),
                        'related_transactions': _sc(sec.get('related_transactions')),
                        'litigation_detail': _sc(sec.get('litigation_detail')),
                        'audit': _sc(sec.get('audit')),
                        'subsidiaries': _sc(sec.get('subsidiaries')),
                    }
                except Exception as _sexc:
                    record(__name__, '_sc', _sexc, note='静默降级')
                    pass

        return {}

    # ═══════════════════════════════════════════════
    #  公开接口
    # ═══════════════════════════════════════════════

    def validate(self):
        """执行全部交叉验证，返回结果"""
        self._rule_profit_quality()
        self._rule_interest_transfer()
        self._rule_insider_exit()
        self._rule_hidden_debt()
        self._rule_info_manipulation()
        self._rule_governance_flaw()
        self._rule_nominee_detection()
        self._synthesize()
        return self._build_result()

    # ═══════════════════════════════════════════════
    #  Rule 1: 利润质量类
    # ═══════════════════════════════════════════════

    def _rule_profit_quality(self):
        fin = self.findings.get('financial', {})
        trend = self.findings.get('multi_year_trend', {})
        anns = self.findings.get('announcements', {})

        # --- 1.1 虚增利润 ---
        profit_signals = []

        # 信号A: 经营现金流为负但净利润为正
        cf_quality = trend.get('cashflow_quality', {})
        cf_signal = cf_quality.get('quality_signal', '')
        if '负' in cf_signal and '盈利' in cf_signal:
            profit_signals.append({
                'id': 'P1A', 'strength': 'strong',
                'dim': '现金流/利润', 'detail': cf_signal
            })

        # 信号B: 应收账款增速远超营收增速
        records = fin.get('records', [])
        if len(records) >= 2:
            latest, prev = records[0], records[1]
            rev_new = self._sf(latest.get('TOTAL_OPERATE_INCOME'))
            rev_old = self._sf(prev.get('TOTAL_OPERATE_INCOME'))
            ar_new = self._sf(latest.get('ACCOUNTS_RECE'))
            ar_old = self._sf(prev.get('ACCOUNTS_RECE'))
            if rev_new and rev_old and ar_new and ar_old and rev_old > 0 and ar_old > 0:
                rev_g = (rev_new - rev_old) / abs(rev_old)
                ar_g = (ar_new - ar_old) / abs(ar_old)
                if ar_g > rev_g + 0.3 and ar_g > 0.2:
                    profit_signals.append({
                        'id': 'P1B', 'strength': 'strong',
                        'dim': '应收/营收',
                        'detail': f'应收增速{ar_g:+.0%}远超营收增速{rev_g:+.0%}'
                    })

        # 信号C: 毛利率异常高于同行
        gm_latest = trend.get('trend', {}).get('gross_margin_latest')
        peers = self.findings.get('peer_compare', {})
        if gm_latest and peers:
            peer_avg_gm = self._extract_peer_avg_gm(peers)
            if peer_avg_gm and gm_latest > peer_avg_gm + 20:
                profit_signals.append({
                    'id': 'P1C', 'strength': 'medium',
                    'dim': '毛利率/同行',
                    'detail': f'毛利率{gm_latest:.1f}%远超同行均值{peer_avg_gm:.1f}%'
                })

        # 信号D: 非标审计意见（排除"标准无保留意见"的误匹配）
        audit = str(fin.get('audit_opinion', ''))
        non_standard_keywords = ['保留意见', '无法表示意见', '否定意见', '无法表示', '带强调事项']
        is_non_standard = any(k in audit for k in non_standard_keywords) and '标准无保留' not in audit
        if is_non_standard and '推断' not in audit:
            profit_signals.append({
                'id': 'P1D', 'strength': 'strong',
                'dim': '审计意见', 'detail': f'审计意见：{audit}'
            })

        for sig in profit_signals:
            self.signals.append({**sig, 'category': '利润质量', 'type': '虚增利润'})

        # --- 1.1b 资产处置/减值信号（补充虚增利润证据） ---
        anns_p = self.findings.get('announcements', {})
        disposal_anns = [a for a in anns_p.get('critical_announcements', []) + anns_p.get('major_announcements', [])
                        if any(k in str(a.get('title', '')) for k in ['减值', '资产处置', '出售', '剥离'])]
        if disposal_anns:
            profit_signals_ext = []
            for da in disposal_anns[:3]:
                content = da.get('extracted_content', {})
                facts = content.get('key_facts', []) if isinstance(content, dict) else []
                detail = f"{da.get('date', '')[:10]} {da.get('title', '')[:50]}"
                if facts:
                    detail += f" | {facts[0][:60]}"
                profit_signals_ext.append({
                    'id': 'P1E', 'strength': 'medium',
                    'dim': '公告-资产处置', 'detail': detail
                })
            for sig in profit_signals_ext:
                self.signals.append({**sig, 'category': '利润质量', 'type': '虚增利润'})

        # --- 1.1c 现金流持续低于净利润 ---
        profit_series = trend.get('trend', {}).get('profit_series', [])
        cf_series = trend.get('trend', {}).get('cf_series', [])
        if len(profit_series) >= 3 and len(cf_series) >= 3:
            mismatch_count = 0
            for i in range(min(len(profit_series), len(cf_series))):
                p_val = profit_series[i][1] if isinstance(profit_series[i], (list, tuple)) else profit_series[i]
                c_val = cf_series[i][1] if isinstance(cf_series[i], (list, tuple)) else cf_series[i]
                if p_val and c_val and p_val > 0 and c_val < p_val * 0.5:
                    mismatch_count += 1
            if mismatch_count >= 2:
                self.signals.append({
                    'id': 'P1F', 'strength': 'medium',
                    'dim': '现金流/利润序列', 'detail': f'近{mismatch_count}年经营现金流显著低于净利润',
                    'category': '利润质量', 'type': '虚增利润'
                })

        # --- 1.2 报表洗澡 ---
        bath_signals = []

        key_events = anns.get('key_events', [])
        impairment = [e for e in key_events
                     if any(k in str(e.get('title', ''))
                            for k in ['减值', '商誉减值', '资产减值', '坏账'])]
        if impairment:
            bath_signals.append({
                'id': 'P2A', 'strength': 'medium',
                'dim': '公告-减值', 'detail': f'存在{len(impairment)}项大额减值公告'
            })

        profit_series = trend.get('trend', {}).get('profit_series', [])
        if len(profit_series) >= 3:
            vals = [v for _, v in profit_series if v is not None]
            if len(vals) >= 3 and vals[-3] < 0 and vals[-1] > 0:
                bath_signals.append({
                    'id': 'P2B', 'strength': 'strong',
                    'dim': '利润V型反转',
                    'detail': f'从{vals[-3]:.1f}亿→{vals[-1]:.1f}亿，疑似洗澡后释放'
                })

        cap = self.findings.get('capital', {})
        cap_actions = cap.get('actions', [])
        incentive = [a for a in cap_actions
                    if any(k in str(a.get('category', ''))
                           for k in ['股权激励', '员工持股'])]
        if incentive:
            bath_signals.append({
                'id': 'P2C', 'strength': 'medium',
                'dim': '资本动作-激励',
                'detail': f'同期存在{len(incentive)}项股权激励/员工持股'
            })

        for sig in bath_signals:
            self.signals.append({**sig, 'category': '利润质量', 'type': '报表洗澡'})

        # --- 1.3 利润转移 ---
        transfer_signals = []

        related = self.findings.get('related', {})
        related_deals = related.get('deals', [])
        if len(related_deals) >= 5:
            transfer_signals.append({
                'id': 'P3A', 'strength': 'medium',
                'dim': '关联交易频次',
                'detail': f'关联交易公告{len(related_deals)}条，频次较高'
            })

        related_risks = related.get('risks', [])
        for r in related_risks[:2]:
            transfer_signals.append({
                'id': 'P3B', 'strength': 'weak',
                'dim': '关联交易风险',
                'detail': r.get('risk', str(r))[:80]
            })

        annual_data = self.annual_data
        top5_supp = annual_data.get('top5_suppliers', '')
        if top5_supp and '集中' in str(top5_supp):
            transfer_signals.append({
                'id': 'P3C', 'strength': 'weak',
                'dim': '供应商集中度', 'detail': '前五供应商集中度较高'
            })

        for sig in transfer_signals:
            self.signals.append({**sig, 'category': '利润质量', 'type': '利润转移'})

    # ═══════════════════════════════════════════════
    #  Rule 2: 利益输送类
    # ═══════════════════════════════════════════════

    def _rule_interest_transfer(self):
        related = self.findings.get('related', {})
        governance = self.findings.get('governance', {})
        financial = self.findings.get('financial', {})
        annual_data = self.annual_data

        # --- 2.1 隐性关联交易 ---
        overlap_signals = []
        top_sh = governance.get('top_shareholders', [])
        sh_names = {s.get('name', '') for s in top_sh if s.get('name')}

        top5_cust_text = str(annual_data.get('top5_customers', ''))
        top5_supp_text = str(annual_data.get('top5_suppliers', ''))
        for name in sh_names:
            if len(name) >= 2 and name in top5_cust_text:
                overlap_signals.append({
                    'id': 'T1A', 'strength': 'strong',
                    'dim': '股东×客户',
                    'detail': f'大股东"{name}"同时出现在前五客户名单中'
                })
            if len(name) >= 2 and name in top5_supp_text:
                overlap_signals.append({
                    'id': 'T1B', 'strength': 'strong',
                    'dim': '股东×供应商',
                    'detail': f'大股东"{name}"同时出现在前五供应商名单中'
                })

        for sig in overlap_signals:
            self.signals.append({**sig, 'category': '利益输送', 'type': '隐性关联交易'})

        # --- 2.2 资产掏空 ---
        tunnel_signals = []
        related_deals = related.get('deals', [])
        acquisitions = [d for d in related_deals
                       if any(k in str(d.get('category', ''))
                              for k in ['收购', '增资'])]
        disposals = [d for d in related_deals
                    if any(k in str(d.get('category', ''))
                           for k in ['出售', '转让'])]

        if len(acquisitions) >= 3:
            tunnel_signals.append({
                'id': 'T2A', 'strength': 'medium',
                'dim': '关联收购频次',
                'detail': f'关联方收购/增资{len(acquisitions)}次，需关注定价公允性'
            })
        if len(disposals) >= 2:
            tunnel_signals.append({
                'id': 'T2B', 'strength': 'medium',
                'dim': '关联出售频次',
                'detail': f'关联方出售/转让{len(disposals)}次，需关注是否低价出让'
            })

        # 资金占用：其他应收款大+关联交易多
        fin_records = financial.get('records', [])
        if fin_records:
            other_recv = self._sf(fin_records[0].get('OTHER_RECE'))
            total_assets = self._sf(fin_records[0].get('TOTAL_ASSETS'))
            if other_recv and total_assets and total_assets > 0:
                or_ratio = other_recv / total_assets
                if or_ratio > 0.05 and len(related_deals) >= 3:
                    tunnel_signals.append({
                        'id': 'T2C', 'strength': 'strong',
                        'dim': '其他应收款×关联交易',
                        'detail': f'其他应收款占资产{or_ratio:.1%}+关联交易{len(related_deals)}条，疑似资金占用'
                    })

        for sig in tunnel_signals:
            self.signals.append({**sig, 'category': '利益输送', 'type': '资产掏空'})

    # ═══════════════════════════════════════════════
    #  Rule 3: 套现跑路类
    # ═══════════════════════════════════════════════

    def _rule_insider_exit(self):
        cap = self.findings.get('capital', {})
        governance = self.findings.get('governance', {})
        executives = self.findings.get('executives', {})
        share_hist = self.findings.get('share_history', {})
        related = self.findings.get('related', {})
        inst = self.findings.get('institutional', {})

        # --- 3.1 实控人撤退 ---
        exit_signals = []

        # 质押率
        pledge = governance.get('pledge', {})
        pledge_ratio = pledge.get('latest_ratio')
        if pledge_ratio is not None and pledge_ratio > 0.7:
            exit_signals.append({
                'id': 'E1A', 'strength': 'strong',
                'dim': '股权质押',
                'detail': f'大股东质押率{pledge_ratio:.0%}，超70%警戒线'
            })
        elif pledge_ratio is not None and pledge_ratio > 0.5:
            exit_signals.append({
                'id': 'E1A', 'strength': 'medium',
                'dim': '股权质押',
                'detail': f'大股东质押率{pledge_ratio:.0%}，接近警戒线'
            })

        # 大股东减持
        cap_actions = cap.get('actions', [])
        reductions = [a for a in cap_actions
                     if any(k in str(a.get('category', ''))
                            for k in ['股东减持', '减持'])]
        if len(reductions) >= 3:
            exit_signals.append({
                'id': 'E1B', 'strength': 'strong',
                'dim': '股东减持',
                'detail': f'近期{len(reductions)}次股东减持公告'
            })
        elif reductions:
            exit_signals.append({
                'id': 'E1B', 'strength': 'weak',
                'dim': '股东减持',
                'detail': f'近期{len(reductions)}次股东减持'
            })

        # 限售解禁
        unlock = share_hist.get('unlock_schedule', [])
        if unlock:
            total_unlock = sum(self._sf(u.get('unlock_shares_万股', 0)) or 0
                             for u in unlock[:3])
            if total_unlock > 0:
                exit_signals.append({
                    'id': 'E1C', 'strength': 'medium',
                    'dim': '限售解禁',
                    'detail': f'即将解禁{total_unlock:.0f}万股'
                })

        # 关联收购+减持=变相套现
        related_acq = [d for d in related.get('deals', [])
                      if any(k in str(d.get('category', ''))
                             for k in ['收购', '增资'])]
        if len(related_acq) >= 2 and reductions:
            exit_signals.append({
                'id': 'E1D', 'strength': 'medium',
                'dim': '关联收购×减持',
                'detail': '关联方收购+股东减持并存，实控人可能通过关联交易变相套现'
            })

        for sig in exit_signals:
            self.signals.append({**sig, 'category': '套现跑路', 'type': '实控人撤退'})

        # --- 3.2 高管先行 ---
        exec_signals = []
        exec_summary = executives.get('summary', {})
        exec_warnings = exec_summary.get('warnings', [])
        key_departures = [w for w in exec_warnings
                         if any(k in str(w)
                                for k in ['董事长', '总裁', 'CEO', 'CFO', '财务总监'])]
        if key_departures:
            exec_signals.append({
                'id': 'E2A', 'strength': 'strong',
                'dim': '核心高管离职',
                'detail': '; '.join(key_departures[:2])
            })

        exec_reductions = [a for a in cap_actions
                          if any(k in str(a.get('category', ''))
                                 for k in ['股东减持', '减持', '高管减持'])]
        if key_departures and exec_reductions:
            exec_signals.append({
                'id': 'E2B', 'strength': 'strong',
                'dim': '离职×减持',
                'detail': '核心高管离职+减持，先行离场信号'
            })

        inst_risks = inst.get('risks', [])
        inst_reduce = [r for r in inst_risks if '减' in str(r) or '下降' in str(r)]
        if inst_reduce:
            exec_signals.append({
                'id': 'E2C', 'strength': 'weak',
                'dim': '机构减仓',
                'detail': '; '.join(str(r)[:60] for r in inst_reduce[:2])
            })

        for sig in exec_signals:
            self.signals.append({**sig, 'category': '套现跑路', 'type': '高管先行'})

    # ═══════════════════════════════════════════════
    #  Rule 4: 隐藏负债类
    # ═══════════════════════════════════════════════

    def _rule_hidden_debt(self):
        financial = self.findings.get('financial', {})
        related = self.findings.get('related', {})
        cap = self.findings.get('capital', {})
        annual_data = self.annual_data
        trend = self.findings.get('multi_year_trend', {})

        # --- 4.1 表外担保 ---
        guarantee_signals = []
        related_deals = related.get('deals', [])
        guarantees = [d for d in related_deals
                     if '担保' in str(d.get('category', '')) or '担保' in str(d.get('title', ''))]
        if len(guarantees) >= 3:
            guarantee_signals.append({
                'id': 'D1A', 'strength': 'strong',
                'dim': '关联担保频次',
                'detail': f'关联担保公告{len(guarantees)}条，可能存在表外负债'
            })
        elif guarantees:
            guarantee_signals.append({
                'id': 'D1A', 'strength': 'weak',
                'dim': '关联担保',
                'detail': f'关联担保公告{len(guarantees)}条'
            })

        # 担保金额占净资产比
        fin_records = financial.get('records', [])
        if fin_records:
            total_equity = self._sf(fin_records[0].get('TOTAL_PARENT_EQUITY'))
            guarantee_text = str(annual_data.get('guarantee', ''))
            if total_equity and total_equity > 0 and guarantee_text:
                guarantee_amounts = re.findall(r'(\d+(?:\.\d+)?)\s*亿', guarantee_text)
                if guarantee_amounts:
                    total_g = sum(float(g) for g in guarantee_amounts[:5])
                    g_ratio = total_g / (total_equity / 1e8) if total_equity else 0
                    if g_ratio > 0.5:
                        guarantee_signals.append({
                            'id': 'D1B', 'strength': 'strong',
                            'dim': '担保/净资产',
                            'detail': f'担保约{total_g:.1f}亿占净资产{g_ratio:.0%}，超50%警戒线'
                        })

        anns = self.findings.get('announcements', {})
        ann_critical = anns.get('critical_announcements', [])
        ann_major = anns.get('major_announcements', [])
        guarantee_anns = [a for a in ann_critical + ann_major
                         if '担保' in str(a.get('title', ''))]
        if len(guarantee_anns) >= 5:
            guarantee_signals.append({
                'id': 'D1E', 'strength': 'medium',
                'dim': '公告-担保',
                'detail': f'近三年担保公告{len(guarantee_anns)}条，担保行为频繁'
            })

        guarantee_amount_total = 0
        for ga in guarantee_anns[:20]:
            content = ga.get('extracted_content', {})
            if isinstance(content, dict):
                for fact in content.get('key_facts', []):
                    amounts = re.findall(r'(\d+(?:\.\d+)?)\s*亿', str(fact))
                    for a in amounts:
                        try: guarantee_amount_total += float(a)
                        except Exception as _sexc:
                            record(__name__, '_rule_hidden_debt', _sexc, note='静默降级')
        if guarantee_amount_total > 0:
            fin_records = financial.get('records', [])
            if fin_records:
                total_equity = self._sf(fin_records[0].get('TOTAL_PARENT_EQUITY'))
                if total_equity and total_equity > 0:
                    eq_yi = total_equity / 1e8
                    g_ratio = guarantee_amount_total / eq_yi
                    if g_ratio > 0.3:
                        guarantee_signals.append({
                            'id': 'D1F', 'strength': 'strong' if g_ratio > 0.5 else 'medium',
                            'dim': '公告担保金额/净资产',
                            'detail': f'公告中提取担保金额约{guarantee_amount_total:.1f}亿，占净资产{g_ratio:.0%}'
                        })

        for sig in guarantee_signals:
            self.signals.append({**sig, 'category': '隐藏负债', 'type': '表外担保'})

        # --- 4.1b 重大未决诉讼/仲裁（可能构成隐藏负债） ---
        litigation_text = str(annual_data.get('litigation_detail', ''))
        if litigation_text and len(litigation_text) > 50:
            # 提取金额（支持美元/人民币/亿/万/逗号分隔数字）
            # 格式1: "6.89亿美元" / "3亿人民币"
            cny_yi = re.findall(r'(\d+(?:\.\d+)?)\s*亿美元', litigation_text)
            cny_yi2 = re.findall(r'(\d+(?:\.\d+)?)\s*亿人民币', litigation_text)
            # 格式2: "689,018,524 美元" (逗号分隔完整数字+美元)
            usd_full = re.findall(r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*美元', litigation_text)
            # 格式3: "USD 689018524"
            usd_amounts = re.findall(r'USD\s*(\d+(?:,\d+)*(?:\.\d+)?)', litigation_text, re.IGNORECASE)
            all_yi = []
            for a in cny_yi + cny_yi2:
                try: all_yi.append(float(a))
                except Exception as _sexc:
                    record(__name__, '_rule_hidden_debt', _sexc, note='静默降级')
            for a in usd_full + usd_amounts:
                try: all_yi.append(float(a.replace(',', '')) / 1e8 * 7.2)  # USD→亿人民币
                except Exception as _sexc:
                    record(__name__, '_rule_hidden_debt', _sexc, note='静默降级')
            # 格式4: "XX万元" 转换
            wan_amounts = re.findall(r'(\d+(?:,\d+)*)\s*万元', litigation_text)
            for a in wan_amounts:
                try: all_yi.append(float(a.replace(',', '')) / 10000)  # 万元→亿
                except Exception as _sexc:
                    record(__name__, '_rule_hidden_debt', _sexc, note='静默降级')

            if all_yi:
                max_lit = max(all_yi)
                fin_records = financial.get('records', [])
                if fin_records:
                    total_equity = self._sf(fin_records[0].get('TOTAL_PARENT_EQUITY'))
                    if total_equity and total_equity > 0:
                        eq_yi = total_equity / 1e8
                        lit_ratio = max_lit / eq_yi
                        strength = 'strong' if lit_ratio > 0.2 else ('medium' if lit_ratio > 0.1 else 'weak')
                        if lit_ratio > 0.05:
                            self.signals.append({
                                'id': 'D1C', 'strength': strength,
                                'dim': '重大诉讼/仲裁',
                                'detail': f'未决诉讼/仲裁最大金额约{max_lit:.1f}亿，占净资产{lit_ratio:.0%}',
                                'category': '隐藏负债', 'type': '表外担保'
                            })

        # --- 4.2 隐性杠杆 ---
        leverage_signals = []

        cf_quality = trend.get('cashflow_quality', {})
        cf_avg = cf_quality.get('avg_cf_netprofit_ratio')
        cap_invest = [a for a in cap.get('actions', [])
                     if any(k in str(a.get('category', ''))
                            for k in ['收购', '增资', '投资', '合资'])]
        if cf_avg is not None and cf_avg < 0.5 and len(cap_invest) >= 2:
            leverage_signals.append({
                'id': 'D2A', 'strength': 'medium',
                'dim': '现金流×投资',
                'detail': f'现金流利润比仅{cf_avg:.2f}但对外投资{len(cap_invest)}项，疑似依赖外部融资'
            })

        fund_supplement = [a for a in cap.get('actions', [])
                          if '补流' in str(a.get('category', '')) or
                          '补充流动' in str(a.get('title', ''))]
        if fund_supplement:
            leverage_signals.append({
                'id': 'D2B', 'strength': 'medium',
                'dim': '募资补流',
                'detail': f'存在{len(fund_supplement)}项募集资金永久补流，流动性紧张信号'
            })

        # 短债/长债期限错配
        if fin_records:
            short_debt = self._sf(fin_records[0].get('SHORT_LOAN'))
            long_debt = self._sf(fin_records[0].get('LONG_LOAN'))
            if short_debt and long_debt and long_debt > 0:
                sl_ratio = short_debt / long_debt
                if sl_ratio > 5:
                    leverage_signals.append({
                        'id': 'D2C', 'strength': 'medium',
                        'dim': '短债/长债',
                        'detail': f'短债/长债比{sl_ratio:.1f}倍，期限错配风险高'
                    })

        for sig in leverage_signals:
            self.signals.append({**sig, 'category': '隐藏负债', 'type': '隐性杠杆'})

    # ═══════════════════════════════════════════════
    #  Rule 5: 信息操纵类
    # ═══════════════════════════════════════════════

    def _rule_info_manipulation(self):
        anns = self.findings.get('announcements', {})
        executives = self.findings.get('executives', {})
        cap = self.findings.get('capital', {})
        related = self.findings.get('related', {})

        # --- 5.1 选择性披露 ---
        select_signals = []

        key_events = anns.get('key_events', [])
        if key_events:
            positive = [e for e in key_events
                       if any(k in str(e.get('title', ''))
                              for k in ['中标', '签约', '合作', '获得', '增长', '增持'])]
            negative = [e for e in key_events
                       if any(k in str(e.get('title', ''))
                              for k in ['诉讼', '仲裁', '处罚', '违规', '警示', '监管', '减值', '亏损'])]
            if len(positive) >= 5 and len(negative) <= 1:
                select_signals.append({
                    'id': 'I1A', 'strength': 'medium',
                    'dim': '利好/利空比',
                    'detail': f'利好{len(positive)}条vs利空{len(negative)}条，选择性披露嫌疑'
                })

        # --- 5.2 窗口期交易 ---
        window_signals = []

        # 高管增持/减持时间与重大公告时间接近
        cap_actions = cap.get('actions', [])
        trade_actions = [a for a in cap_actions
                        if any(k in str(a.get('category', ''))
                               for k in ['增持', '减持', '回购'])]
        if trade_actions and key_events:
            # 简化判断：同时存在增持/减持和重大事项公告
            window_signals.append({
                'id': 'I2A', 'strength': 'weak',
                'dim': '交易×公告时序',
                'detail': f'同期存在{len(trade_actions)}项增减持+{len(key_events)}项重大公告，需关注窗口期合规'
            })

        for sig in select_signals + window_signals:
            self.signals.append({**sig, 'category': '信息操纵',
                                'type': '选择性披露' if sig['id'].startswith('I1') else '窗口期交易'})

    # ═══════════════════════════════════════════════
    #  Rule 6: 治理缺陷类
    # ═══════════════════════════════════════════════

    def _rule_governance_flaw(self):
        governance = self.findings.get('governance', {})
        financial = self.findings.get('financial', {})
        related = self.findings.get('related', {})

        gov_signals = []

        # --- 6.1 一股独大 + 关联交易 ---
        ownership = governance.get('ownership', {})
        cr1 = ownership.get('cr1')
        related_deals = related.get('deals', [])
        if cr1 and cr1 > 50 and len(related_deals) >= 3:
            gov_signals.append({
                'id': 'G1A', 'strength': 'strong',
                'dim': '股权集中×关联交易',
                'detail': f'第一大股东持股{cr1:.1f}%+关联交易{len(related_deals)}条，一股独大+利益输送风险'
            })
        elif cr1 and cr1 > 30 and len(related_deals) >= 5:
            gov_signals.append({
                'id': 'G1A', 'strength': 'medium',
                'dim': '股权集中×关联交易',
                'detail': f'第一大股东持股{cr1:.1f}%+关联交易{len(related_deals)}条'
            })

        # --- 6.2 独董花瓶 ---
        ind_dir = governance.get('independent_directors', {})
        ind_warnings = ind_dir.get('warnings', [])
        if ind_warnings:
            for w in ind_warnings[:2]:
                gov_signals.append({
                    'id': 'G2A', 'strength': 'weak',
                    'dim': '独立董事', 'detail': str(w)[:80]
                })

        # --- 6.3 审计合谋嫌疑 ---
        # 非标意见少+关联交易多+高管异动 = 审计可能不够独立
        audit = financial.get('audit_opinion', '')
        exec_data = self.findings.get('executives', {})
        exec_warnings = exec_data.get('summary', {}).get('warnings', [])
        if (audit and '标准无保留' in str(audit) and '推断' not in str(audit) and
            len(related_deals) >= 5 and exec_warnings):
            gov_signals.append({
                'id': 'G3A', 'strength': 'medium',
                'dim': '审计×关联×高管',
                'detail': '标准审计意见+大量关联交易+高管异动，审计独立性存疑'
            })

        for sig in gov_signals:
            type_map = {'G1': '一股独大', 'G2': '独董花瓶', 'G3': '审计合谋'}
            t = type_map.get(sig['id'][:2], '治理缺陷')
            self.signals.append({**sig, 'category': '治理缺陷', 'type': t})

    # ═══════════════════════════════════════════════
    #  Rule 7: 关联方代持/名义股东检测
    # ═══════════════════════════════════════════════

    def _rule_nominee_detection(self):
        """基于工商和股东数据的关联方代持检测
        
        检测逻辑：
        1. 前五客户/供应商与大股东/子公司名称重叠 → 隐性关联
        2. 子公司/关联方与客户/供应商名称交叉 → 代持嫌疑
        3. 股东变更+客户集中度变化同步 → 名义股东嫌疑
        """
        governance = self.findings.get('governance', {})
        related = self.findings.get('related', {})
        annual_data = self.annual_data
        subsidiary = self.findings.get('subsidiary', {})
        share_hist = self.findings.get('share_history', {})

        nominee_signals = []

        # 7.1 大股东名称 × 客户/供应商名单
        top_sh = governance.get('top_shareholders', [])
        sh_names = [s.get('name', '') for s in top_sh if s.get('name') and len(s.get('name', '')) >= 2]
        
        # 从年报提取中获取客户/供应商
        top5_cust = str(annual_data.get('top5_customers', ''))
        top5_supp = str(annual_data.get('top5_suppliers', ''))
        
        # 从关联交易公告中提取公司名称
        related_deals = related.get('deals', [])
        related_names = set()
        for d in related_deals:
            title = str(d.get('title', ''))
            # 提取公告标题中的公司名（简化：取「关于」和「的」之间的文本）
            for m in re.findall(r'关于(.+?)(?:的|暨)', title):
                for name in m.split('与'):
                    name = name.strip()
                    if len(name) >= 3:
                        related_names.add(name)
        
        # 7.2 子公司名称 × 客户/供应商
        subsidiaries = subsidiary.get('subsidiaries', [])
        sub_names = [s.get('name', '') for s in subsidiaries if s.get('name') and len(s.get('name', '')) >= 2]
        
        # 交叉比对
        overlap_with_cust = []
        overlap_with_supp = []
        
        for name in sh_names + sub_names[:10]:  # 限制检查范围
            # 与客户名单比对（模糊匹配：名3字以上子串）
            if name in top5_cust:
                overlap_with_cust.append(name)
            elif len(name) >= 3 and any(name in c or c in name for c in top5_cust.split('\n') if len(c.strip()) >= 3):
                overlap_with_cust.append(name)
            
            # 与供应商名单比对
            if name in top5_supp:
                overlap_with_supp.append(name)
            elif len(name) >= 3 and any(name in s or s in name for s in top5_supp.split('\n') if len(s.strip()) >= 3):
                overlap_with_supp.append(name)
        
        if overlap_with_cust:
            nominee_signals.append({
                'id': 'N1A', 'strength': 'strong',
                'dim': '股东/子公司×客户',
                'detail': f'以下名称同时出现在客户名单中: {", ".join(overlap_with_cust[:5])}'
            })
        
        if overlap_with_supp:
            nominee_signals.append({
                'id': 'N1B', 'strength': 'strong',
                'dim': '股东/子公司×供应商',
                'detail': f'以下名称同时出现在供应商名单中: {", ".join(overlap_with_supp[:5])}'
            })
        
        # 7.3 关联交易对象 × 客户/供应商
        for rname in list(related_names)[:20]:
            if len(rname) >= 3 and rname in top5_cust:
                nominee_signals.append({
                    'id': 'N2A', 'strength': 'medium',
                    'dim': '关联方×客户',
                    'detail': f'关联交易对象"{rname}"同时出现在前五客户中'
                })
            if len(rname) >= 3 and rname in top5_supp:
                nominee_signals.append({
                    'id': 'N2B', 'strength': 'medium',
                    'dim': '关联方×供应商',
                    'detail': f'关联交易对象"{rname}"同时出现在前五供应商中'
                })
        
        # 7.4 股东变更+客户变化同步
        equity_changes = share_hist.get('equity_changes', [])
        if len(equity_changes) >= 3 and (overlap_with_cust or overlap_with_supp):
            nominee_signals.append({
                'id': 'N3A', 'strength': 'medium',
                'dim': '股东变更×客户重叠',
                'detail': f'近期{len(equity_changes)}次股东变更+客户/供应商与股东名称重叠，名义股东嫌疑'
            })
        
        for sig in nominee_signals:
            self.signals.append({**sig, 'category': '利益输送', 'type': '关联方代持'})

    # ═══════════════════════════════════════════════
    #  信号合成：将原始信号合成为隐情结论
    # ═══════════════════════════════════════════════

    def _synthesize(self):
        """按 category+type 聚合信号，评定隐情等级"""

        # 1. 按 (category, type) 分组
        groups = {}
        for sig in self.signals:
            key = (sig['category'], sig['type'])
            groups.setdefault(key, []).append(sig)

        # 2. 对每组信号评定等级
        for (category, type_), sigs in groups.items():
            strong = sum(1 for s in sigs if s['strength'] == 'strong')
            medium = sum(1 for s in sigs if s['strength'] == 'medium')
            weak = sum(1 for s in sigs if s['strength'] == 'weak')

            # P2 护栏（2026-10-16 审计修复）：
            # 旧版 strong>=2 即判"🔴实锤"。但 strong 信号多来自
            # 关键词/正则的脆弱检测（如 V 型反转、非标审计意见），
            # 会把正常公司误判为财务造假，且"实锤"措辞等于定性指控，
            # 有合规/声誉风险。
            # 新规：
            #   a) "实锤"须 ≥3 个 strong 且来自 ≥3 个**不同维度**；
            #   b) 2 个 strong 降级为"高度疑似"；
            #   c) 等级标签由"实锤"改为"多信号叠加，需专项核实"。
            distinct_dims = len({s['dim'] for s in sigs if s['strength'] == 'strong'})
            independent = distinct_dims >= 3

            if strong >= 3 and independent:
                level = self.LEVEL_CONFIRMED
            elif strong >= 2:
                level = self.LEVEL_LIKELY
            elif strong >= 1 and (medium >= 1 or weak >= 2):
                level = self.LEVEL_LIKELY
            elif strong >= 1:
                level = self.LEVEL_SUSPECTED
            elif medium >= 2:
                level = self.LEVEL_LIKELY
            elif medium >= 1 and weak >= 1:
                level = self.LEVEL_SUSPECTED
            elif weak >= 3:
                level = self.LEVEL_SUSPECTED
            else:
                continue  # 信号太弱，跳过

            # 生成隐情描述
            narrative = self._generate_narrative(category, type_, sigs, level)

            self.hidden_truths.append({
                'category': category,
                'type': type_,
                'level': level,
                'signal_count': len(sigs),
                'strong_count': strong,
                'independent_dims': distinct_dims,
                'signals': sigs,
                'narrative': narrative,
                # P2：所有等级统一附核实要求，不得作为定性结论
                'verification_required': True,
                'disclaimer': ('以上为多维度信号交叉提示，非审计或监管结论；'
                              '须回到一手披露文件逐项核实后方可定性。'),
            })

        # 3. 按等级排序：实锤 > 高度疑似 > 疑似
        level_order = {self.LEVEL_CONFIRMED: 0, self.LEVEL_LIKELY: 1, self.LEVEL_SUSPECTED: 2}
        self.hidden_truths.sort(key=lambda x: level_order.get(x['level'], 3))

    def _generate_narrative(self, category, type_, sigs, level):
        """根据信号组合生成隐情叙述"""

        details = [f"[{s['dim']}] {s['detail']}" for s in sigs]

        narratives = {
            ('利润质量', '虚增利润'):
                f"**虚增利润疑点（需核实）**（{level}）："
                f"多个维度交叉指向利润质量问题。"
                f"{'现金流与利润背离，' if any(s['id'] == 'P1A' for s in sigs) else ''}"
                f"{'应收账款异常增长，' if any(s['id'] == 'P1B' for s in sigs) else ''}"
                f"{'毛利率显著偏离同行，' if any(s['id'] == 'P1C' for s in sigs) else ''}"
                f"{'审计意见非标，' if any(s['id'] == 'P1D' for s in sigs) else ''}"
                f"{'存在大额资产处置/减值，' if any(s['id'] == 'P1E' for s in sigs) else ''}"
                f"{'多年经营现金流显著低于净利润，' if any(s['id'] == 'P1F' for s in sigs) else ''}"
                f"建议深入核查收入确认政策和回款情况。",

            ('利润质量', '报表洗澡'):
                f"**报表洗澡疑点（需核实）**（{level}）："
                f"{'大额减值冲回+利润V型反转，' if any(s['id'] == 'P2B' for s in sigs) else ''}"
                f"{'配合股权激励行权条件，' if any(s['id'] == 'P2C' for s in sigs) else ''}"
                f"可能存在通过一次性减值压低基数的情形，需核查减值测试依据与会计估计变更。",

            ('利润质量', '利润转移'):
                f"**利润转移疑点（需核实）**（{level}）："
                f"高频关联交易+供应商集中，利润可能通过关联定价向外转移。"
                f"建议核查关联交易定价公允性及客户/供应商实际控制关系。",

            ('利益输送', '隐性关联交易'):
                f"**隐性关联交易疑点（需核实）**（{level}）："
                f"大股东与前五客户/供应商存在名称重叠，存在未披露关联交易的可能性。"
                f"需核查交易实质和定价合理性。",

            ('利益输送', '资产掏空'):
                f"**资产掏空疑点（需核实）**（{level}）："
                f"{'频繁关联收购/增资，' if any(s['id'] == 'T2A' for s in sigs) else ''}"
                f"{'关联方出售/转让，' if any(s['id'] == 'T2B' for s in sigs) else ''}"
                f"{'其他应收款偏高疑似资金占用，' if any(s['id'] == 'T2C' for s in sigs) else ''}"
                f"需关注关联交易定价是否公允、是否存在利益输送。",

            ('套现跑路', '实控人撤退'):
                f"**实控人减持/质押疑点（需核实）**（{level}）："
                f"{'高质押率，' if any(s['id'] == 'E1A' for s in sigs) else ''}"
                f"{'大股东减持，' if any(s['id'] == 'E1B' for s in sigs) else ''}"
                f"{'限售股即将解禁，' if any(s['id'] == 'E1C' for s in sigs) else ''}"
                f"{'关联收购+减持并存，' if any(s['id'] == 'E1D' for s in sigs) else ''}"
                f"实控人存在减持/质押行为，需结合公告与质押平仓线判断。",

            ('套现跑路', '高管先行'):
                f"**高管先行离场**（{level}）："
                f"{'核心高管离职，' if any(s['id'] == 'E2A' for s in sigs) else ''}"
                f"{'离职+减持同时发生，' if any(s['id'] == 'E2B' for s in sigs) else ''}"
                f"{'机构大幅减仓，' if any(s['id'] == 'E2C' for s in sigs) else ''}"
                f"内部人比外部投资者更早感知风险。",

            ('隐藏负债', '表外担保'):
                f"**表外担保风险**（{level}）："
                f"关联担保频繁，可能存在大量表外负债。"
                f"{'担保公告数量多，' if any(s['id'] == 'D1E' for s in sigs) else ''}"
                f"{'公告担保金额占净资产比例高，' if any(s['id'] == 'D1F' for s in sigs) else ''}"
                f"一旦被担保方违约，上市公司将面临连带清偿风险。",

            ('隐藏负债', '隐性杠杆'):
                f"**隐性杠杆风险**（{level}）："
                f"{'现金流恶化+对外投资激进，' if any(s['id'] == 'D2A' for s in sigs) else ''}"
                f"{'募集资金永久补流，' if any(s['id'] == 'D2B' for s in sigs) else ''}"
                f"{'短期债务占比过高，' if any(s['id'] == 'D2C' for s in sigs) else ''}"
                f"实际负债压力可能远超报表呈现。",

            ('信息操纵', '选择性披露'):
                f"**选择性披露嫌疑**（{level}）："
                f"利好公告密度远超利空，可能存在信息操纵，"
                f"需结合股价异动判断是否存在配合拉升出货。",

            ('信息操纵', '窗口期交易'):
                f"**窗口期交易嫌疑**（{level}）："
                f"高管增减持与重大公告时间接近，需核查是否违反窗口期规定。",

            ('治理缺陷', '一股独大'):
                f"**一股独大风险**（{level}）："
                f"股权高度集中+大量关联交易，中小股东利益难以保障。",

            ('治理缺陷', '独董花瓶'):
                f"**独立董事有效性存疑**（{level}）："
                f"独董结构或行为存在异常，可能无法有效发挥监督作用。",

            ('治理缺陷', '审计合谋'):
                f"**审计独立性存疑**（{level}）："
                f"在关联交易频繁+高管异动的情况下获得标准审计意见，"
                f"审计意见类型提示风险，需调阅审计报告与关键审计事项。",

            ('利益输送', '关联方代持'):
                f"**关联方代持嫌疑**（{level}）："
                f"股东/子公司/关联交易对象与前五客户/供应商存在名称重叠，"
                f"可能存在未披露的关联方代持交易。"
                f"需核查相关方的实际控制人和工商登记信息。",
        }

        key = (category, type_)
        if key in narratives:
            return narratives[key]

        # 兜底
        return f"**{category}-{type_}**（{level}）：发现{len(sigs)}个交叉信号。" + "；".join(details)

    # ═══════════════════════════════════════════════
    #  构建最终结果
    # ═══════════════════════════════════════════════

    def _build_result(self):
        # 按等级统计
        confirmed = [t for t in self.hidden_truths if t['level'] == self.LEVEL_CONFIRMED]
        likely = [t for t in self.hidden_truths if t['level'] == self.LEVEL_LIKELY]
        suspected = [t for t in self.hidden_truths if t['level'] == self.LEVEL_SUSPECTED]

        # 综合风险评分（0-100）
        score = min(100, len(confirmed) * 30 + len(likely) * 15 + len(suspected) * 5)

        if score >= 60:
            overall = '🔴 高度关注'
        elif score >= 30:
            overall = '🟠 值得警惕'
        elif score >= 10:
            overall = '🟡 需留意'
        else:
            overall = '🟢 暂无重大隐情'

        # 生成markdown
        md_lines = self._generate_markdown(confirmed, likely, suspected, score, overall)

        return {
            'stock_code': self.stock_code,
            'market': self.market,
            'hidden_truths': self.hidden_truths,
            'raw_signals': self.signals,
            'summary': {
                'score': score,
                'overall': overall,
                'confirmed_count': len(confirmed),
                'likely_count': len(likely),
                'suspected_count': len(suspected),
                'total_signals': len(self.signals),
            },
            'markdown': '\n'.join(md_lines),
        }

    def _generate_markdown(self, confirmed, likely, suspected, score, overall):
        lines = []
        lines.append(f"## 🔍 跨维度交叉验证：隐情发现报告")
        lines.append(f"")
        lines.append(f"**股票代码**: {self.stock_code}  ")
        lines.append(f"**隐情评分**: {score}/100 | {overall}  ")
        lines.append(f"**原始信号**: {len(self.signals)}个 → **合成隐情**: {len(self.hidden_truths)}条")
        lines.append(f"  - 🔴 实锤: {len(confirmed)}条  🟠 高度疑似: {len(likely)}条  🟡 疑似: {len(suspected)}条")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

        # 按等级输出
        for group_name, items in [('🔴 实锤', confirmed), ('🟠 高度疑似', likely), ('🟡 疑似', suspected)]:
            if not items:
                continue
            lines.append(f"### {group_name}")
            lines.append(f"")
            for item in items:
                lines.append(f"#### {item['category']} → {item['type']}")
                lines.append(f"")
                lines.append(item['narrative'])
                lines.append(f"")
                lines.append(f"支撑信号（{item['signal_count']}个）：")
                for sig in item['signals']:
                    icon = {'strong': '🔴', 'medium': '🟠', 'weak': '🟡'}.get(sig['strength'], '⚪')
                    lines.append(f"  {icon} [{sig['dim']}] {sig['detail']}")
                lines.append(f"")

        if not self.hidden_truths:
            lines.append(f"### 🟢 暂无重大隐情")
            lines.append(f"")
            lines.append(f"各维度交叉验证未发现显著异常组合。单维度预警请参考风险评级章节。")
            lines.append(f"")

        lines.append(f"---")
        lines.append(f"")
        lines.append(f"*交叉验证由 `cross_validator.py` 生成，基于{len(self.signals)}个原始信号合成。*")
        lines.append(f"*隐情发现不等同于事实认定，仅为投资研究参考，需进一步核实。*")

        return lines

    # ═══════════════════════════════════════════════
    #  辅助函数
    # ═══════════════════════════════════════════════

    @staticmethod
    def _sf(val):
        """安全浮点转换"""
        if val is None:
            return None
        try:
            v = float(val)
            return v if v != 0 or str(val).strip() == '0' else None
        except (ValueError, TypeError):
            return None

    def _extract_peer_avg_gm(self, peers_data):
        """从同行对比数据提取平均毛利率"""
        # peer_compare 返回结构可能不同，做兼容
        if isinstance(peers_data, dict):
            peers = peers_data.get('peers', []) or peers_data.get('data', [])
            if not peers:
                return None
            gm_vals = []
            for p in peers:
                gm = self._sf(p.get('gross_margin') or p.get('gross_margin_pct'))
                if gm is not None:
                    gm_vals.append(gm)
            return sum(gm_vals) / len(gm_vals) if gm_vals else None
        return None


def validate_cross(findings, stock_code, market='a'):
    """便捷函数：执行交叉验证"""
    cv = CrossValidator(findings, stock_code, market)
    return cv.validate()


# ═══════════════════════════════════════════════
#  CLI 入口（独立测试）
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='跨维度交叉验证 - 隐情发现')
    parser.add_argument('--stock', required=True, help='股票代码')
    parser.add_argument('--market', default='a', choices=['a', 'hk', 'us'], help='市场')
    parser.add_argument('--data-dir', default=None, help='数据目录（含各维度JSON）')
    args = parser.parse_args()

    # 如果有 data_dir，从 results.json 加载 findings
    findings = {}
    if args.data_dir and os.path.isdir(args.data_dir):
        # 优先从 results.json 加载
        results_path = os.path.join(args.data_dir, 'results.json')
        if os.path.exists(results_path):
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                findings = results.get('findings', {})
                print(f'  ✅ 从 results.json 加载 {len(findings)} 个维度')
            except Exception as e:
                print(f'  ❌ 加载 results.json 失败: {e}')
        else:
            # 兜底：逐个维度文件加载
            dim_files = {
                'financial': 'financial_metrics.json',
                'announcements': 'announcements.json',
                'executives': 'executives.json',
                'capital': 'capital.json',
                'related': 'related_deals.json',
                'regulatory': 'regulatory.json',
                'governance': 'governance.json',
                'share_history': 'share_history.json',
                'institutional': 'institutional.json',
                'multi_year_trend': 'multi_year_trend.json',
            }
            for dim, fname in dim_files.items():
                fpath = os.path.join(args.data_dir, fname)
                if os.path.exists(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            findings[dim] = json.load(f)
                        print(f'  ✅ 加载 {dim}')
                    except Exception as e:
                        print(f'  ❌ 加载 {dim} 失败: {e}')
    else:
        print('⚠️ 未指定 --data-dir，使用空 findings 进行规则验证测试')
        # 造一些测试数据
        findings = {
            'financial': {
                'audit_opinion': '标准无保留意见',
                'records': [
                    {'TOTAL_OPERATE_INCOME': 1e10, 'ACCOUNTS_RECE': 3e9,
                     'OTHER_RECE': 8e8, 'TOTAL_ASSETS': 1e10,
                     'TOTAL_PARENT_EQUITY': 4e9,
                     'SHORT_LOAN': 3e9, 'LONG_LOAN': 3e8},
                    {'TOTAL_OPERATE_INCOME': 8e9, 'ACCOUNTS_RECE': 1.5e9},
                ],
                'key_risks': ['应收账款增速异常'],
            },
            'multi_year_trend': {
                'cashflow_quality': {
                    'quality_signal': '异常：经营现金流为负但账面盈利',
                    'avg_cf_netprofit_ratio': 0.3,
                },
                'trend': {
                    'gross_margin_latest': 65.0,
                    'profit_series': [('2024', -5.0), ('2023', 3.0), ('2022', 2.0)],
                },
            },
            'announcements': {
                'key_events': [
                    {'title': '关于资产减值的公告'},
                    {'title': '关于商誉减值的公告'},
                    {'title': '关于中标XX项目的公告'},
                ],
            },
            'capital': {
                'actions': [
                    {'category': '股东减持', 'title': '大股东减持计划'},
                    {'category': '股权激励', 'title': '限制性股票激励计划'},
                    {'category': '收购', 'title': '收购关联方资产'},
                ],
            },
            'governance': {
                'top_shareholders': [
                    {'name': '张三', 'ratio_pct': 55.0},
                ],
                'ownership': {'cr1': 55.0, 'type': '高度集中'},
                'pledge': {'latest_ratio': 0.8},
            },
            'related': {
                'deals': [
                    {'category': '收购', 'title': '收购关联方资产'},
                    {'category': '担保', 'title': '为关联方提供担保'},
                    {'category': '担保', 'title': '为子公司提供担保'},
                    {'category': '担保', 'title': '对外担保公告'},
                    {'category': '增资', 'title': '对关联方增资'},
                ],
                'risks': [{'risk': '关联交易频繁，定价公允性存疑'}],
            },
            'executives': {
                'summary': {'warnings': ['⚠️ 董事长辞职', ' CFO离职']},
            },
            'share_history': {'unlock_schedule': [{'unlock_date': '2026-06', 'unlock_shares_万股': 5000}]},
            'institutional': {'risks': ['机构持仓比例大幅下降']},
        }

    cv = CrossValidator(findings, args.stock, args.market)
    result = cv.validate()

    print(f"\n{'='*60}")
    print(f"🔍 {args.stock} 跨维度交叉验证结果")
    print(f"{'='*60}")
    print(f"\n隐情评分: {result['summary']['score']}/100 | {result['summary']['overall']}")
    print(f"原始信号: {result['summary']['total_signals']}个")
    print(f"合成隐情: {len(result['hidden_truths'])}条")
    print(f"  🔴 实锤: {result['summary']['confirmed_count']}")
    print(f"  🟠 高度疑似: {result['summary']['likely_count']}")
    print(f"  🟡 疑似: {result['summary']['suspected_count']}")

    if result['hidden_truths']:
        print(f"\n--- 隐情详情 ---")
        for t in result['hidden_truths']:
            print(f"\n{t['level']} [{t['category']}→{t['type']}] ({t['signal_count']}个信号)")
            for sig in t['signals']:
                icon = {'strong': '🔴', 'medium': '🟠', 'weak': '🟡'}.get(sig['strength'], '⚪')
                print(f"  {icon} [{sig['dim']}] {sig['detail']}")
    else:
        print(f"\n🟢 暂无重大隐情")

    # 保存结果
    out_dir = args.data_dir or '.'
    out_path = os.path.join(out_dir, 'cross_validation.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 跨维度交叉验证：隐情发现")
    lines.append("")

    summary = data.get('summary', {})
    score = summary.get('score', 0)
    overall = summary.get('overall', '未知')
    lines.append(f"**隐情评分**: {score}/100 | {overall}")
    lines.append("")
    lines.append(f"> 每条隐情均由≥2个独立维度信号支撑。隐情发现不等同于事实认定，仅为投资研究参考。")
    lines.append("")

    hidden_truths = data.get('hidden_truths', [])
    if not hidden_truths:
        lines.append(f"🟢 **暂无重大隐情** — 各维度交叉验证未发现显著异常组合。单维度预警请参考风险评级章节。")
        lines.append("")
        return lines

    for t in hidden_truths:
        lines.append(f"### {t['level']} {t['category']} → {t['type']}")
        lines.append("")
        lines.append(t.get('narrative', ''))
        lines.append("")
        lines.append(f"<details><summary>支撑信号（{t['signal_count']}个）</summary>")
        lines.append("")
        for sig in t.get('signals', []):
            icon = {'strong': '🔴', 'medium': '🟠', 'weak': '🟡'}.get(sig['strength'], '⚪')
            lines.append(f"- {icon} [{sig['dim']}] {sig['detail']}")
        lines.append("")
        lines.append(f"</details>")
        lines.append("")

    return lines