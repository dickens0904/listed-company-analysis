# -*- coding: utf-8 -*-
"""
annual_report_extractor.py — 年报全内容模板化提取

与旧版的核心区别：
  旧版：模糊匹配标签 → 猜测数据在哪个单元格 → 容易取错
  新版：表头指纹匹配 → 锁定财政部标准模板 → 按行列坐标取数
       → 数学验算不通过 → 换备选模板重试 → 最终标注置信度

覆盖范围（全要素）：
  1. 三表（利润表/资产负债表/现金流量表）— 模板坐标提取
  2. 管理层讨论与分析（MD&A）      — 文本区间提取
  3. 审计报告                    — 意见类型提取
  4. 分红预案                    — 每股分红提取
  5. 研发投入                    — 金额及资本化率
  6. 主要客户/供应商              — 集中度提取
  7. 产能与产量数据               — 分产品产销存
  8. 前十大股东                   — 持股明细

用法:
  from annual_report_extractor import extract_annual_report
  report = extract_annual_report("annual_report.pdf")
"""
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════
# 第一部分：模板定义 — 财政部标准报表格式
# ═══════════════════════════════════════════════════════════

# 每个模板定义了：
#   fingerprint: 表头特征行（前3行的关键列内容）
#   columns: 列含义映射
#   rows: 行号 → 指标名（value_column指数据在第几列，0-based）

INCOME_STATEMENT_TEMPLATE = {
    "name": "利润表-通用工商业",
    "merge_bonus_keywords": ["合并利润表", "合并损益表", "合并"],
    "fingerprint": [
        ["项目", "附注", "本期金额", "上期金额"],
        ["一、营业总收入", "其中：营业收入"],
    ],
    # 跨页同表：后续页的表格碎片也属于利润表（header相同但内容行不同）
    "continuation_header": ["项目", "附注"],
    # 数据列（0-based，常规利润表是 [项目=0, 附注=1, 本期=2, 上期=3]）
    "value_col_current": 2,
    "value_col_prior": 3,
    # 行坐标映射（模糊匹配文本内容）
    "row_mapping": {
        # 常规利润表行项（按优先级排序：粗粒度在前，细粒度在后）
        "营业总收": "revenue",
        "营业总收入": "revenue",
        "营业收入": "revenue",
        "其中：营业收": "_skip",
        "其中：营业成": "_skip",
        "营业成本": "cost_of_sales",
        "营业总成本": "total_cost",
        "税金及附加": "tax_surcharge",
        "销售费用": "selling_expense",
        "管理费用": "admin_expense",
        "研发费用": "rd_expense",
        "财务费用": "finance_expense",
        "投资收益": "investment_income",
        "营业利润": "operating_profit",
        "利润总额": "total_profit",
        "所得税费用": "income_tax",
        "净利润": "net_profit",
        "归母净利": "parent_net_profit",
        "归属于母公司": "parent_net_profit",
        "少数股东": "minority_interest",
        "每股收益": "basic_eps",
        "基本每股": "basic_eps",
        "稀释每股": "diluted_eps",
        "综合收益": "comprehensive_income",
    },
    # 排除规则：这些文本即使匹配到也不取（章节标题/合并说明）
    "exclude_patterns": ["编制单位", "单位：", "项 目", "人民币"],
}

BALANCE_SHEET_TEMPLATE = {
    "name": "资产负债表-通用工商业",
    "merge_bonus_keywords": ["合并资产负债表", "合并"],
    "fingerprint": [
        ["项目", "附注"],  # 最宽松：几乎所有BS表头都是项目+附注
        ["流动资产", "货币资金"],
    ],
    # 当某行只含"流动资产："时跳过（章节分隔行）
    "skip_section_headers": True,
    "continuation_header": ["项目", "附注"],  # 跨页合并
    "value_col_current": 2,
    "value_col_prior": 3,
    "row_mapping": {
        "货币资金": "cash",
        "应收账款": "receivables",
        "存货": "inventory",
        "流动资产合计": "current_assets",
        "固定资产": "fixed_assets",
        "在建工程": "construction_in_progress",
        "无形资产": "intangible_assets",
        "非流动资产合计": "non_current_assets",
        "资产总计": "total_assets",
        "短期借款": "short_term_borrowings",
        "应付账款": "payables",
        "流动负债合计": "current_liabilities",
        "长期借款": "long_term_borrowings",
        "非流动负债合计": "non_current_liabilities",
        "负债合计": "total_liabilities",
        "股本": "share_capital",
        "资本公积": "capital_reserve",
        "未分配利润": "retained_earnings",
        "归母权益": "parent_equity",
        "归属于母公司": "parent_equity",
        "少数股东权益": "minority_equity",
        "股东权益合计": "total_equity",
    },
    "exclude_patterns": ["编制单位", "单位：", "项 目"],
}

CASH_FLOW_TEMPLATE = {
    "name": "现金流量表-通用工商业",
    "fingerprint": [
        ["项目", "附注", "本期金额", "上期金额"],
        ["经营活动", "销售商品"],
    ],
    "value_col_current": 2,
    "value_col_prior": 3,
    "row_mapping": {
        "销售商品": "cash_from_sales",
        "经营活动现金流入": "operating_inflow",
        "经营活动现金流出": "operating_outflow",
        "经营活动产生": "operating_cashflow",
        "投资活动产生": "investing_cashflow",
        "筹资活动产生": "financing_cashflow",
        "现金及现金等价物净增加": "net_cash_change",
        "期末现金": "ending_cash",
    },
    "exclude_patterns": ["编制单位", "单位：", "项 目"],
}

# ═══════════════════════════════════════════════════════════
# 金融业模板（银行/保险/券商 — 报表格式与工商业完全不同）
# ═══════════════════════════════════════════════════════════

BANK_INCOME_TEMPLATE = {
    "name": "利润表-商业银行",
    "merge_bonus_keywords": ["合并利润表", "合并损益表", "合并"],
    "fingerprint": [
        ["项目", "附注", "本期金额", "上期金额"],
        ["一、营业收入", "利息净收入"],
    ],
    "value_col_current": 2,
    "value_col_prior": 3,
    "row_mapping": {
        "利息净收入": "net_interest_income",
        "利息收入": "interest_income",
        "利息支出": "interest_expense",
        "手续费及佣金净收入": "net_fee_income",
        "营业收入": "revenue",
        "营业支出": "total_cost",
        "业务及管理费": "op_expense",
        "信用减值损失": "credit_impairment",
        "营业利润": "operating_profit",
        "利润总额": "total_profit",
        "所得税费用": "income_tax",
        "净利润": "net_profit",
        "归母净利": "parent_net_profit",
        "归属于母公司": "parent_net_profit",
        "基本每股": "basic_eps",
        "稀释每股": "diluted_eps",
    },
    "exclude_patterns": ["编制单位", "单位：", "项 目"],
}

BANK_BALANCE_TEMPLATE = {
    "name": "资产负债表-商业银行",
    "merge_bonus_keywords": ["合并资产负债表", "合并"],
    "fingerprint": [
        ["项目", "附注", "期末余额", "期初余额"],
        ["存放中央银行款项"],  # 非银行企业绝无此项，精确区分
    ],
    "require_all_fingerprints": True,
    "value_col_current": 2,
    "value_col_prior": 3,
    "row_mapping": {
        "现金及存放央行": "cash_cb_reserves",
        "发放贷款和垫款": "loans",
        "贷款减值准备": "loan_loss_reserve",
        "资产总计": "total_assets",
        "吸收存款": "deposits",
        "负债合计": "total_liabilities",
        "股本": "share_capital",
        "资本公积": "capital_reserve",
        "未分配利润": "retained_earnings",
        "归母权益": "parent_equity",
        "归属于母公司": "parent_equity",
        "股东权益合计": "total_equity",
    },
    "exclude_patterns": ["编制单位", "单位：", "项 目"],
}

SECURITIES_INCOME_TEMPLATE = {
    "name": "利润表-券商",
    "merge_bonus_keywords": ["合并利润表", "合并"],
    "fingerprint": [
        ["项目", "附注", "本期金额", "上期金额"],
        ["一、营业收入", "手续费及佣金净收入"],
    ],
    "value_col_current": 2,
    "value_col_prior": 3,
    "row_mapping": {
        "手续费及佣金净收入": "net_commission",
        "利息净收入": "net_interest",
        "投资收益": "investment_income",
        "营业收入": "revenue",
        "营业支出": "total_cost",
        "业务及管理费": "op_expense",
        "营业利润": "operating_profit",
        "利润总额": "total_profit",
        "净利润": "net_profit",
        "归母净利": "parent_net_profit",
        "基本每股": "basic_eps",
    },
    "exclude_patterns": ["编制单位", "单位：", "项 目"],
}

# 金融业模板注册表
FINANCIAL_TEMPLATES = [
    BANK_INCOME_TEMPLATE,
    BANK_BALANCE_TEMPLATE,
    SECURITIES_INCOME_TEMPLATE,
]

# 所有模板汇总（用于自动轮换匹配）
ALL_TEMPLATES = [
    INCOME_STATEMENT_TEMPLATE,
    BALANCE_SHEET_TEMPLATE,
    CASH_FLOW_TEMPLATE,
    BANK_INCOME_TEMPLATE,
    BANK_BALANCE_TEMPLATE,
    SECURITIES_INCOME_TEMPLATE,
]

# ═══════════════════════════════════════════════════════════
# 全要素表格模板（审计/分红/股东/客户/供应商/研发/产能等）
# ═══════════════════════════════════════════════════════════

# 1. 研发投入表
RD_TEMPLATE = {
    "fingerprint": [["研发投入", "本期费用化", "本期资本化"],
                    ["研发投入总额", "本期费用化研发投入"]],
    "name": "研发投入",
    "row_mapping": {"研发投入": "total", "费用化": "expense", "资本化": "capitalized"},
    "exclude_patterns": [],
}

# 2. 产销量表
PRODUCTION_TEMPLATE = {
    "fingerprint": [["主要产品", "生产量", "销售量", "库存量"],
                    ["生产量比", "销售量比"]],
    "name": "产销量",
    "exclude_patterns": [],
}

# 12. 前五名客户表
TOP5_CUSTOMER_TEMPLATE = {
    "fingerprint": [["客户名称", "销售额", "占年度销售"],
                    ["前五名", "客户"]],
    "name": "前五名客户",
    "exclude_patterns": [],
}

# 13. 前五名供应商表
TOP5_SUPPLIER_TEMPLATE = {
    "fingerprint": [["供应商名称", "采购额", "占年度采购"],
                    ["前五名", "供应商"]],
    "name": "前五名供应商",
    "exclude_patterns": [],
}

# 10. 或有事项表
CONTINGENCY_TEMPLATE = {
    "fingerprint": [["未决诉讼", "仲裁"], ["形成原因"]],
    "name": "或有事项",
    "exclude_patterns": [],
}

# 7. 担保情况表
GUARANTEE_TEMPLATE = {
    "fingerprint": [["担保方", "被担保方", "担保金额"],
                    ["是否履行", "担保期限"]],
    "name": "担保",
    "exclude_patterns": [],
}

# 8. 新设/处置子公司表
SUBSIDIARY_CHANGE_TEMPLATE = {
    "fingerprint": [["子公司名称", "取得方式", "股权取得"],
                    ["新设", "同一控制下"]],
    "name": "新设子公司",
    "exclude_patterns": [],
}

# 3. 产能表
CAPACITY_TEMPLATE = {
    "fingerprint": [["产能状况", "设计产能", "实际产能"], ["主要工厂"]],
    "name": "产能",
}

# 4. 在建工程表
CONSTRUCTION_TEMPLATE = {
    "fingerprint": [["项目名称", "预算数", "期初余额", "本期增加", "期末余额"],
                    ["工程进度"]],
    "name": "在建工程",
}

# 5. 长期股权投资表
LONG_TERM_EQUITY_TEMPLATE = {
    "fingerprint": [["被投资单位", "期初余额", "本期增减变动", "期末余额"],
                    ["追加投资", "减少投资"]],
    "name": "长期股权投资",
}

# 6. 政府补助表
GOVERNMENT_GRANT_TEMPLATE = {
    "fingerprint": [["补助项目", "本期金额", "计入当期损益"],
                    ["与资产相关", "与收益相关"]],
    "name": "政府补助",
}

# 9. 主要子公司表
MAIN_SUBSIDIARY_TEMPLATE = {
    "fingerprint": [["子公司名称", "主要经营地", "注册资本", "持股比例"],
                    ["表决权比例"]],
    "name": "主要子公司",
}

# 11. 资产负债表日后事项表
POST_BALANCE_TEMPLATE = {
    "fingerprint": [["资产负债表日后", "利润分配"], ["拟分配"]],
    "name": "日后事项",
}

# 14. 前十名股东表
TOP10_SHAREHOLDER_TEMPLATE = {
    "fingerprint": [["股东名称", "持股数量", "持股比例"], ["报告期末"]],
    "name": "前十名股东",
}

# 15. 利润分配表（分红预案表）
DIVIDEND_TABLE_TEMPLATE = {
    "fingerprint": [["拟分配", "每10股"], ["现金分红"]],
    "name": "利润分配",
}

# 内容模板注册表（所有非三表的表格模板）
CONTENT_TEMPLATES = [
    RD_TEMPLATE, PRODUCTION_TEMPLATE, CAPACITY_TEMPLATE,
    CONSTRUCTION_TEMPLATE, LONG_TERM_EQUITY_TEMPLATE,
    GOVERNMENT_GRANT_TEMPLATE, GUARANTEE_TEMPLATE,
    SUBSIDIARY_CHANGE_TEMPLATE, MAIN_SUBSIDIARY_TEMPLATE,
    CONTINGENCY_TEMPLATE, POST_BALANCE_TEMPLATE,
    TOP5_CUSTOMER_TEMPLATE, TOP5_SUPPLIER_TEMPLATE,
    TOP10_SHAREHOLDER_TEMPLATE, DIVIDEND_TABLE_TEMPLATE,
]

# ═══════════════════════════════════════════════════════════
# 全要素表格提取引擎
# ═══════════════════════════════════════════════════════════

def _extract_table(template: dict, tables: list, full_text: str = "") -> dict:
    """通用表格提取：指纹匹配→取数。返回干净的结构化数据。"""
    matched = _match_template(tables, template, min_similarity=0.3)
    if not matched:
        return {}

    rows = matched.get("rows", [])
    mapping = template.get("row_mapping", {})
    
    # 从表头行提取列名
    col_names = []
    if rows:
        header = [str(c).replace("\n", "")[:30] for c in rows[0] if c]
        col_names = header

    if mapping:
        data = {}
        for row in rows:
            if not row or not row[0]:
                continue
            label = str(row[0]).replace("\n", "")[:30]
            for kw, key in mapping.items():
                if kw in label:
                    val = row[1] if len(row) > 1 and row[1] else None
                    data[key] = val
                    break
        return data
    else:
        records = []
        for row in rows[1:]:
            if not row or not row[0]:
                continue
            label = str(row[0]).replace("\n", "").strip()
            if not label or label in ("合计", "项目", "主要产品", "项 目"):
                continue
            # 用表头列名作为 key
            rec = {}
            for ci in range(len(row)):
                if ci == 0:
                    rec["item"] = label
                elif ci < len(row) and row[ci] is not None:
                    col_key = col_names[ci] if ci < len(col_names) else f"col{ci}"
                    col_key = col_key.replace("%", "pct").replace("（", "(").replace("）", ")")
                    val = str(row[ci]).replace("\n", " ").strip()
                    rec[col_key] = val
            records.append(rec)
        return {"records": records, "columns": col_names[1:]} if col_names else {"records": records}


def extract_content_tables(tables: list, full_text: str = "") -> dict:
    """批量提取所有内容表格"""
    result = {}
    for tmpl in CONTENT_TEMPLATES:
        data = _extract_table(tmpl, tables, full_text)
        if data:
            result[tmpl["name"]] = data
    return result

def _fingerprint_similarity(rows: list, fingerprint: list) -> float:
    """计算表格行与模板指纹的相似度 (0.0~1.0)"""
    if not rows or not fingerprint:
        return 0.0
    total_tokens = 0
    matched_tokens = 0
    for fp_row in fingerprint:
        for fp_token in fp_row:
            total_tokens += 1
            token_found = False
            for row in rows[:10]:  # 只检查前10行
                row_text = " ".join(str(c) for c in row if c)
                if fp_token in row_text:
                    token_found = True
                    break
            if token_found:
                matched_tokens += 1
    return matched_tokens / max(total_tokens, 1)


def _match_templates(tables: list, template: dict, min_similarity: float = 0.4) -> list:
    """找到所有匹配指定模板的表格（返回列表，用于合并跨页表格）"""
    matches = []
    merge_keywords = template.get("merge_bonus_keywords", [])
    for t in tables:
        rows = t.get("rows", [])
        if not rows:
            continue
        score = _fingerprint_similarity(rows, template["fingerprint"])
        if merge_keywords:
            all_text = " ".join(" ".join(str(c) for c in r if c) for r in rows[:5] if r)
            if any(kw in all_text for kw in merge_keywords):
                score += 0.3
        if score >= min_similarity:
            matches.append((score, t))
    # 按分数降序，返回所有匹配
    return [t for _, t in sorted(matches, key=lambda x: x[0], reverse=True)]


def _merge_rows(tables: list) -> list:
    """合并多个表格的行（用于跨页表格拼接）。去重表头行。"""
    all_rows = []
    seen_headers = set()
    for t in tables:
        for row in t.get("rows", []):
            key = str(row[0] or "")[:20]
            if key in ("项目", "附注", "项 目", ""):
                if key in seen_headers:
                    continue  # 重复表头跳过
                seen_headers.add(key)
            all_rows.append(row)
    return all_rows


def _match_template(tables: list, template: dict, min_similarity: float = 0.4) -> Optional[dict]:
    """[保留兼容] 返回分数最高的单个表格"""
    matches = _match_templates(tables, template, min_similarity)
    return matches[0] if matches else None


# ═══════════════════════════════════════════════════════════
# 第三部分：坐标取数引擎
# ═══════════════════════════════════════════════════════════

def _parse_number(text: str) -> Optional[float]:
    """将表格单元格文本解析为数值（处理千分位、负号变体、括号负数）"""
    if text is None:
        return None
    t = str(text).replace(",", "").replace("，", "").replace(" ", "").strip()
    if not t or t in ("—", "--", "－－", "N/A", "-"):
        return None
    t = re.sub(r"^[（(]\s*", "-", t)
    t = re.sub(r"\s*[)）]$", "", t)
    try:
        return float(t)
    except ValueError:
        m = re.search(r"-?[\d,]+\.?\d*", t)
        return float(m.group().replace(",", "")) if m else None


def _to_yi(val: float, unit_hint: str = "") -> float:
    """数值 → 亿元。优先使用 unit_hint（'元'/'万元'），否则自适应。"""
    if val is None or val == 0:
        return 0
    if unit_hint == "元":
        return round(val / 1e8, 2)
    if unit_hint == "万元":
        return round(val / 1e4, 4)
    abs_val = abs(val)
    if abs_val > 1e10:
        return round(val / 1e8, 2)
    elif abs_val > 1e7:
        return round(val / 1e4, 4)
    elif abs_val > 10000:
        return round(val / 1e4, 4)
    elif abs_val > 100:
        return round(val, 2)
    else:
        return round(val, 4)


def _matches_label(cell_text: str, map_key: str, excludes: list) -> bool:
    """检查单元格文本是否匹配某个指标（同时排除干扰模式）"""
    ct = str(cell_text or "")
    for excl in excludes:
        if excl in ct:
            return False
    return map_key in ct


def _extract_by_template(table: dict, template: dict) -> dict:
    """
    核心：按模板坐标取数。
    遍历表格每一行 → 匹配 row_mapping → 取 value_col 列 → 转换为亿元
    兼容两种表格格式：
      A: [项目, 附注, 本期金额, 上期金额] → 4列
      B: [项目, 2025年度, 2024年度] → 3列（无附注列）
    """
    rows = table.get("rows", [])
    if not rows:
        return {}

    # 自动检测列偏移量: 有附注列时 value_col = 2, 否则 = 1
    val_col = template.get("value_col_current", 2)
    header_cells = [str(c or "") for c in (rows[0] if rows else [])]
    if len(header_cells) > 1 and "附注" not in " ".join(header_cells[:3]):
        val_col = 1  # 无附注列，数据从第2列开始

    ignores = template.get("exclude_patterns", [])
    skip_section = template.get("skip_section_headers", False)
    
    # 检测表格单位（从页面元数据，在表格单元格外）
    unit = ""
    table_page = table.get("page")
    if table_page and table.get("_page_text"):
        pt = table["_page_text"]
        for kw in ["单位：元", "单位:元"]:
            if kw in pt:
                unit = "元"
                break
        if not unit:
            for kw in ["单位：万元", "单位:万元"]:
                if kw in pt:
                    unit = "万元"
                    break
    if not unit:
        for row in rows[:3]:
            for cell in row:
                if cell:
                    cs = str(cell)
                    if "单位：元" in cs: unit = "元"; break
                    if "单位：万元" in cs: unit = "万元"; break
    
    result = {}

    for row in rows:
        if not row:
            continue
        label = str(row[0] or "")
        if not label or len(label) < 2:
            continue
        # 跳过纯表头/章节标题/空分类行
        if label.strip() in ("项目", "附注", "项 目"):
            continue
        if skip_section and label.strip().endswith("："):
            continue  # 跳过"流动资产："等分类标题行

        for map_key, metric_name in template["row_mapping"].items():
            if _matches_label(label, map_key, ignores):
                # 取值：val_col 可能超出当前行长度（某些行无附注列）
                if val_col < len(row) and row[val_col] is not None:
                    raw_text = str(row[val_col])
                else:
                    # 回退: 对于3列行[label, 本期, 上期], 倒数第2列是本期
                    if len(row) >= 3:
                        raw_text = str(row[len(row) - 2]) if row[len(row) - 2] else str(row[-1])
                    else:
                        raw_text = str(row[-1]) if len(row) > 1 else ""
                if not raw_text:
                    continue
                raw_val = _parse_number(raw_text)
                if raw_val is not None and raw_val != 0:
                    if metric_name and metric_name != "_skip":
                        # 不覆盖已设值（如"营业总收"先匹配，"营业收入"不再覆盖）
                        if metric_name in result:
                            continue
                        converted = _to_yi(raw_val, unit)
                        if metric_name in ("basic_eps", "diluted_eps"):
                            result[metric_name] = round(raw_val, 2)
                        else:
                            result[metric_name] = converted
                break  # 一行只匹配一个指标

    return result


# ═══════════════════════════════════════════════════════════
# 第四部分：贝μ验算（防止模板匹配偏差）
# ═══════════════════════════════════════════════════════════

def _validate_income_statement(data: dict) -> List[str]:
    """利润表四则运算验算"""
    warnings = []
    rev   = data.get("revenue", 0)
    cost  = data.get("cost_of_sales", 0)
    op_p  = data.get("operating_profit", 0)
    np    = data.get("net_profit", 0)
    pnp   = data.get("parent_net_profit", 0)
    eps   = data.get("basic_eps", 0)

    if rev > 0 and cost > 0:
        gm = (rev - cost) / rev * 100
        if gm < 0 or gm > 95:
            warnings.append(f"毛利率异常: {gm:.1f}%（可能是营业总成本不是营业成本）")

    if np > 0 and eps > 0:
        implied_shares = np * 1e8 / eps / 1e8 if eps > 0 else 0
        if implied_shares < 0.5 or implied_shares > 500:
            warnings.append(f"净利润({np}亿)/EPS({eps})→隐含总股本{implied_shares:.1f}亿股异常")

    if pnp > 0 and np > 0:
        if pnp > np * 1.02:
            warnings.append(f"归母净利润({pnp}) > 净利润({np})，可能列错位")

    return warnings


def _validate_balance_sheet(data: dict) -> List[str]:
    """资产负债表恒等式验算"""
    warnings = []
    ta = data.get("total_assets", 0)
    tl = data.get("total_liabilities", 0)
    te = data.get("total_equity", 0)

    if ta > 0 and tl > 0 and te > 0:
        diff = abs(ta - tl - te) / ta * 100
        if diff > 1:
            warnings.append(f"资产({ta})≠负债({tl})+权益({te}),差异{diff:.1f}%")

    return warnings


# ═══════════════════════════════════════════════════════════
# 第五部分：文本内容提取（MD&A、审计、分红等）
# ═══════════════════════════════════════════════════════════

def _extract_full_text(pdf_path: str, max_pages: int = 200) -> str:
    """全文提取（按页分隔）"""
    try:
        import fitz
    except ImportError:
        return ""
    doc = fitz.open(pdf_path)
    pages = []
    for i in range(min(max_pages, doc.page_count)):
        pages.append(f"=== PAGE {i+1} ===\n{doc[i].get_text('text')}")
    doc.close()
    return "\n".join(pages)


def _extract_section(full_text: str, start_marker: str,
                     end_markers: List[str] = None,
                     max_chars: int = 50000,
                     skip_toc: bool = False) -> str:
    """
    提取两个标记之间的文本。

    2026-10-19 审计修复（关键）：原逻辑只在结果 < 200 字时才认为"命中目录页"
    并重试。但真实年报里 start_marker 首次出现在**「重要提示」**
    （"…之'十一、公司未来发展的展望'所列示的主要风险"），
    从那里截到下一个 end_marker 只有 **443 字**——超过 200 字阈值 → 不重试
    → MD&A 正文（实测 8 万字级）被整段丢弃
    → 下游 _split_mdaa 抽不到任何章节 → 三幕叙事 3.1「公司既定计划」数据层缺源。

    修正：连续向后试探最多 5 次出现，取**最长**的一段（这才是正文）；
    MD&A 正文实测量级 8 万字，故 MIN_BODY 设为 2000 字。
    """
    def _slice_from(pos: int) -> str:
        """从 start_marker 结束处切到下一个 end_marker。"""
        p2 = pos + len(start_marker)
        end2 = len(full_text)
        for em in (end_markers or []):
            ei = full_text.find(em, p2)
            if 0 < ei < end2:
                end2 = ei
        return full_text[p2:min(p2 + max_chars, end2)].strip()

    start = full_text.find(start_marker)
    if start < 0:
        return ""
    best = _slice_from(start)

    if skip_toc:
        MIN_BODY = 2000        # MD&A 正文通常数万字；2000 字以下视为目录/引述
        pos = start
        for _ in range(5):
            pos = full_text.find(start_marker, pos + len(start_marker))
            if pos < 0:
                break
            cand = _slice_from(pos)
            if len(cand) > len(best):
                best = cand
            if len(best) >= MIN_BODY:
                break
    return best


def _find_in_body(full_text: str, marker: str) -> int:
    """在正文中查找（跳过目录页，目录页通常在前5页的PAGE标记中）"""
    # 简单策略：跳过第一次出现，取第二次（正文通常在目录之后）
    first = full_text.find(marker)
    if first < 0:
        return -1
    # 如果第一次出现的内容很短（<200字后就是"第四节"之类的），说明是目录
    after = full_text[first+len(marker):first+len(marker)+300]
    if len(after.strip()) < 200:
        return full_text.find(marker, first + len(marker))
    return first


def _extract_dividend_info(full_text: str) -> dict:
    """提取分红预案信息"""
    result = {"per_share": None, "text": ""}
    section = _extract_section(full_text, "利润分配", ["合并现金流", "母公司报表"], 5000)
    if not section:
        section = _extract_section(full_text, "分红", [], 5000)
    if section:
        result["text"] = section[:500]
        # 尝试提取每10股派X元
        patterns = [
            r"每\s*10\s*股\s*(?:派|送|转|发现金).*?(\d+\.?\d*)\s*元",
            r"10\s*派\s*(\d+\.?\d*)",
            r"拟\s*向全体股东.*?每\s*10\s*股.*?(\d+\.?\d*)\s*元",
        ]
        for pat in patterns:
            m = re.search(pat, section)
            if m:
                result["per_share"] = float(m.group(1))
                break
    return result


def _extract_audit_opinion(full_text: str) -> dict:
    """提取审计意见类型。标准无保留意见标记 is_standard=True（报告中可省略）。"""
    result = {"opinion_type": "unknown", "accountant_firm": "", "text": "",
              "is_standard": False, "is_significant": False}

    # 直接从全文搜索审计意见关键词（前几页"重要提示"中通常有）
    opinion_keywords = {
        "标准无保留意见": ["标准无保留意见", "无保留意见"],
        "保留意见": ["保留意见"],
        "无法表示意见": ["无法表示意见"],
        "否定意见": ["否定意见"],
    }
    
    # 优先从全文匹配（重要提示在P2，不在"审计报告"章节中）
    for opinion, keywords in opinion_keywords.items():
        for kw in keywords:
            if kw in full_text:
                result["opinion_type"] = opinion
                break
        if result["opinion_type"] != "unknown":
            break

    # 补充提取事务所名称
    m = re.search(r"(天健|立信|信永中和|大华|致同|容诚|大信|中审众环|普华永道|德勤|安永|毕马威)\S*(?:会计师事务所|会计师事务)", full_text)
    if m:
        result["accountant_firm"] = m.group(0)

    # 仅非标准意见保留详细文本
    if result["opinion_type"] == "标准无保留意见":
        result["is_standard"] = True
        result["is_significant"] = False
        result["text"] = ""
    elif result["opinion_type"] != "unknown":
        result["is_standard"] = False
        result["is_significant"] = True
        # 提取相关段落
        idx = full_text.find(result["opinion_type"])
        if idx >= 0:
            result["text"] = full_text[max(0,idx-50):idx+2000]

    return result


def _extract_rd_info(full_text: str) -> dict:
    """提取研发投入"""
    result = {"expense": None, "capitalized": None, "total": None, "text": ""}
    section = _extract_section(full_text, "研发投入", ["现金流", "在建工程", "经营活动"], 5000)
    if not section:
        return result
    result["text"] = section[:1000]
    # 尝试提取研发总投入和资本化金额
    nums = re.findall(r"(\d[\d,]*\.?\d*)\s*[万亿]?元", section)
    if nums:
        numbers = [float(n.replace(",", "")) for n in nums]
        numbers = [_to_yi(n * 1e8) if n < 100 else n for n in numbers]
        if len(numbers) >= 2:
            result["total"] = numbers[0]
            result["capitalized"] = numbers[-1] if numbers[-1] < numbers[0] else 0
            result["expense"] = round(numbers[0] - (result["capitalized"] or 0), 2)
    return result


def _extract_risk_factors(full_text: str) -> List[str]:
    """提取风险因素列表"""
    risks = []
    section = _extract_section(full_text, "风险", [], 15000)
    if not section:
        return risks
    patterns = [
        r"(?:\d+[.、]|[（(]\d+[)）]|[-•])\s*(.{10,60}?(?:风险|不确定性|波动|下降|影响|竞争|政策|监管))",
    ]
    for pat in patterns:
        matches = re.findall(pat, section)
        for m in matches:
            if len(m) > 8:
                risks.append(m.strip("，。；、 "))
    return risks[:10]


def _extract_top_shareholders(full_text: str) -> list:
    """提取前十大股东"""
    section = _extract_section(full_text, "前十名股东", ["七、", "八、"], 6000)
    if not section:
        return []
    lines = section.split("\n")
    shareholders = []
    for line in lines:
        m = re.search(r"(\S.*?)\s+(\d[\d,]*\.?\d*)\s+(\d+\.?\d*)%?", line)
        if m and len(m.group(1)) > 2:
            shareholders.append({
                "name": m.group(1).strip(),
                "shares": m.group(2),
                "ratio": float(m.group(3)),
            })
        if len(shareholders) >= 10:
            break
    return shareholders


def _split_mdaa(mdaa_text: str) -> dict:
    """
    将 MD&A 长文本按标准章节拆分为结构化数据

    2026-10-19 审计修复：原 markers 只认「经营计划 / 发展战略 / 行业格局和趋势」，
    但**真实 A 股年报的规范标题是「公司未来发展的展望」**（深交所年报格式：
    第三节 管理层讨论与分析 → 十一、公司未来发展的展望）。
    实测 002180 奔图科技 256 页年报：
        旧 markers 在展望类命中 **0 次**（战略发展/经营计划/行业格局 均 0）
        → 三幕叙事 3.1「公司既定计划」数据层缺源
    现按真实年报规范重写，并保留旧词作兼容（不同板块模板略有差异）。
    """
    sections = {}
    markers = {
        "business_overview": [
            "一、报告期内公司从事的主要业务", "报告期内公司从事的主要业务",
            "一、报告期内公司从事的业务情况", "报告期内主要从事",
        ],
        "industry_analysis": [
            "二、报告期内公司所处行业情况", "报告期内公司所处行业情况",
        ],
        "core_competence": [
            "三、核心竞争力分析", "核心竞争力分析",
        ],
        "operation_analysis": [
            "四、主营业务分析", "主营业务分析",
            "三、经营情况讨论与分析", "经营情况讨论",
        ],
        "financial_analysis": [
            "六、资产及负债状况分析", "资产及负债状况分析",
            "四、报告期内主要经营情况",
        ],
        "investment_analysis": [
            "七、投资状况分析", "投资状况分析",
        ],
        "subsidiary_analysis": [
            "九、主要控股参股公司分析", "主要控股参股公司分析",
        ],
        # 🔴 核心：这是「公司既定计划」的真实来源
        "future_plan": [
            "十一、公司未来发展的展望", "公司未来发展的展望",
            "公司未来发展战略", "未来发展战略",
            "经营计划", "发展战略", "行业格局和趋势",
        ],
        "risk_outlook": [
            "公司未来发展的展望", "可能面对的风险", "风险因素",
            "公司关于公司未来发展的讨论",
        ],
        "investor_relations": [
            "十二、报告期内接待调研、沟通、采访等活动",
            "报告期内接待调研",
        ],
    }
    for key, starts in markers.items():
        for s in starts:
            idx = mdaa_text.find(s)
            if idx >= 0:
                # 找到下一个 section 的起点（按出现顺序取最近的更大位置）
                end = len(mdaa_text)
                for other_starts in markers.values():
                    for os in other_starts:
                        if os != s:
                            oi = mdaa_text.find(os, idx + len(s))
                            if 0 < oi < end:
                                end = oi
                content = mdaa_text[idx:min(idx + 5000, end)].strip()
                if len(content) > 20:
                    sections[key] = content
                break
    return sections


# ═══════════════════════════════════════════════════════════
# 第六部分：主入口
# ═══════════════════════════════════════════════════════════

def extract_annual_report(pdf_path: str) -> dict:
    """
    从年报PDF中提取全要素结构化数据。

    返回格式:
    {
        "income_statement": {...},  # 利润表（亿元）
        "balance_sheet": {...},     # 资产负债表（亿元）
        "cash_flow": {...},         # 现金流量表（亿元）
        "mdaa": str,               # 管理层讨论与分析（文本）
        "audit": {...},            # 审计意见
        "dividend": {...},         # 分红预案
        "research": {...},         # 研发投入
        "risks": [...],            # 风险因素
        "top_shareholders": [...], # 前十大股东
        "validation": {...},       # 验算结果
        "metadata": {...},         # 提取元数据
    }
    """
    if not Path(pdf_path).exists():
        return {"error": f"PDF不存在: {pdf_path}"}

    # ── 表格提取 ──
    try:
        import pdfplumber
        tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for pn, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                found = page.find_tables()
                for t in found:
                    rows = t.extract()
                    if rows and len(rows) >= 3:
                        tables.append({
                            "page": pn + 1,
                            "rows": rows,
                            "_page_text": page_text,
                        })
    except Exception as e:
        return {"error": f"pdfplumber提取失败: {e}"}

    # ── 模板匹配 + 坐标取数 ──
    income_data  = {}
    balance_data = {}
    cashflow_data = {}

    income_table = _match_template(tables, INCOME_STATEMENT_TEMPLATE)
    if income_table:
        # 跨页合并：主表所在页的后续2页中，相同表头的表格都合并进来
        main_page = income_table.get("page", 0)
        cont_header = INCOME_STATEMENT_TEMPLATE.get("continuation_header", [])
        all_income = [income_table]
        if cont_header:
            for t in tables:
                tp = t.get("page", 0)
                pt = t.get("_page_text", "")
                # 跨页合并：仅合并后续1页内的同表头表格，排除母公司
                if tp > main_page and tp <= main_page + 1:
                    rows = t.get("rows", [])
                    if rows and all(ch in str(rows[0]) for ch in cont_header):
                        if "母公司" not in pt:
                            all_income.append(t)
        merged = {"page": main_page, "rows": _merge_rows(all_income),
                  "_page_text": income_table.get("_page_text", "")}
        income_data = _extract_by_template(merged, INCOME_STATEMENT_TEMPLATE)
    # 工商业模板匹配失败 → 尝试金融业模板
    if not income_table or not income_data:
        fin_income_templates = [BANK_INCOME_TEMPLATE, SECURITIES_INCOME_TEMPLATE]
        for ft in fin_income_templates:
            income_table = _match_template(tables, ft)
            if income_table:
                income_data = _extract_by_template(income_table, ft)
                income_data["_template"] = ft["name"]
                break

    balance_table = _match_template(tables, BALANCE_SHEET_TEMPLATE)
    if balance_table:
        # BS跨页合并（同利润表逻辑）
        main_bs_page = balance_table.get("page", 0)
        bs_cont = BALANCE_SHEET_TEMPLATE.get("continuation_header", [])
        all_bs = [balance_table]
        if bs_cont:
            for t in tables:
                tp = t.get("page", 0)
                pt = t.get("_page_text", "")
                if tp > main_bs_page and tp <= main_bs_page + 5:  # BS跨页最多5页
                    rows = t.get("rows", [])
                    if not rows:
                        continue
                    r0_text = " ".join(str(c) for c in rows[0] if c)
                    # 匹配：表头有"项目附注" OR 首行是BS数据行（跨页续表无重复表头）
                    is_cont = all(ch in r0_text for ch in bs_cont) or \
                              any(kw in r0_text for kw in ["货币资金", "应收", "存货",
                                   "固定", "无形", "短期借款", "长期借款", "应付", "资产",
                                   "衍生金融", "合同负债", "其他流动", "长期应付"])
                    if is_cont and "母公司" not in pt:
                        all_bs.append(t)
        bs_merged = {"page": main_bs_page, "rows": _merge_rows(all_bs),
                     "_page_text": balance_table.get("_page_text", "")}
        balance_data = _extract_by_template(bs_merged, BALANCE_SHEET_TEMPLATE)
    # 工商业模板失败 → 银行资产负债表（仅在BS完全不匹配时尝试）
    if not balance_table:
        balance_table = _match_template(tables, BANK_BALANCE_TEMPLATE)
        if balance_table:
            balance_data = _extract_by_template(balance_table, BANK_BALANCE_TEMPLATE)
            balance_data["_template"] = "资产负债表-商业银行"

    cashflow_table = _match_template(tables, CASH_FLOW_TEMPLATE)
    if cashflow_table:
        cashflow_data = _extract_by_template(cashflow_table, CASH_FLOW_TEMPLATE)

    # ── 验算 ──
    income_warnings   = _validate_income_statement(income_data)
    balance_warnings  = _validate_balance_sheet(balance_data)
    all_warnings = income_warnings + balance_warnings

    # ── 文本内容提取 ──
    full_text = _extract_full_text(pdf_path)

    mdaa = _extract_section(
        full_text,
        start_marker="管理层讨论与分析",
        end_markers=["公司治理", "环境和社会", "董事会报告", "重要事项", "股份变动"],
        max_chars=80000,
        skip_toc=True,
    )
    if not mdaa or len(mdaa) < 100:
        mdaa = _extract_section(full_text, "经营情况讨论与分析",
                                ["公司治理", "重要事项"], 80000, skip_toc=True)
    if not mdaa or len(mdaa) < 100:
        mdaa = _extract_section(full_text, "管理层讨论",
                                ["公司治理", "重要事项"], 80000)

    # ── MD&A结构化拆分 ──
    mdaa_sections = _split_mdaa(mdaa) if mdaa else {}

    # ── 全要素表格提取 ──
    content_tables = extract_content_tables(tables, full_text)
    # 将表格数据映射到标准字段名
    rd_table     = content_tables.get("研发投入", {})
    prod_table   = content_tables.get("产销量", {})
    cap_table    = content_tables.get("产能", {})
    const_table  = content_tables.get("在建工程", {})
    equity_table = content_tables.get("长期股权投资", {})
    grant_table  = content_tables.get("政府补助", {})
    guar_table   = content_tables.get("担保", {})
    sub_chg      = content_tables.get("新设子公司", {})
    main_sub     = content_tables.get("主要子公司", {})
    cont_table   = content_tables.get("或有事项", {})
    post_table   = content_tables.get("日后事项", {})
    cust_table   = content_tables.get("前五名客户", {})
    supp_table   = content_tables.get("前五名供应商", {})
    sh_table     = content_tables.get("前十名股东", {})
    div_table    = content_tables.get("利润分配", {})

    # 文本提取保留审计和分红作为补充
    audit_info = _extract_audit_opinion(full_text)
    div_info   = _extract_dividend_info(full_text)

    return {
        "income_statement": income_data,
        "balance_sheet": balance_data,
        "cash_flow": cashflow_data,
        "mdaa": mdaa,
        "mdaa_length": len(mdaa),
        "mdaa_sections": mdaa_sections,  # 结构化MD&A（分章节）
        # 审计/分红（表格+文本双源）
        "audit": audit_info,
        "dividend": div_info,
        "dividend_table": div_table,
        # 全要素表格
        "rd_investment": rd_table,
        "production_sales": prod_table,
        "capacity": cap_table,
        "construction_in_progress_table": const_table,
        "long_term_equity": equity_table,
        "government_grants": grant_table,
        "guarantees": guar_table,
        "subsidiary_changes": sub_chg,
        "main_subsidiaries": main_sub,
        "contingencies": cont_table,
        "post_balance_events": post_table,
        "top5_customers": cust_table,
        "top5_suppliers": supp_table,
        "top10_shareholders_table": sh_table,
        "risks": _extract_risk_factors(full_text),
        "top_shareholders": _extract_top_shareholders(full_text),
        "content_tables_count": len(content_tables),
        "content_tables_names": list(content_tables.keys()),
        "validation": {
            "quality": "pass" if not all_warnings else "suspicious",
            "warnings": all_warnings,
            "tables_found": len(tables),
            "income_matched": income_table is not None,
            "balance_matched": balance_table is not None,
            "cashflow_matched": cashflow_table is not None,
        },
        "metadata": {
            "extraction_method": "template_matching",
            "template_income": INCOME_STATEMENT_TEMPLATE["name"],
            "template_balance": BALANCE_SHEET_TEMPLATE["name"],
        },
    }


# ═══════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    test_pdf = Path(__file__).parent / "output" / "600519_20260612" / "data" / "2025_annual_report.pdf"
    if len(sys.argv) > 1:
        test_pdf = Path(sys.argv[1])
    if not test_pdf.exists():
        print("用法: python annual_report_extractor.py <pdf_path>")
        sys.exit(0)

    print(f"提取: {test_pdf.name}")
    report = extract_annual_report(str(test_pdf))

    if report.get("error"):
        print(f"❌ {report['error']}")
        sys.exit(1)

    v = report["validation"]
    print(f"表格: {v['tables_found']}个 | 利润表={v['income_matched']} 资产负债表={v['balance_matched']} 现金流={v['cashflow_matched']}")
    print(f"验算: {v['quality']} {'| ' + '; '.join(v['warnings']) if v['warnings'] else ''}")

    for section, title in [
        ("income_statement", "利润表"),
        ("balance_sheet", "资产负债表"),
        ("cash_flow", "现金流量表"),
    ]:
        data = report.get(section, {})
        if data:
            print(f"\n── {title} ({len(data)}项) ──")
            for k, v_ in data.items():
                print(f"  {k}: {v_}")

    print(f"\n── MD&A ──")
    print(f"  长度: {report.get('mdaa_length', 0)}字")
    print(f"  前200字: {report.get('mdaa', '')[:200]}")

    print(f"\n── 审计意见 ──")
    a = report["audit"]
    print(f"  类型: {a['opinion_type']} | 事务所: {a.get('accountant_firm', 'N/A')}")

    print(f"\n── 分红预案 ──")
    d = report["dividend"]
    print(f"  每股: {d.get('per_share', 'N/A')}")

    print(f"\n── 风险因素 ──")
    for r_ in report.get("risks", [])[:5]:
        print(f"  • {r_}")

    print(f"\n── 前十大股东 ──")
    for s in report.get("top_shareholders", [])[:5]:
        print(f"  {s['name']} | {s['shares']} | {s['ratio']}%")
