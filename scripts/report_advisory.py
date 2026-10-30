# -*- coding: utf-8 -*-
"""
report_advisory.py — 咨询报告模式·形态 B 落地（对标"智数分析专家团" HTML 咨询报告）
============================================================================

消费 listed-company-analysis 三层产物，离线生成结构化咨询报告（HTML）：
  ① 执行摘要 + 6 张核心指标卡
  ② 六理论框架整合（表 + 雷达图 SVG）
  ③ 核心问题卡片（已知缺口，严重程度 + 说明）
  ④ 战略举措与改善建议（数据驱动，明确标"建议"非结论）
  ⑤ 图表：叙事强度轨迹(line) / 理论雷达(radar) / 词频热力图(heatmap) / KPI 对比(bar)
  ⑥ 附录 A–D：缩略语表 / 数据来源 / 脚本说明 / 口径说明

纪律（继承 SKILL.md / 同 mda_semantic / theoretical_framework）：
  - 全部内容来自落盘产物，缺失维度显示 data_gap，**不编造结论、不现算**（图表数据取自 *_out 文件）。
  - 中性学术配色（#3d5a80 / #2f6b5f / #8a6520），不套任何机构品牌色。
  - 单文件 HTML（内联 CSS + 内联 SVG），双击离线可开，无外部依赖。

输入：
  data_dir       含 results.json / evidence_pack.json 的数据目录（先跑 analyze + article_brief + 语义/理论量化）
  --output PATH  报告 HTML 路径（默认 <data_dir>/consulting_report.html）
  --company / --code  覆盖页头（缺省读 evidence meta）

运行（从 skill 根目录）：
  python scripts/report_advisory.py <data_dir> --output consulting_report.html
"""
import os
import sys
import json
import csv
import math
import argparse
from pathlib import Path
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── 中性学术配色 ────────────────────────────────────────────────────────────
C_PRIMARY = "#3d5a80"   # 深蓝
C_SECOND = "#2f6b5f"    # 墨绿
C_ACCENT = "#8a6520"    # 古铜
C_BG = "#f7f8fa"
C_CARD = "#ffffff"
C_TEXT = "#1f2933"
C_MUTED = "#6b7280"
C_BORDER = "#e2e8f0"
C_GAP = "#c0392b"       # data_gap 红
C_OK = "#2f6b5f"

SECTION_ORDER = ["数字化", "战略", "增长", "研发", "风险", "资本"]


# ─────────────────────────────────────────────────────────────────────────
# 1. 数据读取（全部防御式，缺失即 data_gap）
# ─────────────────────────────────────────────────────────────────────────
def _read_json(path):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def load_evidence(data_dir):
    return _read_json(os.path.join(data_dir, "evidence_pack.json")) or {}


def load_theoretical(data_dir):
    return _read_json(os.path.join(data_dir, "theoretical_framework_out",
                                   "theoretical_framework.json")) or {}


def load_intensity(data_dir):
    return _read_json(os.path.join(data_dir, "mda_semantic_out",
                                   "narrative_intensity.json")) or {}


def load_nvf(data_dir):
    return _read_json(os.path.join(data_dir, "mda_semantic_out",
                                   "narrative_vs_fact.json")) or {}


def load_financials(data_dir):
    return _read_json(os.path.join(data_dir, "financials.json")) or {}


def load_wordfreq(data_dir):
    p = os.path.join(data_dir, "mda_semantic_out", "word_freq_matrix.csv")
    if not Path(p).exists():
        return None, None
    try:
        with open(p, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return None, None
        years = [c for c in rows[0][1:] if c]
        matrix = OrderedDict()
        for r in rows[1:]:
            if not r:
                continue
            word = r[0]
            vals = [float(x) if x not in ("", None) else 0.0 for x in r[1:]]
            matrix[word] = vals
        return years, matrix
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────
# 2. 指标卡提取（6 张：营收CAGR/毛利率/研发强度/人均效能/叙事强度峰值/关键相关系数）
# ─────────────────────────────────────────────────────────────────────────
def _avg_metric(fin, metric):
    if not fin:
        return None
    vals = []
    for y, d in fin.items():
        if isinstance(d, dict) and metric in d and d[metric] is not None:
            try:
                vals.append(float(d[metric]))
            except Exception:
                pass
    return sum(vals) / len(vals) if vals else None


def build_kpis(data_dir):
    fin = load_financials(data_dir)
    intensity = load_intensity(data_dir)
    nvf = load_nvf(data_dir)
    cards = []

    rev_cagr = _avg_metric(fin, "revenue_cagr")
    cards.append(("营收复合增速", _pct(rev_cagr), "近 N 年 CAGR" if rev_cagr is not None else "financials.json 缺失",
                  rev_cagr is not None))

    gm = _avg_metric(fin, "gross_margin")
    cards.append(("毛利率", _pct(gm), "毛利/营收均值" if gm is not None else "financials.json 缺失",
                  gm is not None))

    rdi = _avg_metric(fin, "rd_intensity")
    cards.append(("研发强度", _pct(rdi), "研发投入/营收均值" if rdi is not None else "financials.json 缺失",
                  rdi is not None))

    # 人均效能：通常不在财务序列 → data_gap
    cards.append(("人均效能", "data_gap", "需员工结构/营收数据，未提供", False))

    # 叙事强度峰值：各年主题密度总和的最大值
    peak = None
    if intensity:
        totals = []
        for y, themes in intensity.items():
            if isinstance(themes, dict):
                tot = sum(v for k, v in themes.items()
                          if k != "_total_tokens" and isinstance(v, (int, float)))
                totals.append(tot)
        if totals:
            peak = max(totals)
    cards.append(("叙事强度峰值", (f"{peak:.1f}" if peak is not None else "data_gap"),
                  "MD&A 主题密度/千词峰值" if peak is not None else "mda_semantic 未跑",
                  peak is not None))

    # 关键相关系数：取 narrative_vs_fact 首个指标的 r
    key_r = None
    if nvf.get("status") == "ok":
        for m, d in nvf.get("metrics", {}).items():
            if isinstance(d, dict) and d.get("pearson_r") is not None:
                key_r = (m, d["pearson_r"], d.get("interpretation", ""))
                break
    cards.append(("关键相关系数", (f"r={key_r[1]}" if key_r else "data_gap"),
                  (f"{key_r[0]} · {key_r[2]}" if key_r else "叙事偏离检测未跑/年数<3"),
                  key_r is not None))
    return cards


def _pct(v):
    return f"{v*100:.1f}%" if isinstance(v, (int, float)) else "—"


# ─────────────────────────────────────────────────────────────────────────
# 3. SVG 图表（内联，离线可用）
# ─────────────────────────────────────────────────────────────────────────
def _lerp_color(t, lo="#eef2f7", hi=C_PRIMARY):
    """t in [0,1] → 在浅色与主题色间插值（粗略 hex 插值）。"""
    def hx(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
    r0, g0, b0 = hx(lo)
    r1, g1, b1 = hx(hi)
    r = int(r0 + (r1 - r0) * t)
    g = int(g0 + (g1 - g0) * t)
    b = int(b0 + (b1 - b0) * t)
    return f"rgb({r},{g},{b})"


def svg_radar(scores: dict, size=320):
    """scores: {framework_name: score(0-5)}，data_gap 跳过。"""
    items = [(k, v) for k, v in scores.items() if isinstance(v, (int, float))]
    if not items:
        return '<p class="gap">雷达图不可用：无已评分框架（全部 data_gap）。</p>'
    n = len(items)
    cx = size / 2
    cy = size / 2
    R = size / 2 - 42
    ang = [(-90 + 360 / n * i) * 3.14159 / 180 for i in range(n)]
    pts = []
    for i, (k, v) in enumerate(items):
        rr = R * max(0.06, v / 5.0)
        x = cx + rr * math.cos(ang[i])
        y = cy + rr * math.sin(ang[i])
        pts.append((x, y))
    # 网格圈
    grid = ""
    for g in (1, 2, 3, 4, 5):
        rr = R * g / 5.0
        poly = " ".join(f"{cx+rr*math.cos(a):.1f},{cy+rr*math.sin(a):.1f}" for a in ang)
        grid += f'<polygon points="{poly}" fill="none" stroke="{C_BORDER}" stroke-width="1"/>'
    axis = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{cx+R*math.cos(ang[i]):.1f}" y2="{cy+R*math.sin(ang[i]):.1f}" stroke="{C_BORDER}"/>'
        f'<text x="{cx+(R+14)*math.cos(ang[i]):.1f}" y="{cy+(R+14)*math.sin(ang[i]):.1f}" font-size="10" fill="{C_MUTED}" text-anchor="middle">{_short(k)}</text>'
        for i in range(n))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{C_PRIMARY}"/>' for x, y in pts)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'{grid}{axis}'
            f'<polygon points="{poly}" fill="{C_PRIMARY}33" stroke="{C_PRIMARY}" stroke-width="2"/>'
            f'{dots}</svg>')


def svg_line(intensity: dict, size=360):
    """叙事强度轨迹：各年主题密度总和。"""
    years = sorted(intensity.keys())
    if not years:
        return '<p class="gap">叙事轨迹图不可用：narrative_intensity.json 缺失。</p>'
    series = []
    for y in years:
        th = intensity[y]
        if isinstance(th, dict):
            series.append(sum(v for k, v in th.items()
                              if k != "_total_tokens" and isinstance(v, (int, float))))
        else:
            series.append(0)
    W, H = size, 200
    mx = max(series) if max(series) > 0 else 1
    pad = 30
    px = [pad + (W - 2 * pad) * i / max(1, len(series) - 1) for i in range(len(series))]
    py = [H - pad - (H - 2 * pad) * v / mx for v in series]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(px, py))
    xlab = "".join(f'<text x="{px[i]:.1f}" y="{H-8}" font-size="10" fill="{C_MUTED}" text-anchor="middle">{years[i]}</text>' for i in range(len(years)))
    ylab = f'<text x="6" y="{pad-12}" font-size="9" fill="{C_MUTED}">峰值 {mx:.1f}</text>'
    area = f"M{px[0]:.1f},{H-pad} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in zip(px, py)) + f" L{px[-1]:.1f},{H-pad} Z"
    return (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<path d="{area}" fill="{C_SECOND}22"/>'
            f'<polyline points="{poly}" fill="none" stroke="{C_SECOND}" stroke-width="2"/>'
            f'{xlab}{ylab}</svg>')


def heatmap_table(years, matrix, top_n=12):
    """词频热力图：行=词(取总量 top_n)，列=年。"""
    if not matrix:
        return '<p class="gap">词频热力图不可用：word_freq_matrix.csv 缺失。</p>'
    totals = {w: sum(v) for w, v in matrix.items()}
    top = sorted(totals.items(), key=lambda x: -x[1])[:top_n]
    if not years:
        return '<p class="gap">词频热力图：年份缺失。</p>'
    maxv = max((max(matrix.get(w, [0]) or [0]) for w, _ in top), default=1) or 1
    head = "<th>关键词</th>" + "".join(f"<th>{y}</th>" for y in years)
    body = ""
    for w, _ in top:
        cells = matrix.get(w, [])
        row = ""
        for j, y in enumerate(years):
            val = cells[j] if j < len(cells) else 0
            t = min(1.0, val / maxv)
            bg = _lerp_color(t, "#ffffff", C_PRIMARY) if val > 0 else "#ffffff"
            fg = "#fff" if t > 0.55 else C_TEXT
            row += f'<td style="background:{bg};color:{fg}">{int(val)}</td>'
        body += f"<tr><td class='w'>{w}</td>{row}</tr>"
    return (f'<table class="hm"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


# ─────────────────────────────────────────────────────────────────────────
# 4. 章节构建
# ─────────────────────────────────────────────────────────────────────────
def _short(name):
    return name.replace("理论", "").replace("分析", "").replace("与网络效应", "").replace("框架", "")[:5]


def sec_header(ev, company, code):
    meta = ev.get("meta", {})
    name = company or meta.get("company_name") or "未知公司"
    c = code or meta.get("stock") or "—"
    scope = f"覆盖维度 {meta.get('dims_present_count','?')} 项 ｜ 摘录 {meta.get('excerpt_count','?')} 条 ｜ 数字台账 {meta.get('number_ledger_count','?')} 项"
    return f"""
<header>
  <div class="brand">listed-company-analysis · 咨询报告（形态 B）</div>
  <h1>{name} <span class="code">{c}</span></h1>
  <div class="sub">生成时间：{meta.get('generated_at','—')} ｜ {scope}</div>
</header>"""


def sec_exec(ev):
    one = ev.get("one_liner", "")
    gaps = ev.get("evidence", {}).get("known_gaps", [])
    tf = ev.get("evidence", {}).get("theoretical_framework", {})
    scored = tf.get("scored_frameworks", {}) if isinstance(tf, dict) else {}
    lines = []
    if one:
        lines.append(f"<p class='lead'>{one}</p>")
    lines.append("<ul class='bullets'>")
    lines.append(f"<li>理论框架：{len(scored)} 个已评分" +
                 (f"（{', '.join(f'{k}={v}' for k,v in scored.items())}）" if scored else "") +
                 f"；data_gap 框架：{tf.get('gap_frameworks') or '无'}。</li>")
    lines.append(f"<li>已知数据缺口：{len(gaps)} 项（均须 data_gap 标注，不得写成结论）。</li>")
    nvf = ev.get("evidence", {}).get("narrative_vs_fact", {})
    if isinstance(nvf, dict) and nvf.get("status") == "ok":
        lines.append(f"<li>叙事 vs 事实偏离检测：已量化（{nvf.get('aligned_years')} 年）。</li>")
    else:
        lines.append("<li>叙事 vs 事实偏离检测：未跑或年数&lt;3（data_gap）。</li>")
    lines.append("</ul>")
    return "<section><h2>一、执行摘要</h2>" + "".join(lines) + "</section>"


def sec_kpi(cards):
    items = ""
    for title, val, sub, ok in cards:
        cls = "" if ok else " gap-card"
        vcls = "v" if ok else "v gap"
        items += f"""<div class="kpi{cls}"><div class="kt">{title}</div>
          <div class="{vcls}">{val}</div><div class="ks">{sub}</div></div>"""
    return f"<section><h2>二、核心指标卡</h2><div class='kpis'>{items}</div>" \
           f"<p class='note'>指标卡取自已落盘产物；标 data_gap 表示对应数据源未提供，非结论缺失。</p></section>"


def sec_theory(tf):
    fws = tf.get("frameworks", []) if isinstance(tf, dict) else []
    if not fws:
        return "<section><h2>三、六理论框架整合</h2><p class='gap'>未找到 theoretical_framework.json（请先跑 theoretical_framework.py）。</p></section>"
    rows = ""
    scores = {}
    for f in fws:
        o = f.get("overall_score")
        if isinstance(o, (int, float)):
            scores[f["name_cn"]] = o
        band = f.get("overall_band", "data_gap")
        gap = "、".join(f.get("gap_dims", [])) or "无"
        rows += f"<tr><td>{f['name_cn']}<br><span class='en'>{f['name_en']}</span></td>" \
                f"<td class='{'ok' if isinstance(o,(int,float)) else 'gap'}'>{o if o is not None else 'data_gap'}</td>" \
                f"<td>{band}</td><td>{gap}</td></tr>"
    table = f"""<table class="grid"><thead><tr><th>理论框架</th><th>整体评分</th><th>档位</th><th>待补维度</th></tr></thead>
      <tbody>{rows}</tbody></table>"""
    radar = svg_radar(scores)
    return f"<section><h2>三、六理论框架整合</h2><div class='two'>{table}<div class='chart'>{radar}</div></div></section>"


def sec_problems(ev):
    gaps = ev.get("evidence", {}).get("known_gaps", [])
    if not gaps:
        return "<section><h2>四、核心问题卡片</h2><p>未发现已知缺口（证据完整）。</p></section>"
    cards = ""
    for g in gaps:
        dim = g.get("dimension", "?")
        stat = g.get("status", "")
        note = g.get("note", "")
        forbid = g.get("forbidden", "")
        cards += f"""<div class="pcard"><div class="ph"><span class="tag">{stat}</span>{dim}</div>
          <div class="pb">{note}</div>{('<div class="pf">🔴 {forbid}</div>') if forbid else ''}</div>"""
    return f"<section><h2>四、核心问题卡片</h2><div class='pcards'>{cards}</div></section>"


def sec_reco(ev, tf):
    gaps = ev.get("evidence", {}).get("known_gaps", [])
    fws = tf.get("frameworks", []) if isinstance(tf, dict) else []
    recos = []
    for g in gaps:
        dim = g.get("dimension", "")
        note = g.get("note", "")
        recos.append(f"针对「{dim}」：{note} 建议补充一手信源后复核，当前不下定量结论。")
    for f in fws:
        if f.get("status") != "ok" and f.get("gap_dims"):
            recos.append(f"「{f['name_cn']}」因 {', '.join(f['gap_dims'])} 未评出整体分，"
                         f"建议补齐外部源（{f['dimensions'][0].get('source','')}）后再做框架级判断。")
    if not recos:
        recos.append("当前证据较完整，建议聚焦执行摘要所列维度做深入归因。")
    items = "".join(f"<li>{r}</li>" for r in recos[:8])
    return f"<section><h2>五、战略举措与改善建议</h2>" \
           f"<p class='note'>以下为<strong>建议（非结论）</strong>，均源自已知缺口与框架缺口，须补数据后落地。</p>" \
           f"<ul class='bullets'>{items}</ul></section>"


def sec_charts(data_dir):
    intensity = load_intensity(data_dir)
    years, matrix = load_wordfreq(data_dir)
    line = svg_line(intensity)
    hm = heatmap_table(years, matrix)
    return f"<section><h2>六、可视化图表</h2>" \
           f"<div class='chart-block'><h3>叙事强度轨迹（MD&A 主题密度/千词）</h3>{line}</div>" \
           f"<div class='chart-block'><h3>MD&A 关键词词频热力图（按年）</h3>{hm}</div></section>"


def sec_appendix(ev, data_dir):
    abbr = [
        ("CAGR", "复合年均增长率"),
        ("MD&A", "管理层讨论与分析（年报章节）"),
        ("RBV·VRIO", "资源基础观（价值/稀缺/难模仿/组织）"),
        ("TAM", "技术接受模型"),
        ("data_gap", "数据缺口：对应来源未提供，禁止编造结论"),
    ]
    abbr_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in abbr)
    src = ("MCP 优先数据源（wind-finance / dzh-mcp / qcc-company / alphapai）；"
           "年报 PDF 爬虫与网页搜索作兜底。")
    scripts = ("analyze.py（采集）→ mda_semantic.py（语义量化）→ theoretical_framework.py（理论打分）"
               "→ article_brief.py（证据包）→ article_checklist.py（45+ 门禁）→ 本报告。")
    caliber = ("财务口径取自 financials.json（年序列均值）；叙事强度取自 mda_semantic_out；"
               "理论评分阈值为分析脚手架，引用前须与年报原文核对。")
    return f"""<section><h2>七、附录</h2>
    <h3>附录 A · 缩略语</h3><table class="grid"><tbody>{abbr_rows}</tbody></table>
    <h3>附录 B · 数据来源</h3><p>{src}</p>
    <h3>附录 C · 脚本说明</h3><p>{scripts}</p>
    <h3>附录 D · 口径说明</h3><p>{caliber}</p></section>"""


# ─────────────────────────────────────────────────────────────────────────
# 5. 主流程
# ─────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="咨询报告形态 B（离线 HTML）")
    ap.add_argument("data_dir", help="含 results.json / evidence_pack.json 的数据目录")
    ap.add_argument("--output", default=None, help="报告 HTML 路径")
    ap.add_argument("--company", default=None)
    ap.add_argument("--code", default=None)
    args = ap.parse_args()

    data_dir = args.data_dir
    out = args.output or os.path.join(data_dir, "consulting_report.html")

    ev = load_evidence(data_dir)
    if not ev:
        sys.stderr.write(f"[report_advisory] 未找到 {data_dir}/evidence_pack.json，请先跑 article_brief.py\n")
        sys.exit(2)
    tf = load_theoretical(data_dir)
    kpis = build_kpis(data_dir)

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>咨询报告 · {ev.get('meta',{}).get('company_name') or args.company or ''}</title>
<style>
  :root{{--p:{C_PRIMARY};--s:{C_SECOND};--a:{C_ACCENT};--bg:{C_BG};--card:{C_CARD};--t:{C_TEXT};--m:{C_MUTED};--bd:{C_BORDER};}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--t);font-family:"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.6}}
  .wrap{{max-width:980px;margin:0 auto;padding:28px 22px 60px;background:var(--card)}}
  header{{border-bottom:3px solid var(--p);padding-bottom:14px;margin-bottom:18px}}
  .brand{{color:var(--m);font-size:12px;letter-spacing:.5px}}
  h1{{margin:6px 0;font-size:26px}}
  .code{{color:var(--p);font-size:18px;font-weight:normal}}
  .sub{{color:var(--m);font-size:13px}}
  h2{{color:var(--p);border-left:4px solid var(--p);padding-left:10px;margin-top:30px;font-size:19px}}
  h3{{color:var(--s);font-size:15px;margin:16px 0 8px}}
  section{{margin-bottom:10px}}
  .lead{{font-size:15px;background:#f0f4f8;padding:12px 14px;border-radius:6px}}
  .bullets{{padding-left:20px}} .bullets li{{margin:4px 0}}
  .note{{color:var(--m);font-size:12px;font-style:italic}}
  .kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:8px}}
  .kpi{{border:1px solid var(--bd);border-radius:8px;padding:14px;text-align:center;background:#fafbfc}}
  .kpi.gap-card{{border-color:#f0c5c0}}
  .kt{{color:var(--m);font-size:13px}}
  .kpi .v{{font-size:24px;font-weight:700;color:var(--p);margin:6px 0}}
  .kpi .v.gap{{color:var(--a);font-size:18px}}
  .ks{{color:var(--m);font-size:11px}}
  .grid{{width:100%;border-collapse:collapse;font-size:13px}}
  .grid th,.grid td{{border:1px solid var(--bd);padding:7px 9px;text-align:left;vertical-align:top}}
  .grid th{{background:#eef2f7;color:var(--p)}}
  .ok{{color:var(--s);font-weight:700}} .gap{{color:var(--a);font-weight:700}}
  .en{{color:var(--m);font-size:11px}}
  .two{{display:flex;gap:18px;flex-wrap:wrap;align-items:center}}
  .two table{{flex:1;min-width:320px}} .chart{{flex:0 0 340px;text-align:center}}
  .pcards{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}
  .pcard{{border:1px solid var(--bd);border-left:4px solid var(--a);border-radius:6px;padding:10px 12px;background:#fffdfb}}
  .ph{{font-weight:700;font-size:14px}} .tag{{background:var(--a);color:#fff;font-size:11px;padding:1px 6px;border-radius:3px;margin-right:6px}}
  .pb{{font-size:13px;margin:5px 0}} .pf{{font-size:12px;color:var(--a)}}
  .chart-block{{margin:10px 0 18px}} .chart-block svg{{max-width:100%}}
  table.hm{{border-collapse:collapse;font-size:12px;margin-top:6px}}
  table.hm th,table.hm td{{border:1px solid var(--bd);padding:4px 7px;text-align:center}}
  table.hm th{{background:#eef2f7;color:var(--p)}} table.hm td.w{{text-align:left;color:var(--t);background:#fafbfc}}
  footer{{margin-top:34px;border-top:1px solid var(--bd);padding-top:12px;color:var(--m);font-size:11px}}
</style></head><body><div class="wrap">
{sec_header(ev, args.company, args.code)}
{sec_exec(ev)}
{sec_kpi(kpis)}
{sec_theory(tf)}
{sec_problems(ev)}
{sec_reco(ev, tf)}
{sec_charts(data_dir)}
{sec_appendix(ev, data_dir)}
<footer>本报告由 listed-company-analysis · 咨询报告模式（形态 B）自动生成；内容全部源自落盘产物，data_gap 维度未做结论。配色为中性学术色，非任何机构品牌。</footer>
</div></body></html>"""

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    print(f"[report_advisory] 报告 → {out}")
    print(f"  指标卡={len(kpis)} | 理论框架={len(tf.get('frameworks',[]))} | "
          f"问题卡片={len(ev.get('evidence',{}).get('known_gaps',[]))}")


if __name__ == "__main__":
    main()
