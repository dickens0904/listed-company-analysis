# -*- coding: utf-8 -*-
"""
article_brief.py — 「评论文章证据包」生成器（基座 → 写作层 的桥梁）
================================================================

## 定位（2026-10-21 升级）

这是三层架构里的**第二层（证据包层）**。第一层是 37 维度的采集基座（results.json），
第三层是 LLM 深度评论生成。本模块把基座里的原始数据，**提炼成一份 LLM 可读、可溯源、
且"全量开放"的证据包**——既给写作环节当骨架，又把底层素材原样摊开，避免两层之间
出现"信息黑洞"（LLM 只能看到被我二次加工过的 8 条摘要，于是开始编造）。

### 与旧版的核心区别
旧版做的是"降维"——从 37 维度只抽 12 个要素，且每条只给 1-2 句 curated 摘要。
这恰恰是"信息黑洞"的来源：原文、页码、口径全丢了，LLM 只能凭摘要写，容易臆造。

新版做"**降噪不降维**"：
  - 保留 7 节拍叙事骨架（story spine）——这是文章结构，必须有人把关；
  - 但**素材全量开放**：原文摘录(≤500字)、数字台账(口径+来源)、实体索引、
    已知缺口(把"没取到"的地方明说出来，反向锁死 LLM 的编造空间)。

### 证据包核心件（事实萃取 + 赛道曝光）
1. **excerpts（原文摘录）**   —— 每条带 citation：来源类型 / 文件 / 日期 / **页码** / 链接。
                                年报 23 个章节、资本运作公告、新业务线索、决策动因原文
                                （权益变动目的 / 交易背景和目的，用 fitz 直接啃 PDF 第 N 页）、
                                诉讼/风险信号，全部摊开。
2. **number_ledger（数字台账）** —— 每个数字带"口径"和"来源"。凡数值必能追到年报/公告原文。
3. **entity_index（实体索引）**  —— 公司 / 点名客户 / 产品型号 / 交易对手 / **穿透持股链**。
3.5. **sector_exposure（赛道曝光）** —— 新兴领域名词聚合（机器人/AI/半导体/新能源/低空…），
                                  附原文句+出处；**只聚合不判断**，弥补"原文笼统讲赛道、
                                  不点名客户"时的信号丢失。
4. **known_gaps（已知缺口）**    —— 把"这一维没取到 / 数据缺失 / 工具不可用"的地方显式列出，
                                并标注"禁止编造"。这是反向护栏：LLM 看到缺口清单，就知道
                                哪些数字不能凭空填。

### 自动化两件事（用户点名要的）
- **权益变动目的原文**：扫描《详式权益变动报告书》《重大资产出售/购买预案》等，用 fitz
  直接定位"权益变动的目的 / 本次交易的背景和目的"章节，连同页码一起抠出来。
- **穿透持股计算**：从 structure.equity_penetration 直接取已算好的分层持股链与最终控制比例。

### 依赖
- 纯 Python，不依赖 LLM。
- 页码提取用 PyMuPDF（fitz）。fitz 不可用时**优雅降级**：页码留 null 并注明
  "需 PyMuPDF"，其余证据照常产出。运行时请用带 fitz 的 venv：
  `envs/default/Scripts/python.exe scripts/article_brief.py <data_dir>`

### 用法
    python scripts/article_brief.py <data_dir> [--out-dir <dir>] [--no-md]
    默认产出：<data_dir>/evidence_pack.json + evidence_pack.md
    兼容产出：<data_dir>/article_brief.json（旧骨架，下游如需）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# fitz 可选依赖（页码提取用）。不可用时降级，不阻断证据包生成。
try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except Exception:
    fitz = None
    _HAS_FITZ = False


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _f(x, unit=1e8, nd=2):
    """金额格式化到亿；None/非法返回 None"""
    try:
        return round(float(x) / unit, nd)
    except (TypeError, ValueError):
        return None


def _load(data_dir: str) -> Dict[str, Any]:
    with open(os.path.join(data_dir, 'results.json'), encoding='utf-8') as fh:
        return json.load(fh)


def _clean(txt: str) -> str:
    """压掉 PDF 提取常见的行内多余空白与软换行，便于切句/定位"""
    if not txt:
        return ''
    txt = txt.replace('\u00a0', ' ')
    txt = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', '', txt)
    txt = re.sub(r'\s*\n\s*', '\n', txt)
    return txt.strip()


def _cap(s: str, n: int = 500) -> str:
    s = (s or '').strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + '…（截断，完整见源文件）'


# ---------------------------------------------------------------------------
# 页码定位（fitz 可选）
# ---------------------------------------------------------------------------

def _read_pdf_pages(pdf_path: str) -> Optional[List[Tuple[int, str]]]:
    if not _HAS_FITZ or not pdf_path or not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        pages = [(i + 1, (doc[i].get_text() or '')) for i in range(len(doc))]
        doc.close()
        return pages
    except Exception:
        return None


# 同一次运行内缓存 PDF 分页文本，避免多章节反复开文件
_PDF_PAGES_CACHE: Dict[str, Optional[List[Tuple[int, str]]]] = {}


def _get_pages(pdf_path: str) -> Optional[List[Tuple[int, str]]]:
    if pdf_path in _PDF_PAGES_CACHE:
        return _PDF_PAGES_CACHE[pdf_path]
    v = _read_pdf_pages(pdf_path)
    _PDF_PAGES_CACHE[pdf_path] = v
    return v


def _locate_page(fragment: str, pdf_path: str) -> Optional[int]:
    """在 PDF 中定位某个片段首次出现的页码（未装 fitz 返回 None）"""
    pages = _get_pages(pdf_path)
    if not pages or not fragment:
        return None
    frag = _clean(fragment)[:50]
    frag = re.sub(r'\s+', '', frag)
    if not frag:
        return None
    for pno, txt in pages:
        if re.sub(r'\s+', '', txt).find(frag) >= 0:
            return pno
    return None


def _resolve_pdf(pdf_path: str, data_dir: str) -> str:
    """results.json 里常存相对路径（相对 analyze 运行时 cwd），在 evidence_pack 下失效；
    退回 data_dir 下按 basename 查找，再退回 data_dir 内首个 annual PDF。"""
    if pdf_path and os.path.isabs(pdf_path) and os.path.exists(pdf_path):
        return pdf_path
    if pdf_path and os.path.exists(pdf_path):
        return pdf_path
    if pdf_path:
        cand = os.path.join(data_dir, os.path.basename(pdf_path))
        if os.path.exists(cand):
            return cand
    if data_dir and os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            fl = fn.lower()
            if 'annual' in fl and fl.endswith('.pdf'):
                return os.path.join(data_dir, fn)
    return pdf_path


def _toc_page_loose(toc: List[Dict], name: str) -> Optional[int]:
    """toc 标题用词常有"方案/预案""前五名/前五大"等差异，严格子串会漏；
    退而取核心词（去常见后缀）与前 2 字做包含匹配。"""
    if not toc or not name:
        return None
    core = re.sub(r'(方案|情况|明细|详情与金额|详情|分析|数据|状况|报告|预案)$', '', name)
    cands = [name, core]
    if len(core) >= 2:
        cands.append(core[:2])
    for c in cands:
        if len(c) < 2:
            continue
        for e in toc:
            t = e.get('title') or ''
            if c in t:
                return e.get('page')
    return None


def _annual_section_page(skey: str, name: str, content: str, toc: List[Dict],
                        pdf_path: str, data_dir: str = '') -> Optional[int]:
    """年报章节页码：toc 严格 → _SECTION_TOC_KW → toc 模糊 → fitz 直接定位首句/标题"""
    page = _toc_page_for(toc, name)
    if page is None:
        page = _toc_page_for(toc, _SECTION_TOC_KW.get(skey, skey))
    if page is None:
        page = _toc_page_loose(toc, name)
    if page is None and pdf_path:
        rp = _resolve_pdf(pdf_path, data_dir)
        frag = (content or '')[:40]
        if frag.strip():
            page = _locate_page(frag, rp)
        if page is None:
            page = _locate_page(name, rp)
    return page


def _extract_section_text(pdf_path: str, markers: List[str],
                         stop_markers: List[str], max_chars: int = 900) -> Tuple[str, Optional[int]]:
    """从 PDF 抠出"某个章节"的正文（从首个 marker 起，到 stop 或 max_chars 止）。

    Returns: (正文, 首命中页码)
    """
    pages = _read_pdf_pages(pdf_path)
    if not pages:
        return '', None
    full = '\n'.join(t for _, t in pages)
    full_clean = _clean(full)
    for mk in markers:
        idx = full_clean.find(mk)
        if idx < 0:
            continue
        # 找到本章节起始，向后截 max_chars
        seg = full_clean[idx: idx + max_chars]
        # 截到下一个章节标题前
        for sm in stop_markers:
            j = seg.find(sm, len(mk))
            if j > 0:
                seg = seg[:j]
                break
        # 定位页码：用 marker 前若干字
        page = _locate_page(mk[:30], pdf_path)
        return _clean(seg), page
    return '', None


# ---------------------------------------------------------------------------
# 报告期 PDF 定位 + 全文提取（fitz 可选）
# ---------------------------------------------------------------------------

def _periodic_pdfs(data_dir: str) -> Dict[str, str]:
    """在 data_dir 下识别 年报/半年报/季报 PDF 路径。
    🔴 semi_annual 文件名也含 'annual'，须先判 'semi' 再判 'annual'。"""
    out: Dict[str, str] = {}
    if not data_dir or not os.path.isdir(data_dir):
        return out
    for fn in os.listdir(data_dir):
        fl = fn.lower()
        if not fl.endswith('.pdf'):
            continue
        p = os.path.join(data_dir, fn)
        if 'semi' in fl and 'annual' in fl:
            out.setdefault('semi', p)
        elif 'quarter' in fl or '一季' in fl or '三季' in fl:
            out.setdefault('quarterly', p)
        elif 'annual' in fl:
            out.setdefault('annual', p)
    return out


def _extract_full_text(pdf_path: str) -> str:
    """fitz 全文（分页缓存复用）；fitz 不可用/文件缺失返回 ''。"""
    if not _HAS_FITZ or not pdf_path or not os.path.exists(pdf_path):
        return ''
    pages = _get_pages(pdf_path)
    if not pages:
        return ''
    return '\n'.join(t for _, t in pages)


# ---------------------------------------------------------------------------
# 最新报告期财务（累计口径 + 同比 + TTM + 全年预测）
# ---------------------------------------------------------------------------

def _latest_financial(f: Dict) -> Dict:
    """从 financial.records 取**最新报告期**，算 累计实际 + 同比 + TTM + 全年预测。

    🔴 关键坑：A 股中期报告（半年报/三季报/一季报）的"营业收入/净利润"是
    **年初至报告期末累计值**，不是单季。直接"年化"(×2)会翻倍。故：
      - 呈现一律用**累计口径**；
      - TTM = 最近完整年报 − 上年同期累计 + 本期累计（标准滚动 12 个月，非预测）；
      - 全年预测 = 本期累计 × (上年全年 / 上年同期累计)（季节性放大，**非承诺**）。
    """
    recs = (f.get('financial') or {}).get('records') or []
    if not recs:
        return {}

    def _rd(r):
        return str(r.get('REPORTDATE') or '')[:10]

    recs = sorted(recs, key=_rd)
    L = recs[-1]
    lrd = _rd(L)
    ly = lrd[:4]
    is_annual = lrd.endswith('12-31')
    qdate = L.get('QDATE') or ''

    annual = None
    for r in recs:
        if _rd(r).endswith('12-31'):
            annual = r  # 已按日期排序 → 最后一个即最近完整年报

    prior_interim = None
    if not is_annual:
        py = str(int(ly) - 1)
        prior_md = lrd[5:]  # 同期月-日，如 '06-30'
        for r in recs:
            d = _rd(r)
            if d[:4] == py and d[5:] == prior_md:
                prior_interim = r

    rev_L = _f(L.get('TOTAL_OPERATE_INCOME'))
    np_L = _f(L.get('PARENT_NETPROFIT'))
    rev_ann = _f(annual.get('TOTAL_OPERATE_INCOME')) if annual else None
    np_ann = _f(annual.get('PARENT_NETPROFIT')) if annual else None
    rev_pri = _f(prior_interim.get('TOTAL_OPERATE_INCOME')) if prior_interim else None
    np_pri = _f(prior_interim.get('PARENT_NETPROFIT')) if prior_interim else None

    out: Dict[str, Any] = {
        'report_date': lrd, 'year': ly, 'is_annual': is_annual,
        'datatype': (L.get('DATATYPE') or L.get('DATEMMDD') or ('年报' if is_annual else '中期报告')),
        'revenue': rev_L, 'net_profit': np_L,
        'eps': L.get('BASIC_EPS'), 'bps': L.get('BPS'),
        'total_assets': _f(L.get('TOTAL_ASSETS')),
        'total_parent_equity': _f(L.get('TOTAL_PARENT_EQUITY')),
        'rev_yoy_pct': L.get('YSTZ'), 'np_yoy_pct': L.get('SJLTZ'),
    }
    # TTM（滚动 12 个月，非预测）
    if is_annual:
        out['ttm_revenue'] = rev_L
        out['ttm_net_profit'] = np_L
    else:
        if None not in (rev_ann, rev_pri, rev_L):
            out['ttm_revenue'] = round(rev_ann - rev_pri + rev_L, 4)
        if None not in (np_ann, np_pri, np_L):
            out['ttm_net_profit'] = round(np_ann - np_pri + np_L, 4)
    # 全年预测（季节性外推，非承诺）
    if not is_annual and rev_pri and rev_pri > 0 and rev_ann is not None:
        factor = rev_ann / rev_pri
        out['fy_revenue_forecast'] = round(rev_L * factor, 4)
        out['fy_revenue_factor'] = round(factor, 3)
        # 利润仅当上年同期与全年同号且非零才外推，否则标注不宜外推
        if np_pri and np_ann is not None and (np_pri > 0) == (np_ann > 0):
            out['fy_netprofit_forecast'] = round(np_L * (np_ann / np_pri), 4)
        else:
            out['fy_netprofit_forecast'] = None
            out['fy_netprofit_note'] = '利润受季节性/年末减值影响，外推置信度低，不宜给数'
    return out


# ---------------------------------------------------------------------------
# 营收剧变归因（托底）：营收同比 |Δ| 大时，自动搜集"为什么变"的证据
# ---------------------------------------------------------------------------

def _revenue_change_attribution(f: Dict, data_dir: str, lp: Dict) -> Optional[Dict]:
    """营收剧变归因。最新报告期营收同比 |Δ| ≥ 25% 时触发，搜集候选归因证据：
    ① 定期报告正文**结构性信号**（最强托底）：合并范围变更/不再纳入合并范围/丧失控制权/
       处置·出售子公司或股权/会计口径变更，连同"营业总收入…同比±X%"事实句一起抠出；
    ② 公告（**时间过滤**：仅取报告期前 ~18 个月内，避免命中多年前的老并购）。
    🔴 只列证据、不下结论；找不到明确归因 → 显式缺口，禁止文章凭常识臆测原因。
    """
    if not lp or lp.get('is_annual'):
        return None
    yoy = lp.get('rev_yoy_pct')
    if yoy is None or abs(yoy) < 25:
        return None

    rd = str(lp.get('report_date') or '')[:10]

    def _cutoff(d, months):
        if not d or len(d) < 7:
            return '0000-00-00'
        y, m = int(d[:4]), int(d[5:7])
        tot = y * 12 + (m - 1) - months
        return f'{tot // 12:04d}-{tot % 12 + 1:02d}-01'
    lo = _cutoff(rd, 18)

    cands: List[Dict] = []
    cause_pats = [
        (r'不再纳入合并范围|不再纳入合并|合并范围变更|合并范围减少', '合并范围变更(并表口径变化/出表)'),
        (r'丧失控制权', '丧失控制权(出表)'),
        (r'处置.{0,8}(子公司|股权|资产)|出售.{0,8}(子公司|股权)|转让.{0,8}(子公司|控股权)', '处置/出售/转让子公司或股权'),
        (r'会计政策.{0,12}变更|会计估计.{0,8}变更|追溯调整|重述|同一控制下', '会计口径变更'),
    ]

    # ① 定期报告正文结构性信号（主托底）
    pp = _periodic_pdfs(data_dir)
    for rkey, rname in (('semi', '半年报'), ('quarterly', '季报')):
        pdfp = pp.get(rkey, '')
        if not pdfp:
            continue
        txt = _extract_full_text(pdfp)
        if not txt:
            continue
        fm = re.search(r'[^。\n]{0,24}(营业收入|营业总收入)[^。\n]{0,40}'
                       r'(下降|减少|增长|增加)[^。\n]{0,30}', txt)
        if fm:
            cands.append({'kind': '营收事实', 'source': rname, 'label': fm.group(0).strip()[:70],
                          'date': '', 'evidence': fm.group(0).strip()[:220]})
        # 归因句：收集所有含结构词的句子，滤掉披露清单/提示句，按 cause 优先级取最佳
        hits = []
        for s in re.split(r'[。；]', txt):
            s = re.sub(r'\s+', '', s)  # 去段内换行/空白，还原被 PDF 折行截断的整句
            if not (12 <= len(s) <= 220):
                continue
            # 跳过披露清单/提示句（"是否…"、□适用√不适用、问句）
            if re.search(r'是否|□适用|√不适用', s) or s.endswith('？') or s.endswith('?'):
                continue
            struct = next((k for p, k in cause_pats if re.search(p, s)), None)
            if not struct:
                continue
            # 会计政策样板段（含"按照/核算/会计处理/准则"且无"本期/本报告期/主要系"）→ 跳过
            if re.search(r'按照|会计核算|会计处理原则|定义为|准则规定', s) and \
                    not re.search(r'本报告期|本期|报告期内|主要系|主要原因', s):
                continue
            # 丧失控制权须带因果链接，避免命中会计政策定义
            if struct.startswith('丧失控制权') and \
                    not re.search(r'主要系|由于|原因|本期|本报告期|导致|因此', s):
                continue
            prio = 0 if '合并范围' in struct else (1 if '丧失控制权' in struct
                                                   else (2 if '处置' in struct else 3))
            hits.append((prio, s, struct))
        if hits:
            hits.sort(key=lambda x: x[0])
            _, s, struct = hits[0]
            cands.append({'kind': struct, 'source': rname, 'label': s[:70],
                          'date': '', 'evidence': s[:240]})
            break

    # ② 公告（时间过滤：仅报告期前 18 个月内）
    ann = f.get('announcements') or {}
    allanns: List[Dict] = []
    for tier in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        allanns += [a for a in (ann.get(tier) or []) if isinstance(a, dict)]
    ann_pats = [
        (r'丧失控制权|不再纳入合并|出表|处置.{0,6}子公司|出售.{0,6}(子公司|股权)|转让.{0,6}控股权|分立|划转', '合并范围减少(出表/处置/转让)'),
        (r'收购|并购|重大资产购买|并表', '合并范围增加(收购/并表)'),
    ]
    seen = set()
    for a in allanns:
        raw = a.get('date')
        d = str(raw) if raw is not None else ''
        # 归一日期：'2026-08-25' 直接取；整数 '20260825' → '2026-08-25'；其余留空（不过滤）
        if '-' in d:
            d = d[:10]
        elif len(d) >= 8 and d[:4].isdigit():
            d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        else:
            d = ''
        if d and d < lo:  # 太老，非本期原因
            continue
        t = a.get('title') or ''
        for pat, kind in ann_pats:
            if re.search(pat, t):
                key = t[:40]
                if key not in seen:
                    seen.add(key)
                    prev = (a.get('extracted_content') or {}).get('full_text_preview') or ''
                    cands.append({'kind': kind, 'source': '公告', 'label': t[:60], 'date': d,
                                  'evidence': prev[:200] if prev.strip() else '（标题命中，正文未取到，须回查原公告）'})
                break

    found = bool(cands)
    return {
        'triggered': True, 'yoy_pct': yoy, 'threshold': 25,
        'direction': '下降' if yoy < 0 else '增长',
        'candidates': cands[:8], 'found': found,
        'note': ('已列出候选归因证据；文章引用须回查原文，并区分"合并范围一次性变动" vs "内生经营持续变动"'
                 if found else
                 '🔴 营收同比剧变，但公告/MD&A 中未找到明确归因（出表/处置/收购/会计变更）。'
                 '禁止凭常识臆测原因；只能写"营收同比±X%"事实，并标注"归因待核实"。'),
    }


# ---------------------------------------------------------------------------
# 赛道曝光统一语料池：年报 + 半年报 + 季报 + 公告 + IR + 权益变动报告书
# ---------------------------------------------------------------------------

def _build_corpus(data_dir: str, r: Dict, f: Dict) -> List[Tuple[str, str, str, Optional[int], str, bool]]:
    """构造赛道曝光语料池 blocks: (text, label, source, page, date, counting)。

    覆盖：年报全文+章节 / 半年报(fitz) / 季报(fitz) / 公告(full_text_preview+关键PDF全文)
    / IR(investor_qa 元数据+PDF全文) / 简式·详式权益变动报告书(标题识别+fitz全文)。
    🔴 去重：文本前120字 hash 防同文双算；art_code 防同一公告 preview+PDF 双算。
    """
    blocks: List[Tuple[str, str, str, Optional[int], str, bool]] = []
    seen_text: set = set()
    seen_art: set = set()

    def _push(text, label, source, page, date, counting, art=None):
        if not text or not text.strip():
            return
        if art:
            if art in seen_art:
                return
            seen_art.add(art)
        key = re.sub(r'\s+', '', text)[:120]
        if key in seen_text:
            return
        seen_text.add(key)
        blocks.append((text, label, source, page, date, counting))

    ap = f.get('annual_pdf') or {}
    toc = ap.get('toc') or []
    pdf_path = _resolve_pdf(ap.get('pdf_path') or '', data_dir)
    sections = ap.get('sections') or {}
    full_text = ap.get('full_text') or ''
    has_full = bool(full_text.strip())

    # 年报分章节：sample 用，带页码；有全文时不计 total（避免与全文重复计数）
    if isinstance(sections, dict):
        sec_pairs = list(sections.items())
    elif isinstance(sections, list):
        sec_pairs = [(s.get('name', ''), s) for s in sections]
    else:
        sec_pairs = []
    for name, v in sec_pairs:
        if not isinstance(v, dict):
            continue
        content = v.get('content') or ''
        if not content.strip():
            continue
        sname = v.get('name') or name
        page = _annual_section_page(name, sname, content, toc, pdf_path, data_dir)
        _push(content, sname, '年报', page, '', not has_full)

    # 年报全文：全量计数
    _push(full_text, '年报全文', '年报', None, '', True)

    # 半年报 / 季报正文（periodic_reports 提取常失败，直接 fitz 啃 PDF）
    pp = _periodic_pdfs(data_dir)
    _push(_extract_full_text(pp.get('semi', '')), '半年报全文', '半年报', None, '', True)
    _push(_extract_full_text(pp.get('quarterly', '')), '季报全文', '季报', None, '', True)

    ann = f.get('announcements') or {}
    ca_dir = os.path.join(data_dir, 'critical_announcements') if data_dir else ''
    ca_ok = bool(ca_dir and os.path.isdir(ca_dir))

    def _pdf_for(art, fallback_pdf=''):
        if ca_ok and art:
            p = os.path.join(ca_dir, f'{art}.pdf')
            if os.path.exists(p):
                return p
        rp = _resolve_pdf(fallback_pdf or '', data_dir)
        return rp if (rp and os.path.exists(rp)) else ''

    all_ann: List[Dict] = []
    for tier in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        for a in (ann.get(tier) or []):
            if isinstance(a, dict):
                all_ann.append(a)

    # ① 关键公告 PDF 全文优先（权益变动报告书 / 重大对外投资·重组·合作类）→ 防 preview 双算
    for a in all_ann:
        title = a.get('title') or ''
        art = a.get('art_code') or ''
        date = str(a.get('date') or '')[:10]
        is_equity = ('权益变动' in title) or ('详式' in title) or ('简式' in title)
        is_keybiz = any(k in title for k in (
            '对外投资', '设立', '增资', '收购', '重组', '战略', '合作',
            '定点', '供货', '中标', '重大合同', '股权转让'))
        if not (is_equity or is_keybiz):
            continue
        pdfp = _pdf_for(art, a.get('pdf_path') or '')
        txt = _extract_full_text(pdfp)
        if txt:
            stype = '权益变动报告书' if is_equity else '公告(全文)'
            _push(txt, title[:50], stype, None, date, True, art=art)

    # ② IR 活动：investor_qa 元数据（标题）+ PDF 全文
    iq = f.get('investor_qa') or {}
    for rec in (iq.get('survey_records') or []) + (iq.get('roadshow_records') or []) + (iq.get('ir_activities') or []):
        if not isinstance(rec, dict):
            continue
        title = rec.get('title') or ''
        date = str(rec.get('date') or '')[:10]
        art = rec.get('art_code') or ''
        pdfp = _pdf_for(art, '')
        txt = _extract_full_text(pdfp)
        if txt:
            _push(txt, title[:50] or 'IR活动', 'IR/投资者关系', None, date, True, art=art)
        elif title:
            _push(title, title[:50], 'IR/投资者关系', None, date, True, art=art)

    # ③ 公告 full_text_preview（未被 PDF 全文覆盖的）
    def _ann_preview(a, stype):
        if not isinstance(a, dict):
            return
        title = a.get('title') or ''
        # 🔴 定期报告(年报/半年报/季报)已由 annual full_text + _periodic_pdfs(fitz) 直接啃 PDF，
        #    其公告 preview 会造成同一文件重复计数 → 跳过
        if re.search(r'(年度报告|半年度报告|季度报告)', title):
            return
        date = str(a.get('date') or '')[:10]
        prev = (a.get('extracted_content') or {}).get('full_text_preview') or a.get('content') or ''
        if prev and prev.strip():
            _push(prev, title[:50], stype, None, date, True, art=a.get('art_code') or '')

    for a in (ann.get('routine_announcements') or []):
        t = a.get('title') or ''
        _ann_preview(a, 'IR/投资者关系' if '投资者' in t else '公告')
    for a in (ann.get('major_announcements') or []):
        _ann_preview(a, '公告')
    for a in (ann.get('critical_announcements') or []):
        _ann_preview(a, '公告')
    cats = ann.get('categories') or {}
    if isinstance(cats, dict):
        for cv in cats.values():
            items = cv if isinstance(cv, list) else ([cv] if isinstance(cv, dict) else [])
            for a in items:
                _ann_preview(a, 'IR/投资者关系')

    return blocks


def _src_rank(stype: str) -> int:
    """样本句来源优先级：年报 > 半年报 > IR > 公告/权益变动/季报。"""
    if stype == '年报':
        return 0
    if stype == '半年报':
        return 1
    if 'IR' in stype or '投资者' in stype:
        return 2
    return 3


# ---------------------------------------------------------------------------
# 年报章节 → 叙事节拍 映射
# ---------------------------------------------------------------------------

# 章节→目录关键词（部分章节名与目录标题字面不完全一致，需映射）
_SECTION_TOC_KW = {
    'audit': '审计报告',
    'dividend': '利润分配',
    'financial_key_data': '主要会计数据',
    'balance_sheet_key': '资产负债表',
    'goodwill': '商誉',
    'litigation': '诉讼',
    'top5_customers': '前五名客户',
    'top5_suppliers': '前五名供应商',
    'rd_spending': '研发投入',
    'subsidiaries': '子公司',
    'new_subsidiaries': '子公司',
    'actual_controller': '实际控制人',
    'top10_shareholders': '股东',
}


# (section_key, 归入的节拍, 该章节在文章里回答什么问题)
_ANNUAL_SECTION_MAP = {
    'main_business': ('这门生意是什么', '公司靠什么赚钱、各业务块贡献'),  # 可能没有
    'company_profile': ('这门生意是什么', '一句话定位'),
    'actual_controller': ('谁在控制', '最终实控人及控制方式'),
    'top10_shareholders': ('谁在控制', '前十大股东结构'),
    'financial_key_data': ('钱是怎么赚的、怎么亏的', '近三年营收/净利/ROE 关键数据'),
    'balance_sheet_key': ('钱是怎么赚的、怎么亏的', '总资产/负债/资产负债率'),
    'production_sales': ('这门生意是什么', '产销量与产能利用'),
    'capacity': ('这门生意是什么', '产能状况'),
    'top5_customers': ('这门生意是什么', '客户集中度/关联销售'),
    'top5_suppliers': ('这门生意是什么', '供应商集中度/关联采购'),
    'rd_spending': ('新业务 / 题材', '研发投入强度'),
    'goodwill': ('资产负债表的重量', '商誉规模与减值'),
    'lt_equity': ('资本运作主线', '长期股权投资'),
    'subsidiaries': ('资本运作主线', '主要控股参股公司'),
    'new_subsidiaries': ('资本运作主线', '新设/处置子公司'),
    'guarantee': ('悬着的问题', '担保敞口'),
    'contingent': ('悬着的问题', '或有事项'),
    'litigation': ('悬着的问题', '重大诉讼仲裁'),
    'litigation_detail': ('悬着的问题', '诉讼金额与进展'),
    'post_events': ('悬着的问题', '资产负债表日后事项'),
    'auditor_change': ('悬着的问题', '审计机构变更'),
    'dividend': ('钱是怎么分的', '分红/送转预案'),
    'cip': ('钱是怎么投的', '在建工程'),
    'gov_subsidy': ('新业务 / 题材', '政府补助'),
    'audit': ('悬着的问题', '审计意见与关键审计事项'),
}


def _toc_page_for(toc: List[Dict], keyword: str) -> Optional[int]:
    """从年报目录里，按关键词找章节页码"""
    if not toc:
        return None
    for e in toc:
        t = (e.get('title') or '')
        if keyword in t:
            return e.get('page')
    # 宽松匹配：标题包含关键词的大部分字
    for e in toc:
        t = (e.get('title') or '')
        if keyword and keyword[:4] in t:
            return e.get('page')
    return None


# ---------------------------------------------------------------------------
# 各来源摘录提取
# ---------------------------------------------------------------------------

def _excerpts_annual(data_dir: str, f: Dict) -> List[Dict]:
    """年报 23 章节 → 摘录（带页码，从 toc 取）"""
    ap = f.get('annual_pdf') or {}
    secs = ap.get('sections') or {}
    toc = ap.get('toc') or []
    pdf_path = _resolve_pdf(ap.get('pdf_path') or '', data_dir)
    year = ap.get('year') or ''
    out = []
    if not isinstance(secs, dict):
        return out
    for skey, sec in secs.items():
        if not isinstance(sec, dict):
            continue
        name = sec.get('name') or skey
        content = sec.get('content') or ''
        if not content.strip():
            continue
        beat, q = _ANNUAL_SECTION_MAP.get(skey, ('其他', '详见年报对应章节'))
        page = _annual_section_page(skey, name, content, toc, pdf_path)
        out.append({
            'beat': beat,
            'question': q,
            'text': _cap(content, 500),
            'citation': {
                'kind': 'annual_report',
                'label': f'年报{year}·{name}',
                'file': os.path.basename(pdf_path) if pdf_path else f'annual_report_{year}.pdf',
                'date': f'{year}-12-31' if year else '',
                'page': page,
            'source': '巨潮/年报',
        },
    })
    return out


def _excerpts_annual_by_keywords(data_dir: str, f: Dict) -> List[Dict]:
    """港美股年报：无 A 股「23 章节」结构 → 按关键词在 PDF 里定位章节并摘录。

    2026-10-21 新增。背景：港股/美股 `annual_pdf` 现在能拿到原文（港交所披露易 /
    SEC 10-K），但 `three_statements` / `strategic_opportunity` 对非 A 股跳过 →
    `annual_pdf.sections` 为空 → `_excerpts_annual` 返回 [] → 证据包「摘录 0 条」，
    明明有 282 页年报却一条素材都没有。

    策略：按关键词组（繁体/简体并存）在页文本里找首个命中页，取该页 ≤500 字，
    带真实页码。宁可少而准，不做全文切片（避免把目录/表格噪声当业务叙述）。
    """
    groups = [
        (('管理層討論及分析', '管理层讨论与分析', '管理層討論與分析'),
         '业务', '管理层如何解释本期经营与变化？'),
        (('主席報告', '主席报告', '董事會報告', '董事会报告', '致股東'),
         '生意', '管理层如何描述业务本质与战略？'),
        (('業務回顧', '业务回顾', '經營回顧', '经营回顾'),
         '业务', '业务结构与经营情况'),
        (('主要風險', '主要风险', '風險因素', '风险因素'),
         '风险', '公司自述的主要风险'),
        (('獨立核數師報告', '独立核数师报告', '核數師報告', '审计报告'),
         '财务', '审计意见类型与关键审计事项'),
    ]
    ap = f.get('annual_pdf') or {}
    pdf_path = _resolve_pdf(ap.get('pdf_path') or '', data_dir)
    if not pdf_path:
        pp = _periodic_pdfs(data_dir)
        pdf_path = pp.get('annual', '') if isinstance(pp, dict) else ''
    if not pdf_path:
        return []
    pages = _get_pages(pdf_path)
    if not pages:
        return []

    year = ap.get('year') or ''
    if not year:
        ym = re.search(r'(20\d{2})', os.path.basename(pdf_path))
        year = ym.group(1) if ym else ''

    out: List[Dict] = []
    used = set()
    for kws, beat, q in groups:
        for idx, (pno, ptxt) in enumerate(pages):
            if idx in used:
                continue
            t = (ptxt or '').strip()
            # 跳过目录页：目录页行短、点多、含页码引导符
            if len(t) < 150 or t.count('…') > 3 or t.count('....') > 3:
                continue
            if any(k in t for k in kws):
                used.add(idx)
                out.append({
                    'beat': beat,
                    'question': q,
                    'text': _cap(t, 500),
                    'citation': {
                        'kind': 'annual_report',
                        'label': f'年报{year}·{kws[0]}',
                        'file': os.path.basename(pdf_path),
                        'date': f'{year}-12-31' if year else '',
                        'page': pno,
                        'source': ap.get('_source') or 'annual_report_pdf',
                    },
                })
                break
    return out


def _excerpts_us_10k(data_dir: str, f: Dict) -> List[Dict]:
    """美股 10-K（HTML 原文）→ 按 SEC Item 定位摘录（2026-10-21 新增）。

    背景：SEC 只给 `.htm` 原文（不是 PDF），`_periodic_pdfs` 扫不到 → 摘录 0 条。
    这里直接抓 10-K 页面、去标签、按 Item 标题切段，取 Item 1(Business) /
    Item 1A(Risk Factors) / Item 7(MD&A) / Item 8(Financial Statements) 各一段。
    """
    ap = f.get('annual_pdf') or {}
    url = ap.get('pdf_url') or ''
    if not url or not str(url).lower().endswith(('.htm', '.html')):
        return []

    cache = os.path.join(data_dir, '10k_filing.htm')
    html = ''
    try:
        import requests as _rq   # 本模块未顶层引入，避免影响其它路径
        if os.path.exists(cache) and os.path.getsize(cache) > 50_000:
            html = open(cache, encoding='utf-8', errors='ignore').read()
        else:
            r = _rq.get(url, headers={'User-Agent': 'research contact@example.com'},
                        timeout=60)
            if r.status_code != 200:
                return []
            html = r.text
            try:
                with open(cache, 'w', encoding='utf-8', errors='ignore') as fh:
                    fh.write(html)
            except Exception:
                pass
    except Exception:
        return []
    if not html:
        return []

    text = ''
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()
        text = soup.get_text(' ')
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) < 5000:
        return []
    low = text.lower()

    items = [
        (('item 1. business', 'item 1.business'), '生意', '公司如何描述业务与收入来源？'),
        (('item 1a. risk factors', 'item 1a.risk factors'), '风险', '公司自述的主要风险'),
        (("item 7. management's discussion", 'item 7. management’s discussion',
          'management\'s discussion and analysis'), '业务', '管理层如何解释经营变化？'),
        (('item 8. financial statements',), '财务', '财务报表与附注要点'),
    ]
    year = ap.get('year') or ap.get('filing_date', '')[:4] or ''
    out: List[Dict] = []
    used: List[int] = []

    def _find_body(kws) -> int:
        """定位正文里的 Item 标题（跳过开头目录：目录页窗口内会挤满 'item '）"""
        for kw in kws:
            start = 0
            while True:
                p = low.find(kw, start)
                if p == -1:
                    break
                window = low[p:p + 900]
                if window.count('item ') <= 2 and len(window) > 400:
                    return p
                start = p + 1
        return -1

    for kws, beat, q in items:
        pos = _find_body(kws)
        if pos == -1 or any(abs(pos - u) < 1500 for u in used):
            continue
        used.append(pos)
        out.append({
            'beat': beat,
            'question': q,
            'text': _cap(text[pos:pos + 900], 500),
            'citation': {
                'kind': 'annual_report',
                'label': f'10-K {year}·{kws[0].title()}',
                'file': os.path.basename(cache),
                'date': ap.get('filing_date') or (f'{year}-12-31' if year else ''),
                'page': None,
                'source': 'SEC EDGAR 10-K',
                'url': url,
            },
        })
    return out


def _excerpts_periodic(data_dir: str, f: Dict) -> List[Dict]:
    """半年报业务叙述摘录（决策1：年报+半年报业务内容都要）。
    半年报含"管理层讨论与分析/经营情况讨论与分析"，是年报之外**最新**的业务叙述源。
    🔴 目录页也会出现该标题（后跟点线+页码），须跳过，只取正文标题页。
    季报多为纯财报，无实质业务叙述，跳过。"""
    pp = _periodic_pdfs(data_dir)
    semi = pp.get('semi', '')
    if not semi:
        return []
    ym = re.search(r'(20\d{2})', os.path.basename(semi))
    year = ym.group(1) if ym else ''
    pages = _get_pages(semi)
    if not pages:
        return []
    headings = ['管理层讨论与分析', '经营情况讨论与分析', '董事会报告']
    stops = ['公司治理', '重要事项', '环境和社会责任', '股份变动', '财务报告', '债券']
    body = ''
    page_no = None
    for i, (pno, ptxt) in enumerate(pages):
        ptxt_clean = _clean(ptxt)
        for h in headings:
            idx = ptxt_clean.find(h)
            if idx < 0:
                continue
            before = ptxt_clean[max(0, idx - 5): idx].rstrip()
            after = ptxt_clean[idx + len(h): idx + len(h) + 50]
            # 跳过目录页：标题后跟一长串点线（≥4 连续点/圈/省略号）再接页码
            if re.search(r'[.。·…]{4,}', after):
                continue
            # 跳过正文交叉引用：标题被引号/书名号括起（如 查阅第三节"管理层讨论与分析"中…）
            if (before.endswith(('《', '<', '>', '（', '(', '“', '”', '"', '‘'))
                    or after[:1] in ('”', '"', '’', ')', '》', '>')):
                continue
            seg = ptxt_clean[idx: idx + 1400]
            for sm in stops:
                j = seg.find(sm, len(h) + 5)
                if j > 0:
                    seg = seg[:j]
                    break
            # 若章节起始接近页尾（正文在下一页），补下一页
            if idx > len(ptxt_clean) - 500 and i + 1 < len(pages):
                seg = seg + '\n' + _clean(pages[i + 1][1])
            body = _clean(seg)
            page_no = pno
            break
        if body:
            break
    out: List[Dict] = []
    if body and len(body) >= 60:
        out.append({
            'beat': '新业务 / 题材',
            'question': '最新半年度经营与新业务进展（累计口径，非全年）',
            'text': _cap(body, 500),
            'citation': {'kind': 'interim_report', 'label': f'{year}半年报·经营讨论',
                         'file': os.path.basename(semi), 'date': f'{year}-06-30' if year else '',
                         'page': page_no, 'source': '巨潮/半年报'},
        })
    return out


def _decision_motive_excerpts(data_dir: str, f: Dict) -> List[Dict]:
    """🔴 决策动因原文：啃《详式权益变动报告书》《重大资产出售/购买预案》等。

    用户教训：写"卖掉了 X"很容易，写"为什么卖"才是文章价值。动因必须取
    公告「交易背景和目的 / 权益变动的目的」章节**原文**，不能凭财务反推。

    扫描全部三档公告（详式权益变动报告书常落在 major/routine，提示性公告
    也可能含"权益变动目的"摘要）。凡能定位到目的章节的，连页码一起抠出。
    """
    ann = f.get('announcements') or {}
    targets = []
    motive_kw = ('权益变动', '重大资产出售', '重大资产购买', '重大资产重组',
                 '资产出售', '资产购买', '要约收购', '协议转让', '表决权委托')
    for k in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        for a in (ann.get(k) or []):
            t = a.get('title') or ''
            if any(w in t for w in motive_kw):
                targets.append(a)

    out = []
    # 章节标识（不同公告措辞不同）
    PURPOSE_MARKERS = [
        '权益变动的目的', '本次权益变动的目的',
        '本次交易的背景和目的', '本次交易的背景', '本次交易的目的',
        '交易背景和目的', '一、交易背景', '二、本次交易的目的',
        '本次协议转让的目的', '控制权变更', '本次收购的目的',
    ]
    STOP_MARKERS = ['第二节', '第三节', '第四节', '第一条', '第二条',
                    '一、', '二、', '三、', '（一）', '（二）', '\n\n']

    for a in targets:
        pdf_path = a.get('pdf_path') or ''
        title = a.get('title') or ''
        date = str(a.get('date') or '')[:10]
        code = a.get('art_code') or ''
        # 优先用 fitz 啃 PDF 全文定位
        text, page = _extract_section_text(pdf_path, PURPOSE_MARKERS, STOP_MARKERS)
        if not text:
            # 退化：看 preview 里有没有
            ec = a.get('extracted_content') or {}
            prev = ec.get('full_text_preview') or ''
            for mk in PURPOSE_MARKERS:
                i = prev.find(mk)
                if i >= 0:
                    text = _clean(prev[i: i + 600])
                    break
        if not text:
            continue
        out.append({
            'beat': '为什么做这个决策',
            'question': '公司自述的决策动因（原文）',
            'text': _cap(text, 600),
            'citation': {
                'kind': 'announcement',
                'label': title[:60],
                'file': f'{code}.PDF' if code else '',
                'date': date,
                'page': page,
                'source': a.get('source') or '巨潮',
                'note': ('fitz 定位' if page else '页码未提取（需 PyMuPDF 或 MCP 全文）'),
            },
        })
    return out


def _capital_op_excerpts(f: Dict) -> List[Dict]:
    """资本运作公告清单（改变公司结构的事），全量摊开，但剔除"伪资本运作"噪音并限幅。

    🔴 限幅与降噪（2026-10-21）：初版把"购买理财/出售闲置资产"等也扫进来，
    单股可产出 80+ 条标题，既淹没真动作又冲爆 LLM 上下文。故：
      - 排除明显非资本结构的标题（闲置/理财/现金管理/募投等）；
      - critical+major 全保留，routine 仅取最近若干，总计 ≤ 18 条。
    """
    ann = f.get('announcements') or {}
    cap_kw = re.compile(r'分拆|分拆上市|借壳|买壳|收购.*控股|要约|再融资|非公开发行|'
                        r'股权激励|控制权|更名|证券简称|境外上市|H ?股|港股|'
                        r'协议转让|股份转让|权益变动|表决权委托|'
                        r'实际控制人变更|控股股东变更|易主|重大资产重组|资产出售|资产购买')
    # 这些标题含"购买/出售/收购"但属日常资金/资产处理，非资本结构动作
    NOISE = re.compile(r'闲置|理财|结构性存款|委托理财|理财产品|现金管理|国债逆回购|'
                       r'募投|募集资金|闲置募集|使用闲置|现金|存款|债券|票据|'
                       r'担保|质押|冻结|减持|增持|回购（|回购股|股权激励限售')
    out = []
    for k in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        tier = 0 if k == 'critical_announcements' else (1 if k == 'major_announcements' else 2)
        for a in (ann.get(k) or []):
            t = a.get('title') or ''
            if '投资者关系' in t:
                continue
            if not cap_kw.search(t):
                continue
            if NOISE.search(t):
                continue
            date = str(a.get('date') or '')[:10]
            code = a.get('art_code') or ''
            out.append({
                'beat': '资本运作主线',
                'question': '改变公司资本结构的动作',
                'text': _cap(t, 200),
                'tier': tier,
                'citation': {
                    'kind': 'announcement',
                    'label': t[:60],
                    'file': f'{code}.PDF' if code else '',
                    'date': date,
                    'page': None,
                    'source': a.get('source') or '巨潮',
                },
            })
    # 去重（同标题）
    seen = set()
    uniq = []
    for x in out:
        key = x['citation']['label']
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)
    # 限幅：critical+major 全保留；routine 仅取最近 10 条；总计 ≤ 18
    crit_major = [x for x in uniq if x['tier'] < 2]
    routine = sorted([x for x in uniq if x['tier'] == 2],
                     key=lambda z: z['citation']['date'] or '', reverse=True)[:10]
    merged = crit_major + routine
    merged = sorted(merged, key=lambda z: z['citation']['date'] or '')[:18]
    for x in merged:
        x.pop('tier', None)
    return merged


def _extract_new_business(data_dir: str, f: Dict) -> Tuple[List[Dict], Dict]:
    """新业务/题材线索（市场真正在买的东西）。

    返回 (excerpts, meta)。扫描投资者关系记录 + 对外投资/年报类公告正文，
    抽点名客户、产品型号、新赛道关键词。每条带 citation（含页码，fitz 定位原文）。
    """
    NEW_KW = ('机器人', '人形', '具身智能', '端侧', '存算一体', 'AI 芯片',
              '3D打印', '3D 打印', '固态电池', '低空', '算力',
              '智算', '数据中心', 'ICT', '卫星', '人工智能', 'AI 应用', '芯片')
    texts: List[Tuple[str, str, str]] = []  # (src_label, text, pdf_path)
    ann = f.get('announcements') or {}

    def _collect(key_filter_re=None):
        for key in ('routine_announcements', 'major_announcements', 'critical_announcements'):
            for a in (ann.get(key) or []):
                t = a.get('title') or ''
                if key_filter_re and not key_filter_re.search(t):
                    continue
                if '投资者关系' in t or '投资者' in t or key_filter_re:
                    c = (a.get('content') if isinstance(a, dict) and a.get('content')
                         else (a.get('extracted_content') or {}).get('full_text_preview') or '')
                    if c:
                        texts.append((f"{t[:34]}({str(a.get('date'))[:10]})",
                                      c, a.get('pdf_path') or ''))

    # ① 投资者关系记录
    _collect(re.compile(r'投资者关系|投资者'))
    # ② 对外投资/设立/增资/定期报告（新业务未必写在 IR 里，实测法狮龙即如此）
    _collect(re.compile(r'对外投资|设立|增资|子公司|投资|年度报告|半年度报告|季度报告'))

    excerpts = []
    entities, models, cautions = set(), set(), []
    seen_frag = set()
    for src, txt, pdf_path in texts:
        if not any(k in txt for k in NEW_KW):
            continue
        clean = _clean(txt)
        for sent in re.split(r'[。；\n]', clean):
            sent = sent.strip()
            if len(sent) < 20 or not any(k in sent for k in NEW_KW):
                continue
            key = sent[:36]
            if key in seen_frag:
                continue
            seen_frag.add(key)
            hot = any(k in sent for k in ('批量出货', '面向', '合资', '定点', '独家', '供货'))
            page = _locate_page(sent[:40], pdf_path) if hot else None
            excerpts.append({
                'beat': '新业务 / 题材',
                'question': '市场真正在买的新故事（点名客户/型号/赛道）',
                'text': _cap(sent, 300),
                'citation': {
                    'kind': 'announcement' if pdf_path else 'ir_record',
                    'label': src,
                    'file': os.path.basename(pdf_path) if pdf_path else '',
                    'date': (src.split('(')[-1].rstrip(')') if '(' in src else ''),
                    'page': page,
                    'source': '巨潮/IR',
                    'note': '点名客户/型号' if hot else '',
                },
            })
            for m in re.finditer(r'面向([\u4e00-\u9fa5A-Za-z]{2,12}(?:科技|智能|技术|股份)?)[、等]?', sent):
                nm = m.group(1).strip()
                if nm and nm not in ('某机器人企业',):
                    entities.add(nm)
            for m in re.finditer(r'(?<![A-Za-z0-9])([A-Z]{1,4}\d{2,4}[A-Z]?\d{0,3})(?![A-Za-z0-9])', sent):
                models.add(m.group(1))
            if ('控股股东' in sent and ('旗下' in sent or '开展' in sent)) or '不在上市公司' in sent:
                cautions.append(sent[:140])

    # 排序：点名客户/型号优先
    excerpts.sort(key=lambda x: 0 if x['citation'].get('note') == '点名客户/型号' else 1)
    # 🔴 限幅（2026-10-21）：初版单股可出 50+ 条新业务句，冲爆上下文。
    #    保留全部"点名客户/型号"（最有价值），其余按序取前若干，总计 ≤ 22。
    hot = [x for x in excerpts if x['citation'].get('note') == '点名客户/型号']
    rest = [x for x in excerpts if x['citation'].get('note') != '点名客户/型号']
    excerpts = (hot + rest)[:22]
    meta = {
        'named_entities': sorted(entities)[:12],
        'product_models': sorted(models)[:12],
        'outside_listco': sorted(cautions)[:5],
        'hit_count': len(excerpts),
    }
    return excerpts, meta


def _risk_excerpts(f: Dict) -> List[Dict]:
    """诉讼/风险信号（悬着的问题），带金额与来源"""
    out = []
    rk = f.get('risk') or {}
    for s in (rk.get('signals') or []):
        lvl = s.get('level')
        if lvl not in ('severe', 'warning'):
            continue
        out.append({
            'beat': '悬着的问题',
            'question': '未决/重大风险信号',
            'text': _cap(f"{s.get('label')}：{s.get('count')} 条（{s.get('detail') or ''}", 240),
            'citation': {'kind': 'risk_signal', 'label': s.get('label') or '',
                         'file': '', 'date': '', 'page': None, 'source': '风险维度'},
        })
    # 年报诉讼详情
    ap = f.get('annual_pdf') or {}
    secs = ap.get('sections') or {}
    lit = secs.get('litigation_detail') or {}
    if isinstance(lit, dict) and lit.get('content'):
        out.append({
            'beat': '悬着的问题',
            'question': '年报披露的重大诉讼/仲裁金额与进展',
            'text': _cap(lit.get('content'), 400),
            'citation': {'kind': 'annual_report', 'label': '年报·诉讼仲裁详情',
                         'file': os.path.basename(ap.get('pdf_path') or ''),
                         'date': f"{ap.get('year','')}-12-31", 'page': None, 'source': '年报'},
        })
    return out


def _ir_excerpts(f: Dict) -> List[Dict]:
    """投资者关系活动（业绩说明会/调研/路演）——资本叙事 + 新业务的另一来源"""
    iq = f.get('investor_qa') or {}
    out = []
    for rec in (iq.get('survey_records') or []) + (iq.get('roadshow_records') or []) + (iq.get('ir_activities') or []):
        if not isinstance(rec, dict):
            continue
        title = rec.get('title') or ''
        date = str(rec.get('date') or '')[:10]
        if not title:
            continue
        out.append({
            'beat': '新业务 / 题材' if any(k in title for k in ('调研', '路演', '说明会')) else '资本运作主线',
            'question': '机构关心 / 公司披露的最新动向',
            'text': _cap(title, 200),
            'citation': {'kind': 'ir_record', 'label': title[:50],
                         'file': f"{rec.get('art_code','')}.PDF" if rec.get('art_code') else '',
                         'date': date, 'page': None, 'source': '巨潮/IR'},
        })
    seen = set()
    uniq = []
    for x in out:
        k = x['citation']['label']
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq[-10:]


# ---------------------------------------------------------------------------
# 数字台账
# ---------------------------------------------------------------------------

def _number_ledger(data_dir: str, f: Dict) -> List[Dict]:
    val = f.get('valuation') or {}
    cur = val.get('current') or {}
    fin = f.get('financial') or {}
    md = f.get('ma_deep') or {}
    gw = md.get('goodwill_analysis') or {}
    st = f.get('structure') or {}
    ap = f.get('annual_pdf') or {}
    secs = ap.get('sections') or {}
    lr = f.get('legal_risk') or {}
    ip = f.get('intellectual_property') or {}
    ef = f.get('earnings_forecast') or {}

    L: List[Dict] = []

    def add(metric, value, caliber, source, page=None, caveat='', group='常规'):
        L.append({'metric': metric, 'value': value, 'caliber': caliber,
                  'source': source, 'page': page, 'caveat': caveat, 'group': group})

    # ===== 最新报告期（累计口径 + 同比 + TTM + 全年预测）=====
    lp = _latest_financial(f)
    if lp:
        src = lp['datatype']
        add('最新报告期', lp['datatype'],
            '数据源中 REPORTDATE 最大的报告期', src, None,
            '🔴 A股中期报告营收/净利为"年初至报告期末累计"，非单季', group='最新报告期')
        add('报告期营收(累计,亿)', lp.get('revenue'), '年初至报告期末累计营业收入', src,
            None, '' if lp.get('is_annual') else '累计口径（非单季）', group='最新报告期')
        add('报告期归母净利(累计,亿)', lp.get('net_profit'),
            '年初至报告期末累计归母净利润', src, None,
            '负值=亏损' if (lp.get('net_profit') or 0) < 0 else '', group='最新报告期')
        if lp.get('rev_yoy_pct') is not None:
            add('报告期营收同比(%)', round(lp['rev_yoy_pct'], 2), '营业收入同比增长', src,
                group='最新报告期')
        if lp.get('np_yoy_pct') is not None:
            add('报告期归母净利同比(%)', round(lp['np_yoy_pct'], 2),
                '归母净利润同比增长（负=亏损扩大）', src, group='最新报告期')
        if lp.get('eps') is not None:
            add('报告期EPS(元)', lp.get('eps'), '基本每股收益', src, group='最新报告期')
        if lp.get('total_assets') is not None:
            add('报告期末总资产(亿)', lp.get('total_assets'), '报告期末总资产', src, group='最新报告期')
        if lp.get('total_parent_equity') is not None:
            add('报告期末归母净资产(亿)', lp.get('total_parent_equity'), '报告期末归母股东权益',
                src, group='最新报告期')
        if lp.get('ttm_revenue') is not None:
            add('TTM营收(亿)', lp.get('ttm_revenue'),
                '滚动12个月营收=上年全年−上年同期累计+本期累计', src, None,
                '非预测', group='最新报告期')
        if lp.get('ttm_net_profit') is not None:
            add('TTM归母净利(亿)', lp.get('ttm_net_profit'), '滚动12个月归母净利润', src, None,
                '非预测；负值=TTM亏损', group='最新报告期')
        if lp.get('fy_revenue_forecast') is not None:
            add('全年营收预测(亿)', lp.get('fy_revenue_forecast'),
                f"季节性外推=本期累计×(上年全年/上年同期累计，系数{lp.get('fy_revenue_factor')})",
                src, None, '🔴 预测·非承诺·仅供预期差参考', group='最新报告期')
        if 'fy_netprofit_forecast' in lp:
            if lp.get('fy_netprofit_forecast') is not None:
                add('全年归母净利预测(亿)', lp.get('fy_netprofit_forecast'), '季节性外推', src, None,
                    '🔴 预测·非承诺·置信度低', group='最新报告期')
            else:
                add('全年归母净利预测', None,
                    lp.get('fy_netprofit_note') or '利润外推置信度低', src, None,
                    '🔴 不给预测数，避免误导', group='最新报告期')

    # 估值（优先行情实时字段；valuation.current 常缺，回退 quote）
    q = f.get('quote') or {}
    mcap = q.get('mcap_yi') or cur.get('market_cap_亿')
    price = q.get('price') or cur.get('price')
    pb = q.get('pb') or cur.get('pb')
    pe_ttm = q.get('pe_ttm') or cur.get('pe_ttm')
    add('总市值(亿)', mcap, '最近交易日总市值', '行情', None, '亏损股 PE 无意义')
    add('股价(元)', price, '最近交易日收盘价', '行情')
    add('PB', round(pb, 2) if isinstance(pb, (int, float)) else pb,
        '市净率（含商誉的资产口径）', '行情')
    ttm_rev = (lp or {}).get('ttm_revenue')
    add('PS(TTM)', round(mcap / ttm_rev, 2) if (mcap and ttm_rev) else None,
        '市销率=总市值/TTM营收', '行情/计算')
    add('PE(TTM)', pe_ttm, '滚动市盈率；负值=亏损', '行情',
        None, '当前 TTM 亏损，不能用 PE 估值')

    # 财务年度序列
    series = _annual_series(f)
    for s in series[-5:]:
        add(f"{s['year']}营收(亿)", s.get('revenue'), '年报营业收入（合并）', '年报·主要会计数据')
        add(f"{s['year']}归母净利(亿)", s.get('net_profit'), '年报归母净利润', '年报·主要会计数据',
            None, '负值=亏损')
        if s.get('roe') is not None:
            add(f"{s['year']}ROE(%)", s.get('roe'), '加权平均净资产收益率', '年报·主要会计数据')

    # 商誉
    if gw.get('total_goodwill') is not None:
        add('商誉期末(亿)', _f(gw.get('total_goodwill')), '合并报表商誉净额（取期末）',
            '年报·商誉', None, '期初≠期末，勿混用')
        add('商誉期初(亿)', _f(gw.get('goodwill_beginning')), '商誉期初数', '年报·商誉')
        add('商誉/净资产(%)', round(gw['goodwill_ratio'], 1) if gw.get('goodwill_ratio') else None,
            '商誉占净资产比例', '年报·商誉', None, f"减值风险判定：{gw.get('impairment_risk')}")
    else:
        add('商誉', None, '年报商誉明细未取到', '—', None, '🔴 数据缺失，禁止下减值结论（勿用总资产比例估算）')

    # 实控人 + 穿透
    ac = st.get('actual_controller') or {}
    pen = st.get('equity_penetration') or []
    eff = None
    ctrl_name = ac.get('name')
    for p in pen:
        if p.get('type') == '最终实际控制人':
            eff = p.get('ratio')
            ctrl_name = p.get('entity')
    add('最终实控人', ctrl_name, '穿透后最终实际控制人', '中证信披/东财F10')
    add('实控人穿透持股(%)', eff, '经股权穿透后的最终控制比例', '股权穿透',
        None, '含一致行动与间接持股')

    # 客户/供应商集中度
    for skey, nm in (('top5_customers', '前五大客户集中度'), ('top5_suppliers', '前五大供应商集中度')):
        sec = secs.get(skey) or {}
        if isinstance(sec, dict) and sec.get('content'):
            add(nm, None, '集中度/关联销售（详见原文）', f'年报·{sec.get("name")}',
                None, _cap(sec.get('content'), 120))

    # 研发投入
    rd = secs.get('rd_spending') or {}
    if isinstance(rd, dict) and rd.get('content'):
        add('研发投入', None, '研发金额/占比（详见原文）', '年报·研发投入',
            None, _cap(rd.get('content'), 120))

    # 法律/IP（若已取到）
    dishonest = (lr.get('dishonest') or {}).get('total')
    if dishonest is not None:
        add('失信记录(条)', dishonest, '失信被执行人记录数', '企查查/法律维度')
    pat = (ip.get('patent') or {}).get('in_force_count')
    if pat is not None:
        add('有效专利(件)', pat, '有效专利数量', '知识产权维度')

    # 目标价
    tp = (ef.get('target_price') or {})
    if not tp.get('average'):
        add('目标价', None, '预测数据不足，未能生成', '盈利预测维度',
            None, '🔴 不可编造估值区间')

    return L


# ---------------------------------------------------------------------------
# 实体索引 + 穿透
# ---------------------------------------------------------------------------

def _looks_like_name(s: str) -> bool:
    """粗判是否为"公司/机构名"，过滤掉句子片段与关系短语"""
    if not s or len(s) < 2:
        return False
    # 句子片段特征
    if any(ch in s for ch in ('\n', '\r', '√', '□', '。', '，', '；', '①', '②')):
        return False
    if re.search(r'^\s*\d', s) or re.search(r'\d\s*位', s):
        return False
    # 强公司后缀（含这些的通常是真名，但关系短语里也夹带，需二次排雷）
    strong = re.search(r'(有限公司|股份有限公司|合伙企业\(有限合伙\)|有限合伙|集团|控股|基金|银行|证券|科技)$', s)
    if strong:
        if any(w in s for w in ('为子公司', '对子公司', '向子公司', '增资', '担保', '份额调整',
                                '设立控股', '出资设立', '控股子公司提供', '关联交易', '提供借款')):
            return False
        return True
    # 弱匹配：短串。关系短语（"为子公司""向控股子公司""协议转让部分公司"）一律排除
    if len(s) > 16:
        return False
    if any(w in s for w in ('为子', '对子', '向控', '子公司', '增资', '担保', '份额', '设立',
                            '出资', '关联', '协议转让', '实际控制', '调整', '部分公司')):
        return False
    if 2 <= len(s) <= 5 and re.fullmatch(r'[\u4e00-\u9fa5]{2,5}', s):
        return True
    return False


def _entity_index(data_dir: str, f: Dict, nb_meta: Dict) -> Dict:
    st = f.get('structure') or {}
    md = f.get('ma_deep') or {}
    rel = f.get('related') or {}
    companies = set()
    for sh in (st.get('top_shareholders') or []):
        if isinstance(sh, dict) and _looks_like_name(sh.get('name') or ''):
            companies.add(sh['name'])
    for rp in (st.get('related_parties') or []):
        if isinstance(rp, dict) and _looks_like_name(rp.get('name') or ''):
            companies.add(rp['name'])
    for sub in (st.get('subsidiaries') or []):
        if isinstance(sub, dict) and _looks_like_name(sub.get('name') or ''):
            companies.add(sub['name'])
    # 交易对手（MA）：只收看起来像机构名的
    counterparties = set()
    for d in (md.get('deals') or []):
        if isinstance(d, dict):
            for k in ('counterparty', 'target', 'buyer', 'seller', 'party'):
                v = d.get(k)
                if isinstance(v, str) and _looks_like_name(v):
                    counterparties.add(v)
    pen = st.get('equity_penetration') or []
    controller = None
    effective = None
    chain = []
    for p in pen:
        if not isinstance(p, dict):
            continue
        if p.get('type') == '最终实际控制人':
            controller = p.get('entity')
            effective = p.get('ratio')
        chain.append({'level': p.get('level'), 'entity': p.get('entity'),
                      'type': p.get('type'), 'ratio': p.get('ratio'),
                      'source': p.get('source')})

    return {
        'companies': sorted(companies)[:20],
        'customers_named': nb_meta.get('named_entities') or [],
        'products_models': nb_meta.get('product_models') or [],
        'counterparties': sorted(counterparties)[:15],
        'outside_listco_caution': nb_meta.get('outside_listco') or [],
        'penetration': {
            'controller': controller,
            'effective_ratio_pct': effective,
            'chain': chain,
        },
    }


# ---------------------------------------------------------------------------
# 已知缺口（反向护栏：把"没取到"说出来，锁死 LLM 编造）
# ---------------------------------------------------------------------------

def _known_gaps(r: Dict, f: Dict) -> List[Dict]:
    gaps = []

    def add(dim, status, note, forbidden=''):
        gaps.append({'dimension': dim, 'status': status, 'note': note, 'forbidden': forbidden})

    # 逐维度扫 data_quality / insufficient / error / missing_tools / gaps
    # 🔴 注意：只收"真缺口"，不收 info 类 warnings（如"ROE为负""连续亏损"是信号，
    #    不是缺口，收进来会污染护栏、误伤正常写作）。
    for dim, v in f.items():
        if not isinstance(v, dict):
            continue
        dq = v.get('data_quality')
        if dq == 'data_missing':
            add(dim, '数据缺失', f"维度 {dim} 数据未取到", '禁止编造该维度任何数字')
        if v.get('insufficient'):
            add(dim, '数据不足', f"维度 {dim} 数据不足以支撑结论", '禁止编造结论/区间')
        if v.get('error'):
            _msg = str(v.get('error'))[:80]
            _mk = str((r or {}).get('market') or 'a').lower()
            if dim == 'quote' and _mk in ('hk', 'us', 'bse'):
                # A 股代码格式报错对港美股是"源不适用"，不是"采集失败"
                add(dim, '脚本源不适用',
                    f"行情脚本源不支持该市场（{_mk.upper()}）；"
                    f"须按 mcp_plan.json 用 Wind get_stock_price_indicators 回填"
                    f"（原始报错：{_msg}）",
                    '未回填前禁止写行情/估值数字')
            else:
                add(dim, '采集错误', f"{dim}: {_msg}", '禁止沿用错误结果')
        mt = v.get('missing_tools') or v.get('gaps')
        if mt:
            add(dim, '工具不可用/有缺口', f"{dim}: {str(mt)[:120]}", '禁止编造该维度')

    # 顶层信号
    sil = r.get('_silenced_errors') or []
    if sil:
        add('采集层', '静默异常', f"有 {len(sil)} 条采集异常被静默，需复核", '禁止假定这些维度已正确')
    red = r.get('redline') or {}
    if isinstance(red, dict) and red.get('blocked'):
        add('红线门禁', '被拦截', f"门禁拦截：{str(red.get('blocked'))[:120]}", '被拦截内容不得出现')
    mcp = r.get('mcp_coverage') or {}
    if isinstance(mcp, dict) and mcp.get('gaps'):
        add('MCP覆盖', '覆盖缺口', f"MCP 未覆盖：{str(mcp.get('gaps'))[:120]}", '缺数据处不得编造')

    # 特定已知缺口（与记忆中的铁律对齐）
    md = f.get('ma_deep') or {}
    gw = md.get('goodwill_analysis') or {}
    if gw.get('data_quality') == 'data_missing':
        add('商誉', '数据缺失', '年报商誉明细未取到，减值风险不可下结论', '禁止用总资产比例估算商誉/减值')
    ef = f.get('earnings_forecast') or {}
    # 目标价有两个来源：financial_projection.valuation.target_price（现行）
    # 与 earnings_forecast.target_price.average（旧）。2026-10-21 修：旧实现只看后者，
    # 推算出了目标价也报"数据不足"，属误报缺口（会误导作者放弃已算出的结论）。
    _fp_v = (f.get('financial_projection') or {}).get('valuation') or {}
    _tp = _fp_v.get('target_price')
    if _tp is None:
        _tp = (ef.get('target_price') or {}).get('average')
    if _tp is None:
        add('目标价', '数据不足', '预测数据不足，未能生成目标价', '禁止编造估值区间/目标价')
    elif _fp_v.get('target_price_note'):
        add('目标价', '口径不适用', str(_fp_v.get('target_price_note'))[:160],
            '可按原文引用该目标价，但必须同时披露"估值锚不适用"')
    lr = f.get('legal_risk') or {}
    if lr.get('missing_tools') or lr.get('status') == 'unavailable':
        add('法律/IP风险', '工具不可用', '企查查法律/IP 维度未取到', '禁止编造法律诉讼/专利数字')

    # 港美股监管：窗口内未命中 ≠ 无违规（2026-10-21）
    rg = f.get('regulatory') or {}
    if rg.get('market') in ('hk', 'us') and not rg.get('count'):
        add('监管', '窗口内未命中',
            f"{rg.get('window') or '专用源'}：未检索到监管相关记录。"
            f"{rg.get('_note') or '未命中不等于无违规'}",
            '禁止写“无监管处罚/无违规”，只能写“本次窗口内未命中”')

    # 🔴 回填门禁（2026-10-22）：港美股/北交所脚本源覆盖不全，未回填的空是"缺"不是"无"
    bf = f.get('_mcp_backfill') or {}
    if bf.get('required'):
        add('数据完整性', '回填缺口',
            f"{str(bf.get('market') or '').upper()} 未回填维度："
            f"{', '.join(bf.get('missing') or bf.get('affected') or [])}。{bf.get('note') or ''}",
            '上述维度禁止写“无/未发生/不适用”，只能写“本次未取到（需回填）”')
    return gaps


# ---------------------------------------------------------------------------
# 赛道曝光信号层（2026-10-21 新增）
# ---------------------------------------------------------------------------

def _sector_exposure(data_dir: str, r: Dict, f: Dict) -> List[Dict]:
    """赛道曝光信号层。

    🔴 原则：**只聚合"原文提到的领域名词"，不做"新质生产力"之类的价值判断**。
    解决用户痛点：若原文只笼统说"布局机器人领域"而不点名具体客户，证据包只呈现
    笼统线索、点名信息会丢。此层把年报/IR 里出现的新兴赛道名词摊开成"曝光表"，
    并附代表原文句+出处，让第三层（LLM/人）一眼看到"这家在讲哪些赛道"。

    领域词典按常见新质生产力赛道分组，但每个词命中只计数+摘录，**绝不归类定性**。
    """
    THEMES = [
        ('人形机器人 / 具身智能', ['人形机器人', '具身智能', '机器人']),
        ('AI / 大模型 / 算力', ['人工智能', '大模型', '算力', '智算', '深度学习', '神经网络']),
        ('半导体 / 芯片', ['半导体', '芯片', '集成电路', 'MCU', 'SoC', '碳化硅', 'IGBT', '晶圆']),
        ('新能源 / 储能 / 固态电池', ['新能源', '储能', '固态电池', '锂电池', '光伏', '氢能']),
        ('低空经济 / eVTOL', ['低空经济', 'eVTOL', '无人机', '飞行汽车']),
        ('3D 打印 / 增材制造', ['3D打印', '3D 打印', '增材制造', '三维打印']),
        ('商业航天 / 卫星', ['商业航天', '卫星', '火箭', '北斗']),
        ('创新药 / 生物医药', ['创新药', '生物医药', '基因', '疫苗']),
        ('自动驾驶 / 智能驾驶', ['自动驾驶', '智能驾驶', 'L3', 'L4']),
        ('量子 / 前沿材料', ['量子', '石墨烯', '超导']),
    ]
    # 统一语料池：年报全文+章节 / 半年报 / 季报 / 公告 / IR / 权益变动报告书
    blocks = _build_corpus(data_dir, r, f)

    results = []
    for theme, kws in THEMES:
        total = 0
        hits: List[Dict] = []
        seen_sent = set()
        for text, label, stype, page, date, counting in blocks:
            if not text:
                continue
            for kw in kws:
                n = text.count(kw)
                if n == 0:
                    continue
                if counting:
                    total += n
                for sent in re.split(r'[。！？\n;；]', text):
                    sent = sent.strip()
                    # 跳过公司名录行（多个"有限公司"罗列，非赛道叙述）
                    if sent.count('有限公司') >= 2:
                        continue
                    if kw in sent and 6 <= len(sent) <= 140 and sent not in seen_sent:
                        seen_sent.add(sent)
                        if stype == '年报':
                            kind = 'annual_report'
                        elif stype in ('半年报', '季报'):
                            kind = 'interim_report'
                        elif 'IR' in stype or '投资者' in stype:
                            kind = 'ir_record'
                        else:
                            kind = 'announcement'
                        hits.append({
                            'text': _cap(sent, 200),
                            'citation': {
                                'kind': kind,
                                'label': label[:50], 'file': '', 'date': date, 'page': page,
                                'source': stype,
                            },
                        })
                if len(hits) >= 24:
                    break
        if total:
            # 🔴 样本优先级：带页码(年报章节) > 来源序(年报>半年报>IR>公告) > 业务叙述信号
            hits.sort(key=lambda h: (0 if h['citation'].get('page') else 1,
                                    _src_rank(h['citation']['source']),
                                    -_biz_score(h['text'])))
            results.append({
                'theme': theme, 'keywords': kws, 'mentions': total,
                'samples': hits[:2],
            })
    results.sort(key=lambda x: -x['mentions'])
    return results


def _biz_score(sent: str) -> int:
    """业务叙述句信号：命中越多越像"在讲业务方向"而非名录/定义"""
    biz = ('推出', '布局', '应用', '产品', '行业', '业务', '融合', '研发', '量产',
           '供货', '客户', '领域', '进入', '转型', '战略', '深度', '一体机',
           '定点', '合资', '作为', '方向', '拓展', '孵化')
    return sum(1 for w in biz if w in sent)


# ---------------------------------------------------------------------------
# 叙事骨架（保留 7 节拍，作为 story spine）
# ---------------------------------------------------------------------------

def _annual_series(f: Dict) -> List[Dict]:
    out, seen = [], set()
    for rcd in (f.get('financial', {}).get('records') or []):
        d = str(rcd.get('REPORTDATE') or '')[:10]
        if not d.endswith('12-31'):
            continue
        y = d[:4]
        if y in seen:
            continue
        seen.add(y)
        rev, npf = _f(rcd.get('TOTAL_OPERATE_INCOME')), _f(rcd.get('PARENT_NETPROFIT'))
        if rev is None:
            continue
        out.append({'year': int(y), 'revenue': rev, 'net_profit': npf,
                    'roe': rcd.get('WEIGHTAVG_ROE')})
    return sorted(out, key=lambda x: x['year'])


def _one_liner(series, gw, cur, sig) -> str:
    parts = []
    if len(series) >= 2:
        last, prev = series[-1], series[-2]
        if last.get('net_profit') is not None and (last['net_profit'] or 0) < 0:
            parts.append(f"{last['year']} 年亏损 {abs(last['net_profit'])} 亿")
        if prev.get('revenue') and last.get('revenue'):
            yoy = (last['revenue'] / prev['revenue'] - 1) * 100
            if abs(yoy) > 15:
                parts.append(f"营收同比 {yoy:+.1f}%")
    if gw.get('goodwill_ratio') and gw['goodwill_ratio'] > 30:
        parts.append(f"商誉占净资产 {gw['goodwill_ratio']:.0f}%")
    if sig and (cur.get('market_cap_亿') or 0) > 0:
        parts.append(f"{len(sig)} 项重大法律风险待解")
    return '；'.join(parts) if parts else '（需结合数据补充核心矛盾）'


def _narrative_skeleton(f: Dict, nb_meta: Dict, cap_count: int, motive_count: int) -> List[Dict]:
    """7 节拍叙事骨架：只给'要回答什么'与'去哪取'，不替 LLM 写正文"""
    ind = f.get('industry') or {}
    gw = (f.get('ma_deep') or {}).get('goodwill_analysis') or {}
    cur = (f.get('valuation') or {}).get('current') or {}
    sig = [s for s in ((f.get('risk') or {}).get('signals') or []) if s.get('level') == 'severe']
    md = f.get('ma_deep') or {}

    beats = []
    beats.append({
        'beat': '这门生意是什么',
        'thesis_hint': '用大白话翻译业务，说清真正赚钱的那块',
        'must_answer': ['各业务块收入/利润贡献', '客户与供应链集中度'],
        'source_spine': ['年报·主营业务/产销量/前五大客户供应商'],
    })
    beats.append({
        'beat': '钱是怎么赚的、怎么亏的',
        'thesis_hint': '找转折年份并解释原因；亏损区分经营性 vs 一次性',
        'must_answer': ['近三年营收/净利曲线', '转折原因'],
        'source_spine': ['年报·主要会计数据/资产负债表'],
    })
    beats.append({
        'beat': '为什么做这个决策',
        'thesis_hint': '🔴 取公告"交易背景和目的/权益变动的目的"原文，翻译为大白话；'
                       '区分战略主动 vs 被逼无奈',
        'must_answer': ['决策动因（原文）', '标的财务佐证', '各方出资比例'],
        'source_spine': ['《详式权益变动报告书》/《重大资产出售预案》对应章节']
        + (['（已抠出 %d 处动因原文）' % motive_count] if motive_count else ['（⚠️ 动因原文未取到，需补采）']),
    })
    if nb_meta.get('hit_count'):
        beats.append({
            'beat': '新业务 / 题材（市场真正在买的东西）',
            'thesis_hint': '点名客户/产品型号/技术对标是硬证据；必须给财务落点',
            'must_answer': ['点名客户与型号', '收入是否单列', '在上市公司体内还是控股股东体内'],
            'source_spine': ['投资者关系记录', '对外投资/年报类公告']
            + (['已抽 %d 条线索' % nb_meta['hit_count']] if nb_meta.get('hit_count') else []),
        })
    if cap_count:
        beats.append({
            'beat': '资本运作主线（改变公司结构的事）',
            'thesis_hint': '分拆/易主/再融资改变的是估值方法，不止利润；算清持股链条',
            'must_answer': ['控制权是否变更、穿透后比例', '买控股≠完成注入', '两个资本平台如何估值'],
            'source_spine': ['权益变动/协议转让/分拆上市类公告（已列 %d 条）' % cap_count],
        })
    if gw.get('total_goodwill'):
        beats.append({
            'beat': '资产负债表的重量',
            'thesis_hint': '商誉是"过去多付的钱"，讲清何时变亏损；期初→期末变化本身即故事',
            'must_answer': ['商誉规模与占比', '减值/处置轨迹'],
            'source_spine': ['年报·商誉'],
        })
    if sig:
        beats.append({
            'beat': '悬着的问题',
            'thesis_hint': '金额换算成"占市值多少"；区分原告/被告',
            'must_answer': ['未决风险金额及占市值比', '原告/被告性质'],
            'source_spine': ['风险维度信号', '年报·诉讼仲裁'],
        })
    beats.append({
        'beat': '怎么估值',
        'thesis_hint': '亏损时 PE 无意义，必须说明并给替代口径；给区间和前提',
        'must_answer': ['适用估值法', '区间与前提'],
        'source_spine': ['估值维度', '（目标价缺失时禁用单点/编造区间）'],
    })
    return beats


# ---------------------------------------------------------------------------
# 主构建
# ---------------------------------------------------------------------------

def build_evidence_pack(data_dir: str) -> Dict[str, Any]:
    r = _load(data_dir)
    f = r.get('findings') or {}

    series = _annual_series(f)
    latest = series[-1] if series else {}
    prev = series[-2] if len(series) >= 2 else {}
    gw = (f.get('ma_deep') or {}).get('goodwill_analysis') or {}
    cur = (f.get('valuation') or {}).get('current') or {}
    sig = [s for s in ((f.get('risk') or {}).get('signals') or []) if s.get('level') == 'severe']

    # 全量素材
    ex_annual = _excerpts_annual(data_dir, f)
    # 港美股：没有 A 股 23 章节结构，按关键词直接啃年报 PDF（2026-10-21 新增）
    if not ex_annual:
        ex_annual = _excerpts_annual_by_keywords(data_dir, f)
    # 美股：10-K 是 HTML 不是 PDF → 单独解析（仍是 0 条才尝试）
    if not ex_annual:
        ex_annual = _excerpts_us_10k(data_dir, f)
    ex_periodic = _excerpts_periodic(data_dir, f)
    ex_motive = _decision_motive_excerpts(data_dir, f)
    ex_cap = _capital_op_excerpts(f)
    ex_nb, nb_meta = _extract_new_business(data_dir, f)
    ex_risk = _risk_excerpts(f)
    ex_ir = _ir_excerpts(f)

    excerpts = ex_annual + ex_periodic + ex_motive + ex_cap + ex_nb + ex_risk + ex_ir
    # 去重（同 text 同 beat）
    _seen = set()
    _dedup = []
    for x in excerpts:
        k = (x['beat'], x['text'][:60])
        if k in _seen:
            continue
        _seen.add(k)
        _dedup.append(x)

    number_ledger = _number_ledger(data_dir, f)
    entity_index = _entity_index(data_dir, f, nb_meta)
    known_gaps = _known_gaps(r, f)
    sector = _sector_exposure(data_dir, r, f)
    skeleton = _narrative_skeleton(f, nb_meta, len(ex_cap), len(ex_motive))

    # 🔴 决策动因原文缺失 → 显式缺口（反向护栏：别让 LLM 凭财务反推"为什么卖"）
    if not ex_motive:
        known_gaps.append({
            'dimension': '决策动因原文', 'status': '数据缺失',
            'note': '未取到《详式权益变动报告书》/《重大资产出售预案》等含"权益变动的目的/'
                    '交易背景和目的"章节的公告原文（常为提示性公告，无 PDF 全文）',
            'forbidden': '禁止凭财务数据反推/编造交易动因；只能写"已公告的控制权变更事实"',
        })

    # 🔴 营收剧变归因（托底）：|同比|≥25% 时搜集"为什么变"的证据；找不到→显式缺口
    lp = _latest_financial(f)
    rev_attr = _revenue_change_attribution(f, data_dir, lp)
    if rev_attr and rev_attr.get('triggered') and not rev_attr.get('found'):
        known_gaps.append({
            'dimension': '营收剧变归因', 'status': '归因未明',
            'note': f"最新报告期营收同比 {rev_attr['yoy_pct']:+.1f}%（{rev_attr['direction']}），"
                    f"但公告/MD&A 未找到明确归因",
            'forbidden': '禁止凭常识臆测营收下滑/增长原因（如"行业下行""并表变化"），'
                         '只能写同比事实并标注归因待核实',
        })

    # 维度覆盖盘点
    dims_present = [k for k, v in f.items() if isinstance(v, dict) and v]
    dims_missing = [g['dimension'] for g in known_gaps if g['status'] in ('数据缺失', '工具不可用', '数据不足')]

    pack = {
        'meta': {
            'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stock': r.get('stock'),
            'company_name': r.get('company_name_resolved') or '',
            'source': os.path.join(data_dir, 'results.json'),
            'dims_present_count': len(dims_present),
            'excerpt_count': len(_dedup),
            'number_ledger_count': len(number_ledger),
            'known_gap_count': len(known_gaps),
            'sector_count': len(sector),
            'revenue_attribution_triggered': bool(rev_attr and rev_attr.get('triggered')),
            'fitz_available': _HAS_FITZ,
        },
        'one_liner': _one_liner(series, gw, cur, sig),
        'narrative_skeleton': skeleton,
        'evidence': {
            'excerpts': _dedup,
            'number_ledger': number_ledger,
            'entity_index': entity_index,
            'known_gaps': known_gaps,
            'sector_exposure': sector,
            'revenue_attribution': rev_attr,
        },
    }
    return pack


def build_brief_legacy(data_dir: str) -> Dict[str, Any]:
    """兼容旧骨架：保留 7 节拍 + 数字台账 + 风险 + 禁止项（下游若仍需）"""
    r = _load(data_dir)
    f = r.get('findings') or {}
    val = f.get('valuation') or {}
    cur = val.get('current') or {}
    gw = (f.get('ma_deep') or {}).get('goodwill_analysis') or {}
    series = _annual_series(f)
    latest = series[-1] if series else {}
    prev = series[-2] if len(series) >= 2 else {}
    sig = [s for s in ((f.get('risk') or {}).get('signals') or []) if s.get('level') == 'severe']
    ef = f.get('earnings_forecast') or {}

    numbers = {
        'market_cap_亿': cur.get('market_cap_亿'),
        'price': cur.get('price'),
        'pe_ttm': cur.get('pe_ttm'),
        'pb': round(cur['pb'], 2) if isinstance(cur.get('pb'), (int, float)) else cur.get('pb'),
        'ps_ttm': cur.get('ps') or cur.get('ps_ttm'),
        'latest_revenue_亿': latest.get('revenue'),
        'latest_net_profit_亿': latest.get('net_profit'),
        'goodwill_ending_亿': _f(gw.get('total_goodwill')),
        'goodwill_beginning_亿': _f(gw.get('goodwill_beginning')),
        'goodwill_to_equity_pct': round(gw['goodwill_ratio'], 2) if gw.get('goodwill_ratio') else None,
        'actual_controller': (f.get('structure') or {}).get('actual_controller'),
        'patent_in_force': (f.get('intellectual_property') or {}).get('patent'),
        'dishonest': (f.get('legal_risk') or {}).get('dishonest'),
        '_series': series,
    }
    traps = []
    if gw.get('impairment_risk') in ('高', '中'):
        traps.append(f"商誉减值风险（{gw.get('impairment_risk')}）")
    for s in sig:
        traps.append(f"{s.get('label')}：{s.get('count')} 条（须换算为占市值比例）")
    if (cur.get('pe_ttm') or 0) < 0:
        traps.append('当前 TTM 亏损，PE 为负 → 不能用 PE 估值')
    if not (ef.get('target_price') or {}).get('average'):
        traps.append('目标价未能生成（数据不足），不可编造估值区间')

    beats = []
    beats.append({'beat': '这门生意是什么',
                  'facts': [(f.get('industry') or {}).get('main_business') or ''][:1],
                  'angles': ['用大白话翻译业务']})
    if series:
        arcs = ' → '.join(f"{s['year']}年 营收{s['revenue']}亿/净利{s['net_profit']}亿" for s in series[-5:])
        beats.append({'beat': '钱是怎么赚的、怎么亏的', 'facts': [arcs],
                      'angles': ['找转折年份并解释原因']})
    beats.append({'beat': '为什么做这个决策',
                  'facts': ['须从《重大资产出售/购买预案》「本次交易的背景和目的」取原文'],
                  'angles': ['必查交易背景和目的章节']})
    beats.append({'beat': '资本运作主线', 'facts': [f"已列 {len(_capital_op_excerpts(f))} 条资本运作公告"],
                  'angles': ['分拆/易主/再融资改变估值方法']})
    beats.append({'beat': '怎么估值',
                  'facts': [f"市值 {cur.get('market_cap_亿')}亿 / PB {numbers['pb']} / "
                            f"PS {cur.get('ps') or cur.get('ps_ttm')} / PE {cur.get('pe_ttm')}"],
                  'angles': ['亏损时 PE 无意义']})

    return {
        'stock': r.get('stock'),
        'company_name': r.get('company_name_resolved') or '',
        'one_liner': _one_liner(series, gw, cur, sig),
        'beats': beats,
        'numbers': numbers,
        'traps': traps,
        'forbidden': [
            '公告逐条列举 / 事件时间线流水账',
            '「本报告覆盖 X 个维度 / Y 条公告」的自证式表述',
            '未经核实的数字（凡数值必须能追到年报/公告原文）',
        ],
    }


# ---------------------------------------------------------------------------
# Markdown 渲染（人工复核用）
# ---------------------------------------------------------------------------

def _render_md(pack: Dict) -> str:
    m = pack['meta']
    L = []
    L.append(f"# 评论文章证据包 · {m.get('company_name') or m.get('stock')}（{m.get('stock')}）")
    L.append('')
    L.append(f"> 生成时间：{m['generated_at']} ｜ 摘录 {m['excerpt_count']} 条 ｜ "
             f"数字台账 {m['number_ledger_count']} 项 ｜ 已知缺口 {m['known_gap_count']} 项 ｜ "
             f"fitz页码：{'可用' if m['fitz_available'] else '不可用'}")
    L.append('')
    L.append(f"**一句话核心矛盾**：{pack['one_liner']}")
    L.append('')
    L.append('## 一、叙事骨架（story spine，7 节拍）')
    L.append('')
    for i, b in enumerate(pack['narrative_skeleton'], 1):
        L.append(f"**{i}. {b['beat']}**")
        L.append(f"  - 论点提示：{b['thesis_hint']}")
        L.append(f"  - 必须回答：{'；'.join(b['must_answer'])}")
        L.append(f"  - 取材线索：{'；'.join(b['source_spine'])}")
        L.append('')
    L.append('## 二、原文摘录（带引用，全量开放）')
    L.append('')
    by_beat: Dict[str, List[Dict]] = {}
    for x in pack['evidence']['excerpts']:
        by_beat.setdefault(x['beat'], []).append(x)
    for beat, xs in by_beat.items():
        L.append(f"### ▍{beat}")
        for x in xs:
            c = x['citation']
            page = c.get('page')
            page_s = f" p{page}" if page else ' p?'
            L.append(f"- 「{x['text']}」")
            L.append(f"  > 出处：{c.get('label')} ｜ {c.get('date')}{page_s} ｜ "
                     f"文件 {c.get('file') or '—'} ｜ {c.get('source')}"
                     + (f" ｜ {c['note']}" if c.get('note') else ''))
        L.append('')
    L.append('## 三、数字台账（每个数字带口径+来源）')
    L.append('')
    # 分组渲染：最新报告期置顶（含 累计实际 + 同比 + TTM + 全年预测）
    _groups: Dict[str, List[Dict]] = {}
    _order: List[str] = []
    for n in pack['evidence']['number_ledger']:
        g = n.get('group') or '常规'
        if g not in _groups:
            _groups[g] = []
            _order.append(g)
        _groups[g].append(n)
    if '最新报告期' in _groups:
        _order = ['最新报告期'] + [g for g in _order if g != '最新报告期']
    for g in _order:
        if g != '常规':
            L.append(f'**▍{g}**')
            L.append('')
        L.append('| 指标 | 数值 | 口径 | 来源 | 页码 | 注意 |')
        L.append('|---|---|---|---|---|---|')
        for n in _groups[g]:
            v = '' if n['value'] is None else n['value']
            L.append(f"| {n['metric']} | {v} | {n['caliber']} | {n['source']} | "
                     f"{n.get('page') or '—'} | {n.get('caveat') or ''} |")
        L.append('')
    # 营收剧变归因（托底）
    ra = pack['evidence'].get('revenue_attribution')
    if ra and ra.get('triggered'):
        L.append(f"**▍营收剧变归因**（营收同比 {ra['yoy_pct']:+.1f}%，阈值±25%）")
        L.append('')
        if ra.get('found'):
            L.append('> 候选归因证据（文章引用须回查原文，区分"合并范围一次性变动" vs "内生经营持续变动"）：')
            for c in ra['candidates']:
                d = f" ｜ {c['date']}" if c.get('date') else ''
                L.append(f"- **[{c['kind']}]** {c['label']}{d}")
                L.append(f"  > {c['evidence']}")
        else:
            L.append(f"> 🔴 {ra['note']}")
        L.append('')
    L.append('## 四、实体索引')
    L.append('')
    ei = pack['evidence']['entity_index']
    L.append(f"- **公司/股东/子公司**：{', '.join(ei['companies']) or '—'}")
    L.append(f"- **点名客户**：{', '.join(ei['customers_named']) or '—'}")
    L.append(f"- **产品型号**：{', '.join(ei['products_models']) or '—'}")
    L.append(f"- **交易对手**：{', '.join(ei['counterparties']) or '—'}")
    if ei.get('outside_listco_caution'):
        L.append(f"- **控股股东体内提示**：{'；'.join(ei['outside_listco_caution'])}")
    pen = ei.get('penetration') or {}
    if pen.get('controller'):
        L.append(f"- **穿透持股**：最终实控人 {pen['controller']}，穿透后持股 "
                 f"{pen.get('effective_ratio_pct')}%。链条：")
        for c in pen.get('chain', [])[:8]:
            L.append(f"    - L{c.get('level')} {c.get('entity')}（{c.get('type')}）"
                     f" 持股 {c.get('ratio')}% ｜ 来源 {c.get('source')}")
    L.append('')
    L.append('## 五、已知缺口（🔴 禁止编造清单）')
    L.append('')
    if not pack['evidence']['known_gaps']:
        L.append('- 无显著缺口。')
    for g in pack['evidence']['known_gaps']:
        L.append(f"- **[{g['status']}] {g['dimension']}**：{g['note']}"
                 + (f" → {g['forbidden']}" if g.get('forbidden') else ''))
    L.append('')
    L.append('## 六、赛道曝光（新兴领域信号 · 仅聚合不判断）')
    L.append('')
    L.append('> 🔴 本表只统计"原文提到的领域名词"出现次数与代表句，**不做"新质生产力"等'
             '价值判断**。若某赛道出现，说明公司在年报/IR 里主动提及；是否真在布局、'
             '占比多少，由第三层（LLM/人）结合财务落点判断。')
    L.append('')
    secs = pack['evidence']['sector_exposure']
    if not secs:
        L.append('- 年报/IR 未检出新兴赛道关键词。')
    for s in secs:
        L.append(f"### ▍{s['theme']}（曝光 {s['mentions']} 次）")
        L.append(f"- 关键词：{', '.join(s['keywords'])}")
        for sm in s['samples']:
            c = sm['citation']
            page = c.get('page')
            page_s = f" p{page}" if page else ' p?'
            L.append(f"- 「{sm['text']}」")
            L.append(f"  > 出处：{c.get('label')} ｜ {c.get('date')}{page_s} ｜ {c.get('source')}")
        L.append('')
    L.append('---')
    L.append('*本证据包由 article_brief.py 生成，是「基座 → LLM 生成层」的桥梁。'
             '凡数值须回查引用；缺口清单内维度禁止编造。*')
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='评论文章证据包生成器')
    ap.add_argument('data_dir', help='含 results.json 的数据目录')
    ap.add_argument('--out-dir', default=None, help='输出目录（默认 data_dir）')
    ap.add_argument('--no-md', action='store_true', help='不生成 markdown')
    a = ap.parse_args()

    data_dir = a.data_dir
    out_dir = a.out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)

    pack = build_evidence_pack(data_dir)
    jpath = os.path.join(out_dir, 'evidence_pack.json')
    with open(jpath, 'w', encoding='utf-8') as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=2)

    # 兼容旧骨架
    legacy = build_brief_legacy(data_dir)
    lpath = os.path.join(out_dir, 'article_brief.json')
    with open(lpath, 'w', encoding='utf-8') as fh:
        json.dump(legacy, fh, ensure_ascii=False, indent=2)

    print(f'证据包 → {jpath}')
    print(f'兼容简报 → {lpath}')
    if not a.no_md:
        mpath = os.path.join(out_dir, 'evidence_pack.md')
        with open(mpath, 'w', encoding='utf-8') as fh:
            fh.write(_render_md(pack))
        print(f'可读版 → {mpath}')

    m = pack['meta']
    print(f"\n【一句话】{pack['one_liner']}")
    print(f"【摘录 {m['excerpt_count']} 条｜数字台账 {m['number_ledger_count']} 项｜"
          f"缺口 {m['known_gap_count']} 项｜fitz：{'可用' if m['fitz_available'] else '不可用'}】")
    print('\n【已知缺口（禁止编造）】')
    for g in pack['evidence']['known_gaps'][:8]:
        print(f"  🔴 [{g['status']}] {g['dimension']}: {g['note']}")


if __name__ == '__main__':
    main()
