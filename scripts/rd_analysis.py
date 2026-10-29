# -*- coding: utf-8 -*-
"""
rd_analysis.py - 净利润下滑归因分析 + 研发质量评估

【分析框架】
一、净利润下滑归因（定量）
   ① 结构性因素   → 重大资产处置/合并范围变更（最优先，影响收入可比性）
   ② 毛利驱动分析 → 毛利率变化 × 营收规模（剔除结构性因素后）
   ③ 营收规模分析 → 有机增长 vs 剥离缩表
   ④ 非经常性损益 → 处置收益/损失（年报PDF提取）
   ⑤ 资产减值分析 → 商誉减值/存货减值

   核心原则：先识别结构性变化（卖子公司/合并范围变更），
   再分析经营性因素。避免把"卖子公司导致营收下降"误判为"经营恶化"。

二、研发质量评估（定性+定量）
   ① 研发强度 = 研发费用 / 营收（与历史比，与行业比）
   ② 资本化率 = 资本化研发 / 研发总额（高质量研发→低资本化率）
   ③ 专利壁垒评估（联网CNIPA专利数据库）
   ④ 结论：高研发→专利壁垒？或纯费用消耗？
"""
import sys, os, re, json, time
sys.stdout.reconfigure(encoding='utf-8')

from scripts.safe_request import safe_get
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

EM_API = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': 'application/json',
}


# =====================================================================
# 0. 资产剥离/合并范围变更检测（最优先，影响归因判断）
# =====================================================================

def _detect_asset_disposal(data_dir):
    """
    从年报PDF全文检测重大资产处置/合并范围变更。
    关键词：出售子公司、重大资产重组、合并范围变更、处置长期股权投资。
    提取：被处置子公司名、处置损益、终止性经营影响。
    """
    result = {
        'has_disposal': False,
        'disposed_subs': [],
        'disposal_gain_loss_亿': None,
        'discontinued_ops_亿': None,
        'investment_loss_亿': None,
        'revenue_impact_note': '',
        'summary': '',
        'warnings': [],
    }

    if not data_dir:
        return result

    # 找年报全文
    text = _get_annual_text(data_dir)
    if not text:
        return result

    # 1. 检测关键词（需排除年报标准表格中的“不适用”场景）
    disposal_keywords = [
        '出售境外子公司', '出售子公司', '重大资产重组',
        '处置子公司', '丧失控制权', '合并范围发生变动',
        '合并范围变更', '不再纳入合并', '终止性经营',
        '利盟终止性', '股权出售交割',
    ]
    detected = []
    for kw in disposal_keywords:
        idx = 0
        while True:
            idx = text.find(kw, idx)
            if idx < 0:
                break
            # 检查关键词后200字内是否有“√不适用”或“□适用”（标准年报表格标记为不适用）
            context = text[idx:idx+200]
            if '√不适用' in context:
                idx += len(kw)
                continue  # 跳过“不适用”场景
            detected.append(kw)
            break
        if kw in detected:
            continue
    if not detected:
        return result

    result['has_disposal'] = True
    result['warnings'].append('检测到重大资产处置/合并范围变更: ' + ', '.join(sorted(set(detected))[:3]))

        # 2. 提取资产处置损益（第一列：当期）
    disposal_gain_loss = re.search(r'资产处置损益[\s\S]{0,200}?(-?[\d,]+(?:\.\d+)?)', text)
    if disposal_gain_loss:
        try:
            result['disposal_gain_loss'] = round(
                float(disposal_gain_loss.group(1).replace(',', '')) / 1e8, 2)
        except Exception as _sexc:
            record(__name__, '_detect_asset_disposal', _sexc, note='静默降级')
            pass

    # 3. 提取终止性经营影响（利盟出售净影响，已是净值）
    discontinued_ops = re.search(r'终止性经营影响[\s\S]{0,200}?(-?\d+\.\d+)\s*亿', text)
    if discontinued_ops:
        try:
            result['discontinued_ops'] = float(discontinued_ops.group(1))
        except Exception as _sexc:
            record(__name__, '_detect_asset_disposal', _sexc, note='静默降级')
            pass

    # 4. 剩余股权重分类收益（权益法转公允价值，第二行数字）
    equity_remeasure = re.search(
        r'权益法转公允价值[\s\S]{0,100}?(-?[\d,]+(?:\.\d+)?)\s*(?:\n|$)', text)
    if equity_remeasure:
        try:
            v = float(equity_remeasure.group(1).replace(',', ''))
            if abs(v) > 1e4:
                result['equity_remeasure'] = round(v / 1e8, 2)
        except Exception as _sexc:
            record(__name__, '_detect_asset_disposal', _sexc, note='静默降级')
            pass

    # 5. 被处置子公司名称（从文本动态提取，不硬编码）
    # 匹配“出售XX子公司”/“处置XX公司”等模式
    sub_match = re.search(r'(?:出售|处置|转让)([\u4e00-\u9fa5]{2,10}(?:公司|有限|集团))', text)
    if sub_match:
        result['disposed_entities'] = [sub_match.group(1)]

    # 6. 收入影响说明
    revenue_drop = re.search(r'合并范围变动.*?减少.*?(\d+\.\d+)\s*亿', text, re.DOTALL)
    if revenue_drop:
        result['revenue_impact_note'] = f'合并范围变动减少收入约{revenue_drop.group(1)}亿'

    # 7. 汇总（一次性处置净损失 = 资产处置损益 + 终止性经营影响）
    g = result.get('disposal_gain_loss', 0) or 0
    d = result.get('discontinued_ops', 0) or 0
    total_impact = g + d
    # 金额阈值：一次性影响<1亿且营收下降<10%，不足以判定为主因
    revenue_threshold_met = result.get('revenue_impact_note', '') != ''
    if total_impact < 0 and (abs(total_impact) >= 1 or revenue_threshold_met):
        extra = ''
        er = result.get('equity_remeasure', 0) or 0
        if er:
            extra = f'，剩余股权重分类收益{er:.2f}亿'
        entity_name = result.get('disposed_entities', ['未知标的'])[0]
        result['summary'] = (
            f'检测到重大资产处置：{entity_name}，'
            f'一次性净损失约{-total_impact:.2f}亿元'
            f'（资产处置损益{g:.2f}亿 + 终止性经营影响{d:.2f}亿）{extra}，'
            f'归因结论：重大资产剥离为净利润下降主因（而非经营恶化）'
        )
        result['warnings'].append(
            f'一次性处置净损失{-total_impact:.2f}亿'
            f'（资产处置损益{g:.2f}亿 + 终止性经营{d:.2f}亿）{extra}'
        )
    elif total_impact < 0 and abs(total_impact) < 1:
        # 金额太小，降级为提示而非主因
        result['has_disposal'] = False
        result['summary'] = f'资产处置损益{g:.2f}亿，金额较小，非主因'
    return result


def _get_annual_text(data_dir):
    """获取年报文本，优先读txt（需验证非乱码且长度充足），其次从PDF提取"""
    if not data_dir:
        return ''

    # 尝试txt（需验证ASCII比例>40%，否则说明是乱码；且长度>20000才算完整年报）
    for fname in ['annual_report_text.txt', 'annual_report_text_full.txt']:
        p = os.path.join(data_dir, fname)
        if os.path.exists(p):
            try:
                with open(p, 'rb') as f:
                    raw = f.read()
                # 乱码检测：ASCII字符占比 > 40% 才算有效
                ascii_ratio = sum(1 for b in raw if b < 128) / max(len(raw), 1)
                if ascii_ratio < 0.4:
                    continue  # 乱码，跳过
                txt = raw.decode('utf-8', errors='replace')
                # 完整年报通常>50页，文本>20000字；太短说明是截断版本
                if len(txt) > 20000:
                    return txt
            except Exception as _sexc:
                record(__name__, '_get_annual_text', _sexc, note='静默降级')
                pass

    # 从PDF提取（优先选含annual_report或数字最多的那个）
    try:
        import glob as glob_mod
        pdfs = glob_mod.glob(os.path.join(data_dir, '*.pdf'))
        if pdfs:
            # 优先选含annual_report关键字的文件，或按大小排序取最大
            pdfs_sorted = sorted(pdfs, key=lambda p: (
                # has_annual=True → 排前面（key=0），False → 排后面（key=1）
                0 if ('annual_report' in p.lower() or '年报' in p) else 1,
                -os.path.getsize(p),  # 同类中最大优先
            ))
            pdf_path = pdfs_sorted[0]
            import fitz
            doc = fitz.open(pdf_path)
            txt = ''
            for page in doc:
                txt += page.get_text('text')
            doc.close()
            return txt
    except Exception as _sexc:
        record(__name__, '_get_annual_text', _sexc, note='静默降级')
        pass
    return ''


# =====================================================================
# 1. 净利润下滑归因
# =====================================================================

def _load_financial_data(data_dir, stock_code):
    """加载已有财务数据"""
    if not data_dir:
        return None
    path = os.path.join(data_dir, 'financial_metrics.json')
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as _sexc:
            record(__name__, '_load_financial_data', _sexc, note='静默降级')
            pass
    return None


def _get_financial_timeseries(stock_code, market='a'):
    """获取多期财务数据（用于趋势分析），只保留年报"""
    secucode = stock_code
    if market == 'a':
        if not (stock_code.endswith('.SZ') or stock_code.endswith('.SH')):
            if stock_code[:2] in ['00', '30']:
                secucode = stock_code + '.SZ'
            elif stock_code[:2] in ['60', '68']:
                secucode = stock_code + '.SH'
            elif stock_code[0] in ['8', '4']:
                secucode = stock_code + '.BJ'
            else:
                secucode = stock_code + '.SZ'

    params = {
        'reportName': 'RPT_LICO_FN_CPD',
        'columns': 'ALL',
        'filter': f'(SECUCODE="{secucode}")',
        'pageNumber': 1,
        'pageSize': 12,  # 12条≈3年年报（含季报），过滤后得3期年报
        'sortTypes': -1,
        'sortColumns': 'REPORTDATE',
        'source': 'WEB',
        'client': 'WEB',
    }
    raw = safe_get(EM_API, params=params, headers=EM_HEADERS, timeout=20)
    from scripts.safe_request import safe_extract
    records = safe_extract(raw, ['result', 'data'], default=[])
    if records is None:
        records = []
    return _filter_annual_reports(records)


def _filter_annual_reports(records):
    """过滤年报（只用12-31报告期）。若无年报，取同季度对比（如Q3 vs Q3）而非直接fallback"""
    annual = [r for r in records if str(r.get('REPORTDATE', ''))[:10].endswith('12-31')]
    if annual:
        return annual
    # 无年报时（如公司刚上市），按最新报告期取同季度对比
    if not records:
        return []
    latest_rd = str(records[0].get('REPORTDATE', ''))[:10]
    month = latest_rd[5:7]  # e.g. '09' for Q3
    same_quarter = [r for r in records if str(r.get('REPORTDATE', ''))[:10].endswith(month + '-')]
    return same_quarter if len(same_quarter) >= 2 else records[:2]


def _get_income_statement(stock_code, market='a'):
    """获取利润表（费用率/毛利拆解），优先取年报（12-31）"""
    secucode = stock_code
    if market == 'a':
        if not (stock_code.endswith('.SZ') or stock_code.endswith('.SH')):
            if stock_code[:2] in ['00', '30']:
                secucode = stock_code + '.SZ'
            elif stock_code[:2] in ['60', '68']:
                secucode = stock_code + '.SH'
            elif stock_code[0] in ['8', '4']:
                secucode = stock_code + '.BJ'
            else:
                secucode = stock_code + '.SZ'

    params = {
        'reportName': 'RPT_LICO_FN_CPD',
        'columns': 'SECURITY_CODE,REPORTDATE,BASIC_EPS,PARENT_NETPROFIT,TOTAL_OPERATE_INCOME,'
                   'WEIGHTAVG_ROE,XSMLL,YSTZ,SJLTZ,MGJYXJJE,BPS,DEDUCT_BASIC_EPS',
        'filter': f'(SECUCODE="{secucode}")',
        'pageNumber': 1,
        'pageSize': 12,  # 12条≈3年（含季报），过滤后得3期年报
        'sortTypes': -1,
        'sortColumns': 'REPORTDATE',
        'source': 'WEB',
        'client': 'WEB',
    }
    raw = safe_get(EM_API, params=params, headers=EM_HEADERS, timeout=20)
    from scripts.safe_request import safe_extract
    records = safe_extract(raw, ['result', 'data'], default=[])
    if records is None:
        records = []
    records = _filter_annual_reports(records)
    return records


def _get_profit_decomposition(records, disposal_info=None):
    """
    净利润变动归因分析。
    优先级：重大资产处置（结构性）> 毛利下降 > 营收大幅下滑 > 由盈转亏。
    """
    if not records or len(records) < 2:
        return None

    curr = records[0]
    prev = records[1]
    curr_date = str(curr.get('REPORTDATE', ''))[:10]
    prev_date = str(prev.get('REPORTDATE', ''))[:10]

    curr_np = curr.get('PARENT_NETPROFIT', 0) or 0
    prev_np = prev.get('PARENT_NETPROFIT', 0) or 0
    curr_rev = curr.get('TOTAL_OPERATE_INCOME', 0) or 0
    prev_rev = prev.get('TOTAL_OPERATE_INCOME', 0) or 0
    curr_gm = curr.get('XSMLL') or 0
    prev_gm = prev.get('XSMLL') or 0
    curr_eps = curr.get('BASIC_EPS') or 0
    prev_eps = prev.get('BASIC_EPS') or 0

    np_change = curr_np - prev_np
    if prev_np > 0 and curr_np > 0:
        np_change_pct = ((curr_np / prev_np) - 1) * 100
    elif prev_np < 0 and curr_np < 0:
        np_change_abs = curr_np - prev_np
        np_change_pct = round(np_change_abs / abs(prev_np) * 100, 1) if prev_np != 0 else None
    else:
        np_change_pct = None

    factors = []

    # 0. 结构性因素（最优先）
    if disposal_info and disposal_info.get('has_disposal'):
        one_time = 0
        # 一次性处置净损失 = 资产处置损益 + 终止性经营（不含剩余股权重分类收益）
        g = disposal_info.get('disposal_gain_loss', 0) or 0
        d = disposal_info.get('discontinued_ops', 0) or 0
        er = disposal_info.get('equity_remeasure', 0) or 0
        one_time = g + d
        impact_label = 'negative' if one_time < 0 else ('positive' if one_time > 0 else 'neutral')
        detail_parts = [disposal_info.get('summary', '重大资产处置')]
        if er:
            detail_parts.append('其中剩余股权重分类收益+' + str(round(er, 2)) + '亿')
        if abs(one_time) > 0.01:
            label = '损失' if one_time < 0 else '收益'
            detail_parts.append('一次性' + label + '合计' + str(round(abs(one_time), 2)) + '亿元')
        if disposal_info.get('revenue_impact_note'):
            detail_parts.append('营收下降部分源于合并范围缩减，非纯经营恶化')
        factors.append({
            'type': '重大资产处置',
            'impact': impact_label,
            'detail': '；'.join(detail_parts),
            'is_structural': True,
        })

    # 1. 毛利分析
    gm_change = curr_gm - prev_gm
    curr_gross_profit = curr_rev * curr_gm / 100 if curr_gm else 0
    prev_gross_profit = prev_rev * prev_gm / 100 if prev_gm else 0
    gross_profit_change_亿 = (curr_gross_profit - prev_gross_profit) / 1e8
    if gm_change < -1:
        factors.append({
            'type': '毛利率下降',
            'impact': 'negative',
            'detail': ('毛利率' + str(round(prev_gm, 2)) + '%→' + str(round(curr_gm, 2)) + '%，'
                       + '下降' + str(round(abs(gm_change), 2)) + 'pp，导致毛利减少'
                       + str(round(abs(gross_profit_change_亿), 1)) + '亿元')
        })
    elif gm_change > 1:
        factors.append({
            'type': '毛利率提升',
            'impact': 'positive',
            'detail': ('毛利率' + str(round(prev_gm, 2)) + '%→' + str(round(curr_gm, 2)) + '%，'
                       + '提升' + str(round(gm_change, 2)) + 'pp')
        })

    # 2. 营收规模
    rev_change_pct = ((curr_rev / prev_rev) - 1) * 100 if prev_rev != 0 else 0
    rev_change_亿 = (curr_rev - prev_rev) / 1e8
    if rev_change_pct < -10:
        factors.append({
            'type': '营收大幅下滑',
            'impact': 'negative',
            'detail': ('营收' + str(round(prev_rev/1e8, 1)) + '亿→' + str(round(curr_rev/1e8, 1))
                       + '亿，下滑' + str(round(rev_change_pct, 1)) + '%，减少'
                       + str(round(abs(rev_change_亿), 1)) + '亿元')
        })
    elif rev_change_pct < -3:
        factors.append({
            'type': '营收小幅下滑',
            'impact': 'negative',
            'detail': ('营收' + str(round(rev_change_pct, 1)) + '%，减少'
                       + str(round(abs(rev_change_亿), 1)) + '亿元')
        })
    elif rev_change_pct > 10:
        factors.append({
            'type': '营收快速增长',
            'impact': 'positive',
            'detail': ('营收' + str(round(prev_rev/1e8, 1)) + '亿→' + str(round(curr_rev/1e8, 1))
                       + '亿，增长' + str(round(rev_change_pct, 1)) + '%')
        })

    # 3. 净利润趋势
    curr_roe = curr.get('WEIGHTAVG_ROE') or 0
    prev_roe = prev.get('WEIGHTAVG_ROE') or 0
    if curr_np < 0 and prev_np > 0:
        factors.append({
            'type': '由盈转亏',
            'impact': 'negative',
            'detail': ('净利润' + str(round(prev_np/1e8, 2)) + '亿→'
                       + str(round(curr_np/1e8, 2)) + '亿，EPS ' + str(prev_eps) + '→' + str(curr_eps) + '，首次亏损')
        })
    elif curr_np < 0 and prev_np < 0:
        abs_change = curr_np - prev_np
        if abs_change < 0:
            factors.append({
                'type': '亏损扩大',
                'impact': 'negative',
                'detail': ('净亏损扩大：' + str(round(abs(prev_np)/1e8, 2)) + '亿→'
                           + str(round(abs(curr_np)/1e8, 2)) + '亿')
            })
        else:
            factors.append({
                'type': '亏损收窄',
                'impact': 'positive',
                'detail': ('净亏损收窄：' + str(round(abs(prev_np)/1e8, 2)) + '亿→'
                           + str(round(abs(curr_np)/1e8, 2)) + '亿')
            })
    elif prev_np < 0 and curr_np >= 0:
        factors.append({'type': '由亏转盈', 'impact': 'positive',
                        'detail': ('净利润' + str(round(prev_np/1e8, 2)) + '亿→'
                                   + str(round(curr_np/1e8, 2)) + '亿')})
    elif np_change_pct and abs(np_change_pct) > 10:
        direction = '增长' if np_change > 0 else '下滑'
        factors.append({
            'type': '净利润' + direction,
            'impact': 'positive' if np_change > 0 else 'negative',
            'detail': ('净利润同比' + str(round(np_change_pct, 1)) + '%')
        })

    # 4. ROE
    if curr_roe < 0 and prev_roe > 0:
        factors.append({'type': 'ROE由正转负', 'impact': 'negative',
                        'detail': 'ROE ' + str(round(prev_roe, 2)) + '%→' + str(round(curr_roe, 2)) + '%'})
    elif curr_roe < 5 and curr_roe > 0:
        factors.append({'type': 'ROE偏低', 'impact': 'neutral',
                        'detail': 'ROE仅' + str(round(curr_roe, 2)) + '%'})

    return {
        'period': prev_date + ' -> ' + curr_date,
        'curr_date': curr_date,
        'prev_date': prev_date,
        'curr_net_profit_亿': round(curr_np / 1e8, 2),
        'prev_net_profit_亿': round(prev_np / 1e8, 2),
        'np_change_亿': round(np_change / 1e8, 2),
        'np_change_pct': round(np_change_pct, 1) if np_change_pct is not None else None,
        'curr_gross_margin': round(curr_gm, 2),
        'prev_gross_margin': round(prev_gm, 2),
        'curr_revenue_亿': round(curr_rev / 1e8, 2),
        'prev_revenue_亿': round(prev_rev / 1e8, 2),
        'curr_roe': round(curr_roe, 2),
        'prev_roe': round(prev_roe, 2),
        'factors': factors,
        'primary_cause': _identify_primary_cause(factors),
        'secondary_causes': [f['type'] for f in factors
                            if f['impact'] == 'negative' and f['type'] != _identify_primary_cause(factors)],
    }


def _identify_primary_cause(factors):
    """判断主要亏损/下滑原因，结构性因素最高优先级"""
    negative = [f for f in factors if f['impact'] == 'negative']
    if not negative:
        positive = [f for f in factors if f['impact'] == 'positive']
        if positive:
            return positive[0]['type']
        return '无明显异常'
    # 优先级：重大资产处置 > 毛利率下降 > 营收大幅下滑 > 由盈转亏 > 亏损扩大
    priority = ['重大资产处置', '毛利率下降', '营收大幅下滑',
                '由盈转亏', '亏损扩大', '营收小幅下滑', 'ROE由正转负']
    for p in priority:
        for f in negative:
            if f['type'] == p:
                return p
    return negative[0]['type']


# =====================================================================
# 2. 研发质量评估
# =====================================================================

def _get_rd_from_pdf(data_dir):
    """从年报PDF全文提取研发数据"""
    result = {
        'rd_expense_亿': None,
        'rd_capitalized_亿': None,
        'capitalization_rate': None,
        'rd_personnel_count': None,
        'patent_count': None,
        'raw_text_rd': None,
    }
    if not data_dir:
        return result
    text = _get_annual_text(data_dir)
    if not text:
        return result
    result['raw_text_rd'] = text[:200]

    # 研发费用（优先匹配跨行格式，再匹配同行格式）
    for pat in [
        # 跨行格式：研发费用\n金额（元）
        r'研发费用\s*\n\s*([\d,]+(?:\.\d+)?)\s*\n',
        r'研发费用\s*\n\s*([\d,]+(?:\.\d+)?)\s*元',
        # 同行格式：研发费用 金额 万元
        r'研发投入[^一-龥]{0,20}([\d,]+(?:\.\d+)?)\s*万元',
        r'研发费用[^一-龥]{0,20}([\d,]+(?:\.\d+)?)\s*万元',
        r'研发投入合计[^一-龥]{0,20}([\d,]+(?:\.\d+)?)\s*万元',
        r'研发投入金额（元）[\s\S]{0,5}?([\d,]+(?:\.\d+)?)',
        r'研发费用[^一-龥]{0,20}([\d,]+(?:\.\d+)?)\s*元',
    ]:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1).replace(',', ''))
                # 判断单位：如果值>1e8或没有明确单位，则认为是“元”
                if '万元' in pat:
                    result['rd_expense_亿'] = round(val / 10000, 2)
                else:
                    # 跨行匹配默认按元处理
                    if val > 1e8:  # 超过1亿元则按元算
                        result['rd_expense_亿'] = round(val / 1e8, 2)
                    else:  # 否则按万元算
                        result['rd_expense_亿'] = round(val / 10000, 2)
                break
            except Exception as _sexc:
                record(__name__, '_get_rd_from_pdf', _sexc, note='静默降级')
                pass

    # 资本化研发（优先匹配年报标准格式“研发投入资本化的金额（元）”，再匹配“万元”）
    for pat in [
        r'研发投入资本化的金额（元）[\s\S]{0,5}?([\d,]+(?:\.\d+)?)',
        r'资本化研发[^\d]{0,20}([\d,]+(?:\.\d+)?)\s*万元',
        r'开发支出[^\d]{0,20}([\d,]+(?:\.\d+)?)\s*万元',
        r'资本化研发[^\d]{0,20}([\d,]+(?:\.\d+)?)\s*元',
    ]:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1).replace(',', ''))
                if '万元' in pat:
                    result['rd_capitalized_亿'] = round(val / 10000, 2)
                else:
                    result['rd_capitalized_亿'] = round(val / 1e8, 2)
                break
            except Exception as _sexc:
                record(__name__, '_get_rd_from_pdf', _sexc, note='静默降级')
                pass

    if result['rd_expense_亿'] and result['rd_capitalized_亿'] and result['rd_expense_亿'] > 0:
        result['capitalization_rate'] = round(
            result['rd_capitalized_亿'] / result['rd_expense_亿'] * 100, 1)

    # 研发人员（年报标准格式：数值在表头下一行）
    for pat in [
        r'研发人员数量（人）\s*\n\s*(\d[\d,]*)',
        r'研发人员[^\d]{0,10}(\d[\d,]+)\s*(?:人|名)',
        r'研发人员数量[^\d]{0,10}(\d[\d,]+)\s*(?:人|名)',
    ]:
        m = re.search(pat, text)
        if m:
            result['rd_personnel_count'] = int(m.group(1).replace(',', ''))
            break

    # 专利数
    for pat in [
        r'已获授权[^\d]{0,10}(?:发明)?专利[^\d]{0,10}(\d+)\s*(?:项|件)',
        r'拥有[^\d]{0,10}(?:发明)?专利[^\d]{0,10}(\d+)\s*(?:项|件)',
        r'累计[^\d]{0,10}(?:发明)?专利[^\d]{0,10}(\d+)\s*(?:项|件)',
    ]:
        m = re.search(pat, text)
        if m:
            result['patent_count'] = int(m.group(1))
            break

    return result


def _assess_rd_quality(rd_pdf, rd_ts, profit_dec, stock_code, company_name, market):
    """研发质量综合评估"""
    result = {
        'rd_expense_亿': rd_pdf.get('rd_expense_亿'),
        'rd_capitalized_亿': rd_pdf.get('rd_capitalized_亿'),
        'capitalization_rate': rd_pdf.get('capitalization_rate'),
        'patent_count': rd_pdf.get('patent_count'),
        'rd_personnel_count': rd_pdf.get('rd_personnel_count'),
        'patent_barrier': 'unknown',
        'patent_growth': None,
        'assessment': '',
        'barrier_evidence': [],
        'warning_flags': [],
    }

    cap_rate = rd_pdf.get('capitalization_rate')
    if cap_rate is not None:
        if cap_rate > 50:
            result['warning_flags'].append('研发资本化率过高(' + str(cap_rate) + '%)，存在利润调节嫌疑')
            result['assessment'] += '高资本化率警示；'
        elif cap_rate > 30:
            result['warning_flags'].append('研发资本化率偏高(' + str(cap_rate) + '%)')
        elif cap_rate < 20:
            result['barrier_evidence'].append('低资本化率(' + str(cap_rate) + '%)，研发投入以费用化为主，财务处理审慎')
            result['assessment'] += '低资本化率反映真实研发投入；'

    patent_count = rd_pdf.get('patent_count')
    if patent_count and patent_count > 100:
        result['patent_barrier'] = 'strong'
        result['barrier_evidence'].append('有效专利' + str(patent_count) + '项（>100），专利壁垒强')
        result['assessment'] += '专利壁垒强；'
    elif patent_count and patent_count > 30:
        result['patent_barrier'] = 'moderate'
        result['assessment'] += '专利壁垒中等；'
    elif patent_count and patent_count > 0:
        result['patent_barrier'] = 'weak'
        result['warning_flags'].append('专利数偏少（' + str(patent_count) + '项）')
        result['assessment'] += '专利壁垒弱；'

    rd_ppl = rd_pdf.get('rd_personnel_count')
    if rd_ppl and rd_ppl > 1000:
        result['barrier_evidence'].append('研发人员' + str(rd_ppl) + '人，规模优势显著')
        result['assessment'] += '研发团队' + str(rd_ppl) + '人；'

    return result


# =====================================================================
# 主函数
# =====================================================================

def fetch_rd_analysis(stock_code, market='a', data_dir=None, company_name=None):
    """净利润下滑归因分析 + 研发质量评估"""
    result = {
        'stock_code': stock_code,
        'market': market,
        'profit_decomposition': {},
        'rd_quality': {},
        'rd_vs_loss_summary': '',
        'warnings': [],
        'findings': {},
    }

    # 步骤0: 资产剥离检测
    disposal_info = _detect_asset_disposal(data_dir)
    result['findings']['disposal_info'] = disposal_info
    if disposal_info.get('has_disposal'):
        result['warnings'].append('检测到重大资产处置: ' + disposal_info['summary'])

    # 步骤1: 获取财务趋势
    records = _get_income_statement(stock_code, market)
    if not records or len(records) < 2:
        fin_data = _load_financial_data(data_dir, stock_code)
        if fin_data and fin_data.get('records'):
            records = fin_data['records']

    # 步骤2: 净利润归因（含结构性因素）
    if records and len(records) >= 2:
        profit_dec = _get_profit_decomposition(records, disposal_info=disposal_info)
        result['profit_decomposition'] = profit_dec
        result['findings']['records'] = records[:4]

    # 步骤3: 研发数据
    rd_pdf = _get_rd_from_pdf(data_dir)
    result['findings']['rd_pdf'] = rd_pdf

    # 步骤4: 研发质量评估
    profit_dec = result.get('profit_decomposition')
    rd_quality = _assess_rd_quality(rd_pdf, None, profit_dec, stock_code,
                                      company_name or stock_code, market)
    result['rd_quality'] = rd_quality

    # 步骤5: 综合结论
    summary_parts = []
    if profit_dec:
        primary = profit_dec.get('primary_cause', '未知')
        np_chg = profit_dec.get('np_change_pct')
        if np_chg is not None:
            summary_parts.append('净利润同比' + str(round(np_chg, 1)) + '%（主因：' + primary + '）')
        else:
            summary_parts.append('净利润主因：' + primary)
    if rd_quality.get('assessment'):
        summary_parts.append('研发质量：' + rd_quality['assessment'])
    result['rd_vs_loss_summary'] = '；'.join(summary_parts) if summary_parts else '数据不足'

    # 步骤6: 战略性亏损信号
    if (rd_quality.get('rd_expense_亿') or 0) > 5 \
       and rd_quality.get('patent_barrier') in ('strong', 'moderate') \
       and profit_dec and '亏损' in profit_dec.get('primary_cause', ''):
        result['findings']['strategic_signal'] = (
            '高研发投入+专利壁垒，净利润下滑为战略性投入，非经营恶化'
        )

    return result


def format_rd_analysis(data):
    """格式化Markdown"""
    if not data:
        return '数据不足，无法分析'

    lines = []
    pd = data.get('profit_decomposition', {})
    disposal_info = data.get('findings', {}).get('disposal_info', {})
    rq = data.get('rd_quality', {})

    # ---- 一、净利润归因 ----
    lines.append('## 一、净利润变动归因')

    # 结构性因素优先展示
    if disposal_info.get('has_disposal'):
        lines.append('')
        lines.append('> **重大资产处置检测**：净利润变化受结构性因素主导，'
                     '营收/利润同比数据不可直接用于经营分析。')
        lines.append('')
        lines.append('| 项目 | 详情 |')
        lines.append('|------|------|')
        if disposal_info.get('disposed_subs'):
            names = ', '.join(s['name'] for s in disposal_info['disposed_subs'][:3])
            lines.append('| 被处置子公司 | ' + names + ' |')
        if disposal_info.get('disposal_gain_loss_亿') is not None:
            d = disposal_info['disposal_gain_loss_亿']
            lines.append('| 资产处置损益 | ' + str(round(d, 2)) + '亿元 |')
        if disposal_info.get('investment_loss_亿') is not None:
            d = disposal_info['investment_loss_亿']
            lines.append('| 处置长期股权投资 | ' + str(round(d, 2)) + '亿元 |')
        if disposal_info.get('discontinued_ops_亿') is not None:
            d = disposal_info['discontinued_ops_亿']
            lines.append('| 终止性经营影响 | ' + str(round(d, 2)) + '亿元 |')
        if disposal_info.get('revenue_impact_note'):
            lines.append('| 营收影响说明 | ' + disposal_info['revenue_impact_note'][:80] + ' |')
        lines.append('')

    if pd:
        period = pd.get('period', '')
        prev_np = pd.get('prev_net_profit_亿', 0)
        curr_np = pd.get('curr_net_profit_亿', 0)
        np_chg = pd.get('np_change_pct')
        lines.append('**分析期间**: ' + period)
        if np_chg is not None:
            lines.append('**净利润**: ' + str(prev_np) + '亿 -> ' + str(curr_np) + '亿（' + str(round(np_chg, 1)) + '%）')
        else:
            lines.append('**净利润**: ' + str(prev_np) + '亿 -> ' + str(curr_np) + '亿（盈亏性质变化）')
        lines.append('**毛利率**: ' + str(pd.get('prev_gross_margin', 0)) + '% -> '
                     + str(pd.get('curr_gross_margin', 0)) + '%')
        lines.append('**营收**: ' + str(pd.get('prev_revenue_亿', 0)) + '亿 -> '
                     + str(pd.get('curr_revenue_亿', 0)) + '亿')
        primary = pd.get('primary_cause', '未知')
        if primary == '重大资产处置':
            lines.append('')
            lines.append('**主因（结构性）**: ' + primary)
            lines.append('')
            lines.append('> 若剔除资产处置一次性影响，剩余净利润变化才反映真实经营情况。')
        else:
            lines.append('**主因**: ' + primary)
        lines.append('')
        lines.append('**因素分解**:')
        for f in pd.get('factors', []):
            if f.get('is_structural'):
                icon = '[建筑]'
            elif f['impact'] == 'negative':
                icon = '[负]'
            elif f['impact'] == 'positive':
                icon = '[正]'
            else:
                icon = '[中]'
            lines.append(icon + ' ' + f['type'] + ': ' + f['detail'])
        lines.append('')
    elif not disposal_info.get('has_disposal'):
        lines.append('数据不足，无法分析')
        lines.append('')

    # ---- 二、研发质量 ----
    lines.append('## 二、研发质量评估')
    if rq:
        if rq.get('rd_expense_亿') is not None:
            lines.append('**研发费用**: ' + str(rq['rd_expense_亿']) + '亿元')
        cap = rq.get('capitalization_rate')
        if cap is not None:
            icon = '[优]' if cap < 20 else ('[中]' if cap < 50 else '[劣]')
            lines.append('**资本化率**: ' + icon + ' ' + str(cap) + '%')
        if rq.get('rd_personnel_count'):
            lines.append('**研发人员**: ' + str(rq['rd_personnel_count']) + '人')
        pc = rq.get('patent_count')
        if pc:
            pb = rq.get('patent_barrier', 'unknown')
            barrier_label = {'strong': '强', 'moderate': '中', 'weak': '弱', 'unknown': '待查'}.get(pb, '待查')
            lines.append('**专利数**: ' + str(pc) + '项（壁垒：' + barrier_label + '）')
        elif not rq.get('rd_expense_亿'):
            lines.append('无法获取研发费用数据，需下载年报PDF')
        for e in rq.get('barrier_evidence', []):
            lines.append('+ ' + e)
        for w in rq.get('warning_flags', []):
            lines.append('! ' + w)
        lines.append('')

    # ---- 三、综合结论 ----
    lines.append('## 三、综合结论')
    lines.append(data.get('rd_vs_loss_summary', '数据不足'))
    sig = data.get('findings', {}).get('strategic_signal', '')
    if sig:
        lines.append('**战略性信号**: ' + sig)
    for w in data.get('warnings', []):
        lines.append('**警告**: ' + w)

    return '\n'.join(lines)


# 向后兼容
fetch_rd_decomposition = fetch_rd_analysis


def generate_report_section(data: dict) -> list:
    if not data or data.get('error'):
        return []
    md = format_rd_analysis(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 研发与利润归因分析\n\n", md]
