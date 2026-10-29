# -*- coding: utf-8 -*-
"""
公司治理深度分析模块（整合版）
数据源: 东方财富 API + AKShare（东方财富/同花顺/CNINFO封装）
功能: 股权集中度、大股东质押、管理层信息、独董有效性、审计信息、内控评价

整合来源:
- 框架/API调用: workspace-agent版本
- 额外数据字段: .qclaw版本 (company_profile, circulate/fund shareholders, management/shareholder changes)
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
from scripts.safe_request import safe_get, safe_extract, safe_float
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json",
}


def _secucode(stock_code):
    if stock_code.endswith((".SH", ".SZ", ".BJ")):
        return stock_code
    if stock_code[:2] in ["00", "30"]:
        return f"{stock_code}.SZ"
    if stock_code[:2] in ["60", "68"]:
        return f"{stock_code}.SH"
    if stock_code[0] in ["8", "4"]:
        return f"{stock_code}.BJ"
    return f"{stock_code}.SZ"


def _safe_float(val, default=None):
    """安全转换为浮点数"""
    if val is None or val == '' or val == 'N/A':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _import_akshare():
    """延迟导入 akshare（避免模块级导入失败）"""
    try:
        import akshare as ak
        return ak
    except ImportError:
        return None


_ak = _import_akshare()

# 安全代理：akshare 未安装时不崩溃，返回 None/空列表
class _AkSafe:
    def __getattr__(self, name):
        return lambda *a, **kw: None

ak = _ak if _ak is not None else _AkSafe()


def _get_ak():
    """获取 akshare 实例，未安装时返回 None"""
    return _ak if _ak is not None else None


def fetch_governance(stock_code, market="a", data_dir=None, annual_pdf_data=None, financial_data=None, announcements_data=None):
    """主函数：治理分析（整合版）"""
    ak_avail = _get_ak()
    if ak_avail is None:
        print("  ⚠️ akshare 未安装，跳过 akshare 增强数据（pip install akshare）")
    result = {
        "stock_code": stock_code,
        # === 来自.qclaw版本的额外字段 ===
        "company_profile": {},
        "circulate_shareholders": [],
        "fund_shareholders": [],
        # === 标准字段 ===
        "top_shareholders": [],
        "ownership": {},
        "pledge": {},
        "pledge_records": [],
        "management": {},
        "management_changes": [],
        "independent_directors": {},
        "auditor": {},
        "internal_control": {},
        "shareholder_changes": [],
        "score": 0,
        "risks": [],
        "warnings": [],
    }

    secucode = _secucode(stock_code)

    # 0. 公司基本信息（.qclaw版本补充）
    if ak is not None:
        result["company_profile"] = _fetch_company_profile_ak(stock_code)

    # 1. 股东结构（前十大股东）
    result["top_shareholders"] = _fetch_top_shareholders(secucode)

    # 2. 流通股东（.qclaw版本补充）
    if ak is not None:
        result["circulate_shareholders"] = _fetch_circulate_shareholders_ak(stock_code)

    # 3. 基金持股（.qclaw版本补充）
    if ak is not None:
        result["fund_shareholders"] = _fetch_fund_shareholders_ak(stock_code)

    # 4. 股权集中度分析
    result["ownership"] = _analyze_ownership(result["top_shareholders"])

    # 5. 质押信息
    result["pledge"], result["pledge_records"] = _fetch_pledge_info_ak(stock_code)

    # 6. 管理层信息
    result["management"] = _fetch_management(secucode, announcements_data=announcements_data)

    # 7. 管理层变动（.qclaw版本补充）
    if ak is not None:
        result["management_changes"] = _fetch_management_changes_ak(stock_code)

    # 8. 独董分析
    result["independent_directors"] = _analyze_independent_directors(result["management"])

    # 9. 审计信息
    result["auditor"] = _fetch_auditor(secucode, annual_pdf_data=annual_pdf_data)

    # 10. 内控评价
    result["internal_control"] = _fetch_internal_control(secucode, annual_pdf_data=annual_pdf_data, financial_data=financial_data)

    # 11. 股东变动追踪（.qclaw版本补充）
    if ak is not None:
        result["shareholder_changes"] = _fetch_shareholder_changes_ak(stock_code)

    # 12. 治理评分
    result["score"] = _governance_score(result)

    # 13. 风险汇总
    result["risks"] = _summarize_governance_risks(result)

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "governance.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


# ============================================================
# 数据获取函数
# ============================================================

def _fetch_company_profile_ak(stock_code):
    """AKShare: 公司基本信息"""
    if ak is None:
        return {}
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_profile_cninfo(symbol=code)
        if df is None or df.empty:
            return {}
        row = df.iloc[0]
        return {
            "name": str(row.get("公司名称", "")),
            "name_en": str(row.get("英文名称", "")),
            "legal_representative": str(row.get("法人代表", "")),
            "registered_capital": _safe_float(row.get("注册资金", 0)),
            "establish_date": str(row.get("成立日期", "")),
            "listing_date": str(row.get("上市日期", "")),
            "industry": str(row.get("所属行业", "")),
            "market": str(row.get("所属市场", "")),
            "website": str(row.get("官方网站", "")),
            "email": str(row.get("电子邮箱", "")),
            "phone": str(row.get("联系电话", "")),
            "registered_address": str(row.get("注册地址", "")),
            "office_address": str(row.get("办公地址", "")),
            "main_business": str(row.get("主营业务", ""))[:200],
        }
    except Exception as e:
        return {}


def _fetch_top_shareholders(secucode):
    """前十大股东"""
    try:
        if ak is None:
            return []
        # 转换为AKShare格式
        if secucode.endswith('.SH'):
            prefix = 'sh'
        elif secucode.endswith('.SZ'):
            prefix = 'sz'
        elif secucode.endswith('.BJ'):
            prefix = 'bj'
        else:
            prefix = 'sh'
        ak_code = prefix + secucode.split('.')[0]
        df = ak.stock_gdfx_top_10_em(symbol=ak_code)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.head(10).iterrows():
            ratio = safe_float(row.get('占总股本持股比例'))
            if ratio is not None:
                result.append({
                    "name": str(row.get('股东名称', '未知')),
                    "ratio_pct": round(ratio, 2),
                    "type": str(row.get('股份类型', '未知')),
                    "change": row.get('增减'),
                    "date": '',
                })
        return result
    except Exception as e:
        return []


def _fetch_circulate_shareholders_ak(stock_code):
    """AKShare: 流通股东"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_circulate_stock_holder(symbol=code)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.head(10).iterrows():
            result.append({
                "name": str(row.get("股东名称", ""))[:30],
                "ratio_pct": _safe_float(row.get("占流通股比例", 0)),
                "shares": _safe_float(row.get("持股数量", 0)),
                "type": str(row.get("股本性质", "")),
                "date": str(row.get("截止日期", "")),
            })
        return result
    except Exception as e:
        return []


def _fetch_fund_shareholders_ak(stock_code):
    """AKShare: 基金持股"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_fund_stock_holder(symbol=code)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.head(10).iterrows():
            result.append({
                "name": str(row.get("基金名称", ""))[:30],
                "ratio_pct": _safe_float(row.get("占流通股比例", 0)),
                "shares": _safe_float(row.get("持仓数量", 0)),
                "value": _safe_float(row.get("持股市值", 0)),
                "date": str(row.get("截止日期", "")),
            })
        return result
    except Exception as e:
        return []


def _analyze_ownership(top_sh):
    """股权集中度分析"""
    if not top_sh:
        return {"type": "未知", "cr1": None, "cr5": None, "cr10": None, "signal": "数据不足"}
    ratios = [s["ratio_pct"] for s in top_sh if s.get("ratio_pct")]
    if not ratios:
        return {"type": "未知", "cr1": None, "cr5": None, "cr10": None, "signal": "数据不足"}
    cr1 = ratios[0] if ratios else None
    cr5 = sum(ratios[:5]) if len(ratios) >= 5 else sum(ratios)
    cr10 = sum(ratios[:10]) if len(ratios) >= 10 else sum(ratios)

    if cr1 and cr1 > 60:
        otype, signal = "高度集中", "一股独大，决策风险集中"
    elif cr1 and cr1 > 30:
        otype, signal = "适度集中", "股权相对集中，大股东控制力较强"
    else:
        otype, signal = "相对分散", "股权相对分散，治理结构更均衡"

    return {"type": otype, "cr1": cr1, "cr5": round(cr5, 2), "cr10": round(cr10, 2), "signal": signal}


def _fetch_pledge_info_ak(stock_code):
    """质押信息 - AKShare"""
    if ak is None:
        return {"latest_ratio": None, "signal": "AKShare未安装", "pledge_count": 0}, []

    pledge_info = {"latest_ratio": None, "signal": "暂无数据", "pledge_count": 0}
    records = []

    try:
        from datetime import datetime, timedelta
        today = datetime.now()
        for days_ago in range(0, 30, 7):
            try:
                date_str = (today - timedelta(days=days_ago)).strftime("%Y%m%d")
                df = ak.stock_gpzy_pledge_ratio_em(date=date_str)
                if df is not None and not df.empty:
                    code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
                    df_filtered = df[df['股票代码'] == code]
                    if not df_filtered.empty:
                        row = df_filtered.iloc[0]
                        pledge_info["latest_ratio"] = _safe_float(row.get('质押比例', 0)) / 100
                        pledge_info["pledge_count"] = int(_safe_float(row.get('质押笔数', 0)) or 0)
                        ratio = pledge_info["latest_ratio"]
                        if ratio and ratio > 0.8:
                            pledge_info["signal"] = "⚠️ 质押率超80%警戒线"
                        elif ratio and ratio > 0.5:
                            pledge_info["signal"] = "⚠️ 质押率偏高"
                        elif ratio and ratio > 0:
                            pledge_info["signal"] = f"质押率{ratio:.0%}"
                        break
            except Exception as _sexc:
                record(__name__, '_fetch_pledge_info_ak', _sexc, note='静默降级')
                pass
    except Exception as e:
        record_result(__name__, '_fetch_pledge_info_ak', e, note='静默降级')
        pass

    # 质押记录
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_gpzy_individual_pledge_ratio_detail_em(symbol=code)
        if df is not None and not df.empty:
            for _, row in df.head(10).iterrows():
                records.append({
                    "pledgor": str(row.get('股东名称', '')),
                    "pledge_shares": str(row.get('质押股份数量', '')),
                    "pledge_ratio_held": _safe_float(row.get('占所持股份比例')),
                    "pledge_ratio_total": _safe_float(row.get('占总股本比例')),
                    "institution": str(row.get('质押机构', '')),
                })
    except Exception as _sexc:
        record(__name__, '_fetch_pledge_info_ak', _sexc, note='静默降级')
        pass

    if pledge_info["latest_ratio"] is None and records:
        total_pledge_ratio = sum(r.get("pledge_ratio_total", 0) or 0 for r in records)
        if total_pledge_ratio > 0:
            pledge_info["latest_ratio"] = total_pledge_ratio / 100
            pledge_info["pledge_count"] = len(records)
            ratio = pledge_info["latest_ratio"]
            if ratio > 0.8:
                pledge_info["signal"] = "⚠️ 质押率超80%警戒线（基于明细计算）"
            elif ratio > 0.5:
                pledge_info["signal"] = "⚠️ 质押率偏高（基于明细计算）"
            elif ratio > 0:
                pledge_info["signal"] = f"质押率{ratio:.0%}（基于明细计算）"

    return pledge_info, records


def _fetch_management(secucode, announcements_data=None):
    """管理层信息 - 从公告数据提取"""
    result = {
        "executives": [],
        "chairman": None,
        "general_manager": None,
        "cfo": None,
        "board_secretary": None,
        "total_count": 0
    }

    if announcements_data:
        critical = announcements_data.get('critical_announcements', [])
        major = announcements_data.get('major_announcements', [])
        routine = announcements_data.get('routine_announcements', [])
        all_anns = critical + major + routine

        mgmt_anns = []
        for a in all_anns:
            title = a.get('title', '')
            if any(k in title for k in ['董事', '高管', '总裁', '总经理', '聘任', '辞职', '换届', '监事']):
                mgmt_anns.append(a)

        mgmt_anns.sort(key=lambda x: x.get('date', ''), reverse=True)

        for a in mgmt_anns[:30]:
            title = a.get('title', '')
            date = a.get('date', '')[:10]

            change_type = '其他'
            if '辞职' in title or '离任' in title:
                change_type = '辞职'
            elif '聘任' in title or '任命' in title:
                change_type = '聘任'
            elif '换届' in title:
                change_type = '换届'
            elif '选举' in title:
                change_type = '选举'

            result["executives"].append({
                "date": date,
                "title": title[:80],
                "type": change_type,
            })

        result["total_count"] = len(result["executives"])

    if ak is not None and not result["executives"]:
        try:
            stock_code = secucode.split('.')[0]
            df = ak.stock_gdfx_holding_detail_em(symbol=stock_code)
            if df is not None and not df.empty:
                pass
        except Exception as _sexc:
            record(__name__, '_fetch_management', _sexc, note='静默降级')
            pass

    return result


def _fetch_management_fallback():
    return {
        "executives": [],
        "chairman": None,
        "general_manager": None,
        "cfo": None,
        "board_secretary": None,
        "total_count": 0
    }


def _fetch_management_changes_ak(stock_code):
    """管理层变动 - AKShare"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_ggcg_history(symbol=code)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.head(20).iterrows():
            result.append({
                "announcement_date": str(row.get("公告日期", "")),
                "change_type": str(row.get("变动类型", "")),
                "position": str(row.get("职位", "")),
                "name_before": str(row.get("变更前姓名", "")),
                "name_after": str(row.get("变更后姓名", "")),
            })
        return result
    except Exception as e:
        return []


def _fetch_shareholder_changes_ak(stock_code):
    """股东变动追踪 - AKShare"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_shareholder_change_holdernum(symbol=code)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.head(10).iterrows():
            result.append({
                "date": str(row.get("季度", "")),
                "holder_count": _safe_float(row.get("股东总户数", 0)),
                "avg_hold": _safe_float(row.get("户均持股数", 0)),
                "change_pct": _safe_float(row.get("环比变化", 0)),
            })
        return result
    except Exception as e:
        return []


def _analyze_independent_directors(mgmt):
    """独董分析"""
    execs = mgmt.get("executives", [])
    id_list = [e for e in execs if "独立" in e.get("position", "") or "独立董事" in e.get("title", "")]
    total = len(execs)
    ratio = round(len(id_list) / total * 100, 1) if total > 0 else 0
    has_acct = any("会计" in e.get("education", "") or "财务" in e.get("position", "") or "会计" in e.get("title", "") for e in id_list)
    has_law = any("法律" in e.get("education", "") or "律师" in e.get("position", "") or "法律" in e.get("title", "") for e in id_list)

    if ratio >= 33 and (has_acct or has_law):
        score = "良好"
    elif ratio >= 33:
        score = "一般"
    else:
        score = "⚠️独董占比不足"

    return {"count": len(id_list), "ratio_pct": ratio,
            "has_accounting_expert": has_acct, "has_law_expert": has_law,
            "independence_score": score, "list": id_list}


def _fetch_auditor(secucode, annual_pdf_data=None):
    """审计信息 - 东方财富API + 年报PDF补全"""
    result = {"auditor": None, "fee": None, "opinion": None, "years": 0, "latest_year": None}

    try:
        params = {
            'reportName': 'RPT_F10_AUDIT',
            'columns': 'ALL',
            'filter': f'(SECUCODE="{secucode}")',
            'pageNumber': 1, 'pageSize': 3,
            'sortTypes': -1, 'sortColumns': 'REPORTDATE',
            'source': 'WEB', 'client': 'WEB',
        }
        raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=10)
        records = safe_extract(raw, ['result', 'data'], default=[])
        if records:
            latest = records[0]
            result = {
                "auditor": latest.get('AUDITAGENCY'),
                "fee": latest.get('AUDITFEE'),
                "opinion": latest.get('AUDITOPINION'),
                "years": len(records),
                "latest_year": str(latest.get('REPORTDATE', ''))[:4],
            }
    except Exception as _sexc:
        record(__name__, '_fetch_auditor', _sexc, note='静默降级')
        pass

    if result["auditor"] is None and annual_pdf_data:
        sections = annual_pdf_data.get('sections', {})
        auditor_change = sections.get('auditor_change', {})
        content = auditor_change.get('content', '')
        if content:
            import re
            m = re.search(r'境内会计师事务所名称\s*\n?\s*(.+?)(?:\n|$)', content)
            if m:
                result["auditor"] = m.group(1).strip()
            m = re.search(r'境内会计师事务所报酬（万元）\s*\n?\s*(\d+\.?\d*)', content)
            if m:
                result["fee"] = float(m.group(1))
            m = re.search(r'连续年限\s*\n?\s*(\d+)\s*年', content)
            if m:
                result["years"] = int(m.group(1))
            if not result["opinion"]:
                audit_opinion = annual_pdf_data.get('audit_opinion', '')
                if audit_opinion:
                    result["opinion"] = audit_opinion

    return result


def _fetch_internal_control(secucode, annual_pdf_data=None, financial_data=None):
    """内控信息 - 从年报PDF和财务数据获取"""
    result = {"opinion": "暂无数据", "self_eval": None, "audit_opinion": None, "year": None}

    if financial_data:
        audit_opinion = financial_data.get('audit_opinion', '')
        if audit_opinion:
            result["audit_opinion"] = audit_opinion

    if annual_pdf_data:
        sections = annual_pdf_data.get('sections', {})
        auditor_change = sections.get('auditor_change', {})
        content = auditor_change.get('content', '')
        if content:
            import re
            m = re.search(r'内部控制审计会计师事务所.*?为(.+?)(?:，|。)', content)
            if m:
                result["self_eval"] = m.group(1).strip()

        audit_section = sections.get('audit', {})
        audit_content = audit_section.get('content', '')
        if '内部控制' in audit_content or '内控' in audit_content:
            result["opinion"] = "已披露内控评价报告"

    if result["opinion"] == "暂无数据" and result["audit_opinion"]:
        result["opinion"] = f"审计意见: {result['audit_opinion']}"

    return result


# ============================================================
# 评分与风险
# ============================================================

def _governance_score(result):
    score = 50
    ow = result.get("ownership", {})
    if ow.get("cr1"):
        if ow["cr1"] > 60:
            score -= 15
        elif ow["cr1"] < 30:
            score += 10
    idd = result.get("independent_directors", {})
    if idd.get("ratio_pct", 0) >= 33:
        score += 10
    if idd.get("has_accounting_expert"):
        score += 5
    if idd.get("has_law_expert"):
        score += 5
    aud = result.get("auditor", {})
    if aud.get("auditor"):
        score += 10
    if "非标" in str(aud.get("opinion", "")):
        score -= 20
    pledge = result.get("pledge", {})
    if pledge.get("latest_ratio"):
        if pledge["latest_ratio"] > 0.8:
            score -= 15
        elif pledge["latest_ratio"] > 0.5:
            score -= 5
    ic = result.get("internal_control", {})
    if "缺陷" in str(ic.get("opinion", "")):
        score -= 10
    return max(0, min(100, score))


def _summarize_governance_risks(result):
    risks = []
    ow = result.get("ownership", {})
    if ow.get("cr1") and ow["cr1"] > 60:
        risks.append({"level": "medium", "dim": "治理", "signal": f"一股独大(CR1={ow['cr1']:.1f}%)"})
    pledge = result.get("pledge", {})
    if pledge.get("latest_ratio") and pledge["latest_ratio"] > 0.8:
        risks.append({"level": "high", "dim": "治理", "signal": f"大股东质押比例偏高({pledge['latest_ratio']:.1%})"})
    elif pledge.get("latest_ratio") and pledge["latest_ratio"] > 0.5:
        risks.append({"level": "medium", "dim": "治理", "signal": f"质押比例{pledge['latest_ratio']:.1%}"})
    aud = result.get("auditor", {})
    if aud.get("opinion") and "非标" in str(aud["opinion"]):
        risks.append({"level": "high", "dim": "治理", "signal": f"审计意见: {aud['opinion']}"})
    ic = result.get("internal_control", {})
    if "缺陷" in str(ic.get("opinion", "")):
        risks.append({"level": "medium", "dim": "治理", "signal": "内控存在缺陷"})
    return risks


# ============================================================
# Markdown格式化（保留原有函数）
# ============================================================

def format_markdown(data):
    if not data:
        return "## 公司治理分析\n\n_暂无数据_"

    ow = data.get("ownership", {})
    mgmt = data.get("management", {})
    idd = data.get("independent_directors", {})
    aud = data.get("auditor", {})
    ic = data.get("internal_control", {})
    pledge = data.get("pledge", {})
    top_sh = data.get("top_shareholders", [])
    score = data.get("score", 0)
    risks = data.get("risks", [])
    profile = data.get("company_profile", {})
    circ_sh = data.get("circulate_shareholders", [])
    fund_sh = data.get("fund_shareholders", [])
    mgmt_chg = data.get("management_changes", [])
    sh_chg = data.get("shareholder_changes", [])

    lines = ["## 公司治理深度分析\n"]
    sc = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
    lines.append(f"### 治理评分: {sc} **{score}/100**\n")

    # 公司基本信息（新增）
    if profile:
        lines.append("### 公司基本信息\n")
        if profile.get("name"):
            lines.append(f"- 公司名称: {profile['name']}")
        if profile.get("listing_date"):
            lines.append(f"- 上市日期: {profile['listing_date']}")
        if profile.get("industry"):
            lines.append(f"- 所属行业: {profile['industry']}")
        if profile.get("legal_representative"):
            lines.append(f"- 法人代表: {profile['legal_representative']}")
        if profile.get("registered_capital"):
            lines.append(f"- 注册资本: {profile['registered_capital']}万元")
        lines.append("")

    lines.append("### 股权结构与集中度\n")
    lines.append(f"- 股权类型: {ow.get('type', '未知')} | CR1: **{ow.get('cr1', 'N/A')}%** | CR5: **{ow.get('cr5', 'N/A')}%** | CR10: **{ow.get('cr10', 'N/A')}%**")
    lines.append(f"- 信号: {ow.get('signal', '数据不足')}")
    if top_sh:
        lines.append("\n**前十大股东**:")
        lines.append("| 股东名称 | 持股比例 | 股东类型 |")
        lines.append("|----------|---------|---------|")
        for sh in top_sh[:5]:
            lines.append(f"| {sh.get('name', '?')[:20]} | {sh.get('ratio_pct', '?')}% | {sh.get('type', '?')} |")
    lines.append("")

    # 流通股东（新增）
    if circ_sh:
        lines.append("**流通股东（Top 5）**:")
        lines.append("| 股东名称 | 占流通股比例 |")
        lines.append("|----------|-----------|")
        for sh in circ_sh[:5]:
            lines.append(f"| {sh.get('name', '?')[:20]} | {sh.get('ratio_pct', '?')}% |")
        lines.append("")

    # 基金持股（新增）
    if fund_sh:
        lines.append("**基金持股（Top 5）**:")
        lines.append("| 基金名称 | 占流通股比例 | 持股市值 |")
        lines.append("|----------|-----------|----------|")
        for sh in fund_sh[:5]:
            val = f"{sh.get('value', 0)/10000:.1f}亿" if sh.get('value') else "N/A"
            lines.append(f"| {sh.get('name', '?')[:20]} | {sh.get('ratio_pct', '?')}% | {val} |")
        lines.append("")

    lines.append("### 股份质押\n")
    pl_ratio = pledge.get("latest_ratio")
    if pl_ratio:
        lines.append(f"- 最新质押比例: **{pl_ratio:.1%}** → {pledge.get('signal', '暂无数据')}")
    else:
        lines.append(f"- {pledge.get('signal', '暂无质押数据')}")
    for r in pledge.get("pledge_records", [])[:3]:
        lines.append(f"  - {r.get('pledgor', '?')} → {r.get('institution', '?')}（{r.get('pledge_ratio_total', '?')}%）")
    lines.append("")

    lines.append("### 管理层\n")
    for role, label in [("chairman", "董事长"), ("general_manager", "总经理"), ("cfo", "财务总监"), ("board_secretary", "董秘")]:
        p = mgmt.get(role)
        if p:
            lines.append(f"- {label}: {p.get('name', '?')}（{p.get('education', '?')}）")
    lines.append("")

    # 管理层变动（新增）
    if mgmt_chg:
        lines.append("**管理层变动（最近）**:")
        for chg in mgmt_chg[:5]:
            lines.append(f"- [{chg.get('announcement_date', '')}] {chg.get('change_type', '')}: {chg.get('position', '')}")
        lines.append("")

    lines.append("### 独立董事\n")
    lines.append(f"- 独董人数: {idd.get('count', 0)}，占比: {idd.get('ratio_pct', 0)}%")
    lines.append(f"- 有效性评估: {idd.get('independence_score', '数据不足')}")
    if idd.get("has_accounting_expert"):
        lines.append("- ✓ 有会计背景独董")
    if idd.get("has_law_expert"):
        lines.append("- ✓ 有法律背景独董")
    lines.append("")

    lines.append("### 审计信息\n")
    lines.append(f"- 审计机构: {aud.get('auditor', '未知')}")
    if aud.get("fee"):
        lines.append(f"- 审计费用: {aud['fee']:.0f}万元/年")
    if aud.get("opinion"):
        lines.append(f"- 审计意见: **{aud['opinion']}**")
    if aud.get("years"):
        lines.append(f"- 合作年限: {aud['years']}年")
    lines.append("")

    lines.append("### 内控评价\n")
    lines.append(f"- 内控意见: {ic.get('opinion', '暂无数据')}")
    if ic.get("self_eval"):
        lines.append(f"- 自评结论: {ic['self_eval']}")
    lines.append("")

    # 股东户数变化（新增）
    if sh_chg:
        lines.append("**股东户数趋势**:")
        for s in sh_chg[:4]:
            chg = f"{s.get('change_pct', 0):+.1f}%" if s.get('change_pct') else "N/A"
            lines.append(f"- {s.get('date', '')}: {s.get('holder_count', 0):,.0f}户 {chg}")
        lines.append("")

    if risks:
        lines.append("### 治理风险信号\n")
        for r in risks:
            icon = "🔴" if r["level"] == "high" else "🟡"
            lines.append(f"- {icon} [{r['dim']}] {r['signal']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "002180"
    data = fetch_governance(stock, data_dir="output/test")
    print(format_markdown(data))


def _generate_governance_ai_narrative(data):
    """生成公司治理AI综合解读"""
    if not data:
        return ""

    evidence_parts = []

    if data.get('score') is not None:
        evidence_parts.append(f"治理评分: {data['score']}/100")

    top1 = data.get('top1_holder', {})
    if top1:
        evidence_parts.append(f"控股股东: {top1.get('name', '')} 持股{top1.get('pct', '')}%")

    for key, label in [('cr1', '第一大股东持股'), ('cr5', '前五大股东持股'),
                        ('hhi', '股权集中度HHI'), ('pledge_ratio', '股权质押比例')]:
        if data.get(key) is not None:
            evidence_parts.append(f"{label}: {data[key]}")

    idd = data.get('independent_directors', {})
    if idd:
        evidence_parts.append(f"独董人数: {idd.get('count', 0)}，占比: {idd.get('ratio_pct', 0)}%")
        evidence_parts.append(f"独董有效性: {idd.get('independence_score', 'N/A')}")

    aud = data.get('audit', {})
    if aud:
        evidence_parts.append(f"审计机构: {aud.get('auditor', '未知')}")
        if aud.get('opinion'):
            evidence_parts.append(f"审计意见: {aud['opinion']}")
        if aud.get('fee'):
            evidence_parts.append(f"审计费用: {aud['fee']:.0f}万元/年")

    ic = data.get('internal_control', {})
    if ic and ic.get('opinion'):
        evidence_parts.append(f"内控意见: {ic['opinion']}")

    risks = data.get('risk_signals', [])
    if risks:
        evidence_parts.append(f"治理风险信号: {len(risks)}条")
        for r in risks[:5]:
            evidence_parts.append(f"  [{r.get('dim', '')}] {r.get('signal', '')}")

    if not evidence_parts:
        return ""

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司的公司治理数据，请写一段专业的公司治理分析（200-400字）。

要求：
1. 评估公司治理的整体水平（基于治理评分）
2. 分析股权结构的合理性和稳定性
3. 评估独董制度和审计机制的有效性
4. 关注股权质押、内控等风险信号
5. 提出治理层面的投资关注点

{evidence_block}

请输出公司治理分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券商公司治理分析师，擅长评估上市公司治理结构和风险。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [治理AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建公司治理证据块"""
    if not data:
        return ""
    parts = []
    if data.get('score') is not None:
        parts.append(f"治理评分: {data['score']}/100")
    top1 = data.get('top1_holder', {})
    if top1:
        parts.append(f"控股股东: {top1.get('name', '')} 持股{top1.get('pct', '')}%")
    for key, label in [('cr1', '第一大股东持股'), ('cr5', '前五大股东持股'),
                        ('hhi', '股权集中度HHI'), ('pledge_ratio', '股权质押比例')]:
        if data.get(key) is not None:
            parts.append(f"{label}: {data[key]}")
    idd = data.get('independent_directors', {})
    if idd:
        parts.append(f"独董人数: {idd.get('count', 0)}，占比: {idd.get('ratio_pct', 0)}%")
        parts.append(f"独董有效性: {idd.get('independence_score', 'N/A')}")
    aud = data.get('audit', {})
    if aud:
        parts.append(f"审计机构: {aud.get('auditor', '未知')}")
        if aud.get('opinion'):
            parts.append(f"审计意见: {aud['opinion']}")
    ic = data.get('internal_control', {})
    if ic and ic.get('opinion'):
        parts.append(f"内控意见: {ic['opinion']}")
    risks = data.get('risk_signals', [])
    if risks:
        parts.append(f"治理风险信号: {len(risks)}条")
        for r in risks[:5]:
            parts.append(f"  [{r.get('dim', '')}] {r.get('signal', '')}")
    return '\n'.join(parts)


def generate_report_section(data: dict, batch_analysis=None) -> list:
    if not data:
        return []

    lines = []
    lines.append("## 公司治理")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('governance'):
        ai_narrative = batch_analysis['governance']
    else:
        ai_narrative = _generate_governance_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI公司治理分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    md = format_markdown(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    lines.append(md)

    return lines
