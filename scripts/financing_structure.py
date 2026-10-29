# -*- coding: utf-8 -*-
"""
融资结构全景模块
数据源: 东方财富API + 年报PDF提取 + 联网搜索补充
功能: 全面覆盖公司融资渠道——股票质押、可转债、银行贷款、租赁、定增、债券等
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
# Add parent dir to path for module import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.safe_request import safe_get, safe_extract, safe_float

EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_SEARCH = "https://searchapi.eastmoney.com/api/suggest/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json",
}


def _secucode(stock_code):
    """转换为东财证券代码格式"""
    if stock_code.endswith((".SH", ".SZ", ".BJ")):
        return stock_code
    if stock_code[:2] in ["00", "30"]:
        return f"{stock_code}.SZ"
    if stock_code[:2] in ["60", "68"]:
        return f"{stock_code}.SH"
    if stock_code[0] in ["8", "4"]:
        return f"{stock_code}.BJ"
    return f"{stock_code}.SZ"


def fetch_financing_structure(stock_code, market="a", data_dir=None, financial_metrics=None, governance_data=None, share_history_data=None, announcements_data=None):
    """
    融资结构全景主函数
    
    策略: 优先从已有模块数据聚合(governance/share_history/financial_metrics/announcements)，
    缺失部分用东方财富API补充，API仍无数据则标注[需从年报PDF/公告提取]
    
    覆盖维度:
    1. 资本结构总览（负债率/有息负债/净负债率）
    2. 股票质押明细（质押率/质押方/资金用途/平仓风险）
    3. 可转债（存量/转股价/转股进度/下修历史）
    4. 公司债券（存量/到期日/票面利率/评级）
    5. 银行贷款与授信（短期/长期/授信额度/已用额度）
    6. 租赁融资（经营租赁/融资租赁/使用权资产）
    7. 定增/配股历史（发行价/募资/浮盈浮亏）
    8. 担保链全景（对外担保/被担保/担保余额/风险敞口）
    9. 偿债能力评估（利息覆盖率/现金短债比/速动比率）
    10. 对外投资（长期股权投资/金融资产/投资收益）
    11. 理财产品（结构性存款/理财产品/委托理财）
    """
    result = {
        "stock_code": stock_code,
        "market": market,
        "capital_structure": {},
        "pledge_detail": [],
        "convertible_bonds": [],
        "corporate_bonds": [],
        "bank_loans": {},
        "lease_financing": {},
        "additional_issues": [],
        "guarantee_chain": {},
        "solvency": {},
        "investments": {},
        "wealth_products": [],
        "warnings": [],
    }

    if market != "a":
        result["warnings"].append(f"{market}市场融资结构数据暂不支持，需从年报PDF提取")
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "financing_structure.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        return result

    secucode = _secucode(stock_code)

    # 1. 资本结构总览（从financial_metrics提取）
    result["capital_structure"] = _extract_capital_structure(financial_metrics)

    # 2. 股票质押明细（优先AKShare含预估平仓线，回退governance，再回退API）
    akshare_pledge = _fetch_pledge_detail_akshare(stock_code)
    if akshare_pledge and not (isinstance(akshare_pledge, list) and akshare_pledge and akshare_pledge[0].get('note')):
        result["pledge_detail"] = akshare_pledge
    elif governance_data and governance_data.get('pledge', {}).get('records'):
        result["pledge_detail"] = _aggregate_pledge_from_governance(governance_data)
    else:
        result["pledge_detail"] = _fetch_pledge_detail(secucode)

    # 3. 可转债
    result["convertible_bonds"] = _fetch_convertible_bonds_akshare(stock_code)

    # 4. 公司债券
    result["corporate_bonds"] = _fetch_corporate_bonds(secucode)

    # 5. 银行贷款与授信（从financial_metrics + AKShare同花顺）
    result["bank_loans"] = _fetch_bank_loans(secucode, financial_metrics)
    result["financial_debt_ths"] = _fetch_financial_debt_ths(stock_code)

    # 6. 租赁融资
    result["lease_financing"] = _fetch_lease_financing(secucode, financial_metrics)

    # 7. 定增/配股（从share_history_data聚合，API补充）
    if share_history_data and share_history_data.get('financing_history', {}).get('additional_issues'):
        result["additional_issues"] = share_history_data['financing_history']['additional_issues']
    else:
        result["additional_issues"] = _fetch_additional_issues(secucode)

    # 8. 担保链全景（优先AKShare巨潮，回退API+公告）
    akshare_guarantee = _fetch_guarantee_cninfo(stock_code)
    api_guarantee = _fetch_guarantee_chain(secucode, announcements_data)
    result["guarantee_chain"] = {
        **api_guarantee,
        "cninfo_summary": akshare_guarantee,
    }

    # 9. 偿债能力评估
    result["solvency"] = _calculate_solvency(financial_metrics, result)

    # 10. 公司债券（公告搜索确认）
    result["corporate_bonds"] = _search_corporate_bonds_announcements(stock_code, announcements_data)

    # 11. 对外投资
    result["investments"] = _fetch_investments(stock_code, financial_metrics, governance_data)

    # 12. 理财产品
    result["wealth_products"] = _fetch_wealth_products(stock_code, financial_metrics, announcements_data)

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "financing_structure.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def _extract_capital_structure(fm):
    """从financial_metrics提取资本结构"""
    if not fm:
        return {"note": "financial_metrics为空，需从其他数据源补充"}
    
    latest = fm.get("latest", fm)
    
    total_assets = safe_float(latest.get("TOTAL_ASSETS"))
    total_current_liab = safe_float(latest.get("TOTAL_CURRENT_LIAB"))
    total_noncurrent_liab = safe_float(latest.get("TOTAL_NONCURRENT_LIAB"))
    total_parent_equity = safe_float(latest.get("TOTAL_PARENT_EQUITY"))
    short_loan = safe_float(latest.get("SHORT_LOAN"))
    long_loan = safe_float(latest.get("LONG_LOAN"))
    
    total_liab = (total_current_liab or 0) + (total_noncurrent_liab or 0)
    interest_bearing_debt = (short_loan or 0) + (long_loan or 0)
    
    return {
        "report_date": latest.get("REPORTDATE", "")[:10],
        "total_assets_yi": round(total_assets / 1e8, 2) if total_assets else None,
        "total_liab_yi": round(total_liab / 1e8, 2) if total_liab else None,
        "total_equity_yi": round(total_parent_equity / 1e8, 2) if total_parent_equity else None,
        "debt_ratio_pct": round(total_liab / total_assets * 100, 2) if total_assets and total_liab else None,
        "interest_bearing_debt_yi": round(interest_bearing_debt / 1e8, 2) if interest_bearing_debt else None,
        "short_loan_yi": round(short_loan / 1e8, 2) if short_loan else None,
        "long_loan_yi": round(long_loan / 1e8, 2) if long_loan else None,
        "net_debt_ratio_note": "净负债率需贷款币资金数据，从年报补充",
        "leverage_signal": _assess_leverage(total_liab, total_assets, interest_bearing_debt),
    }


def _assess_leverage(total_liab, total_assets, ibd):
    """评估杠杆水平"""
    if not total_assets or not total_liab:
        return "数据不足"
    dr = total_liab / total_assets
    if dr > 0.7:
        return "🔴 高杠杆——负债率超70%"
    elif dr > 0.5:
        return "🟠 中高杠杆——负债率50-70%"
    elif dr > 0.3:
        return "🟡 中等杠杆——负债率30-50%"
    else:
        return "🟢 低杠杆——负债率低于30%"


def _aggregate_pledge_from_governance(gov_data):
    """从governance模块聚合质押明细"""
    pledge = gov_data.get('pledge', {})
    records = pledge.get('records', [])
    result = []
    for r in records:
        result.append({
            "pledgor": r.get("pledgor", ""),
            "pledgee": r.get("institution", r.get("pledgee", "")),
            "pledge_shares_wan_gu": round(safe_float(r.get("pledge_shares"), 0) / 1e4, 2),
            "pledge_ratio_held": r.get("pledge_ratio_held"),
            "pledge_ratio_total": r.get("pledge_ratio_total"),
            "source": "governance模块",
        })
    
    # 在最后添加汇总信息
    result.append({
        "note": f"共{pledge.get('pledge_count', len(records))}条股权质押记录，最新质押率{pledge.get('latest_ratio', '?')}，信号：{pledge.get('signal', '?')}"
    })
    return result


def _fetch_pledge_detail_akshare(stock_code):
    """从AKShare获取股票质押明细"""
    try:
        import akshare as ak
        df = ak.stock_em_gpzy_profile(symbol=stock_code)
        if len(df) == 0:
            return [{"note": "AKShare无质押记录"}]
        result = []
        for _, row in df.head(10).iterrows():
            result.append({
                "pledgor": str(row.get("股东名称", "")),
                "pledge_shares_wan_gu": round(safe_float(row.get("质押股数", 0)) / 1e4, 2),
                "pledge_ratio_held": row.get("质押比例(%)"),
                "source": "AKShare",
            })
        return result
    except Exception as e:
        return [{"note": f"AKShare质押数据获取失败: {str(e)[:80]}"}]


def _fetch_pledge_detail(secucode):
    """从东财API获取股票质押明细"""
    params = {
        "reportName": "RPT_F10_EH_HOLDERNUM_TXT",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1,
        "pageSize": 50,
        "sortTypes": -1,
        "sortColumns": "END_DATE",
    }
    data = safe_get(EM_API, params=params, headers=HEADERS)
    if not data:
        return [{"note": "[需从年报PDF提取质押明细]"}]
    
    rows = safe_extract(data, ["Data", 0, "Data"]) or []
    if not rows:
        return [{"note": "[API返回空数据]"}]
    
    result = []
    for row in rows:
        result.append({
            "pledgor": row.get("HOLDER_NAME", ""),
            "pledgee": row.get("PLEDGEE", ""),
            "pledge_shares_wan_gu": round(safe_float(row.get("PLEDGE_SHARES"), 0) / 1e4, 2),
            "pledge_ratio_held": row.get("PLEDGE_RATIO"),
            "source": "东财API",
        })
    return result


def _fetch_convertible_bonds_akshare(stock_code):
    """从AKShare获取可转债信息"""
    try:
        import akshare as ak
        # 集思录可转债列表
        cb_list = ak.bond_cb_jsl()
        # 筛选该股票的可转债
        matching = cb_list[cb_list['股票代码'] == stock_code]
        if len(matching) == 0:
            return [{"note": "无存续可转债"}]
        
        result = []
        for _, row in matching.iterrows():
            result.append({
                "bond_code": row.get("债券代码", ""),
                "bond_name": row.get("债券简称", ""),
                "conversion_price": row.get("转股价", ""),
                "current_price": row.get("现价", ""),
                "conversion_premium_ratio": row.get("转股溢价率(%)", ""),
                "source": "AKShare",
            })
        return result
    except Exception as e:
        return [{"note": f"可转债数据获取失败: {str(e)[:80]}"}]


def _fetch_corporate_bonds(secucode):
    """从东财API获取公司债券"""
    params = {
        "reportName": "RPT_BOND_BASICINFO_LIST",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1,
        "pageSize": 20,
    }
    data = safe_get(EM_API, params=params, headers=HEADERS)
    if not data:
        return [{"note": "[需从公告搜索公司债券]"}]
    
    rows = safe_extract(data, ["Data", 0, "Data"]) or []
    if not rows:
        return [{"note": "无存续公司债券"}]
    
    result = []
    for row in rows:
        result.append({
            "bond_code": row.get("BOND_CODE", ""),
            "bond_name": row.get("BOND_NAME", ""),
            "issue_amount_yi": round(safe_float(row.get("ISSUE_AMOUNT"), 0) / 1e8, 2),
            "maturity_date": row.get("MATURITY_DATE", ""),
            "coupon_rate": row.get("COUPON_RATE"),
            "source": "东财API",
        })
    return result


def _fetch_bank_loans(secucode, fm):
    """获取银行贷款信息"""
    result = {"note": "银行贷款数据需从年报补充"}
    
    if fm:
        latest = fm.get("latest", fm)
        short_loan = safe_float(latest.get("SHORT_LOAN"))
        long_loan = safe_float(latest.get("LONG_LOAN"))
        if short_loan or long_loan:
            result = {
                "short_loan_yi": round((short_loan or 0) / 1e8, 2),
                "long_loan_yi": round((long_loan or 0) / 1e8, 2),
                "total_loan_yi": round(((short_loan or 0) + (long_loan or 0)) / 1e8, 2),
                "source": "financial_metrics",
            }
    
    return result


def _fetch_financial_debt_ths(stock_code):
    """从AKShare同花顺获取完整资产负债表"""
    try:
        import akshare as ak
        df = ak.stock_financial_debt_ths(symbol=stock_code, indicator='按报告期')
        if len(df) == 0:
            return {"note": "同花顺资产负债表无数据"}
        
        latest = df.iloc[0]
        return {
            "report_date": str(latest.get("报告期", "")),
            "total_liab_yi": round(safe_float(latest.get("负债合计"), 0) / 1e8, 2),
            "interest_bearing_liab_yi": round(safe_float(latest.get("有息负债"), 0) / 1e8, 2),
            "source": "AKShare同花顺",
        }
    except Exception as e:
        return {"note": f"同花顺财务数据获取失败: {str(e)[:80]}"}


def _fetch_lease_financing(secucode, fm):
    """获取租赁融资信息"""
    result = {"note": "[需从年报附注提取租赁负债明细]"}
    
    # 尝试从financial_metrics提取使用权资产
    if fm:
        latest = fm.get("latest", fm)
        right_of_use = safe_float(latest.get("RIGHT_OF_USE_ASSETS"))
        lease_liab = safe_float(latest.get("LEASE_LIAB"))
        if right_of_use or lease_liab:
            result = {
                "right_of_use_assets_yi": round((right_of_use or 0) / 1e8, 2),
                "lease_liab_yi": round((lease_liab or 0) / 1e8, 2),
                "source": "financial_metrics",
            }
    
    return result


def _fetch_additional_issues(secucode):
    """从东财API获取定增/配股历史"""
    params = {
        "reportName": "RPT_F10_FINANCE_RAISE",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1,
        "pageSize": 20,
    }
    data = safe_get(EM_API, params=params, headers=HEADERS)
    if not data:
        return [{"note": "[需从公告搜索定增历史]"}]
    
    rows = safe_extract(data, ["Data", 0, "Data"]) or []
    if not rows:
        return [{"note": "无定增/配股记录"}]
    
    result = []
    for row in rows:
        result.append({
            "issue_type": row.get("ISSUE_TYPE", ""),
            "issue_price": row.get("ISSUE_PRICE"),
            "raise_amount_yi": round(safe_float(row.get("RAISE_AMOUNT"), 0) / 1e8, 2),
            "issue_date": row.get("ISSUE_DATE", ""),
            "source": "东财API",
        })
    return result


def _fetch_guarantee_chain(secucode, announcements_data):
    """获取担保链信息"""
    result = {
        "对外担保": [],
        "被担保": [],
        "note": "[需从公告搜索担保明细]"
    }
    
    if announcements_data and announcements_data.get('data'):
        # 从公告中搜索担保相关
        for ann in announcements_data['data'][:20]:
            title = ann.get('title', '')
            if '担保' in title or '保证' in title:
                result["对外担保"].append({
                    "title": title,
                    "date": ann.get("announcementTime", ""),
                    "source": "公告搜索",
                })
    
    return result


def _fetch_guarantee_cninfo(stock_code):
    """从AKShare巨潮获取担保信息"""
    try:
        import akshare as ak
        df = ak.stock_guarantee_cninfo(symbol=stock_code)
        if len(df) == 0:
            return {"note": "巨潮无担保记录"}
        
        result = []
        for _, row in df.head(10).iterrows():
            result.append({
                "guarantor": row.get("担保人", ""),
                "guaranteed": row.get("被担保人", ""),
                "amount_yi": round(safe_float(row.get("担保金额", 0)) / 1e8, 2),
                "expiry_date": row.get("担保到期日", ""),
                "source": "AKShare巨潮",
            })
        return result
    except Exception as e:
        return {"note": f"巨潮担保数据获取失败: {str(e)[:80]}"}


def _calculate_solvency(fm, fs_result):
    """计算偿债能力指标"""
    result = {"note": "偿债能力指标需从年报补充"}
    
    if not fm:
        return result
    
    latest = fm.get("latest", fm)
    
    # 现金短债比
    cash = safe_float(latest.get("MONETARY_CAPITAL"))
    short_loan = safe_float(latest.get("SHORT_LOAN"))
    non_current_liab_due = safe_float(latest.get("NON_CURRENT_LIAB_DUE"))
    total_current_liab = safe_float(latest.get("TOTAL_CURRENT_LIAB"))
    total_assets = safe_float(latest.get("TOTAL_ASSETS"))
    
    short_term_debt = (short_loan or 0) + (non_current_liab_due or 0)
    
    if cash and short_term_debt:
        cash_to_debt = round(cash / short_term_debt, 2)
    else:
        cash_to_debt = None
    
    # 速动比率
    if total_current_liab and total_assets:
        # 简化计算：假设速动资产 = 总资产 - 存货（数据不全时用负债率替代）
        quick_ratio = None
    else:
        quick_ratio = None
    
    return {
        "cash_to_short_debt": cash_to_debt,
        "short_term_debt_yi": round(short_term_debt / 1e8, 2) if short_term_debt else None,
        "cash_yi": round(cash / 1e8, 2) if cash else None,
        "note": "利息覆盖率/速动比率需从年报补充",
    }


def _search_corporate_bonds_announcements(stock_code, announcements_data):
    """从公告搜索公司债券"""
    result = [{"note": "[需从公告搜索公司债券]"}]
    
    if not announcements_data or not announcements_data.get('data'):
        return result
    
    bonds = []
    for ann in announcements_data['data'][:50]:
        title = ann.get('title', '')
        if '公司债券' in title or '公司债' in title:
            bonds.append({
                "title": title,
                "date": ann.get("announcementTime", ""),
                "source": "公告搜索",
            })
    
    return bonds if bonds else result


def _fetch_investments(stock_code, fm, gov_data):
    """获取对外投资信息"""
    result = {"note": "[需从年报提取长期股权投资明细]"}
    
    if fm:
        latest = fm.get("latest", fm)
        long_equity = safe_float(latest.get("LONG_EQUITY_INVEST"))
        fin_assets = safe_float(latest.get("FIN_ASSETS"))
        
        if long_equity or fin_assets:
            result = {
                "long_equity_invest_yi": round((long_equity or 0) / 1e8, 2),
                "fin_assets_yi": round((fin_assets or 0) / 1e8, 2),
                "source": "financial_metrics",
            }
    
    return result


def _fetch_wealth_products(stock_code, fm, announcements_data):
    """获取理财产品信息"""
    result = [{"note": "[需从公告搜索理财产品]"}]
    
    if not announcements_data or not announcements_data.get('data'):
        return result
    
    products = []
    for ann in announcements_data['data'][:30]:
        title = ann.get('title', '')
        if '理财' in title or '委托理财' in title:
            products.append({
                "title": title,
                "date": ann.get("announcementTime", ""),
                "source": "公告搜索",
            })
    
    return products if products else result



def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 融资结构分析")
    lines.append("")

    if not data:
        lines.append("*融资结构数据暂未获取*")
        lines.append("")
        return lines

    cap = data.get('capital_structure', {})
    if cap and not cap.get('note'):
        lines.append("### 资本结构总览")
        lines.append("")
        lines.append(f"**报告期**: {cap.get('report_date', '未知')}")
        lines.append(f"**总资产**: {cap.get('total_assets_yi', '?')}亿元")
        lines.append(f"**总负债**: {cap.get('total_liab_yi', '?')}亿元")
        lines.append(f"**股东权益**: {cap.get('total_equity_yi', '?')}亿元")
        lines.append(f"**资产负债率**: {cap.get('debt_ratio_pct', '?')}%")
        lines.append(f"**有息负债**: {cap.get('interest_bearing_debt_yi', '?')}亿元")
        lines.append(f"**杠杆信号**: {cap.get('leverage_signal', '?')}")
        lines.append("")

    pledge = data.get('pledge_detail', [])
    if pledge and isinstance(pledge, list):
        lines.append("### 股票质押明细")
        lines.append("")
        for p in pledge[:10]:
            if p.get('note'):
                lines.append(f"- {p.get('note')}")
            else:
                pledgor = p.get('pledgor', '未知')
                pledgee = p.get('pledgee', '未知')
                shares = p.get('pledge_shares_wan_gu', '?')
                ratio = p.get('pledge_ratio_held', '?')
                lines.append(f"- **{pledgor}** → {pledgee}: {shares}万股，质押比例{ratio}%")
        lines.append("")

    loans = data.get('bank_loans', {})
    if loans and not loans.get('note'):
        lines.append("### 银行贷款")
        lines.append("")
        lines.append(f"**短期贷款**: {loans.get('short_loan_yi', '?')}亿元")
        lines.append(f"**长期贷款**: {loans.get('long_loan_yi', '?')}亿元")
        lines.append(f"**贷款合计**: {loans.get('total_loan_yi', '?')}亿元")
        lines.append("")

    cb = data.get('convertible_bonds', [])
    if cb and isinstance(cb, list):
        lines.append("### 可转债")
        lines.append("")
        for c in cb[:5]:
            if c.get('note'):
                lines.append(f"- {c.get('note')}")
            else:
                lines.append(f"- **{c.get('bond_name', '未知')}** ({c.get('bond_code', '?')}): 转股价{c.get('conversion_price', '?')}，溢价率{c.get('conversion_premium_ratio', '?')}%")
        lines.append("")

    solvency = data.get('solvency', {})
    if solvency:
        lines.append("### 偿债能力评估")
        lines.append("")
        if solvency.get('cash_to_short_debt'):
            lines.append(f"**现金短债比**: {solvency.get('cash_to_short_debt', '?')}")
        if solvency.get('note'):
            lines.append(f"- {solvency.get('note')}")
        lines.append("")

    warnings = data.get('warnings', [])
    if warnings:
        lines.append("### 警告信号")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return lines


# 导出函数
__all__ = ['fetch_financing_structure']
