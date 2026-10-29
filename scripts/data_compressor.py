# -*- coding: utf-8 -*-
"""
数据压缩器：将 results.json 压缩为 AI 友好的结构化素材包
目标：从 ~4MB 压缩到 ~40KB，保留所有关键信息，去除冗余
"""
import json
import os
import sys
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result


def compress(results: dict, results_path: str = None) -> dict:
    """
    将 results.json 压缩为 AI 友好的素材包。

    Returns:
        素材包 dict，每个维度保留关键字段，去除冗余
    """
    findings = results.get('findings', {})
    stock = results.get('stock', '')
    market = results.get('market', 'a')
    date = results.get('date', '')

    pack = {
        'meta': {
            'stock': stock,
            'market': market,
            'date': date,
            'company': _get_company_name(findings),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        },
    }

    # 1. 行情快照
    pack['quote'] = _compress_quote(findings.get('quote', {}))

    # 2. 财务数据
    pack['financial'] = _compress_financial(findings.get('financial', {}), findings.get('financial_multiyear', {}))

    # 3. 公告（增强版）
    pack['announcements'] = _compress_announcements(findings)

    # 4. 高管
    pack['executives'] = _compress_executives(findings.get('executives', {}))

    # 5. 股权结构
    pack['structure'] = _compress_structure(findings.get('structure', {}))

    # 6. 子公司
    pack['subsidiary'] = _compress_subsidiary(findings.get('subsidiary', {}), findings.get('valuation', {}))

    # 7. 关联方
    pack['related'] = _compress_related(findings.get('related', {}))

    # 8. 监管
    pack['regulatory'] = _compress_regulatory(findings.get('regulatory', {}))

    # 9. 资金动作
    pack['capital'] = _compress_capital(findings.get('capital', {}))

    # 10. 行业竞争
    pack['industry'] = _compress_industry(findings.get('industry', {}))

    # 11. 风险
    pack['risk'] = _compress_risk(findings.get('risk', {}))

    # 12. 产品产线
    pack['product'] = _compress_product(findings.get('product_line_intro', {}))

    # 13. 商业模式
    pack['business'] = _compress_business(findings.get('business_fetch', {}))

    # 14. 融资结构
    pack['financing'] = _compress_financing(findings.get('financing_structure', {}))

    # 15. 估值
    pack['valuation'] = _compress_valuation(findings.get('valuation', {}))

    # 16. 投资逻辑
    pack['investment'] = _compress_investment(findings.get('investment_thesis', {}))

    # 17. TDX增强数据
    tdx_data = findings.get('tdx', {})
    if tdx_data.get('success'):
        pack['tdx'] = _compress_tdx(tdx_data)

    # 18. 审计意见（含强调事项/关键审计）
    pack['audit'] = _compress_audit(findings.get('financial', {}), findings.get('regulatory', {}))

    # 19. 前十大股东（精简）
    pack['top10'] = _compress_top10(findings.get('structure', {}))

    # 20. 股权质押/冻结
    pack['pledge'] = _compress_pledge(findings.get('structure', {}), findings.get('financing_structure', {}), findings, results_path)

    # 21. 诉讼/仲裁（重大）
    pack['lawsuits'] = _compress_lawsuits(findings.get('announcements', {}))

    # 22. 募集资金/再融资（年报提取）
    pack['fundraising'] = _compress_fundraising(findings, results_path)

    # 23. 历年主要财务指标（多年趋势）
    pack['metrics_trend'] = _compress_metrics_trend(findings.get('financial', {}))

    # 24. 三表详细数据（资产负债表、利润表、现金流量表）
    pack['three_statements'] = _compress_three_statements(
        findings.get('three_statements', {}),
        findings.get('financial_multiyear', {})
    )

    # 25. 审计意见补充（从公告提取强调事项段、关键审计事项）
    _enrich_audit_from_announcements(pack['audit'], findings.get('announcements', {}))

    # 26. 融资结构补充（含货币资金数据）
    _enrich_financing_with_cash(pack['financing'], findings.get('three_statements', {}))

    # 27. 多年财务对比分析（AI预生成内容）
    fms = findings.get('financial_multiyear_summary', '')
    if fms and isinstance(fms, str) and len(fms) > 50:
        pack['financial_summary_ai'] = fms

    # 28. 投资逻辑报告（AI预生成 markdown 全文）
    inv = findings.get('investment_thesis', {})
    if isinstance(inv, dict):
        inv_markdown = inv.get('markdown', '')
        if inv_markdown and isinstance(inv_markdown, str) and len(inv_markdown) > 50:
            pack['investment_markdown'] = inv_markdown
        # 同时补入 structured 字段（标题、催化剂、假设、风险）
        pack['investment'] = {
            'rating': inv.get('investment_rating', ''),
            'thesis': inv.get('thesis', ''),
            'catalysts': inv.get('catalysts', [])[:5],
            'assumptions': inv.get('assumptions', [])[:5],
            'risks': inv.get('risks', [])[:5],
            'target_price': inv.get('target_price'),
        }

    # 29. 同业对比（横向对比表）
    pack['competitors'] = _compress_competitors(findings.get('industry', {}), findings.get('financial', {}), findings.get('product_line_intro', {}))

    # 30. 宏观政策分析（从概念板块、公告、行业信息中提取）
    pack['macro_policy'] = _compress_macro_policy(findings.get('industry', {}), findings.get('announcements', {}), findings.get('product_line_intro', {}))

    # 31. 战略机遇分析（从年报 MD&A、战略定位、业务模式等提取）
    pack['strategic'] = _compress_strategic_opportunity(findings.get('strategic_opportunity', {}), findings.get('industry', {}), findings.get('business_fetch', {}), findings.get('product_line_intro', {}))

    # 32. 价值链 / 产业链分析（从产品线、客户/供应商、业务模式构建）
    pack['value_chain'] = _compress_value_chain(findings.get('strategic_opportunity', {}), findings.get('industry', {}), findings.get('product_line_intro', {}), findings.get('business_fetch', {}), findings.get('three_statements', {}))

    return pack


# ============================================================
# 各维度压缩函数
# ============================================================

def _get_company_name(findings):
    for key in ['industry', 'structure', 'tdx']:
        data = findings.get(key, {})
        name = data.get('company_name', '') or data.get('name', '')
        if name:
            return name
    # 从行情数据中提取
    quote = findings.get('quote', {})
    if quote:
        d = quote.get('data', {})
        if isinstance(d, list):
            d = d[0] if d else {}
        name = d.get('名称') or d.get('name', '')
        if name:
            return name
    return ''


def _compress_quote(quote):
    if not quote or not quote.get('success'):
        return {'status': '无数据'}
    d = quote.get('data', {})
    if isinstance(d, list):
        d = d[0] if d else {}

    # 异常值过滤：PE/PB 超过阈值标记异常
    def _safe_float(v):
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    pe_raw = d.get('市盈率TTM') or d.get('市盈率') or d.get('pe_ttm')
    pb_raw = d.get('市净率') or d.get('pb')
    pe_val = _safe_float(pe_raw)
    pb_val = _safe_float(pb_raw)

    pe_note = ''
    pb_note = ''
    if pe_val is not None:
        if pe_val < 0:
            pe_note = '（亏损，PE为负）'
        elif pe_val > 500:
            pe_note = '（异常高，可能亏损收窄或数据错误）'
        elif pe_val > 200:
            pe_note = '（偏高）'
    if pb_val is not None:
        if pb_val < 0:
            pb_note = '（净资产为负）'
        elif pb_val > 50:
            pb_note = '（异常高）'

    result = {
        '名称': d.get('名称') or d.get('name', ''),
        '最新价': d.get('最新价') or d.get('price') or d.get('买1价'),
        '涨幅': d.get('涨幅') or d.get('change_pct'),
        '成交量': d.get('成交量') or d.get('volume'),
        '成交额': d.get('总金额') or d.get('turnover'),
        '换手率': d.get('换手率'),
        '市盈率TTM': str(pe_raw) + pe_note if pe_raw is not None else None,
        '市净率': str(pb_raw) + pb_note if pb_raw is not None else None,
        '总市值': d.get('总市值') or d.get('total_mv'),
        '流通市值': d.get('流通市值') or d.get('circ_mv'),
        '52周最高': d.get('52周最高') or d.get('最高价'),
        '52周最低': d.get('52周最低') or d.get('最低价'),
        '涨停价': d.get('涨停价'),
        '跌停价': d.get('跌停价'),
        '开盘价': d.get('开盘价') or d.get('开盘涨幅'),
        '昨收价': d.get('昨收价'),
        '总股本': d.get('总股本'),
        '流通股本': d.get('流通股本'),
        '主力净流入': d.get('主力净流入'),
        '量比': d.get('量比'),
        '振幅': d.get('振幅'),
    }
    return result


def _compress_financial(fin, multiyear):
    result = {'records': [], 'multiyear': []}

    # 单期数据 - 按报告期降序排序（新→旧），取最近16期
    records = fin.get('records', []) if isinstance(fin, dict) else fin
    def _get_date(r):
        return (
            r.get('REPORTDATE')
            or r.get('report_date')
            or r.get('报告期')
            or (r.get('summary', {}) if isinstance(r, dict) else {}).get('report_date')
            or ''
        )
    try:
        sorted_records = sorted(records, key=_get_date, reverse=True)
    except Exception:
        sorted_records = list(records)
    for r in sorted_records[:16]:
        # 数据可能在顶层或 summary 子对象中
        s = r.get('summary', {}) if isinstance(r.get('summary'), dict) else r
        result['records'].append({
            'period': r.get('report_date') or r.get('报告期') or r.get('REPORTDATE') or s.get('report_date'),
            'revenue': r.get('revenue') or r.get('revenue_亿') or r.get('TOTAL_OPERATE_INCOME') or s.get('revenue') or s.get('revenue_亿'),
            'net_profit': r.get('net_profit') or r.get('net_profit_亿') or r.get('PARENT_NETPROFIT') or s.get('net_profit') or s.get('net_profit_亿'),
            'eps': r.get('eps') or r.get('BASIC_EPS') or s.get('eps'),
            'roe': r.get('roe') or r.get('roe_pct') or r.get('WEIGHTAVG_ROE') or s.get('roe') or s.get('roe_pct'),
            'gross_margin': r.get('gross_margin') or r.get('gross_margin_pct') or r.get('XSMLL') or s.get('gross_margin') or s.get('gross_margin_pct'),
            'debt_ratio': r.get('debt_ratio') or r.get('资产负债率') or s.get('debt_ratio'),
            'revenue_growth': r.get('revenue_growth') or r.get('revenue_growth_pct') or r.get('YSTZ') or s.get('revenue_growth') or s.get('revenue_growth_pct'),
            'profit_growth': r.get('profit_growth') or r.get('profit_growth_pct') or r.get('SJLTZ') or s.get('profit_growth') or s.get('profit_growth_pct'),
        })

    # 多年数据
    if isinstance(multiyear, dict):
        for year_data in multiyear.get('annual_data', []):
            result['multiyear'].append({
                'year': year_data.get('year') or year_data.get('report_date'),
                'revenue': year_data.get('revenue'),
                'revenue_yi': year_data.get('revenue_yi'),
                'net_profit': year_data.get('net_profit'),
                'net_profit_yi': year_data.get('net_profit_yi'),
                'revenue_yoy': year_data.get('revenue_yoy') or year_data.get('revenue_growth'),
                'profit_yoy': year_data.get('profit_yoy') or year_data.get('profit_growth'),
                'eps': year_data.get('eps'),
                'roe': year_data.get('roe'),
                'gross_margin': year_data.get('gross_margin'),
                'net_margin': year_data.get('net_margin'),
                'debt_ratio': year_data.get('debt_ratio'),
                'bps': year_data.get('bps'),
                'op_cash_ps': year_data.get('op_cash_ps'),
            })

    return result


def _is_recent_5_years(date_str):
    """检查日期是否在最近5年内"""
    try:
        # 解析日期字符串
        if date_str:
            # 尝试多种日期格式
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y年%m月%d日']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    # 计算距今是否小于5年
                    five_years_ago = datetime.now().replace(year=datetime.now().year - 5)
                    return dt >= five_years_ago
                except ValueError:
                    continue
    except Exception as _sexc:
        record(__name__, '_is_recent_5_years', _sexc, note='静默降级')
        pass
    return True  # 默认保留


def _assess_risk_level(risk_signals):
    """评估风险等级"""
    if not isinstance(risk_signals, list):
        return 'medium'
    
    high_keywords = ['重大', '严重', '违规', '处罚', '诉讼', '仲裁', '冻结', '质押', '退市']
    medium_keywords = ['关注', '问询', '提示', '风险', '警告', '异常']
    
    for signal in risk_signals:
        signal_str = str(signal).lower()
        if any(kw in signal_str for kw in high_keywords):
            return 'high'
        if any(kw in signal_str for kw in medium_keywords):
            return 'medium'
    
    return 'low'


def _compress_announcements(findings):
    """压缩公告数据，优先使用增强版，限制最近5年"""
    result = {
        'total': 0, 
        'critical': [], 
        'major': [], 
        'enriched': [],
        'summary_stats': {},  # 汇总统计信息
        'key_events': {       # 关键事件分类
            'spin_off_ipo': [],  # 子公司分拆/IPO
            'asset_restructuring': [],  # 资产重组
            'related_transactions': [],  # 关联交易
            'lawsuits': [],  # 诉讼仲裁
            'guarantees': [],  # 对外担保
            'equity_incentive': [],  # 股权激励
        }
    }

    # 增强版公告
    enriched = findings.get('announcements_enriched', {})
    if enriched:
        result['classification_log'] = enriched.get('classification_log', '')
        stats = enriched.get('stats', {})
        result['stats'] = stats

        # 增强公告（含AI提取）- 过滤最近5年
        for ann in enriched.get('enriched', []):
            date = ann.get('date', '')
            # 时间过滤：内控风险分析只关注最近5年
            if not _is_recent_5_years(date):
                continue
                
            item = {
                'title': ann.get('title', ''),
                'date': date,
                'importance': ann.get('importance', ''),
            }
            ai = ann.get('ai_extracted', {})
            if ai and not ai.get('error'):
                item['event_type'] = ai.get('event_type', '')
                item['key_parties'] = ai.get('key_parties', {})
                item['key_numbers'] = ai.get('key_numbers', {})
                item['key_facts'] = ai.get('key_facts', [])
                item['risk_signals'] = ai.get('risk_signals', [])
                item['impact'] = ai.get('impact_assessment', '')
                
                # 提取关键数字信息
                key_numbers = ai.get('key_numbers', {})
                if isinstance(key_numbers, dict):
                    item['amount'] = key_numbers.get('金额') or key_numbers.get('交易金额') or key_numbers.get('涉及金额')
                    item['ratio'] = key_numbers.get('比例') or key_numbers.get('占比')
                    item['parties'] = key_numbers.get('交易对手') or key_numbers.get('对手方')
                
                # 风险评估
                if ai.get('risk_signals'):
                    item['risk_level'] = _assess_risk_level(ai['risk_signals'])
                    item['risk_detail'] = ai['risk_signals'][:3]
                
                # 分类关键事件
                event_type = ai.get('event_type', '')
                title = ann.get('title', '')
                if '分拆' in title or 'IPO' in title or '上市' in title:
                    result['key_events']['spin_off_ipo'].append(item)
                elif '重组' in title or '资产' in title:
                    result['key_events']['asset_restructuring'].append(item)
                elif '关联' in title:
                    result['key_events']['related_transactions'].append(item)
                elif '诉讼' in title or '仲裁' in title:
                    result['key_events']['lawsuits'].append(item)
                elif '担保' in title:
                    result['key_events']['guarantees'].append(item)
                elif '股权' in title and '激励' in title:
                    result['key_events']['equity_incentive'].append(item)
                    
            result['enriched'].append(item)

        # 仅标题公告 - 过滤最近5年
        recent_titles = []
        for a in enriched.get('title_only', []):
            if _is_recent_5_years(a.get('date', '')):
                recent_titles.append({'title': a.get('title', ''), 'date': a.get('date', '')})
                if len(recent_titles) >= 20:
                    break
        result['title_only_count'] = len(recent_titles)
        result['title_only_recent'] = recent_titles
        result['total'] = stats.get('total', 0)
        
        # 统计各类关键事件数量
        result['summary_stats'] = {
            'spin_off_ipo_count': len(result['key_events']['spin_off_ipo']),
            'asset_restructuring_count': len(result['key_events']['asset_restructuring']),
            'related_transactions_count': len(result['key_events']['related_transactions']),
            'lawsuits_count': len(result['key_events']['lawsuits']),
            'guarantees_count': len(result['key_events']['guarantees']),
            'equity_incentive_count': len(result['key_events']['equity_incentive']),
            'enriched_count': len(result['enriched']),
        }
    else:
        # 无增强数据，用原始数据
        ann_data = findings.get('announcements', {})
        if isinstance(ann_data, dict):
            result['total'] = ann_data.get('count', 0) or ann_data.get('total', 0)
            
            # 关键公告（支持多种键名）
            critical_pool = ann_data.get('critical_announcements', []) or ann_data.get('critical_anns', [])
            for ann in critical_pool[:10]:
                date = ann.get('date', '')
                if not _is_recent_5_years(date):
                    continue
                result['critical'].append({
                    'title': ann.get('title', ''),
                    'date': date,
                    'type': ann.get('type', ''),
                    'key_content': ann.get('extracted_content', {}).get('key_content', '')[:300] if ann.get('extracted_content') else '',
                })
                
                # 分类关键事件（从原始公告标题）
                title = ann.get('title', '')
                if '分拆' in title or 'IPO' in title or '上市' in title:
                    result['key_events']['spin_off_ipo'].append({'title': title, 'date': date})
                elif '关联' in title:
                    result['key_events']['related_transactions'].append({'title': title, 'date': date})
                elif '诉讼' in title or '仲裁' in title:
                    result['key_events']['lawsuits'].append({'title': title, 'date': date})
                elif '担保' in title:
                    result['key_events']['guarantees'].append({'title': title, 'date': date})
            
            # 近期公告
            for ann in ann_data.get('recent_30', [])[:15]:
                date = ann.get('date', '')
                if not _is_recent_5_years(date):
                    continue
                result['major'].append({
                    'title': ann.get('title', ''),
                    'date': date,
                    'importance': ann.get('importance', ''),
                })
            
            # 更新统计
            result['summary_stats'] = {
                'spin_off_ipo_count': len(result['key_events']['spin_off_ipo']),
                'asset_restructuring_count': len(result['key_events']['asset_restructuring']),
                'related_transactions_count': len(result['key_events']['related_transactions']),
                'lawsuits_count': len(result['key_events']['lawsuits']),
                'guarantees_count': len(result['key_events']['guarantees']),
                'equity_incentive_count': len(result['key_events']['equity_incentive']),
                'enriched_count': len(result['enriched']),
            }

    return result


def _compress_executives(execs):
    if not execs:
        return {'status': '无数据'}
    result = {
        'changes_count': len(execs.get('changes', [])),
        'changes': [],
        'current': [],
    }
    for c in execs.get('changes', [])[:15]:
        result['changes'].append({
            'name': c.get('姓名') or c.get('name', ''),
            'position': c.get('职务') or c.get('position', ''),
            'change': c.get('变动类型') or c.get('change_type', ''),
            'date': c.get('变动日期') or c.get('date', ''),
            'reason': c.get('变动原因') or c.get('reason', ''),
        })
    for p in execs.get('current', [])[:20]:
        result['current'].append({
            'name': p.get('姓名') or p.get('name', ''),
            'position': p.get('职务') or p.get('position', ''),
            'age': p.get('年龄') or p.get('age', ''),
            'education': p.get('学历') or p.get('education', ''),
            'salary': p.get('薪酬') or p.get('salary', ''),
            'shares': p.get('持股数') or p.get('shares', ''),
        })
    # TDX高管
    tdx_exec = execs.get('tdx_executives', {})
    if tdx_exec:
        result['tdx'] = tdx_exec
    return result


def _compress_structure(struct):
    if not struct:
        return {'status': '无数据'}
    result = {
        'actual_controller': struct.get('actual_controller', {}),
        'top10': [],
        'total_shares': struct.get('total_shares', ''),
    }
    raw = (struct.get('structure', {}).get('top10') or struct.get('top_shareholders') or struct.get('top10') or []) if isinstance(struct, dict) else []
    if isinstance(raw, list):
        for s in raw[:10]:
            if isinstance(s, dict):
                result['top10'].append({
                    'name': s.get('name') or s.get('股东名称'),
                    'shares': s.get('shares') or s.get('持股数'),
                    'ratio_pct': s.get('ratio_pct') or s.get('持股比例') or s.get('ratio'),
                    'type': s.get('type') or s.get('股份性质') or s.get('股东性质'),
                })
    return result


def _compress_subsidiary(sub, valuation):
    result = {'subsidiaries': [], 'from_valuation': []}
    for s in sub.get('subsidiaries', [])[:10]:
        result['subsidiaries'].append({
            'name': s.get('公司名称') or s.get('name', ''),
            'business': s.get('主营业务') or s.get('business', ''),
            'capital': s.get('注册资本') or s.get('capital', ''),
            'ratio': s.get('持股比例') or s.get('ratio', ''),
        })
    # 从估值维度补充子公司
    if valuation:
        for seg in valuation.get('segments', []):
            result['from_valuation'].append({
                'name': seg.get('name', ''),
                'ev': seg.get('ev', ''),
                'method': seg.get('method', ''),
            })
    return result


def _compress_related(related):
    if not related:
        return {'status': '无数据'}
    deals = related.get('deals', [])
    if not isinstance(deals, list):
        deals = []
    result = {
        'count': len(deals),
        'deals': [],
    }
    for d in deals[:15]:
        if not isinstance(d, dict):
            continue
        title = d.get('title', '')
        keywords = d.get('keywords', [])
        if isinstance(keywords, list):
            keywords_str = ','.join(keywords)
        else:
            keywords_str = str(keywords)
        item = {
            'date': d.get('date', ''),
            'title': title,
            'type': d.get('type', '') or d.get('交易类型', ''),
            'keywords': keywords_str,
            'risk_signal': d.get('risk', ''),
            'art_code': d.get('art_code', ''),
        }
        result['deals'].append(item)
    return result


def _compress_regulatory(reg):
    if not reg:
        return {'status': '无数据'}
    return {
        'count': len(reg.get('records', [])),
        'records': [{
            'date': r.get('日期') or r.get('date', ''),
            'type': r.get('类型') or r.get('type', ''),
            'source': r.get('来源') or r.get('source', ''),
            'severity': r.get('严重程度') or r.get('severity', ''),
            'detail': r.get('内容摘要') or r.get('detail', '')[:200],
        } for r in reg.get('records', [])[:10]],
    }


def _compress_capital(cap):
    if not cap:
        return {'status': '无数据'}
    return {
        'count': len(cap.get('actions', [])),
        'actions': [{
            'type': a.get('类型') or a.get('type', ''),
            'date': a.get('日期') or a.get('date', ''),
            'title': a.get('标题') or a.get('title', '')[:80],
            'amount': a.get('金额') or a.get('amount', ''),
            'risk': a.get('风险信号') or a.get('risk', ''),
        } for a in cap.get('actions', [])[:15]],
    }


def _compress_industry(ind):
    if not ind:
        return {'status': '无数据'}
    return {
        'industry_name': ind.get('industry_name', ''),
        'company_name': ind.get('company_name', ''),
        'main_business': ind.get('main_business', '')[:500],
        'competitors': [{
            'code': c.get('code', ''),
            'name': c.get('name', ''),
            'main_business': c.get('main_business', '')[:200],
        } for c in ind.get('competitors', [])[:10]],
    }


def _compress_risk(risk):
    if not risk:
        return {'status': '无数据'}
    return {
        'score': risk.get('score', 0),
        'level': risk.get('level', ''),
        'signals': [{
            'type': s.get('类型') or s.get('type', ''),
            'severity': s.get('严重程度') or s.get('severity', ''),
            'detail': s.get('内容') or s.get('detail', '')[:200],
        } for s in risk.get('signals', [])[:10]],
    }


def _compress_product(prod):
    if not prod:
        return {'status': '无数据'}
    rev = prod.get('revenue_structure', [])
    if isinstance(rev, dict):
        rev = [{'name': k, 'value': v} for k, v in rev.items()]
    return {
        'main_business': prod.get('main_business', '')[:500],
        'products': prod.get('products', [])[:10],
        'product_lines': prod.get('product_lines', [])[:10],
        'production_bases': prod.get('production_bases', [])[:5],
        'revenue_structure': rev[:10] if isinstance(rev, list) else [],
    }


def _compress_business(biz):
    if not biz:
        return {'status': '无数据'}
    result = {}
    for key in ['brand', 'products', 'industry', 'summary']:
        val = biz.get(key, '')
        if val:
            result[key] = str(val)[:500] if not isinstance(val, dict) else {k: str(v)[:300] for k, v in val.items()}
    return result if result else {'status': '无数据'}


def _compress_financing(fin):
    if not fin:
        return {'status': '无数据'}
    def _safe_str(v, limit=100):
        if isinstance(v, dict):
            return {kk: str(vv)[:limit] for kk, vv in v.items()}
        return str(v)[:limit] if v else ''

    result = {
        'capital_structure': {k: _safe_str(v) for k, v in fin.get('capital_structure', {}).items()},
        'notes': str(fin.get('notes', ''))[:1000],
        'details': [{
            'type': d.get('类型') or d.get('type', ''),
            'amount': d.get('金额') or d.get('amount', ''),
            'date': d.get('日期') or d.get('date', ''),
        } for d in fin.get('details', [])[:20]],
        'pledge_detail': fin.get('pledge_detail', ''),
        'convertible_bonds': fin.get('convertible_bonds', []),
        'additional_issues': fin.get('additional_issues', []),
        'corporate_bonds': fin.get('corporate_bonds', []),
        'guarantee_chain': fin.get('guarantee_chain', []),
    }
    return result


def _compress_valuation(val):
    if not val:
        return {'status': '无数据'}
    return {
        'total_ev': val.get('total_ev', ''),
        'discount': val.get('discount', ''),
        'method': val.get('method', ''),
        'segments': [{
            'name': s.get('name', ''),
            'ev': s.get('ev', ''),
            'method': s.get('method', ''),
            'detail': str(s.get('detail', ''))[:200],
        } for s in val.get('segments', [])[:8]],
    }


def _compress_investment(inv):
    if not inv:
        return {'status': '无数据'}
    return {
        'rating': inv.get('rating', ''),
        'thesis': inv.get('thesis', '')[:1000],
        'catalysts': inv.get('catalysts', [])[:5],
        'risks': inv.get('risks', [])[:5],
        'assumptions': inv.get('assumptions', [])[:5],
    }


def _compress_tdx(tdx):
    result = {'success': True}
    info = tdx.get('basic_info', {})
    if info:
        result['company'] = {
            'name': info.get('公司名称', ''),
            'industry': info.get('行业', ''),
            'listing_date': info.get('上市日期', ''),
            'total_shares': info.get('总股本', ''),
            'circ_shares': info.get('流通股', ''),
        }
    products = tdx.get('product_structure', [])
    if products:
        result['products'] = products[:8]
    executives = tdx.get('executives', [])
    if executives:
        result['executives'] = executives[:10]
    structure = tdx.get('share_structure', {})
    if structure:
        result['share_structure'] = {
            'total': structure.get('总股本', ''),
            'circ': structure.get('流通股', ''),
            'date': structure.get('截止日期', ''),
        }
    return result


# ============================================================
# 主入口
# ============================================================

def compress_to_file(results: dict, output_path: str, results_path: str = None) -> str:
    """压缩并保存到文件"""
    pack = compress(results, results_path=results_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(pack, f, ensure_ascii=False, indent=2, default=str)

    # 统计
    raw_size = len(json.dumps(results, ensure_ascii=False, default=str))
    compressed_size = len(json.dumps(pack, ensure_ascii=False, default=str))
    ratio = compressed_size / raw_size * 100 if raw_size > 0 else 0

    print(f'  [压缩] 原始: {raw_size//1024}KB → 压缩后: {compressed_size//1024}KB ({ratio:.1f}%)')
    return output_path


def _read_annual_text(findings, results_path=None):
    """读取年报纯文本（用于补充关键章节提取）"""
    path = (
        findings.get('annual_pdf', {}).get('text_path')
        or findings.get('annual_report_text_path')
        or ''
    )
    if not path:
        # 尝试从 pdf_path 推断 text 路径
        pdf_path = findings.get('annual_pdf', {}).get('pdf_path', '')
        if pdf_path:
            # pdf_path: .../data/2025_annual_report.pdf -> .../data/annual_report_text.txt
            data_dir = os.path.dirname(pdf_path)
            candidate = os.path.join(data_dir, 'annual_report_text.txt')
            if os.path.exists(candidate):
                path = candidate
            else:
                # 可能路径不一致（scripts/output vs output），尝试修正
                # 从 results_path 推断
                if results_path:
                    results_dir = os.path.dirname(results_path)
                    candidate2 = os.path.join(results_dir, 'annual_report_text.txt')
                    if os.path.exists(candidate2):
                        path = candidate2
    if not path or not os.path.exists(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def _extract_annual_segment(text, start_keyword, end_keywords):
    if not text or not start_keyword:
        return ''
    idx = text.find(start_keyword)
    if idx == -1:
        return ''
    chunk = text[idx:idx+6000]
    for kw in end_keywords:
        pos = chunk.find(kw, len(start_keyword))
        if pos != -1:
            return chunk[:pos]
    return chunk


def _compress_audit(fin, reg):
    fin = fin if isinstance(fin, dict) else {}
    reg = reg if isinstance(reg, dict) else {}
    result = {
        'opinion': fin.get('audit_opinion', ''),
        'auditor': fin.get('auditor', ''),
        'internal_control_opinion': fin.get('internal_control_opinion', ''),
        'emphasis': [],
        'key_audit_matters': [],
        'regulatory_hits': [],
    }
    for r in reg.get('records', [])[:10]:
        result['regulatory_hits'].append({
            'date': r.get('日期') or r.get('date', ''),
            'type': r.get('类型') or r.get('type', ''),
            'source': r.get('来源') or r.get('source', ''),
            'detail': str(r.get('内容摘要') or r.get('detail', ''))[:200],
        })
    return result


def _compress_top10(struct):
    struct = struct if isinstance(struct, dict) else {}
    raw = (struct.get('structure', {}).get('top10') or struct.get('top_shareholders') or struct.get('top10') or []) if isinstance(struct, dict) else []
    result = []
    if isinstance(raw, list):
        for s in raw[:10]:
            if isinstance(s, dict):
                result.append({
                    'name': s.get('name') or s.get('股东名称'),
                    'shares': s.get('shares') or s.get('持股数'),
                    'ratio_pct': s.get('ratio_pct') or s.get('持股比例') or s.get('ratio'),
                    'type': s.get('type') or s.get('股份性质') or s.get('股东性质'),
                })
    return result


def _compress_pledge(struct, fin, findings=None, results_path=None):
    struct = struct if isinstance(struct, dict) else {}
    fin = fin if isinstance(fin, dict) else {}
    pledge = {
        'controlling_shareholder_pledge': struct.get('controlling_shareholder_pledge', ''),
        'pledge_detail': fin.get('pledge_detail', ''),
        'pledge_warnings': fin.get('pledge_warnings', []),
        'freeze_warnings': fin.get('freeze_warnings', []),
        'annual_report_pledge': '',
    }

    # 从年报文本中抽取质押/冻结信息
    if findings:
        annual_text = _read_annual_text(findings, results_path)
        if annual_text:
            # 尝试多种起始关键词
            start_keywords = [
                '控股股东截至本报告披露日的股票质押情况',
                '股份质押情况',
                '控股股东股份质押',
                '股票质押情况',
            ]
            pledge_seg = ''
            for kw in start_keywords:
                pledge_seg = _extract_annual_segment(
                    annual_text,
                    kw,
                    ['股份冻结情况', '十八、', '第六节', '五、', '六、', '（三）', '三、']
                )
                if pledge_seg:
                    break

            if not pledge_seg:
                # 直接搜索包含"质押"的段落
                import re
                matches = list(re.finditer(r'质押.{0,2000}', annual_text))
                if matches:
                    # 合并前5个匹配，优先选择包含"控股股东"或"赛纳科技"的
                    sorted_matches = sorted(matches, key=lambda m: (
                        '控股股东' in m.group() or '赛纳科技' in m.group(),
                        m.start()
                    ), reverse=True)
                    pledge_seg = '\n'.join(m.group()[:800] for m in sorted_matches[:5])
            if pledge_seg:
                pledge['annual_report_pledge'] = pledge_seg[:3500]

    return pledge


def _compress_lawsuits(announcements):
    announcements = announcements if isinstance(announcements, dict) else {}
    result = []
    critical = announcements.get('critical_announcements', []) or []
    for ann in critical[:10]:
        title = ann.get('title', '')
        if '诉讼' in title or '仲裁' in title or '赔偿' in title:
            item = {
                'date': ann.get('date', ''),
                'title': title,
                'art_code': ann.get('art_code', ''),
            }
            extracted = ann.get('extracted_content', {}) or {}
            if extracted:
                item['key_facts'] = extracted.get('key_facts', [])[:5]
                item['full_text_preview'] = str(extracted.get('full_text_preview', ''))[:1500]
            result.append(item)
    return result


def _compress_fundraising(findings, results_path=None):
    financing = findings.get('financing_structure', {}) or {}
    annual_text = _read_annual_text(findings, results_path)
    fundraising = {
        'notes': str(financing.get('notes', ''))[:1000],
        'annual_report_segments': {},
    }
    segments = {
        '总体使用情况': _extract_annual_segment(annual_text, '募集资金总体使用情况', ['募集资金承诺项目情况', '3、募集资金变更项目情况']),
        '承诺项目情况': _extract_annual_segment(annual_text, '2、募集资金承诺项目情况', ['3、募集资金变更项目情况', '4、']),
        '变更项目情况': _extract_annual_segment(annual_text, '3、募集资金变更项目情况', ['4、', '（十六）', '十六、其他重大事项的说明']),
    }
    for k, v in segments.items():
        if v:
            fundraising['annual_report_segments'][k] = v[:3500]
    return fundraising


def _compress_metrics_trend(fin):
    fin = fin if isinstance(fin, dict) else {}
    records = fin.get('records', []) if isinstance(fin, dict) else fin
    # 按报告期降序排序（新→旧），取最近16期
    def _get_date(r):
        return (
            r.get('REPORTDATE')
            or r.get('report_date')
            or r.get('报告期')
            or (r.get('summary', {}) if isinstance(r, dict) else {}).get('report_date')
            or ''
        )
    try:
        sorted_records = sorted(records, key=_get_date, reverse=True)
    except Exception:
        sorted_records = list(records)
    result = []
    for r in sorted_records[:16]:
        s = r.get('summary', {}) if isinstance(r.get('summary'), dict) else r
        item = {
            'period': r.get('report_date') or r.get('报告期') or r.get('REPORTDATE') or s.get('report_date'),
            'revenue': r.get('revenue') or r.get('revenue_亿') or r.get('TOTAL_OPERATE_INCOME') or s.get('revenue') or s.get('revenue_亿'),
            'net_profit': r.get('net_profit') or r.get('net_profit_亿') or r.get('PARENT_NETPROFIT') or s.get('net_profit') or s.get('net_profit_亿'),
            'eps': r.get('eps') or r.get('BASIC_EPS') or s.get('eps'),
            'roe': r.get('roe') or r.get('roe_pct') or r.get('WEIGHTAVG_ROE') or s.get('roe') or s.get('roe_pct'),
            'gross_margin': r.get('gross_margin') or r.get('gross_margin_pct') or r.get('XSMLL') or s.get('gross_margin') or s.get('gross_margin_pct'),
            'debt_ratio': r.get('debt_ratio') or r.get('资产负债率') or s.get('debt_ratio'),
            'bps': r.get('bps') or r.get('BPS') or s.get('bps'),
            'op_cash_ps': r.get('op_cash_ps') or r.get('MGJYXJJE') or s.get('op_cash_ps'),
        }
        result.append(item)
    return result


def _compress_three_statements(ts, multiyear):
    """从三表数据提取关键财务指标（资产负债表、利润表、现金流量表）"""
    result = {
        'balance_sheet': {},
        'income_statement': {},
        'cash_flow': {},
        'summary': {},
    }
    if not isinstance(ts, dict):
        return result

    def _get_value_from_rows(rows_list, item_name, col_idx=1):
        """从 rows 数组中查找对应项的金额"""
        if not isinstance(rows_list, list):
            return None
        for row in rows_list:
            if isinstance(row, list) and len(row) > col_idx and row[0] == item_name:
                val = row[col_idx]
                try:
                    return float(str(val).replace(',', ''))
                except (ValueError, TypeError):
                    return None
        return None

    def _get_value_from_dict(d, item_name):
        """从 dict 结构中查找（值为 [期末, 期初] 数组）"""
        val = d.get(item_name)
        if isinstance(val, list) and len(val) >= 1:
            try:
                return float(val[0])
            except (ValueError, TypeError):
                return None
        return None

    # ========== 1. 资产负债表 ==========
    balance = ts.get('balance_sheet', {})
    if isinstance(balance, dict):
        assets = balance.get('assets', {})
        if not isinstance(assets, dict):
            assets = {}
        rows = balance.get('rows', [])

        key_assets = [
            '货币资金', '交易性金融资产', '应收票据', '应收账款',
            '应收款项融资', '预付款项', '其他应收款', '存货',
            '合同资产', '持有待售资产', '一年内到期的非流动资产',
            '其他流动资产', '流动资产合计', '债权投资',
            '其他债权投资', '长期应收款', '长期股权投资',
            '其他权益工具投资', '其他非流动金融资产',
            '投资性房地产', '固定资产', '在建工程',
            '使用权资产', '无形资产', '开发支出',
            '商誉', '长期待摊费用', '递延所得税资产',
            '其他非流动资产', '非流动资产合计',
        ]

        for item in key_assets:
            v = _get_value_from_dict(assets, item)
            if v is None:
                v = _get_value_from_rows(rows, item)
            if v is not None:
                result['balance_sheet'][item] = round(v / 1e8, 2)

        # 负债部分
        liabilities = balance.get('liabilities', {})
        if isinstance(liabilities, dict):
            key_liabilities = [
                '短期借款', '交易性金融负债', '应付票据', '应付账款',
                '合同负债', '应付职工薪酬', '应交税费', '其他应付款',
                '一年内到期的非流动负债', '其他流动负债',
                '流动负债合计', '长期借款', '应付债券', '租赁负债',
                '递延收益', '递延所得税负债', '其他非流动负债',
                '非流动负债合计', '负债合计',
            ]
            for item in key_liabilities:
                v = _get_value_from_dict(liabilities, item)
                if v is None:
                    v = _get_value_from_rows(rows, item)
                if v is not None:
                    result['balance_sheet'][item] = round(v / 1e8, 2)

        # 权益部分
        equity = balance.get('equity', {})
        if isinstance(equity, dict):
            key_equity = [
                '实收资本(或股本)', '资本公积', '其他权益工具', '减：库存股',
                '其他综合收益', '专项储备', '盈余公积', '一般风险准备',
                '未分配利润', '归属于母公司股东权益合计', '少数股东权益',
                '股东权益合计',
            ]
            for item in key_equity:
                v = _get_value_from_dict(equity, item)
                if v is None:
                    v = _get_value_from_rows(rows, item)
                if v is not None:
                    result['balance_sheet'][item] = round(v / 1e8, 2)

        total_assets = balance.get('total_assets')
        if total_assets:
            try:
                result['summary']['total_assets_亿'] = round(float(total_assets) / 1e8, 2)
            except (ValueError, TypeError):
                pass

    # ========== 2. 利润表 ==========
    income = ts.get('income_statement', {})
    if isinstance(income, dict):
        inc_items = income.get('items', {})
        inc_rows = income.get('rows', [])
        inc_revenue = income.get('revenue')
        if isinstance(inc_revenue, list) and len(inc_revenue) >= 1:
            result['income_statement']['营业收入_本期'] = round(float(inc_revenue[0]) / 1e8, 2)

        key_income = [
            '营业收入', '营业成本', '税金及附加', '销售费用',
            '管理费用', '研发费用', '财务费用', '资产减值损失',
            '信用减值损失', '公允价值变动收益', '投资收益',
            '资产处置收益', '其他收益', '营业利润', '营业外收入',
            '营业外支出', '利润总额', '所得税费用', '净利润',
            '其中：归属于母公司所有者的净利润',
            '基本每股收益', '稀释每股收益',
        ]
        for item in key_income:
            v = _get_value_from_dict(inc_items, item)
            if v is None:
                v = _get_value_from_rows(inc_rows, item)
            if v is not None:
                result['income_statement'][item] = round(float(v) / 1e8, 2) if abs(float(v)) >= 1e6 else round(float(v), 4)

        # 计算毛利率
        rev = result['income_statement'].get('营业收入', None)
        cost = result['income_statement'].get('营业成本', None)
        if rev and cost and rev > 0:
            result['income_statement']['毛利率_percent'] = round((rev - cost) / rev * 100, 2)

    # ========== 3. 从 multiyear 补充汇总数据 ==========
    if isinstance(multiyear, dict):
        annual = multiyear.get('annual', {})
        if isinstance(annual, dict) and annual:
            latest_year = max(annual.keys())
            if isinstance(annual.get(latest_year), dict):
                data = annual[latest_year]
                for key in ['revenue', 'net_profit', 'total_assets', 'total_equity']:
                    if key in data:
                        try:
                            result['summary'][f'{key}_亿'] = round(float(data[key]) / 1e8, 2)
                        except (ValueError, TypeError):
                            pass

    return result


def _enrich_audit_from_announcements(audit, announcements):
    """从公告数据中提取审计意见、强调事项段、关键审计事项"""
    if not isinstance(audit, dict):
        return
    if not isinstance(announcements, dict):
        return

    critical = announcements.get('critical_announcements', [])
    if not isinstance(critical, list):
        return

    emphasis_items = []
    key_audit_matters = []
    auditor_name = audit.get('auditor', '')

    for ann in critical:
        if not isinstance(ann, dict):
            continue
        title = ann.get('title', '')
        extracted = ann.get('extracted_content', {}) if isinstance(ann.get('extracted_content'), dict) else {}

        is_audit_related = any(keyword in title for keyword in [
            '审计报告', '带强调事项段', '审计意见', '专项说明',
            '非标准', '非标', '内部控制', '立信', '普华永道',
            '德勤', '毕马威', '安永', '天职国际', '大华',
        ])

        if not is_audit_related:
            continue

        if '强调' in title or '审计报告' in title or '专项说明' in title:
            text_preview = extracted.get('full_text_preview', '')
            if text_preview:
                # 提取强调事项段
                if '强调事项' in text_preview or '解释性说明' in text_preview:
                    emphasis_items.append({
                        'date': ann.get('date', ''),
                        'title': title,
                        'content': str(text_preview)[:2000],
                    })

                # 提取审计机构名称
                for auditor in ['立信会计师事务所', '普华永道', '德勤华永', '毕马威华振',
                                '安永华明', '天职国际', '大华会计师事务所', '天健会计师事务所']:
                    if auditor in text_preview:
                        if not auditor_name:
                            auditor_name = auditor
                        break

                # 提取关键审计事项
                if '关键审计事项' in text_preview:
                    key_audit_matters.append({
                        'date': ann.get('date', ''),
                        'title': title,
                        'content': str(text_preview)[:1500],
                    })

    if emphasis_items:
        audit['emphasis'] = emphasis_items[:3]
    if key_audit_matters:
        audit['key_audit_matters'] = key_audit_matters[:3]
    if auditor_name and not audit.get('auditor'):
        audit['auditor'] = auditor_name


def _enrich_financing_with_cash(financing, three_statements):
    """将货币资金数据补充到融资结构，用于计算净负债率"""
    if not isinstance(financing, dict):
        return
    if not isinstance(three_statements, dict):
        return

    balance = three_statements.get('balance_sheet', {})
    if isinstance(balance, dict):
        assets = balance.get('assets', {})
        cash_val = None
        if isinstance(assets, dict):
            cash = assets.get('货币资金')
            if isinstance(cash, list) and len(cash) >= 1:
                try:
                    cash_val = round(float(cash[0]) / 1e8, 2)
                except (ValueError, TypeError):
                    pass

        if cash_val is None:
            rows = balance.get('rows', [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list) and len(row) >= 2 and row[0] == '货币资金':
                        try:
                            cash_val = round(float(str(row[1]).replace(',', '')) / 1e8, 2)
                        except (ValueError, TypeError):
                            pass
                        break

        if cash_val is not None:
            financing['cash_and_cash_equivalents_亿'] = cash_val

            # 计算净负债
            interest_bearing = None
            ib_debt = financing.get('capital_structure', {}) if isinstance(financing.get('capital_structure'), dict) else {}
            if ib_debt.get('interest_bearing_debt_yi'):
                try:
                    interest_bearing = float(ib_debt['interest_bearing_debt_yi'])
                except (ValueError, TypeError):
                    pass
            if interest_bearing is not None:
                net_debt = round(interest_bearing - cash_val, 2)
                financing['net_debt_亿'] = net_debt
                total_equity = ib_debt.get('total_equity_yi')
                if total_equity:
                    try:
                        eq = float(total_equity)
                        if eq > 0:
                            financing['net_debt_ratio_pct'] = round(net_debt / eq * 100, 2)
                    except (ValueError, TypeError):
                        pass


# ============================================================
# 29. 同业对比（横向对比表）
# ============================================================

def _compress_competitors(industry, financial, product_line_intro):
    """从 industry.competitors 提取同业公司基本信息，结合自身财务指标构建对比表"""
    result = {
        'industry_class': {},
        'company_benchmark': {},
        'peers': [],
        'summary_text': '',
    }

    # 行业分类
    if isinstance(industry, dict):
        ic = industry.get('industry_class')
        if isinstance(ic, dict):
            result['industry_class'] = {
                'csrc': ic.get('csrc_industry', ''),
                'board_l1': ic.get('board_l1', ''),
                'board_l2': ic.get('board_l2', ''),
                'board_l3': ic.get('board_l3', ''),
                'em': ic.get('em_industry', ''),
                'region': ic.get('region', ''),
                'bk_code': ic.get('board_code_bk', ''),
            }

        # 自身基准
        findings = industry.get('findings', {})
        if isinstance(findings, dict):
            result['company_benchmark'] = {
                'name': findings.get('SECURITY_NAME_ABBR', ''),
                'main_business_raw': findings.get('main_business_raw', ''),
                'gross_profit_ratio_pct': findings.get('gross_profit_ratio'),
                'max_profit_product': findings.get('max_profit_product', ''),
                'income_stru_name': findings.get('income_stru_name', ''),
                'income_stru_ratio_pct': findings.get('income_stru_ratio', ''),
                'total_employees': findings.get('total_employees'),
                'reg_capital_万元': findings.get('reg_capital'),
                'concepts': findings.get('concepts_raw', ''),
                'former_names': findings.get('former_names', ''),
                'listing_date': findings.get('listing_date', ''),
            }

        # 同业公司
        comps = industry.get('competitors', [])
        if isinstance(comps, list):
            for c in comps:
                if not isinstance(c, dict):
                    continue
                result['peers'].append({
                    'code': c.get('code', ''),
                    'name': c.get('name', ''),
                    'csrc_industry': c.get('csrc_industry', ''),
                    'main_business': (c.get('main_business', '') or '')[:200],
                })

    # 产品线营收占比（作为补充）
    if isinstance(product_line_intro, dict):
        tdx_prods = product_line_intro.get('tdx_products', [])
        if isinstance(tdx_prods, list):
            structured = []
            for p in tdx_prods:
                if isinstance(p, dict):
                    structured.append({
                        'name': p.get('name', ''),
                        'revenue_ratio_pct': round(float(p.get('revenue_ratio') or 0) * 100, 2),
                        'compare_ratio_pct': round(float(p.get('compare_ratio') or 0) * 100, 2),
                    })
            if structured:
                result['company_benchmark']['revenue_structure'] = structured

    # 汇总文本
    parts = []
    if result['peers']:
        names = '、'.join([p['name'] for p in result['peers'][:8]])
        parts.append(f'同板块{len(result["peers"])}家公司：{names}')
    if result['company_benchmark'].get('gross_profit_ratio_pct'):
        parts.append(f'自身毛利率基准约{result["company_benchmark"]["gross_profit_ratio_pct"]}%')
    result['summary_text'] = '；'.join(parts)

    return result


# ============================================================
# 30. 宏观政策分析
# ============================================================

def _compress_macro_policy(industry, announcements, product_line_intro):
    """从概念板块、主营业务、公告中提取宏观/行业政策线索"""
    result = {
        'concept_tags': [],
        'industry_policy_hints': [],
        'policy_relevant_announcements': [],
        'regional_economic_hints': [],
        'summary_text': '',
    }

    # 1) 概念板块 —— 映射政策方向
    if isinstance(industry, dict):
        findings = industry.get('findings', {})
        if isinstance(findings, dict):
            raw = findings.get('concepts_raw', '') or ''
            if isinstance(raw, str) and raw:
                tags = [t.strip() for t in raw.replace('、', ',').replace('；', ',').replace(';', ',').split(',') if t.strip()]
                result['concept_tags'] = list(dict.fromkeys(tags))  # 去重保序

    # 2) 行业政策线索（从概念/业务推断）
    policy_map = {
        '国产芯片': '半导体国产化/自主可控政策利好',
        '国产软件': '信创/国产替代政策利好',
        '信创': '信息技术应用创新（信创）产业政策',
        '网络安全': '《网络安全法》《数据安全法》监管趋严',
        '汽车芯片': '新能源汽车/智能网联汽车产业链政策',
        '物联网': '物联网/数字经济产业规划',
        '人工智能': '人工智能产业规划（算力/算法/数据）',
        '人形机器人': '人形机器人/具身智能产业支持政策',
        '新能源': '新能源产业规划（风光储/新能源汽车）',
        '半导体概念': '半导体产业大基金/先进制造政策',
        '融资融券': '融资标的，市场关注度较高',
        '深股通': '北向资金可投标的，跨境资金流动敏感',
        'MSCI中国': '国际指数纳入，外资配置相关',
        '标准普尔': '国际指数纳入，外资配置相关',
        '富时罗素': '国际指数纳入，外资配置相关',
        '养老金': '养老基金/长期资金入市标的',
        '中盘股': '中等市值，流动性尚可',
        '深成500': '核心指数成分股',
        '智能电网': '能源互联网/电力数字化政策',
        '破增发价股': '估值折让信号',
        '中盘价值': '价值风格偏好',
        '昨日高振幅': '短期波动较大，需关注风险',
    }
    for tag in result['concept_tags']:
        if tag in policy_map:
            result['industry_policy_hints'].append({'tag': tag, 'policy_hint': policy_map[tag]})

    # 3) 相关公告（搜索"政策"/"监管"/"行业"关键词）
    policy_kw = ['政策', '监管', '产业', '行业', '法规', '通知', '指导']
    if isinstance(announcements, dict):
        # 从关键事件/重要公告中搜索
        for pool_name in ['critical_announcements', 'major_announcements', 'key_events', 'recent_30']:
            pool = announcements.get(pool_name, [])
            if not isinstance(pool, list):
                continue
            for item in pool:
                if not isinstance(item, dict):
                    continue
                title = str(item.get('title', ''))
                if any(kw in title for kw in policy_kw):
                    result['policy_relevant_announcements'].append({
                        'date': item.get('date', ''),
                        'title': title[:120],
                        'type': item.get('type', ''),
                    })
                    if len(result['policy_relevant_announcements']) >= 10:
                        break
            if len(result['policy_relevant_announcements']) >= 10:
                break

    # 4) 区域经济（从 region 推断）
    if isinstance(industry, dict):
        ic = industry.get('industry_class', {})
        if isinstance(ic, dict):
            region = ic.get('region', '')
            if region:
                result['regional_economic_hints'].append(
                    f'注册地：{region}，关注区域产业集群政策（如粤港澳大湾区/广东省制造业升级）')

    # 5) 汇总
    summary_parts = []
    if result['concept_tags']:
        summary_parts.append(f'涉及{len(result["concept_tags"])}个概念板块，政策相关标签：{"/".join([p["tag"] for p in result["industry_policy_hints"]][:5]) or "无"}')
    if result['policy_relevant_announcements']:
        summary_parts.append(f'相关公告{len(result["policy_relevant_announcements"])}条')
    result['summary_text'] = '；'.join(summary_parts)

    return result


# ============================================================
# 31. 战略机遇分析
# ============================================================

def _compress_strategic_opportunity(strategic, industry, business_fetch, product_line_intro):
    """从 strategic_opportunity.dimensions + industry.findings + product_line_intro 中聚合战略信息"""
    result = {
        'strategic_positioning': {},
        'business_model': {},
        'product_matrix': {},
        'supply_chain': {},
        'production_base': {},
        'capacity_expansion': {},
        'brand_equity': {},
        'channel_system': {},
        'opportunities': [],
        'summary_text': '',
    }

    # 从 strategic_opportunity.dimensions 中提取（若有实际内容）
    if isinstance(strategic, dict):
        dims = strategic.get('dimensions', {})
        if isinstance(dims, dict):
            for section_key, mapping_key in [
                ('strategic_positioning', 'strategic_positioning'),
                ('business_model', 'business_model'),
                ('brand_equity', 'brand_equity'),
                ('product_matrix', 'product_matrix'),
                ('channel_system', 'channel_system'),
                ('supply_chain', 'supply_chain'),
                ('production_base', 'production_base'),
                ('capacity_expansion', 'capacity_expansion'),
            ]:
                raw = dims.get(section_key, {})
                if not isinstance(raw, dict):
                    continue
                out = {}
                for k, v in raw.items():
                    if isinstance(v, str) and v.strip():
                        out[k] = v[:500]
                    elif isinstance(v, list) and v:
                        # 只保留有内容的项
                        filtered = [x for x in v if isinstance(x, str) and x.strip()]
                        if filtered:
                            out[k] = filtered[:5]
                    elif isinstance(v, (int, float)) and v:
                        out[k] = v
                # 如果有 raw_text，但其他字段都空 —— 单独保留
                if not out and raw.get('raw_text'):
                    rt = raw.get('raw_text', '')
                    if isinstance(rt, str) and len(rt.strip()) > 20:
                        out['raw_text'] = rt[:800]
                result[mapping_key] = out

    # 从 industry.findings 补充
    if isinstance(industry, dict):
        findings = industry.get('findings', {})
        if isinstance(findings, dict):
            mb = findings.get('main_business_raw', '')
            if mb:
                result['strategic_positioning']['main_business_raw'] = mb[:500]

    # 从 product_line_intro 补充
    if isinstance(product_line_intro, dict):
        mb = product_line_intro.get('main_business', '')
        if mb and not result['strategic_positioning'].get('main_business_raw'):
            result['strategic_positioning']['main_business_raw'] = mb[:500]

        tdx_basic = product_line_intro.get('tdx_basic', {})
        if isinstance(tdx_basic, dict) and tdx_basic:
            result['company_basic'] = {
                'company_name': tdx_basic.get('company_name', ''),
                'industry': tdx_basic.get('industry', ''),
                'region': tdx_basic.get('region', ''),
                'website': tdx_basic.get('website', ''),
                'chairman': tdx_basic.get('chairman', ''),
                'general_manager': tdx_basic.get('general_manager', ''),
                'controlling_shareholder': tdx_basic.get('controlling_shareholder', ''),
                'employee_count': tdx_basic.get('employee_count'),
                'company_intro': (tdx_basic.get('company_intro', '') or '')[:500],
                'auditor': tdx_basic.get('auditor', ''),
            }

    # 从 business_fetch 补充
    if isinstance(business_fetch, dict):
        bm = business_fetch.get('business_model', {})
        if isinstance(bm, dict) and not result['business_model']:
            for k, v in bm.items():
                if isinstance(v, str) and v.strip():
                    result['business_model'][k] = v[:300]
                elif isinstance(v, list) and v:
                    filtered = [x for x in v if isinstance(x, str) and x.strip()]
                    if filtered:
                        result['business_model'][k] = filtered[:5]

        inv_qa = business_fetch.get('investor_qa', {})
        if isinstance(inv_qa, dict):
            summary = inv_qa.get('summary', '')
            if isinstance(summary, str) and summary.strip():
                result['investor_qa_summary'] = summary[:500]

    # 汇总
    parts = []
    if result['strategic_positioning']:
        parts.append('战略定位：有业务描述')
    if result['supply_chain']:
        parts.append('供应链：有客户/供应商数据')
    if result['capacity_expansion']:
        parts.append('产能扩张：有在建工程信息')
    if result['business_model']:
        parts.append('商业模式：有结构化字段')
    result['summary_text'] = '；'.join(parts) if parts else '战略相关字段已提取，AI可基于raw_text进一步分析'

    return result


# ============================================================
# 32. 价值链 / 产业链分析
# ============================================================

def _compress_value_chain(strategic, industry, product_line_intro, business_fetch, three_statements):
    """基于业务描述、产品线、客户/供应商、财务数据构建价值链/产业链图谱"""
    result = {
        'upstream': {},     # 上游（原材料/供应商）
        'midstream': {},    # 中游（自身制造/设计环节）
        'downstream': {},   # 下游（客户/渠道/终端）
        'revenue_chain': [],  # 收入链（各环节营收占比）
        'key_products': [],    # 核心产品线
        'value_add_indicators': {},  # 增值能力指标
        'summary_text': '',
    }

    # ========== 1. 收入链 / 产品结构 ==========
    if isinstance(product_line_intro, dict):
        tdx_prods = product_line_intro.get('tdx_products', [])
        if isinstance(tdx_prods, list):
            for p in tdx_prods:
                if not isinstance(p, dict):
                    continue
                name = p.get('name', '')
                ratio = float(p.get('revenue_ratio') or 0)
                if name and ratio > 0:
                    result['revenue_chain'].append({
                        'name': name,
                        'revenue_ratio_pct': round(ratio * 100, 2),
                    })

        # 核心产品线描述
        plines = product_line_intro.get('product_lines', [])
        if isinstance(plines, list):
            unique_lines = set()
            for pl in plines:
                if isinstance(pl, dict):
                    desc = pl.get('description', '')
                    if isinstance(desc, str) and desc.strip() and len(desc) < 200:
                        # 过滤掉历史/变更描述
                        if any(k in desc for k in ['2010', '2013', '变更后', '变更前', '研制、生产']):
                            continue
                        unique_lines.add(desc[:150])
            result['key_products'] = list(unique_lines)[:20]

    # ========== 2. 下游客户（从 strategic.supply_chain 提取）==========
    if isinstance(strategic, dict):
        dims = strategic.get('dimensions', {})
        if isinstance(dims, dict):
            sc = dims.get('supply_chain', {})
            if isinstance(sc, dict):
                customers = sc.get('customers', '')
                suppliers = sc.get('suppliers', '')
                if isinstance(customers, str) and customers.strip():
                    # 提取客户相关信息（文本中包含销售额、占比）
                    result['downstream']['customer_concentration_raw'] = customers[:800]
                    # 简单提取前五客户占比合计
                    import re as _re_local
                    pcts = _re_local.findall(r'(\d+\.\d+)%', customers)
                    if pcts:
                        try:
                            top5 = sum([float(x) for x in pcts[:5]])
                            result['downstream']['top5_customer_ratio_pct'] = round(top5, 2)
                        except ValueError:
                            pass
                if isinstance(suppliers, str) and suppliers.strip():
                    result['upstream']['supplier_concentration_raw'] = suppliers[:800]
                    import re as _re_local2
                    pcts = _re_local2.findall(r'(\d+\.\d+)%', suppliers)
                    if pcts:
                        try:
                            top5 = sum([float(x) for x in pcts[:5]])
                            result['upstream']['top5_supplier_ratio_pct'] = round(top5, 2)
                        except ValueError:
                            pass

    # ========== 3. 中游（自身业务描述） ==========
    if isinstance(industry, dict):
        findings = industry.get('findings', {})
        if isinstance(findings, dict):
            mb = findings.get('main_business_raw', '')
            if isinstance(mb, str) and mb.strip():
                result['midstream']['main_business_description'] = mb[:500]

    # ========== 4. 增值能力指标（来自 three_statements / financial） ==========
    if isinstance(three_statements, dict):
        income = three_statements.get('income_statement', {})
        if isinstance(income, dict):
            rev = income.get('营业收入')
            cost = income.get('营业成本')
            if rev and cost and rev > 0:
                result['value_add_indicators']['gross_margin_pct'] = round((rev - cost) / rev * 100, 2)

        # 毛利率补充
        if isinstance(industry, dict):
            findings = industry.get('findings', {})
            if isinstance(findings, dict):
                gr = findings.get('gross_profit_ratio')
                if gr and not result['value_add_indicators'].get('gross_margin_pct'):
                    result['value_add_indicators']['gross_margin_pct'] = gr

    # ========== 5. 从 business_fetch 补充渠道 ==========
    if isinstance(business_fetch, dict):
        bm = business_fetch.get('business_model', {})
        if isinstance(bm, dict):
            for k in ['sales_channel', 'customer_type', 'revenue_model']:
                v = bm.get(k, '')
                if isinstance(v, str) and v.strip():
                    result['downstream'][k] = v[:300]

    # ========== 6. 汇总文本 ==========
    parts = []
    if result['revenue_chain']:
        desc = '/'.join([f"{x['name']}({x['revenue_ratio_pct']}%)" for x in result['revenue_chain']])
        parts.append(f'收入结构：{desc}')
    if result['downstream'].get('top5_customer_ratio_pct'):
        parts.append(f'前五大客户集中度：{result["downstream"]["top5_customer_ratio_pct"]}%')
    if result['upstream'].get('top5_supplier_ratio_pct'):
        parts.append(f'前五大供应商集中度：{result["upstream"]["top5_supplier_ratio_pct"]}%')
    if result['value_add_indicators'].get('gross_margin_pct'):
        parts.append(f'毛利率：{result["value_add_indicators"]["gross_margin_pct"]}%')
    result['summary_text'] = '；'.join(parts)

    return result


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='数据压缩器')
    parser.add_argument('--results', required=True, help='results.json路径')
    parser.add_argument('--output', help='输出路径（默认同目录下material_pack.json）')

    args = parser.parse_args()

    with open(args.results, 'r', encoding='utf-8') as f:
        results = json.load(f)

    output = args.output or os.path.join(os.path.dirname(args.results), 'material_pack.json')
    compress_to_file(results, output, results_path=args.results)
