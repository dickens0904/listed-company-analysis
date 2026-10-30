# -*- coding: utf-8 -*-
"""
orchestrate_expert_team.py — 专家团模式编排器（对标"智数分析专家团"5 角色分工）
============================================================================

把 listed-company-analysis 的「单 Agent 撰写」升级为 **5 角色专家团编排**：
首席数据编排师 / 知识检索专家 / 数据科学工程师 / 洞察报告撰写师 / 可视化分析设计师。
本脚本**不另搭 LLM API**——它只产出一份「角色分工 + 执行顺序 + 门禁」的任务清单
（manifest JSON + dispatch markdown），由**本会话 Agent** 按清单逐角色执行（复用 skill 既有脚本）。

与官网案例的差异：案例用 5 个独立 LLM Agent 并行；本 skill 用「同一 Agent + 角色化提示词 +
脚本基座」实现等价分工，且全程走 MCP 优先数据源与 45+ 门禁（案例最弱处，本 skill 最强）。

输入：
  --company 公司名  --code 股票代码  --years 2019,2020,...  --topic 分析主题
  --market a/hk/us/bse  --format a|b  (a=通俗评论 / b=咨询报告)
  --output DIR  (落盘清单，默认 expert_team_out)

输出（落盘）：
  expert_team_manifest.json   角色/顺序/门禁结构化清单
  expert_team_dispatch.md     可读派工板（Agent 逐角色执行依据）

运行（从 skill 根目录）：
  python scripts/orchestrate_expert_team.py --company 某公司 --code 600000 \
      --years 2019,2020,2021,2022,2023 --topic 数字化转型叙事分析 --format b
"""
import os
import sys
import json
import argparse
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ─────────────────────────────────────────────────────────────────────────
# 1. 五角色定义（角色化提示词 + 输入/输出 + 对应脚本 + 依赖）
#    严格对齐 skill 既有模块，执行不脱离基座。
# ─────────────────────────────────────────────────────────────────────────
def build_roles(q) -> list:
    return [
        {
            "role": "首席数据编排师 (Chief Data Orchestrator)",
            "mission": "把用户诉求翻译成可执行的采集-分析计划，定序、定源、定门禁。",
            "prompt": (
                f"你是首席数据编排师。针对 {q['company']}（{q['code']}，{q['market']} 市场）"
                f"在 {q['years']} 的「{q['topic']}」，规划一条 MCP 优先的数据链路：\n"
                "① 调用 MCP 连接器（wind-finance / dzh-mcp / qcc-company / alphapai-lite-mcp）"
                "取财务、股权、公告、行业数据，禁止用已废弃源作主源；\n"
                "② 确定 analyze.py 的运行参数（市场/维度/输出目录）；\n"
                "③ 列出下游各角色需要的产物与门禁（45+ 项，缺口不编结论）。\n"
                "输出一份 data_plan（无需写最终报告，只定方案）。"
            ),
            "inputs": ["用户诉求 (company/code/years/topic/format)"],
            "outputs": ["data_plan（源优先级 + analyze 参数 + 输出目录 + 门禁清单）"],
            "scripts": ["analyze.py (规划参数)"],
            "depends_on": [],
        },
        {
            "role": "知识检索专家 (Knowledge Retrieval Specialist)",
            "mission": "补齐一手信源：公告全文、行业研报、竞品/同业、新闻与监管。",
            "prompt": (
                f"你是知识检索专家。围绕 {q['company']}（{q['code']}）做一手信源检索：\n"
                "① 用 MCP/网页搜索取历年年度报告、重大公告全文、问询函回复；\n"
                "② 用 peer_discovery.py 发现同业名单与行业口径；\n"
                "③ 标注每条来源的层级（T1–T6）与可信度，缺失维度显式记为 data_gap。\n"
                "输出结构化检索清单（含 URL/出处），供数据科学工程师并入证据包。"
            ),
            "inputs": ["data_plan（目标公司/区间/维度）"],
            "outputs": ["检索清单（公告/研报/同业/新闻，带源层级）", "entity_index 候选"],
            "scripts": ["peer_discovery.py", "websearch.py", "business_fetch.py"],
            "depends_on": ["首席数据编排师"],
        },
        {
            "role": "数据科学工程师 (Data Science Engineer)",
            "mission": "跑通全维度采集与三层量化，产出可复算的中间产物与证据包。",
            "prompt": (
                f"你是数据科学工程师。按 data_plan 执行采集与量化，全部落盘可复算：\n"
                "① `python scripts/analyze.py --code {q['code']} --market {q['market']} "
                f"--years {q['years']} --output <data_dir>` 跑全维度；\n"
                "② `python scripts/mda_semantic.py --corpus <年报PDF目录> --years {q['years']} "
                "--financial-json <data_dir>/financials.json --output <data_dir>/mda_semantic_out` "
                "做 MD&A 语义量化；\n"
                "③ `python scripts/theoretical_framework.py --financial-json <data_dir>/financials.json "
                "--mda-out <data_dir>/mda_semantic_out --company {q['company']} "
                "--output <data_dir>/theoretical_framework_out` 做六维理论打分；\n"
                "④ `python scripts/article_brief.py <data_dir>` 生成 evidence_pack.json。\n"
                "任何指标缺失 → 显式 data_gap，不编造。"
            ),
            "inputs": ["data_plan", "知识检索专家的检索清单"],
            "outputs": ["results.json", "mda_semantic_out/*", "theoretical_framework_out/*",
                        "evidence_pack.json"],
            "scripts": ["analyze.py", "mda_semantic.py", "theoretical_framework.py",
                        "article_brief.py"],
            "depends_on": ["首席数据编排师", "知识检索专家"],
        },
        {
            "role": "洞察报告撰写师 (Insight Report Writer)",
            "mission": "基于证据包写最终交付物，形态 A 或 B。",
            "prompt": (
                f"你是洞察报告撰写师。读取 evidence_pack.json + mda_semantic_out/* + "
                f"theoretical_framework_out/*，按 --format {q['format']} 撰写：\n"
                "形态 A（通俗评论 2000–3500 字）：结论先行、数据回溯证据包、缺口标 data_gap；\n"
                "形态 B（咨询报告）：执行摘要+指标卡+问题卡片+六理论整合+图表引用+附录 A–D。\n"
                "🔴 铁律：每个结论须回查证据包；叙事背离/解耦断言须有 pearson_r；理论评级须有六维打分；"
                "缺口不得写成结论。"
            ),
            "inputs": ["evidence_pack.json", "mda_semantic_out/*", "theoretical_framework_out/*"],
            "outputs": ["article.md (形态A) 或 report.md (形态B)"],
            "scripts": ["（无独立脚本，由 Agent 按证据包撰写）"],
            "depends_on": ["数据科学工程师"],
        },
        {
            "role": "可视化分析设计师 (Visualization Designer)",
            "mission": "据落盘数据产出图表，供形态 B 报告引用。",
            "prompt": (
                "你是可视化分析设计师。从落盘文件取数（不现算）生成图表：\n"
                "① 趋势图/对比柱状图（financials）；② 雷达图（theoretical_framework_out 六维评分）；\n"
                "③ 词频热力图（mda_semantic_out/word_freq_matrix.csv）；④ 偏离散点（narrative_vs_fact）。\n"
                "配色继承 joint_action_narrative 中性学术色（#3d5a80/#2f6b5f/#8a6520），不用品牌色。"
            ),
            "inputs": ["mda_semantic_out/*", "theoretical_framework_out/*", "financials"],
            "outputs": ["figures/*.png（雷达图/热力图/趋势图）"],
            "scripts": ["visualization.py", "chart_renderer.py"],
            "depends_on": ["数据科学工程师", "洞察报告撰写师"],
        },
    ]


def build_sequence() -> list:
    return [
        "1. 首席数据编排师 → 产出 data_plan（源/参数/输出目录/门禁）",
        "2. 知识检索专家 → 一手信源检索清单（与编排师可并行启动，但并入需等 data_plan）",
        "3. 数据科学工程师 → 跑 analyze + mda_semantic + theoretical_framework + article_brief，落盘全产物",
        "4. 洞察报告撰写师 → 按 --format 写 article.md / report.md",
        "5. 可视化分析设计师 → 出雷达图/热力图/趋势图，回填形态 B 报告",
        "6. 收口：article_checklist.py 45+ 门禁（含 J 叙事解耦、K 理论框架），FAIL 未清零不得交付",
    ]


def build_gates() -> list:
    return [
        "MCP 优先：财务/股权/公告/行业一律走 wind-finance/dzh-mcp/qcc-company/alphapai，废弃源不得作主源",
        "缺口不编结论：指标缺失标 data_gap，叙事背离须 pearson_r、理论评级须六维打分支撑",
        "可复算：mda_semantic_out / theoretical_framework_out / evidence_pack 全部落盘",
        "门禁收口：article_checklist.py 全组通过（I 缺口守门 / J 叙事解耦 / K 理论框架），FAIL 清零才交付",
        "配色纪律：咨询报告中性学术色，不套用任何机构品牌色",
    ]


def main():
    ap = argparse.ArgumentParser(description="专家团模式编排器（产出 5 角色任务清单）")
    ap.add_argument("--company", required=True, help="公司名")
    ap.add_argument("--code", required=True, help="股票代码")
    ap.add_argument("--years", required=True, help="分析年份，逗号分隔")
    ap.add_argument("--topic", default="上市公司深度分析", help="分析主题")
    ap.add_argument("--market", default="a", help="a/hk/us/bse")
    ap.add_argument("--format", default="a", help="a=通俗评论 / b=咨询报告")
    ap.add_argument("--output", default="expert_team_out", help="落盘目录")
    args = ap.parse_args()

    q = {"company": args.company, "code": args.code, "years": args.years,
         "topic": args.topic, "market": args.market, "format": args.format}
    roles = build_roles(q)
    manifest = {
        "mode": "expert_team",
        "query": q,
        "roles": roles,
        "sequence": build_sequence(),
        "gates": build_gates(),
        "note": "本清单由本会话 Agent 逐角色执行；不另搭 LLM API，基座与门禁与单 Agent 模式完全一致。",
    }

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "expert_team_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # dispatch markdown
    L = [f"# 专家团派工板 · {args.company}（{args.code}）", ""]
    L.append(f"- 区间：{args.years} ｜ 主题：{args.topic} ｜ 市场：{args.market} ｜ 形态：{args.format}")
    L.append(f"- 模式：专家团（5 角色，由本会话 Agent 逐角色执行，基座与门禁不变）")
    L.append("\n## 执行顺序")
    for s in manifest["sequence"]:
        L.append(f"- {s}")
    L.append("\n## 角色分工")
    for i, r in enumerate(roles, 1):
        L.append(f"\n### {i}. {r['role']}")
        L.append(f"**职责**：{r['mission']}")
        L.append(f"**输入**：{r['inputs']}")
        L.append(f"**产出**：{r['outputs']}")
        L.append(f"**脚本**：{r['scripts']}")
        L.append(f"**依赖**：{r['depends_on'] or '（起点）'}")
        L.append("\n**角色提示词**：\n")
        L.append("```\n" + r["prompt"] + "\n```")
    L.append("\n## 收口门禁")
    for g in manifest["gates"]:
        L.append(f"- 🔴 {g}")
    (out / "expert_team_dispatch.md").write_text("\n".join(L), encoding="utf-8")

    print(f"[orchestrate_expert_team] 公司={args.company} | 形态={args.format} | 落盘={out}")
    print(f"  角色数={len(roles)} | 顺序步数={len(manifest['sequence'])} | 门禁={len(manifest['gates'])}")


if __name__ == "__main__":
    main()
