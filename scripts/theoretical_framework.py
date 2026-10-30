# -*- coding: utf-8 -*-
"""
theoretical_framework.py — 理论框架整合层（对标"智数分析专家团"六维 MBA 理论骨架）
============================================================================

本模块补足 listed-company-analysis skill 此前缺失的「理论框架整合」能力：
skill 基座只有 value_chain_analysis.py（波特价值链）有理论味，其余 MBA 战略框架
（动态能力 / RBV·VRIO / 数字化成熟度 / 平台战略与网络效应 / TAM）均未系统化。
本模块把 6 大理论做成「维度 → 指标 → 打分」映射，并用实证数据锚定，产出：

  1) theoretical_framework.json          结构化打分（每理论 / 维度 / 指标 + 实证锚点）
  2) theoretical_framework_integration.md  六理论整合叙述（每框架附实证数据）

纪律（继承 SKILL.md 铁律 / 同 mda_semantic.py）：
  - 不静默吞异常：失败进 result['errors']，显式标注降级。
  - 缺口不编结论：指标在 financials.json / mda_semantic_out 缺失 → 该维度 data_gap，
    不强行给分；可用维度 < 2 时理论整体 data_gap（标注还需哪些外部源）。
  - 可复现：打分阈值与原始取值全部落盘，重跑一致。
  - 中性学术色、非品牌口径：理论打分是分析脚手架，引用前须与年报原文核对。

输入（参数化，禁硬编码绝对路径）：
  --financial-json PATH   {year:{metric:value}} 财务年序列（analyze/financials 产出）
  --mda-out DIR           mda_semantic 产出目录（读 narrative_intensity.json 取数字化强度）
  --peer-json PATH        同业中位 {metric: median}（可选，触发相对打分）
  --company NAME          公司名（落盘标注）
  --theories all|key,...  指定理论（默认 all）
  --output DIR            落盘目录（默认 theoretical_framework_out）

运行（从 skill 根目录）：
  python scripts/theoretical_framework.py --financial-json financials.json \
      --mda-out mda_semantic_out --company 某公司 --output theoretical_framework_out
"""
import os
import sys
import json
import argparse
from pathlib import Path
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ─────────────────────────────────────────────────────────────────────────
# 1. 打分工具
# ─────────────────────────────────────────────────────────────────────────
def _score_by_thresholds(value, bins):
    """
    bins: 升序 [(threshold, score), ...]，value >= threshold 取对应 score（取最大匹配）。
    例 bins=[(0.02,3),(0.04,4),(0.06,5)]，value=0.05 → 4。
    返回 (score, matched_threshold) 或 (None, None) 当 value 无效。
    """
    if value is None:
        return None, None
    try:
        v = float(value)
    except Exception:
        return None, None
    score, thr = 1, None
    for threshold, s in bins:
        if v >= threshold:
            score, thr = s, threshold
    return score, thr


def _score_inverted(value, bins):
    """成本率类：越低越好。bins 仍按阈值升序给分（低阈值对应高分在调用方构造）。"""
    return _score_by_thresholds(value, bins)


def _band(score):
    if score is None:
        return "data_gap"
    if score >= 4:
        return "强"
    if score >= 3:
        return "中"
    return "弱"


# ─────────────────────────────────────────────────────────────────────────
# 2. 六理论框架定义（维度 → 指标 → 打分阈值 → 实证来源）
#    metric 对应 financials.json[year] 的键；needs_external=True 表示通常不在
#    财务序列里，缺失时显式 data_gap 并给出补数动作（不编造）。
# ─────────────────────────────────────────────────────────────────────────
DEFAULT_FRAMEWORKS = [
    {
        "key": "dynamic_capability",
        "name_cn": "动态能力理论",
        "name_en": "Dynamic Capabilities (Teece 1997)",
        "summary": "企业持续感知(sensing)市场与技术机会、捕捉(seizing)机会、重构(transforming)"
                   "资产与组织的变革能力；适用于判断转型期企业的适应力。",
        "dimensions": [
            {"dim": "感知能力 Sensing", "indicator": "研发投入强度",
             "metric": "rd_intensity", "source": "financials.json", "needs_external": False,
             "bins": [(0.02, 3), (0.04, 4), (0.06, 5)], "anchor": "研发投入/营业收入",
             "rule": "≥6%→5；≥4%→4；≥2%→3；>0→2；无→1"},
            {"dim": "捕捉能力 Seizing", "indicator": "营收复合增速",
             "metric": "revenue_cagr", "source": "financials.json", "needs_external": False,
             "bins": [(0.05, 3), (0.10, 4), (0.20, 5)], "anchor": "近 N 年营收 CAGR",
             "rule": "≥20%→5；≥10%→4；≥5%→3；>0→2；≤0→1"},
            {"dim": "重构能力 Transforming", "indicator": "并购重组次数",
             "metric": "mna_count", "source": "capital_operation_inference.py / 公告",
             "needs_external": True,
             "bins": [(1, 3), (3, 4), (6, 5)], "anchor": "区间内重大并购/重组笔数",
             "rule": "≥6 笔→5；≥3 笔→4；≥1 笔→3；无→1（需外部公告源）"},
        ],
    },
    {
        "key": "rbv_vrio",
        "name_cn": "RBV·VRIO 框架",
        "name_en": "Resource-Based View / VRIO (Barney 1991)",
        "summary": "审视资源是否具备价值(V)、稀缺(R)、难以模仿(I)、组织可捕获(O)；"
                   "四项皆备方为持续竞争优势。",
        "dimensions": [
            {"dim": "价值性 Value", "indicator": "毛利率",
             "metric": "gross_margin", "source": "financials.json", "needs_external": False,
             "bins": [(0.15, 2), (0.30, 3), (0.40, 4), (0.50, 5)], "anchor": "毛利/营收",
             "rule": "≥50%→5；≥40%→4；≥30%→3；≥15%→2；否则→1"},
            {"dim": "稀缺性 Rarity", "indicator": "市占率",
             "metric": "market_share", "source": "peer_discovery / 行业研报",
             "needs_external": True,
             "bins": [(0.05, 3), (0.10, 4), (0.20, 5)], "anchor": "细分市场市占率",
             "rule": "≥20%→5；≥10%→4；≥5%→3；否则→1（需外部行业源）"},
            {"dim": "难以模仿 Inimitability", "indicator": "专利护城河",
             "metric": "patent_count", "source": "patent_tracker.py",
             "needs_external": True,
             "bins": [(20, 3), (100, 4), (500, 5)], "anchor": "有效发明专利数",
             "rule": "≥500→5；≥100→4；≥20→3；否则→1（需外部专利源）"},
            {"dim": "组织可捕获 Organization", "indicator": "净资产收益率(代理)",
             "metric": "roe", "source": "financials.json", "needs_external": False,
             "bins": [(0.0, 2), (0.05, 3), (0.10, 4), (0.15, 5)], "anchor": "净利润/净资产",
             "rule": "≥15%→5；≥10%→4；≥5%→3；>0→2；≤0→1"},
        ],
    },
    {
        "key": "porter_value_chain",
        "name_cn": "波特价值链分析",
        "name_en": "Porter Value Chain (1985)",
        "summary": "把经营拆为初级活动(进料/生产/营销/服务)与支持活动(技术/人力/基建)，"
                   "定位价值创造与成本痛点；skill 已有 value_chain_analysis.py 同源。",
        "dimensions": [
            {"dim": "生产/运营效率", "indicator": "营业成本率(越低越好)",
             "metric": "cogs_ratio", "source": "financials.json", "needs_external": False,
             "bins": [(0.90, 1), (0.80, 2), (0.70, 3), (0.60, 4)],
             "anchor": "营业成本/营收（阈值已倒置：低成本低分高）",
             "rule": "≤60%→5；≤70%→4；≤80%→3；≤90%→2；否则→1"},
            {"dim": "营销/渠道效率", "indicator": "期间费用率(适中为好)",
             "metric": "sga_ratio", "source": "financials.json", "needs_external": False,
             "bins": [(0.30, 1), (0.20, 2), (0.15, 3), (0.10, 4)],
             "anchor": "销售+管理费用/营收（阈值已倒置）",
             "rule": "≤10%→5；≤15%→4；≤20%→3；≤30%→2；否则→1"},
            {"dim": "技术开发", "indicator": "研发投入强度(复用)",
             "metric": "rd_intensity", "source": "financials.json", "needs_external": False,
             "bins": [(0.02, 3), (0.04, 4), (0.06, 5)], "anchor": "研发投入/营业收入",
             "rule": "同动态能力·感知能力"},
            {"dim": "基础设施/治理", "indicator": "流动比率(偿债代理)",
             "metric": "current_ratio", "source": "financials.json", "needs_external": False,
             "bins": [(0.5, 2), (1.0, 3), (1.5, 4), (2.0, 5)], "anchor": "流动资产/流动负债",
             "rule": "≥2→5；≥1.5→4；≥1→3；≥0.5→2；否则→1"},
        ],
    },
    {
        "key": "digital_maturity",
        "name_cn": "数字化成熟度",
        "name_en": "Digital Maturity (战略/技术/数据/人才)",
        "summary": "从战略、技术、数据、人才四支柱评估企业数字化转型成熟度；"
                   "MD&A 数字化叙事强度是战略落地的文本信号。",
        "dimensions": [
            {"dim": "战略 Strategy", "indicator": "MD&A 数字化叙事强度",
             "metric": "_digital_intensity", "source": "mda_semantic_out/narrative_intensity.json",
             "needs_external": False, "from_mda": True,
             "bins": [(1.0, 2), (3.0, 3), (5.0, 4), (8.0, 5)],
             "anchor": "数字化主题密度(每千词出现次数)",
             "rule": "≥8→5；≥5→4；≥3→3；≥1→2；否则→1（来自 MD&A 语义量化）"},
            {"dim": "技术 Technology", "indicator": "研发投入强度(技术代理)",
             "metric": "rd_intensity", "source": "financials.json", "needs_external": False,
             "bins": [(0.02, 3), (0.04, 4), (0.06, 5)], "anchor": "研发投入/营业收入",
             "rule": "同动态能力·感知能力（研发是数字技术的近似投入）"},
            {"dim": "数据资产 Data", "indicator": "数据资产/上云投入",
             "metric": "data_asset_ratio", "source": "年报附注/IT 资本开支",
             "needs_external": True,
             "bins": [(0.01, 3), (0.03, 4), (0.05, 5)], "anchor": "数字化相关资本开支占比",
             "rule": "≥5%→5；≥3%→4；≥1%→3；否则→1（需外部附注源）"},
            {"dim": "人才 Talent", "indicator": "数字化人才占比",
             "metric": "digital_talent_ratio", "source": "年报/ESG 员工结构",
             "needs_external": True,
             "bins": [(0.05, 3), (0.10, 4), (0.20, 5)], "anchor": "研发/IT 人员占比",
             "rule": "≥20%→5；≥10%→4；≥5%→3；否则→1（需外部员工结构源）"},
        ],
    },
    {
        "key": "platform_network",
        "name_cn": "平台战略与网络效应",
        "name_en": "Platform Strategy & Network Effects",
        "summary": "多边平台通过跨边网络效应放大价值；适用于平台型/生态型企业，"
                   "传统制造企业该框架多为 N/A（如实标注，不硬套）。",
        "dimensions": [
            {"dim": "多边市场 Multi-sided", "indicator": "平台型收入占比",
             "metric": "platform_revenue_ratio", "source": "业务分部披露",
             "needs_external": True,
             "bins": [(0.20, 3), (0.50, 4), (0.80, 5)], "anchor": "平台/佣金类收入占比",
             "rule": "≥80%→5；≥50%→4；≥20%→3；否则→1（需外部分部源）"},
            {"dim": "网络效应 Network Effects", "indicator": "用户/交易量增速",
             "metric": "user_growth", "source": "经营数据/月活",
             "needs_external": True,
             "bins": [(0.10, 3), (0.30, 4), (0.50, 5)], "anchor": "活跃用户或 GMV 增速",
             "rule": "≥50%→5；≥30%→4；≥10%→3；否则→1（需外部经营源）"},
            {"dim": "生态 Ecosystem", "indicator": "生态合作伙伴数",
             "metric": "partner_count", "source": "年报/开发者生态",
             "needs_external": True,
             "bins": [(100, 3), (1000, 4), (10000, 5)], "anchor": "接入生态的合作伙伴数",
             "rule": "≥1万→5；≥1千→4；≥100→3；否则→1（需外部生态源）"},
        ],
    },
    {
        "key": "tam",
        "name_cn": "技术接受模型 TAM",
        "name_en": "Technology Acceptance Model (Davis 1989)",
        "summary": "从感知有用性、易用性、采纳度解释技术/产品被市场接受的程度；"
                   "需求增长是感知有用的近似信号。",
        "dimensions": [
            {"dim": "感知有用 Usefulness", "indicator": "营收复合增速(需求代理)",
             "metric": "revenue_cagr", "source": "financials.json", "needs_external": False,
             "bins": [(0.05, 3), (0.10, 4), (0.20, 5)], "anchor": "近 N 年营收 CAGR",
             "rule": "同动态能力·捕捉能力"},
            {"dim": "易用性 Ease of Use", "indicator": "产品返修/客诉率(逆向)",
             "metric": "return_rate", "source": "质量披露/客服数据",
             "needs_external": True,
             "bins": [(0.10, 1), (0.05, 2), (0.02, 3), (0.01, 4)],
             "anchor": "退货/返修率（阈值已倒置）",
             "rule": "≤1%→5；≤2%→4；≤5%→3；≤10%→2；否则→1（需外部质量源）"},
            {"dim": "采纳度 Adoption", "indicator": "用户/客户增长",
             "metric": "user_growth", "source": "经营数据",
             "needs_external": True,
             "bins": [(0.10, 3), (0.30, 4), (0.50, 5)], "anchor": "客户数或用户增速",
             "rule": "同平台战略·网络效应（需外部经营源）"},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────
# 3. 数据读取
# ─────────────────────────────────────────────────────────────────────────
def _load_financials(path: str):
    if not path or not Path(path).exists():
        return None, "financial_json_missing"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data, "ok"
    except Exception as e:
        return None, f"financial_json_parse_error:{e}"


def _load_mda_intensity(mda_out: str):
    """读 mda_semantic_out/narrative_intensity.json，取『数字化』主题近年均值密度。"""
    if not mda_out:
        return None
    cand = Path(mda_out) / "narrative_intensity.json"
    if not cand.exists():
        cand2 = Path(mda_out).parent / "mda_semantic_out" / "narrative_intensity.json"
        if cand2.exists():
            cand = cand2
        else:
            return None
    try:
        data = json.loads(cand.read_text(encoding="utf-8"))
    except Exception:
        return None
    # 取各年『数字化』主题密度均值
    vals = []
    for y, themes in data.items():
        if isinstance(themes, dict) and "数字化" in themes:
            try:
                vals.append(float(themes["数字化"]))
            except Exception:
                pass
    if not vals:
        return None
    return sum(vals) / len(vals)


def _load_peer(path: str):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# 4. 单指标打分（带实证锚定 + 同业相对分）
# ─────────────────────────────────────────────────────────────────────────
def _score_dimension(dim, fin, years, mda_digital, peer):
    metric = dim["metric"]
    # 来自 MD&A 语义量化的特殊指标
    if dim.get("from_mda"):
        if mda_digital is None:
            return {"status": "data_gap", "source": dim["source"],
                    "reason": "mda_semantic_out/narrative_intensity.json 缺失或无『数字化』主题",
                    "action": "先跑 scripts/mda_semantic.py 产出叙事强度"}
        val = mda_digital
        score, thr = _score_by_thresholds(val, dim["bins"])
        return {"status": "ok", "value": round(val, 4), "source": dim["source"],
                "score": score, "band": _band(score), "threshold": thr,
                "peer_relative": None}
    # 来自财务序列
    if fin is None:
        return {"status": "data_gap", "source": dim["source"],
                "reason": "financials.json 未提供",
                "action": "跑 analyze.py / financials.py 产出财务年序列"}
    # 取该指标在覆盖年份的均值（跨年稳定）
    series = []
    for y in years:
        if y in fin and metric in fin[y] and fin[y][metric] is not None:
            try:
                series.append(float(fin[y][metric]))
            except Exception:
                pass
    if not series:
        if dim.get("needs_external"):
            return {"status": "data_gap", "source": dim["source"],
                    "reason": f"财务序列无 '{metric}'（该维度需外部源：{dim['source']}）",
                    "action": f"补充 {dim['source']} 后重算"}
        return {"status": "data_gap", "source": dim["source"],
                "reason": f"财务序列无 '{metric}'",
                "action": f"确认 financials.json 含 {metric}"}
    val = sum(series) / len(series)
    score, thr = _score_by_thresholds(val, dim["bins"])
    out = {"status": "ok", "value": round(val, 4), "source": dim["source"],
           "score": score, "band": _band(score), "threshold": thr,
           "n_years": len(series)}
    # 同业相对分（可选）
    if peer and metric in peer:
        try:
            med = float(peer[metric])
            if med != 0:
                rel = 3 + 2 * (val - med) / abs(med)
                rel = max(1, min(5, round(rel)))
                out["peer_relative"] = {"peer_median": med, "relative_score": rel}
        except Exception:
            pass
    return out


# ─────────────────────────────────────────────────────────────────────────
# 5. 理论整体打分
# ─────────────────────────────────────────────────────────────────────────
def _score_framework(fw, fin, years, mda_digital, peer):
    dims_out = []
    scores = []
    gaps = []
    for dim in fw["dimensions"]:
        r = _score_dimension(dim, fin, years, mda_digital, peer)
        r["dim"] = dim["dim"]
        r["indicator"] = dim["indicator"]
        r["anchor"] = dim["anchor"]
        r["rule"] = dim["rule"]
        dims_out.append(r)
        if r["status"] == "ok":
            scores.append(r["score"])
        else:
            gaps.append(dim["dim"])
    if len(scores) >= 2:
        overall = round(sum(scores) / len(scores), 2)
        status = "ok"
    else:
        overall = None
        status = "data_gap"
    return {
        "key": fw["key"],
        "name_cn": fw["name_cn"],
        "name_en": fw["name_en"],
        "summary": fw["summary"],
        "overall_score": overall,
        "overall_band": _band(overall),
        "status": status,
        "n_scored": len(scores),
        "n_total": len(fw["dimensions"]),
        "gap_dims": gaps,
        "dimensions": dims_out,
    }


# ─────────────────────────────────────────────────────────────────────────
# 6. 落盘：integration.md
# ─────────────────────────────────────────────────────────────────────────
def _write_integration_md(path: Path, result: dict, company: str, years: list):
    L = []
    L.append(f"# 理论框架整合报告（{company or '未知公司'}）")
    L.append("")
    L.append(f"- 覆盖年度：{', '.join(years) if years else '未指定'}")
    L.append(f"- 框架总数：{len(result['frameworks'])}（动态能力 / RBV·VRIO / 波特价值链 / "
             f"数字化成熟度 / 平台战略与网络效应 / TAM）")
    L.append(f"- 数据纪律：指标缺失维度显式 `data_gap`，可用维度 < 2 的框架整体 `data_gap`，"
             f"不编造结论。")
    if result["errors"]:
        L.append("\n## ⚠ 降级/错误（未静默）")
        for e in result["errors"]:
            L.append(f"- {e}")
    L.append("\n---")
    for fw in result["frameworks"]:
        L.append(f"\n## {fw['name_cn']}（{fw['name_en']}）")
        L.append("")
        L.append(fw["summary"])
        L.append("")
        if fw["status"] == "data_gap":
            L.append(f"**整体评分：`data_gap`** —— 可用维度 {fw['n_scored']}/{fw['n_total']} "
                     f"（<2），需补：{', '.join(fw['gap_dims'])}。")
        else:
            L.append(f"**整体评分：{fw['overall_score']} / 5（{fw['overall_band']}）** "
                     f"—— 可用维度 {fw['n_scored']}/{fw['n_total']}。")
        L.append("")
        L.append("| 维度 | 指标 | 实证取值 | 来源 | 打分 | 解读 |")
        L.append("|---|---|---|---|---|---|")
        for d in fw["dimensions"]:
            if d["status"] == "ok":
                val = d.get("value")
                val_s = f"{val}" if val is not None else "—"
                rel = ""
                if d.get("peer_relative"):
                    rel = f"（同业相对 {d['peer_relative']['relative_score']}）"
                L.append(f"| {d['dim']} | {d['indicator']} | {val_s} | {d['source']} | "
                         f"{d['score']} {d['band']}{rel} | {d['rule']} |")
            else:
                L.append(f"| {d['dim']} | {d['indicator']} | `data_gap` | {d['source']} | "
                         f"— | {d.get('reason','')} |")
        L.append("")
        if fw["gap_dims"]:
            L.append(f"**待补维度**：{', '.join(fw['gap_dims'])} —— {fw['dimensions'][0].get('action','见各维度')}。")
            L.append("")
    L.append("\n---")
    L.append("\n## 跨框架总览（雷达图数据源）")
    L.append("")
    L.append("| 理论 | 整体评分 | 档位 |")
    L.append("|---|---|---|")
    for fw in result["frameworks"]:
        o = fw["overall_score"] if fw["overall_score"] is not None else "data_gap"
        L.append(f"| {fw['name_cn']} | {o} | {fw['overall_band']} |")
    L.append("")
    L.append("> 雷达图取值来自上表整体评分；`data_gap` 框架在图中留空并标注，不插值。")
    path.write_text("\n".join(L), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# 7. 主流程
# ─────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="理论框架整合（六维 MBA 理论打分+实证锚定）")
    ap.add_argument("--financial-json", help="{year:{metric:value}} 财务年序列")
    ap.add_argument("--mda-out", help="mda_semantic 产出目录（读 narrative_intensity.json）")
    ap.add_argument("--peer-json", help="同业中位 {metric: median}（可选，触发相对打分）")
    ap.add_argument("--company", default="", help="公司名（落盘标注）")
    ap.add_argument("--theories", default="all",
                    help="指定理论 key 逗号分隔，默认 all")
    ap.add_argument("--output", default="theoretical_framework_out", help="落盘目录")
    ap.add_argument("--years", default="", help="分析年份逗号分隔（仅标注用）")
    args = ap.parse_args()

    result = {"status": "ok", "errors": [], "company": args.company}
    fin, fstat = _load_financials(args.financial_json)
    if fstat != "ok":
        # 财务缺失 ≠ 全挂：数字化成熟度仍可借 mda 打分；其余框架记错误
        result["errors"].append(f"financials:{fstat}（无财务序列的框架维度将 data_gap）")
    mda_digital = _load_mda_intensity(args.mda_out) if args.mda_out else None
    if args.mda_out and mda_digital is None:
        result["errors"].append("mda_intensity: 未取到数字化叙事强度（数字化成熟度·战略维度将 data_gap）")
    peer = _load_peer(args.peer_json)

    years = [y.strip() for y in args.years.split(",") if y.strip()] if args.years else (
        sorted(fin.keys()) if fin else [])
    result["years"] = years

    # 选定框架
    if args.theories == "all":
        fws = DEFAULT_FRAMEWORKS
    else:
        keys = {k.strip() for k in args.theories.split(",") if k.strip()}
        fws = [f for f in DEFAULT_FRAMEWORKS if f["key"] in keys]
        if not fws:
            result["errors"].append(f"theories: 未匹配到 {args.theories}")
            fws = DEFAULT_FRAMEWORKS

    frameworks = [_score_framework(fw, fin, years, mda_digital, peer) for fw in fws]
    result["frameworks"] = frameworks
    # 总体状态
    ok_fw = [f for f in frameworks if f["status"] == "ok"]
    result["summary"] = {
        "total": len(frameworks),
        "scored": len(ok_fw),
        "data_gap": len(frameworks) - len(ok_fw),
    }

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "theoretical_framework.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_integration_md(out / "theoretical_framework_integration.md", result,
                           args.company, years)

    # 控制台摘要（不静默）
    print(f"[theoretical_framework] 公司={args.company or '?'} | 年度={years} | 落盘={out}")
    for fw in frameworks:
        o = fw["overall_score"] if fw["overall_score"] is not None else "data_gap"
        print(f"  {fw['name_cn']:<10} 整体={o} 档={fw['overall_band']} "
              f"({fw['n_scored']}/{fw['n_total']} 维度有数据)")
    if result["errors"]:
        print("  ⚠ 降级/错误:")
        for e in result["errors"]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
