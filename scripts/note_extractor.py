# -*- coding: utf-8 -*-
"""
note_extractor.py - 年报附注关键段落抽取（2026-10-22 新增）
==========================================================

解决什么：
    A 股靠东财 F10 直接给"关联交易/对外担保/诉讼/商誉"结构化字段；港美股没有 F10，
    这些信息只存在于年报附注文字里 → 一直是空。本模块从**已下载的年报原文**
    （A股/港股 PDF、美股 10-K HTML）按关键词定位段落并摘录，填进对应维度。

设计取舍：
    - **抽取而非结构化**：只保留 ≤600 字原文片段 + 页码/章节 + 出处，不做数字归一。
      因为附注表述千差万别，硬做结构化必然错（宁给原文让人核，不给错数字）。
    - **只取前 N 处**（默认每组 3 处），避免把整本年报塞进 findings。
    - PDF 用 PyMuPDF 分页取文本；10-K 用 bs4 去标签（无 bs4 时正则兜底）。
    - 失败一律不抛异常，只记 `_errors`，不影响主流程。

用法：
    from note_extractor import extract_notes_into
    stat = extract_notes_into(findings, data_dir)   # 就地写入
    # → findings['related']['note_excerpts'] / ['ma_deep']['goodwill_excerpts']
    #    findings['risk']['litigation_excerpts'] / ['guarantee_excerpts']
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

# (组名, 关键词, 目标维度, 写入字段)
# 🔴 关键词顺序即优先级：越靠前越精确（章节名 > 泛指词）。
NOTE_GROUPS = [
    ('related_party', ('關連交易', '关联交易', '關聯交易', '關連及關聯交易',
                       'related party transactions', 'related-party transactions',
                       'transactions with related parties'),
     'related', 'note_excerpts'),
    ('goodwill', ('商譽減值', '商誉减值', '商譽及無形資產', '商誉及无形资产',
                  '無形資產', '无形资产', 'goodwill impairment', 'goodwill'),
     'ma_deep', 'goodwill_excerpts'),
    ('litigation', ('或有事項', '或然事項', '重大訴訟', '重大诉讼', '法律程序',
                    '訴訟', '诉讼', '仲裁', 'legal proceedings', 'contingencies',
                    'litigation matters'),
     'risk', 'litigation_excerpts'),
    ('guarantee', ('對外擔保', '对外担保', '擔保及或然', '担保及或然',
                   '擔保', '担保', 'letters of credit', 'guarantees of'),
     'risk', 'guarantee_excerpts'),
    ('commitment', ('重大合同', '重大合同及', '承諾事項', '承诺事项',
                    '資本承諾', '资本承诺', '承諾', 'commitments'),
     'related', 'commitment_excerpts'),
]

_MAX_PER_GROUP = 3
_WINDOW = 600

# 命中段落若含这些套话 → 判为噪声（10-K 的 forward-looking 免责声明里塞满了
# litigation/guarantee 等词，抽出来毫无信息量）
_BAD_PHRASES = ('forward-looking', 'private securities litigation', 'not guarantees',
                'safe harbor', 'reform act', '本公告含有前瞻性')


def _clean(t: str) -> str:
    t = re.sub(r'[ \t\u3000]+', ' ', str(t or ''))
    t = re.sub(r'\n{2,}', '\n', t)
    return t.strip()


def _read_pdf_pages(path: str, max_pages: int = 450) -> List[Tuple[int, str]]:
    try:
        import fitz
        doc = fitz.open(path)
        out = []
        for i in range(min(doc.page_count, max_pages)):
            try:
                out.append((i + 1, doc[i].get_text() or ''))
            except Exception:
                continue
        doc.close()
        return out
    except Exception:
        return []


def _read_html_text(path: str) -> str:
    try:
        html = open(path, encoding='utf-8', errors='ignore').read()
    except Exception:
        return ''
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()
        txt = soup.get_text(' ')
    except Exception:
        txt = re.sub(r'<[^>]+>', ' ', html)
    return _clean(txt)


def _resolve_source(findings: dict, data_dir: str) -> Tuple[List[Tuple[int, str]], str, str]:
    """返回 ([(页码, 文本)], 文件名, 来源类型)"""
    ap = findings.get('annual_pdf') or {}
    pdf = ap.get('pdf_path') or ''
    if pdf and not os.path.exists(pdf):
        pdf = ''
    if not pdf and data_dir and os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            if fn.lower().endswith('.pdf') and ('annual' in fn.lower() or '年报' in fn):
                pdf = os.path.join(data_dir, fn)
                break
    if pdf:
        return _read_pdf_pages(pdf), os.path.basename(pdf), 'annual_report_pdf'

    # 美股 10-K：缓存 → 按 annual_pdf.pdf_url 现下（analyze 第 22 步早于证据包，
    # 缓存通常还不存在，必须自己能拉，否则永远是"无命中"）
    if data_dir and isinstance(ap, dict):
        cache = os.path.join(data_dir, '10k_filing.htm')
        url = str(ap.get('pdf_url') or '')
        if not (os.path.exists(cache) and os.path.getsize(cache) > 50_000):
            if url.lower().endswith(('.htm', '.html')):
                try:
                    import requests
                    r = requests.get(url, headers={'User-Agent': 'research contact@example.com'},
                                     timeout=60)
                    if r.status_code == 200 and len(r.text) > 50_000:
                        try:
                            with open(cache, 'w', encoding='utf-8', errors='ignore') as fh:
                                fh.write(r.text)
                        except Exception:
                            pass
                        return ([(0, _read_html_text(cache))],
                                os.path.basename(cache), 'sec_10k_html')
                except Exception:
                    pass
        if os.path.exists(cache) and os.path.getsize(cache) > 50_000:
            return [(0, _read_html_text(cache))], os.path.basename(cache), 'sec_10k_html'
        for fn in os.listdir(data_dir):
            if fn.lower().endswith(('.htm', '.html')) and '10k' in fn.lower():
                return [(0, _read_html_text(os.path.join(data_dir, fn)))], fn, 'sec_10k_html'
    return [], '', ''


def _heading_score(text: str, idx: int) -> int:
    """章节候选打分（>0 才当标题）。

    实测教训：PDF 文本层里**表格行和章节标题长得一样**（短行 + 行首关键词），例如
    「無形資產及土地使用權的攤銷 8,553 8,478 7,546 33,229…」「擔保預計應付的金額；…」
    都会被误判为章节。故加三项惩罚：数字组 ≥2 个（表格）、数字占比高、含排版符号。
    """
    line_start = text.rfind('\n', 0, idx) + 1
    line_end = text.find('\n', idx)
    line = text[line_start: line_end if line_end != -1 else idx + 80].strip()
    if not line or (idx - line_start) > 30:
        return -1
    n = len(line)
    if n > 60:
        return -1
    # 表格行：出现 2 个以上带千分位/小数的数字组
    if len(re.findall(r'\d[\d,\.]{2,}', line)) >= 2:
        return -1
    score = 0
    if n <= 20:
        score += 2
    elif n <= 34:
        score += 1
    if sum(ch.isdigit() for ch in line) / max(n, 1) > 0.15:
        score -= 2
    if sum(line.count(s) for s in ('╱', '（', '(', '‖', '%')) >= 2:
        score -= 1
    if '，' in line or ',' in line or '。' in line:
        score -= 1
    return score


def _hit_kind(text: str, idx: int) -> str:
    """判断命中是「章节标题」还是「正文内联」"""
    return 'heading' if _heading_score(text, idx) > 0 else 'inline'


def extract_notes(findings: dict, data_dir: str = '') -> Dict[str, dict]:
    """抽取年报附注段落（不写 findings，纯返回）。

    两轮策略（2026-10-22 修订）：
      第 1 轮只收**章节标题型**命中（精准，优先给章节开篇）；
      某组标题型不足 1 条时，第 2 轮才退化为正文内联命中（并标 `match_type`）。
    首版只做内联匹配，实测港股 00700 抽到的全是利润表附注里的"商誉减值"碎片，
    根本不是章节 → 才改成标题优先。
    """
    pages, fname, src = _resolve_source(findings, data_dir)
    result: Dict[str, dict] = {'_source': src, '_file': fname, '_errors': []}
    if not pages:
        result['_errors'].append('未找到可读的年报原文（PDF/10-K HTML）')
        return result

    # 🔴 10-K HTML 区域限定（2026-10-22）：整份 HTML 里 'litigation'/'guarantee' 大量
    # 出现在 forward-looking statements 套话中，全文搜索只会抽到废话。故把搜索区
    # 收缩到「Item 8 财务报表与附注」之后（附注才是关联交易/或有事项/商誉所在）。
    if src == 'sec_10k_html' and pages:
        _txt = pages[0][1]
        _low = _txt.lower()
        for mark in ('item 8. financial statements', 'item 8.financial statements',
                     'notes to consolidated financial statements'):
            _p = _low.find(mark)
            if _p != -1:
                pages = [(0, _txt[_p:])]
                result['_region'] = f'10-K Item 8 之后（从 "{mark}" 起）'
                break

    for gname, kws, dim, field in NOTE_GROUPS:
        heading_hits, inline_hits = [], []
        for pno, text in pages:
            low = text.lower()
            best = None
            for kw in kws:
                idx = low.find(kw.lower())
                if idx == -1:
                    continue
                kind = _hit_kind(text, idx)
                # 标题型优先占位；内联仅记账
                if kind == 'heading' and best is None:
                    best = (kw, idx, kind)
                elif best is None:
                    best = (kw, idx, kind)
            if not best:
                continue
            kw, idx, kind = best
            # 标题型：从标题处往后取；内联型：向前带一点上下文
            start = idx if kind == 'heading' else max(0, idx - 120)
            seg = _clean(text[start: start + _WINDOW])
            if len(seg) < 120:
                continue
            if any(b in seg.lower() for b in _BAD_PHRASES):
                continue
            (heading_hits if kind == 'heading' else inline_hits).append({
                'keyword': kw,
                'page': pno if pno else None,
                'text': seg,
                'match_type': kind,
                'source': src,
                'file': fname,
            })
            if len(heading_hits) >= _MAX_PER_GROUP:
                break

        hits = heading_hits[:_MAX_PER_GROUP] or inline_hits[:_MAX_PER_GROUP]
        result[gname] = {
            'hits': hits, 'count': len(hits), 'dim': dim, 'field': field,
            'match_type': hits[0]['match_type'] if hits else None,
            'heading_pool': len(heading_hits), 'inline_pool': len(inline_hits),
        }
    return result


def extract_notes_into(findings: dict, data_dir: str = '') -> Dict[str, int]:
    """抽取并就地写入 findings，返回 {组名: 命中数}"""
    r = extract_notes(findings, data_dir)
    stat: Dict[str, int] = {}
    if r.get('_errors'):
        findings.setdefault('_note_extract', {})['errors'] = r['_errors']
        return stat

    for gname, kws, dim, field in NOTE_GROUPS:
        item = r.get(gname) or {}
        hits = item.get('hits') or []
        stat[gname] = len(hits)
        if not hits:
            continue
        base = findings.get(dim)
        if not isinstance(base, dict):
            base = {}
        base[field] = hits
        base.setdefault('_note_source', {
            'source': r.get('_source'), 'file': r.get('_file'),
            'note': ('附注段落为**原文关键词命中片段**（非章节摘要），'
                     'match_type=heading 表示命中了章节标题行，inline 表示正文内命中；'
                     '引用前须按页码核对原文'),
        })
        findings[dim] = base

    findings.setdefault('_note_extract', {}).update({
        'source': r.get('_source'), 'file': r.get('_file'), 'stats': stat,
    })
    return stat


if __name__ == '__main__':
    import json
    import sys
    sys.path.insert(0, '.')
    import _ctxfix  # noqa: F401
    d = sys.argv[1]
    res = json.load(open(os.path.join(d, 'results.json'), encoding='utf-8'))
    st = extract_notes_into(res['findings'], d)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    for dim in ('related', 'ma_deep', 'risk'):
        block = res['findings'].get(dim) or {}
        for k, v in block.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and 'keyword' in v[0]:
                print(f"{dim}.{k}: {len(v)} 条 →", v[0]['text'][:80].replace('\n', ' '))
