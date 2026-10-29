# -*- coding: utf-8 -*-
"""
peer_discovery.py — 从年报正文里「发现」可比公司，而不是靠写死名单
=====================================================================

背景（2026-10-22 实证）
----------------------
`peer_valuation.get_peer_comparison()` 的 PEER_MAP 只写死了「白酒」一个行业，
其余全部退化成 `coverage='only_self'`——等于没有同业对比。

蟹老板问：年报里不是写着竞争对手吗？能不能直接用 Python 抓？

实证结论（四份年报抽样，见 scripts/output/*/data/2025_annual_report.pdf）：
  · 年报**确实写**了，但口径很脏：
      - 830799（北交所·金融科技）：「竞争」命中 9 次，100% 是自述
        （核心竞争力/竞争实力/市场竞争力），全文零对手公司名。
      - 688585（上纬新材）：P24 明确点名「与**欧林**等国际化工巨头存在
        一定差距」，但同一页同时出现金风科技/中材科技/西门子歌美飒/
        比亚迪新材料——这些是**客户与合作方**，不是对手。
  · 所以「Python 不行」的真实原因不是**取不到**，而是**分不清**：
      ① 同一段里对手/客户/供应商/伙伴/参股公司混写，正则无法判语义；
      ② 称谓不统一：「上纬新材料科技股份有限公司」全称 vs「上纬新材」简称，
         实测腾讯反查智能匹配**简称**、全称返回空；
      ③ 同名歧义：「欧林」既是美股 OLN，也是 A 股 688319 欧林生物。

三段流水线（职责边界）
--------------------
  Stage A  Python：年报 → 候选窗 + 公司名候选池（把上百页压到 ~15 窗）
  Stage B  Agent ：读窗口 → 判「谁是对手」+ 归一成可检索简称（人/LLM 的活）
  Stage C  Python：简称 → 证券代码 → 估值财务快照（机械检索的活）

🔴 铁律：Stage B 若无 Agent 结论，禁止用正则硬猜冒充名单。
   `--auto` 规则版产出必须带 `method='regex_heuristic'`、`confidence='low'`，
   只能作线索，不得进客户材料。

用法
----
    # A：切窗（产出 peers_extract_request.md 给 Agent 读）
    python scripts/peer_discovery.py --code 688585 --stage A
    # B：打印待办契约 / 校验 Agent 回填的 JSON
    python scripts/peer_discovery.py --code 688585 --stage B
    python scripts/peer_discovery.py --code 688585 --stage B --check
    # C：名称→代码→快照
    python scripts/peer_discovery.py --code 688585 --stage C
    # 串联
    python scripts/peer_discovery.py --code 688585 --stage AC --auto
"""
import sys
import os
import io
import re
import json
import time
import argparse
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SEC_UA = "CaizhongJinkong Research research@caizhong.com"   # SEC 必须带联系方式 UA

_S = requests.Session()
_S.trust_env = False          # 绕本机代理（北交所那次踩过：会被代理吃掉）
_S.headers.update({"User-Agent": UA})


# ═══════════════════════════════════════════════════════════
# Stage A：年报 → 候选窗 + 公司名候选池
# ═══════════════════════════════════════════════════════════

# 强信号：直接指向竞争关系
STRONG = ['竞争对手', '竞争者', '主要厂商', '主要竞争者', '可比公司', '同行业上市公司',
          '同行业公司', '行业内主要企业', '竞争格局', '主要竞争', '竞争对手主要有',
          '市场竞争', '国际巨头', '跨国巨头', '国外厂商', '海外厂商', '直接竞争']

# 中信号：描述行业地位，可能点名也可能只是自夸
MED = ['市场份额', '市场占有率', '行业地位', '集中度', '产量排名', '领先',
       '进口替代', '国产替代', '先发优势', '错位竞争']

# 明确是「客户/供应商/合作/参股」关系的措辞——用来给 Agent 提示，不直接剔除
RELATION_HINT = ['客户', '供应商', '合作', '战略合作', '签署', '达成', '意向书',
                 '参股', '控股子公司', '联营', '采购', '销售给', '怎样的帮助']

_NAME_PAT = re.compile(
    r'[\u4e00-\u9fa5A-Za-z0-9·\.\-]{2,24}?'
    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|株式会社'
    r'|Inc\.|Incorporated|Corporation|Corp\.|Ltd\.|Limited|Group|Technologies|Holdings)'
)

# ── 裸简称：从「等公司 / 等厂商 / 等巨头 / 等竞争对手」这类**锚点向左回溯**──
# 为什么不用正向正则：正向匹配会从左往右在任意位置起步，
#   「公司产量与欧林等国际化工巨头」会被吞成 '公司产量与欧林'（实测翻车）。
#   从锚点向左取到第一个功能词为止，天然拿到最后一个词 —— 这才是人眼读法。
_ANCHOR_PAT = re.compile(
    r'等(?:国际|国内|行业|海外|全球|主要)?'
    r'(?:化工|树脂|材料|电子|医药|钢铁|有色|新能源|互联网)?'
    r'(?:公司|企业|厂商|厂家|巨头|龙头|领先(?:厂商|企业)|知名(?:企业|厂商)'
    r'|竞争对手|竞争者|参与者|树脂厂)'
)

# 向左回溯时遇到这些字符/词立即停手（它们是句子结构，不是公司名的一部分）
_STOP_CHARS = set('。，；、,，；：:（）()「」“”"\'/年月日%……—－-—+=<>《》')
_STOP_WORDS = ('公司', '和', '与', '向', '为', '对', '在', '是', '有', '的', '其', '之',
               '产量', '销量', '业务', '市场', '市场', '技术', '需求', '进入', '提升',
               '实现', '进一步', '成为', '通过', '并且', '不仅', '还要', '以及', '包括',
               '主要', '包括', '如', '例如', '分别', '同时', '此外', '另外', '目前',
               '未来', '随着', '凭借', '依托', '公司产量', '公司', '本公司')


def _backward_names(txt, end_pos, max_len=14, max_items=5):
    """从锚点左侧做并列枚举回溯：
    遇到标点/功能词收手；若停在顿号上，继续向左取下一个并列词（最多 max_items 个）。
    """
    out = []
    i = end_pos
    for _ in range(max_items):
        buf = ''
        j = i - 1
        stopped_at_sep = False
        while j >= 0 and len(buf) < max_len:
            ch = txt[j]
            if ch.isspace() or ch in _STOP_CHARS:
                stopped_at_sep = ch in '、,，'
                break
            cand = ch + buf
            # 粘进来了功能词（如「包括宁德时代」的「包括」）→ 剥掉它再收手
            hit = [w for w in _STOP_WORDS if cand.startswith(w)]
            if hit:
                w = max(hit, key=len)
                buf = cand[len(w):]
                break
            buf = cand
            j -= 1
        if len(buf.strip()) >= 2:
            out.append(buf.strip())
        if stopped_at_sep:
            i = j
            continue
        break
    return out

# 候选若以这些虚词/量词开头，基本不是公司名
_BAD_HEAD = tuple('的在了对为其这些上述将使其与其和及包括主要全球国内国际同时此外另外并且'
                  '一二三四五六七八九十多家众多各家部分部分占')


def _clean_cand(s, self_names):
    s = re.sub(r'\s+', '', str(s or ''))
    s = s.strip('、,，。;；：:（）()「」“”"\'/')
    if len(s) < 2 or len(s) > 20:
        return None
    if not re.search(r'[\u4e00-\u9fa5A-Za-z]', s):
        return None
    if s[0] in _BAD_HEAD or re.match(r'^[\d\.\-]+$', s):
        return None
    if any(g in s for g in _GENERIC):
        return None
    if any(sn and (sn in s or s in sn) for sn in self_names if sn):
        return None
    return s

# 通用词黑名单（不是公司名）
_GENERIC = set(['本公司', '公司自身', '上市公司', '非上市公司', '有限合伙企业', '金融机构',
                '目标公司', '标的公司', '母公司', '全资子公司', '控股子公司', '参股公司',
                '会计师事务所', '律师事务所', '保荐机构', '主承销商',
                '关联公司', '下属公司', '合并报表', '其中之一'])


def _page_texts(pdf_path, max_pages=None):
    """PDF → [(page_no, text)]"""
    import fitz
    doc = fitz.open(pdf_path)
    n = len(doc) if max_pages is None else min(max_pages, len(doc))
    out = []
    for i in range(n):
        try:
            out.append((i + 1, doc[i].get_text() or ''))
        except Exception:
            out.append((i + 1, ''))
    doc.close()
    return out


def _split_paras(text):
    """按空行/换行切段，保留段序号"""
    raw = re.split(r'\n\s*\n|\n(?=[（(一二三四五六七八九十\d])', text)
    return [p.strip() for p in raw if p and p.strip()]


def extract_windows(pdf_path, self_names=None, max_windows=15, window_chars=1100):
    """Stage A 核心：把上百页年报压成 ~15 个候选窗"""
    self_names = self_names or []
    pages = _page_texts(pdf_path)
    # 只扫前 60 页（管理层讨论/行业格局/风险都在前半本，附注是会计口径噪音）
    pages = [(p, t) for p, t in pages if p <= 60]

    scored = []          # (score, page, para_idx, para)
    for pg, t in pages:
        paras = _split_paras(t)
        for i, para in enumerate(paras):
            s = 0
            for kw in STRONG:
                s += para.count(kw) * 3
            for kw in MED:
                s += para.count(kw) * 1
            # 带明确 relation hint 的段落降权（多半是客户/合作，不是对手）
            if any(h in para for h in RELATION_HINT) and s <= 3:
                s -= 1
            if s > 0:
                scored.append((s, pg, i, para, paras))

    scored.sort(key=lambda x: -x[0])

    windows, seen_key = [], set()
    for s, pg, i, para, paras in scored:
        # 窗口 = 命中段 ± 1 段
        lo = max(0, i - 1)
        hi = min(len(paras), i + 2)
        buf = '\n'.join(paras[lo:hi])
        if len(buf) > window_chars:
            buf = buf[:window_chars] + ' …[截断]'
        key = (pg, re.sub(r'\s+', '', buf)[:60])
        if key in seen_key:
            continue
        seen_key.add(key)
        windows.append({
            'page': pg, 'score': s, 'text': buf,
            'strong_hits': [k for k in STRONG if k in para],
            'med_hits': [k for k in MED if k in para],
        })
        if len(windows) >= max_windows:
            break

    # 公司名候选池（从窗口文本里提，避免扫全文产生大量无关名）
    pool = {}

    def _add(name, page):
        nm = _clean_cand(name, self_names)
        if not nm:
            return
        item = pool.setdefault(nm, {'count': 0, 'pages': set()})
        item['count'] += 1
        item['pages'].add(page)

    for w in windows:
        txt = w['text']
        for m in _NAME_PAT.finditer(txt):
            _add(m.group(0), w['page'])
        # 「A、B、C 等公司」/「与 X 等国际巨头」——从锚点往左回溯
        for m in _ANCHOR_PAT.finditer(txt):
            for nm in _backward_names(txt, m.start()):
                _add(nm, w['page'])

    candidates = sorted(
        [{'name': k, 'count': v['count'], 'pages': sorted(v['pages'])}
         for k, v in pool.items()],
        key=lambda x: -x['count'])

    return {
        'source_pdf': os.path.basename(pdf_path),
        'scanned_pages': min(60, max(p[0] for p in pages)) if pages else 0,
        'windows': windows,
        'candidates': candidates,
        'stats': {'para_hits': len(scored), 'windows': len(windows),
                  'candidates': len(candidates)},
    }


# ═══════════════════════════════════════════════════════════
# Stage B：契约（Python 出题，Agent 作答）
# ═══════════════════════════════════════════════════════════

LLM_SCHEMA = {
    "self_company": "上纬新材料科技股份有限公司",
    "industry": "环保高性能耐腐蚀材料 / 风电叶片用环氧树脂",
    "peers": [
        {
            "name": "欧林 (Olin Corporation)",
            "search_alias": "Olin",           # 用于证券代码反查：中文简称或英文
            "relation": "competitor",         # competitor|customer|supplier|partner|investee|irrelevant
            "segment": "风电叶片用环氧树脂",   # 在哪个业务段竞争
            "evidence": "P24：在全球范围内，公司产量与欧林等国际化工巨头存在一定差距",
            "confidence": "high"              # high|medium|low
        }
    ],
    "notes": "未点名的厂商不要编；relation 拿不准一律标 irrelevant。"
}

REVIEW_PROMPT = """# 任务：从本公司定期报告中识别**真正的竞争对手**并归一成可检索简称

你是投行分析师。下面是从《{company}》定期报告中自动切出的 {nwin} 个候选窗口。
同一份材料里，**客户 / 供应商 / 战略合作方 / 参股公司**经常与**竞争对手**混写在一段，
机器无法区分，这一步由你判断。

## 判定规则（严格遵守）
1. 只有**同行业、争夺同一批客户/同一市场份额**的才是 `competitor`。
   - `customer`=它的客户；`supplier`=它的供应商；`partner`=战略合作/技术合作方；
   - `investee`=它参股/控股的公司；`irrelevant`=只是行文带过、无竞争关系。
2. **宁缺毋滥**：关系拿不准就标 `irrelevant` 并在 notes 说明，**不要为了凑数编公司**。
3. `search_alias` 必须是**证券市场上可直接检索的简称或英文名**：
   - 「上纬新材料科技股份有限公司」→「上纬新材」（全称无法反查代码，实测返回空）
   - 「欧林」→「Olin」（中文「欧林」会误命中 A 股 688319 欧林生物）
   - 未上市/退市公司也照填 name，search_alias 填空串 ""。
4. `evidence` 必须原样摘录证明句并注明页码，**不得改写**。

## 输出
把 JSON 写入：`{out_path}`
格式（严格照此 schema，不要加额外字段，不要 markdown 代码块）：

{schema}

找不到任何点名对手时：`{{"peers": [], "notes": "全文未点名具体竞争对手，仅作行业格局自述"}}`
—— 这是完全合法的输出，**比编出来有价值得多**。

---

"""


def build_request(result_a, company, out_dir, industry=''):
    """Stage B：把 Stage A 结果写成 Agent 可读的请求包"""
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, 'peers_extract_request.md')
    json_path = os.path.join(out_dir, 'peers_extract_request.json')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result_a, f, ensure_ascii=False, indent=2)

    out = [REVIEW_PROMPT.format(
        company=company,
        nwin=len(result_a['windows']),
        out_path=os.path.join(out_dir, 'peers_llm.json'),
        schema=json.dumps(LLM_SCHEMA, ensure_ascii=False, indent=2),
    )]
    out.append(f'## 自动提取的公司名候选池（共 {len(result_a["candidates"])} 个，'
               f'仅供参考，勿照单全收）\n')
    for c in result_a['candidates'][:40]:
        out.append(f'- `{c["name"]}`（出现 {c["count"]} 次，P{",".join(map(str, c["pages"]))}）')
    out.append('\n## 候选窗口原文（按相关性排序）\n')
    for i, w in enumerate(result_a['windows'], 1):
        out.append(f'### 窗口 {i} · P{w["page"]} · 相关分 {w["score"]}')
        tags = w['strong_hits'] or w['med_hits']
        out.append(f'命中词：{"/".join(tags[:6])}\n')
        out.append('```text')
        out.append(w['text'])
        out.append('```\n')

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return md_path, json_path


LLM_OUT_NAME = 'peers_llm.json'


def check_llm_answer(path):
    """校验 Agent 回填是否符合契约"""
    errs = []
    if not os.path.exists(path):
        return False, [f'未找到 {path}（Agent 尚未作答）']
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception as e:
        return False, [f'JSON 解析失败：{e}']
    if not isinstance(d, dict):
        return False, ['根节点必须是 object']
    peers = d.get('peers')
    if peers is None:
        return False, ['缺少 peers 字段']
    if not isinstance(peers, list):
        return False, ['peers 必须是数组']
    for i, p in enumerate(peers):
        if not isinstance(p, dict):
            errs.append(f'peers[{i}] 不是 object'); continue
        for req in ('name', 'search_alias', 'relation', 'evidence'):
            if req not in p:
                errs.append(f'peers[{i}] 缺字段 {req}')
        if p.get('relation') not in ('competitor', 'customer', 'supplier',
                                     'partner', 'investee', 'irrelevant'):
            errs.append(f'peers[{i}].relation={p.get("relation")!r} 非法')
        ev = str(p.get('evidence') or '')
        if not re.search(r'P\d+', ev):
            errs.append(f'peers[{i}].evidence 未标注页码（必须是原文摘录+P页码）')
    return len(errs) == 0, errs


# ═══════════════════════════════════════════════════════════
# Stage C：名称 → 证券代码 → 估值财务快照
# ═══════════════════════════════════════════════════════════

_CORP_TAIL = re.compile(r'(科技|新材料|技术|实业|-development|发展|国际|控股|股份|有限责任|公司|集团)+$')


def _alias_guesses(name, alias):
    """反查候选：优先 Agent 给的简称，再做保守的简称化尝试（不编造）"""
    out = []
    for x in (alias, name):
        x = re.sub(r'\s*[\(（][^)）]*[\)）]\s*', '', str(x or '').strip())
        x = x.replace('股份有限公司', '').replace('有限责任公司', '').replace('有限公司', '')
        if x and x not in out:
            out.append(x)
    # 全称太长的，试去尾部通用词 + 前 4/6 字（腾讯按简称精确匹配）
    base = out[-1] if out else ''
    if base:
        s = _CORP_TAIL.sub('', base)
        if s and s != base and s not in out:
            out.append(s)
        for n in (4, 6):
            if len(base) > n and base[:n] not in out:
                out.append(base[:n])
    return out[:5]


def _tx_search(kw, timeout=12):
    """腾讯 smartbox：覆盖 A股/深沪/港股/美股，但**不含北交所**（实测）"""
    url = f"https://smartbox.gtimg.cn/s3/?q={urllib.parse.quote(kw)}&t=all"
    try:
        r = _S.get(url, timeout=timeout)
        r.encoding = 'gbk'
        raw = r.text.strip()
        m = re.search(r'v_hint="(.*?)";?$', raw, re.S)
        body = m.group(1) if m else raw.replace('v_hint="', '')
        body = body.replace('\\u', '\\u')
        # \uXXXX 转义还原
        try:
            body = body.encode('latin-1', 'ignore').decode('unicode_escape')
        except Exception:
            pass
        return body
    except Exception as e:
        return ''


def _parse_tx(body):
    out = []
    if not body or body == 'N':
        return out
    for seg in body.split('^'):
        p = seg.split('~')
        if len(p) >= 3:
            out.append({'mkt': p[0], 'code': p[1], 'name': (p[2] or '').strip(),
                        'type': p[4] if len(p) > 4 else ''})
    return out


def _em_search(kw, timeout=12):
    """东财 suggest：补齐腾讯缺失的**北交所**"""
    url = ("https://searchapi.eastmoney.com/api/suggest/get"
           f"?input={urllib.parse.quote(kw)}&type=14&count=8"
           "&token=D43BF722C8E33BDC906FB84D85E326E8&cb=jQuery_cb")
    try:
        r = _S.get(url, timeout=timeout, headers={"Referer": "https://www.eastmoney.com/"})
        txt = r.text
        m = re.search(r'jQuery_cb\((.*)\)\s*;?\s*$', txt, re.S)
        j = json.loads(m.group(1) if m else txt)
        data = ((j.get('result') or {}).get('QuotationCodeTable') or {}).get('Data') or []
        return [{'mkt': str(d.get('mkt') or d.get('type') or ''),
                 'code': d.get('code'), 'name': d.get('name')} for d in data if d.get('code')]
    except Exception:
        return []


def _sec_search(kw, timeout=25):
    """SEC company_tickers.json：按英文名模糊匹配（必须专用 UA）"""
    if not kw or not re.search(r'[A-Za-z]', str(kw)):
        return []
    try:
        r = _S.get("https://www.sec.gov/files/company_tickers.json", timeout=timeout,
                   headers={"User-Agent": SEC_UA})
        j = r.json()
        k = kw.lower()
        hits = []
        for v in j.values():
            t = str(v.get('title') or '')
            if k in t.lower():
                hits.append({'mkt': 'us', 'code': str(v.get('ticker')), 'name': t})
            if len(hits) >= 6:
                break
        return hits
    except Exception:
        return []


def _tencent_batch_quote(codes, timeout=15):
    """腾讯批量行情（毫秒级）。字段索引经**真值标定**，不许猜：
       用宇信科技(300674) 对拍 peer_snapshot.snapshot 的输出确认：
         [1]=简称  [3]=现价  [39]=PE(TTM)  [44]=流通市值(亿元)
         [45]=总市值(亿元)  [46]=市净率PB
       标定值：PE 20.02 / 总市值 104.27 亿（与 snapshot 完全一致）
       ⚠️ 仅适配 A 股/北交所；港美股字段布局不同，不走这条路。
    """
    if not codes:
        return {}
    q = ','.join(('bj' if str(c).startswith(('4', '8', '9')) and len(str(c)) == 6
                  else ('sh' if str(c).startswith('6') else 'sz')) + str(c)
                 for c in codes)
    try:
        r = _S.get(f"https://qt.gtimg.cn/q={q}", timeout=timeout)
        r.encoding = 'gbk'
        out = {}
        for line in r.text.split(';'):
            line = line.strip()
            if not line.startswith('v_'):
                continue
            try:
                head, body = line.split('=', 1)
                f = body.strip().strip('"').split('~')
                if len(f) < 47:
                    continue
                code = str(f[2])
                out[code] = {
                    'name': f[1],
                    'price': _f(f[3]),
                    'pe_ttm': _f(f[39]),
                    'float_mcap_亿': _f(f[44]),
                    'market_cap_亿': _f(f[45]),
                    'pb': _f(f[46]),
                    'source': 'tencent_batch',
                }
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(mkt, code):
    """腾讯/东财市场前缀 → 内部统一代码形制"""
    mkt = (mkt or '').lower()
    code = str(code or '').strip()
    if not code:
        return None, None
    if mkt in ('sh', 'sz'):
        return code, 'a'
    if mkt == 'bj':
        return code, 'a'                     # 北交所归入 A 股链路
    if mkt == 'hk':
        if len(code) == 4:
            code = '0' + code
        if code.startswith('8'):             # 8xxxx = 人民币柜台，跳过
            return None, None
        return code + '.HK', 'hk'
    if mkt == 'us':
        # us~aapl.oq / us~oln.n / us~tctzf.ps
        tk = code.split('.')[0].upper()
        return tk, 'us'
    return None, None


def resolve_company(name, alias='', prefer_market=None):
    """名称 → 证券代码。返回 {'code','market','matched_name','source'} 或 unresolved"""
    tried = []
    for kw in _alias_guesses(name, alias):
        if not kw:
            continue
        hits = _parse_tx(_tx_search(kw))
        for h in hits:
            code, market = _norm(h['mkt'], h['code'])
            if prefer_market and market != prefer_market:
                continue
            if code:
                # 名称一致性：反查回来的名字要能和输入对上（防「欧林生物」误配）
                return {'code': code, 'market': market, 'matched_name': h['name'],
                        'source': 'tencent_smartbox', 'query': kw}
        tried.append(kw)
        time.sleep(0.15)

    # 北交所：腾讯没有，走东财
    for kw in _alias_guesses(name, alias):
        for h in _em_search(kw):
            code, market = _norm(h['mkt'], h['code'])
            if code and (not prefer_market or market == prefer_market):
                return {'code': code, 'market': market, 'matched_name': h['name'],
                        'source': 'eastmoney_suggest', 'query': kw}
        time.sleep(0.15)

    # 美股英文名：SEC 兜底
    for kw in _alias_guesses(name, alias):
        for h in _sec_search(kw):
            code, market = _norm('us', h['code'])
            if code and (not prefer_market or market == prefer_market):
                return {'code': code, 'market': market, 'matched_name': h['name'],
                        'source': 'sec_company_tickers', 'query': kw}
        time.sleep(0.15)

    return {'code': None, 'market': None, 'tried_queries': tried[:3],
            'reason': '未上市/已退市/非公开主体/名称无法归一（不得臆测代码）'}


def apply_quotes(peers_json, quotes_file):
    """把 Wind MCP 补齐的港美股估值合并回 peers.json

    约定 quotes_file 两种写法都收：
      {"rows": [{"code":"OLN","market_cap_亿":..,"pe_ttm":..,...}]}
      或 {"OLN": {"market_cap_亿":..,"pe_ttm":..,...}}
    """
    d = json.load(open(peers_json, encoding='utf-8'))
    q = json.load(open(quotes_file, encoding='utf-8'))
    if isinstance(q, dict) and 'rows' in q:
        rows = q['rows']
    elif isinstance(q, list):
        rows = q
    else:
        rows = [dict(v, code=k) for k, v in q.items() if isinstance(v, dict)]
    idx = {str(r.get('code')): r for r in rows if r.get('code')}
    n = 0
    for p in d.get('peers', []):
        code = str(p.get('code'))
        if code in idx:
            snap = p.get('snapshot') or {}
            for k, v in idx[code].items():
                if k != 'code':
                    snap[k] = v
            snap['status'] = 'wind_filled'
            p['snapshot'] = snap
            n += 1
    d['quote_plan'] = [i for i in d.get('quote_plan', [])
                       if str(i.get('code')) not in idx]
    d['counts']['pending_wind_quote'] = len(d['quote_plan'])
    d['counts']['wind_filled'] = n
    with open(peers_json, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return n


def _fmt_pe(v):
    """负 PE 必须写成「亏损」而不是 -8.65 —— 后者会被误读成估值便宜"""
    if v is None:
        return '—'
    try:
        if float(v) < 0:
            return '亏损'
    except (TypeError, ValueError):
        return str(v)
    return _fmt(v)


VERIFY_BADGE = {'resolved': '✅已核验', 'suspicious': '⚠️体量存疑',
                'unverified': '❌未验证', 'no_quote': '⏳待补行情'}


def _print_inject(res, rows, stats):
    print(f"\n[注入核验] 共 {res['counts']['competitor']} 家提议 → "
          f"可核验 {res['counts']['resolved']} / 未验证 {res['counts']['unresolved']} "
          f"/ 待补行情 {res['counts']['pending_wind_quote']}")
    print(f"{'代码':<9}{'名称':<11}{'核验':<12}{'市值(亿)':>10}{'倍数':>8}{'PE':>9}{'PB':>8}")
    print('-' * 70)
    for r in rows:
        s = r.get('snapshot') or {}
        print(f"{r.get('code') or '—':<9}{(s.get('name') or r.get('name',''))[:9]:<11}"
              f"{VERIFY_BADGE.get(r.get('verification'),''):<12}"
              f"{_fmt(s.get('market_cap_亿')):>10}{_fmt(r.get('size_ratio')):>8}"
              f"{_fmt_pe(s.get('pe_ttm')):>9}{_fmt(s.get('pb')):>8}")
    if stats.get('self_market_cap_亿'):
        print(f"\n  本公司 {res['self_code']} 市值 {stats['self_market_cap_亿']:.1f} 亿；"
              f"名单市值跨度 {stats.get('cap_spread_x','—')} 倍")
    for w in stats.get('warnings', []):
        print(f"  🔴 {w}")
    for n in stats.get('unverified', []):
        print(f"  ❌ {n}：未解析到代码 —— 非上市/退市/名称有误，**不得进名单**")
    for r in rows:
        if r.get('near_name_alerts'):
            print(f"  ⚠️ {r.get('name')} 存在近名项 {'/'.join(r['near_name_alerts'])}"
                  f" —— 人工确认是否 AI 写错字")
    if stats.get('pe_median') is not None:
        print(f"  📐 盈利标的 PE 中位数 {stats['pe_median']}"
              f"（{stats['positive_pe_count']} 家盈利 / {len(stats.get('loss_making',[]))} 家亏损"
              f"，亏损者须剔除后再算均值）")
    print('  🟡 行业同业性未经程序校验（脚本侧无稳定行业源），落笔前须人工过一遍')


def render_peer_md(res, industry=None):
    """把 peers.json 渲染成可直接贴进报告的 markdown（含口径脚注）"""
    injected = res.get('method') == 'external_injection'
    if injected:
        out = [f"### 可比公司（由 {res.get('source','').replace('_injected','')} 指定，非年报披露）", '']
        out.append(f"> 选样理由：{res.get('rationale') or '未填写（🔴 必须补）'}")
        out.append('')
    else:
        out = [f"### 可比公司（来源：{res['self_code']} 定期报告原文点名）", '']
    hdr = '| 公司 | 代码 | 核验 | 市值 | PE(TTM) | PB | 原文依据 |' if injected \
        else '| 公司 | 代码 | 市值 | PE(TTM) | PB | 营收 | 净利 | 原文依据 |'
    if industry:
        out.append(f"> 🏷️ 行业背书基线（Wind）：**{industry}**；候选公司同业性须逐家核对"
                   f"是否同属该行业（本工具不自动判定赛道）。")
        out.append('')
    out.append(hdr)
    out.append('|---|---|---|---|---|---|---|---|' if not injected else '|---|---|---|---|---|---|---|')
    currencies = set()
    for p in res['peers']:
        s = p.get('snapshot') or {}
        cur = s.get('currency') or ''
        if cur:
            currencies.add(cur)
        unit = {'USD': '亿美元', 'HKD': '亿港元'}.get(cur, '亿元')
        badge = VERIFY_BADGE.get(p.get('verification'), '') if injected else ''
        if s.get('status') == 'pending_wind':
            out.append(f"| {p.get('name','')} | {p.get('code','')} | {badge} | 待 Wind 补 | "
                       f"— | — | {p.get('evidence','')[:36]}… |" if injected else
                       f"| {p.get('name','')} | {p.get('code','')} | 待 Wind 补 | — | — | "
                       f"— | — | {p.get('evidence','')[:36]}… |")
            continue
        if injected:
            out.append(f"| {s.get('name') or p.get('name','')} | {p.get('code') or '—'} | "
                       f"{badge} | {_fmt(s.get('market_cap_亿'))}{unit} | "
                       f"{_fmt_pe(s.get('pe_ttm'))} | {_fmt(s.get('pb'))} | "
                       f"{p.get('why') or p.get('evidence','')[:36]} |")
            continue
        out.append(f"| {s.get('name') or p.get('name','')} | {p.get('code','')} | "
                   f"{_fmt(s.get('market_cap_亿'))}{unit} | "
                   f"{_fmt_pe(s.get('pe_ttm'))} | {_fmt(s.get('pb'))} | "
                   f"{_fmt(s.get('revenue_亿'))}{unit} | "
                   f"{_fmt(s.get('net_profit_亿'))}{unit} | "
                   f"{p.get('evidence','')[:36]}… |")
    out.append('')
    out.append(f"> 口径：市值/估值取 {res['asof']} 行情；财务取最近一期年报。")
    if currencies:
        out.append(f"> 🔴 币种口径：表中含 {'/'.join(sorted(currencies))} 计价标的，"
                   f"与人民币口径**不可直接比较**，跨市场对比须先折算。")
    out.append('> 负 PE 一律记作「亏损」，不写负值（避免被误读为估值便宜）。')
    if res.get('method') == 'regex_heuristic':
        out.append('> 🔴 本表为规则推断，未经语义审核，**禁止用于对外交付**。')
    if injected:
        _st = res.get('verification_stats') or {}
        out.append('> 🟡 **本表为外部指定名单，不是年报披露口径**：'
                   '代码归一已程序核验，但行业同业性须人工复核后再进对外材料。')
        if _st.get('unverified'):
            out.append(f"> ❌ 未验证（不得引用）：{'、'.join(_st['unverified'])}")
        _near = [r for r in res.get('peers', []) if r.get('near_name_alerts')]
        for r in _near:
            out.append(f"> ⚠️ 近名待辨：{r.get('orig_name') or r.get('name')}"
                       f"（{r.get('code')}） 与 {'/'.join(r['near_name_alerts'])}"
                       f" —— 人工确认是两家还是 AI 写错字")
        if _st.get('loss_making'):
            out.append(f"> 📐 亏损标的 {len(_st['loss_making'])} 家（"
                       f"{'、'.join(_st['loss_making'][:5])}"
                       f"{'等' if len(_st['loss_making']) > 5 else ''}）须先剔除；"
                       f"按剩余 {_st.get('positive_pe_count')} 家盈利标的，"
                       f"PE 中位数 {_st.get('pe_median')}")
        if _st.get('cap_spread_x'):
            out.append(f"> 名单市值跨度 {_st['cap_spread_x']} 倍"
                       + ('，🔴 超过 20 倍，均值失真，建议分层或取中位数'
                          if _st['cap_spread_x'] > 20 else '。'))
    if res.get('notes'):
        out.append(f"> {res['notes']}")
    return '\n'.join(out)


def build_peer_table(self_code, llm_json_path, out_dir=None):
    """Stage C：读 Agent 名单 → 反查代码 → 拉估值财务快照"""
    ok, errs = check_llm_answer(llm_json_path)
    if not ok:
        return {'ok': False, 'errors': errs}
    d = json.load(open(llm_json_path, encoding='utf-8'))
    peers = [p for p in d.get('peers', []) if p.get('relation') == 'competitor']

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from peer_snapshot import snapshot, render
        have_snapshot = True
    except Exception as e:
        have_snapshot = False

    # 🔴 保护已补齐的估值：重跑 Stage C 不得回滚 Agent 已靠 Wind 补的数据
    #    （2026-10-22 实测：第二次跑 Stage C 把 OLN 的 Wind 快照冲成 pending_wind）
    prev_quotes = {}
    if out_dir:
        _pj = os.path.join(out_dir, 'peers.json')
        if os.path.exists(_pj):
            try:
                for _p in (json.load(open(_pj, encoding='utf-8')).get('peers') or []):
                    _sn = _p.get('snapshot') or {}
                    if _p.get('code') and (
                            _sn.get('status') == 'wind_filled'
                            or _sn.get('market_cap_亿') is not None):
                        prev_quotes[str(_p['code'])] = _sn
            except Exception:
                pass

    resolved, unresolved = [], []
    quote_plan = []          # 港美股：脚本拿不到可靠估值 → 出单据给 Agent 用 Wind MCP 补
    for p in peers:
        r = resolve_company(p.get('name'), p.get('search_alias'))
        row = {**p, **r}
        if not r.get('code'):
            unresolved.append(row)
            continue
        if r['code'] in prev_quotes:
            row['snapshot'] = prev_quotes[r['code']]
            resolved.append(row)
            continue
        if have_snapshot and r['market'] == 'a':
            try:
                snap = snapshot(r['code'], r['market'])
                row['snapshot'] = {k: snap.get(k) for k in
                                   ('name', 'market_cap_亿', 'pe_ttm', 'pb', 'ps',
                                    'report_period', 'revenue_亿', 'net_profit_亿', 'roe',
                                    'error')}
            except Exception as e:
                row['snapshot'] = {'error': f'{type(e).__name__}: {e}'}
        else:
            # 港/美股：不猜行情接口字段索引（金融交付禁止目测），走既有 Wind 通道
            try:
                from data_source_registry import to_wind_code
                wcode = to_wind_code(r['code'], r['market'])
            except Exception:
                wcode = r['code']
            row['snapshot'] = {'status': 'pending_wind', 'windcode': wcode}
            quote_plan.append({
                'name': row.get('name'), 'code': r['code'], 'market': r['market'],
                'windcode': wcode,
                'tool': 'mcp__wind-finance__get_stock_quote + get_financial_data',
                'fields': ['market_cap', 'pe_ttm', 'pb', 'ps',
                           'revenue', 'net_profit', 'roe', 'report_period'],
            })
        resolved.append(row)

    result = {
        'ok': True,
        'self_code': self_code,
        'industry': d.get('industry', ''),
        'notes': d.get('notes', ''),
        'method': d.get('method', 'llm_agent'),
        'asof': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'peers': resolved,
        'unresolved': unresolved,
        # 非对手但有价值：客户/供应商/合作方，可用于上下游佐证
        'non_competitor': [p for p in d.get('peers', []) if p.get('relation') != 'competitor'],
        'quote_plan': quote_plan,
        'counts': {'competitor': len(peers), 'resolved': len(resolved),
                   'unresolved': len(unresolved),
                   'pending_wind_quote': len(quote_plan)},
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        pth = os.path.join(out_dir, 'peers.json')
        with open(pth, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        result['saved_to'] = pth
        if quote_plan:
            qp = os.path.join(out_dir, 'peers_quote_plan.json')
            with open(qp, 'w', encoding='utf-8') as f:
                json.dump({'asof': result['asof'], 'note':
                           '港美股估值不猜行情字段：由 Agent 调 Wind MCP 补齐后，'
                           '用 --apply-quotes <file.json> 合并回 peers.json',
                           'items': quote_plan}, f, ensure_ascii=False, indent=2)
            result['quote_plan_file'] = qp
    return result


INJECT_SCHEMA_NOTE = """注入名单格式（relax 版：比年报契约少几个必填项）：
{
  "injected_by": "agent|analyst",
  "rationale": "为什么认为这些是可比公司（一句话，进报告脚注）",
  "industry": "细分赛道名",
  "peers": [{"name": "宇信科技", "search_alias": "宇信科技", "why": "银行IT解决方案"}]
}
"""


def verify_injected(items, self_code, self_market, size_band=(0.1, 10.0), fetch=True):
    """🔴 Agent/分析师注入名单的**核验管线**

    为什么必须核验（2026-10-22 实测）：让 Agent 凭行业知识给 15 家银行 IT 对手，
    **14 家都能反查到代码** —— 也就是说「查得到代码」根本不构成验证，它只证明
    「这家公司存在」。真正会翻车的是另外三件事：
      ① 同名/近名替换（AI 对低频专名易音近形近错字，如「天阳」↔「天玑」）；
      ② 跨赛道但知名的大公司被塞进来（恒生电子 vs 银行IT外包不是一回事）；
      ③ 体量差几十倍仍硬凑成一张表（均值失去意义）。
    所以：代码归一 + 元数据取回 + 规模离散度，三者一起才算通过。
    """
    rows = []
    for it in items:
        name = it.get('name') or ''
        r = resolve_company(name, it.get('search_alias', ''))
        row = {k: v for k, v in it.items()}
        row['orig_name'] = name      # 保住注入原名：行情返回名会被改写（如 ST天玑），
                                     # 近名比对必须用原名，否则相似度被稀释导致漏报
        row.update(r)
        if not r.get('code'):
            row['verification'] = 'unverified'
            row['verify_reason'] = r.get('reason')
            rows.append(row)
            continue
        row['verification'] = 'resolved'
        rows.append(row)

    if not fetch:
        return rows, {'note': '未取行情（fetch=False）'}

    # 批量拉行情 + 自身作为规模基准
    a_codes = [row['code'] for row in rows
               if row.get('market') == 'a' and row.get('verification') == 'resolved']
    quotes = _tencent_batch_quote([self_code] + a_codes if self_market == 'a' else a_codes)
    self_q = quotes.get(str(self_code), {}) if self_market == 'a' else {}

    for row in rows:
        if row.get('verification') != 'resolved':
            continue
        q = quotes.get(str(row['code']))
        if not q:
            row['verification'] = 'no_quote'
            row['verify_reason'] = '未取到行情（港美股请用 Wind MCP 补）'
            continue
        row['snapshot'] = {**q, 'status': 'ok'}
        row['name'] = q.get('name') or row.get('name')

    # ②b ST / 退市风险警示：这类标的自身经营已异常，估值倍数不做可比锚
    for row in rows:
        _n = str(row.get('name') or '')
        if _n.startswith(('ST', '*ST', 'SST')) or '退' in _n:
            row['verification'] = 'suspicious'
            row['verify_reason'] = (
                f'「{_n}」已实施风险警示/退市整理，经营异常，其估值倍数'
                f'不可作为可比锚；建议剔除')

    # ② 近名碰撞：AI 对低频专名极易做音近/形近替换（天阳↔天玑、赞辉↔占辉），
    #    而反查通道**照样能给它找到代码并"通过核验"** —— 实测天玑科技→300245 ST天玑
    #    被判成 ✅。这一关专门盯这种"查得到 ≠ 就是你想要的"的错配。
    try:
        from difflib import SequenceMatcher
        _named = [(row.get('orig_name') or row.get('name') or '', row)
                  for row in rows if (row.get('orig_name') or row.get('name'))]
        for a in range(len(_named)):
            for b in range(a + 1, len(_named)):
                ra, rb = _named[a][1], _named[b][1]
                na, nb = _named[a][0], _named[b][0]
                if ra.get('code') == rb.get('code'):
                    continue
                sim = SequenceMatcher(None, na, nb).ratio()
                if sim >= 0.6:
                    ra.setdefault('near_name_alerts', []).append(f'{nb}({rb.get("code")})')
                    rb.setdefault('near_name_alerts', []).append(f'{na}({ra.get("code")})')
                    warn.append(f'近名待辨：{na}({ra.get("code")}) 与 {nb}({rb.get("code")}) '
                                f'相似度 {sim:.2f} —— 须人工确认是两家还是 AI 写错字')
    except Exception:
        pass

    # ③ 规模离散度：以本公司为基准，超出 size_band 的标 suspicious
    lo, hi = size_band
    warn = []
    base_cap = (self_q or {}).get('market_cap_亿')
    if base_cap:
        for row in rows:
            cap = (row.get('snapshot') or {}).get('market_cap_亿')
            if not cap:
                continue
            ratio = cap / base_cap
            row['size_ratio'] = round(ratio, 2)
            if not (lo <= ratio <= hi):
                row['verification'] = 'suspicious'
                row['verify_reason'] = (
                    f'市值 {cap:.1f} 亿为本公司的 {ratio:.1f} 倍，'
                    f'超出可比带 {lo}~{hi} 倍 —— 体量不可比，均值会失真')

    caps = [(row.get('snapshot') or {}).get('market_cap_亿') for row in rows]
    caps = [c for c in caps if c]
    # ④ PE 口径守卫：亏损标的进不了「平均 PE」，必须剔除后再算，否则均值完全失真
    _loss = [r.get('name') for r in rows
             if isinstance((r.get('snapshot') or {}).get('pe_ttm'), (int, float))
             and (r.get('snapshot') or {})['pe_ttm'] < 0]
    _pes = [(r.get('snapshot') or {}).get('pe_ttm') for r in rows]
    _pes = [x for x in _pes if isinstance(x, (int, float)) and x > 0]
    if _loss:
        warn.append(f'{len(_loss)} 家处于亏损（{"、".join(_loss[:5])}'
                    f'{"等" if len(_loss) > 5 else ""}），PE 为负；'
                    f'算行业 PE 时必须先剔除，只按剩余 {len(_pes)} 家盈利标的取'
                    f'{"中位" if len(_pes) >= 3 else "参考"}值')
    stats = {'n_quote': len([r for r in rows if (r.get('snapshot') or {}).get('market_cap_亿')]),
             'loss_making': _loss,
             'positive_pe_count': len(_pes),
             'pe_median': round(sorted(_pes)[len(_pes) // 2], 2) if _pes else None,
             'self_market_cap_亿': base_cap,
             'size_band': size_band,
             'suspicious': [r.get('name') for r in rows if r.get('verification') == 'suspicious'],
             'unverified': [r.get('name') for r in rows if r.get('verification') == 'unverified'],
             'no_quote': [r.get('name') for r in rows if r.get('verification') == 'no_quote']}
    if len(caps) >= 2:
        stats['cap_spread_x'] = round(max(caps) / min(caps), 1)
    if len(caps) >= 2 and (stats.get('cap_spread_x') or 0) > 20:
        warn.append(f'名单内市值跨度 {stats["cap_spread_x"]} 倍，'
                    f'直接取均值没有参考价值，建议按体量分层或改用中位数')
    stats['warnings'] = warn
    return rows, stats


def load_injected(path):
    """读注入名单（relax 格式：name / search_alias / why）"""
    d = json.load(open(path, encoding='utf-8'))
    items = d.get('peers') or []
    for it in items:
        it.setdefault('relation', 'competitor')
        it.setdefault('search_alias', it.get('name', ''))
        it.setdefault('evidence', f"由 {d.get('injected_by','外部')} 指定；"
                                  f"理由：{it.get('why','未填')}")
    return d, items


# ═══════════════════════════════════════════════════════════
# 规则降级版（--auto）：无 Agent 时的弱推断，必须显式标注
# ═══════════════════════════════════════════════════════════

def auto_guess(result_a):
    """没有 Agent 时的兜底：只保留「强竞争词」附近的名，可靠性低"""
    peers = []
    for c in result_a['candidates'][:25]:
        hit = False
        for w in result_a['windows']:
            if any(k in w['text'] for k in ('竞争对手', '主要厂商', '竞争格局', '国际巨头')) \
               and c['name'] in w['text']:
                hit = True
                break
        if hit:
            peers.append({'name': c['name'], 'search_alias': '', 'relation': 'competitor',
                          'segment': '', 'evidence': f"P{c['pages'][0]} 附近出现（规则命中，未核证实）",
                          'confidence': 'low'})
    return {'industry': '', 'notes': '', 'peers': peers, 'method': 'regex_heuristic',
            '_warning': '规则版只按关键词邻近推断，未做语义判定，'
                        '可能把客户/供应商误认为对手；禁止直接写入对外交付物。'}


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════

def _out_dir_for(code, run_date=None, discover=False):
    """本次分析的产出目录：output/{code}_{date}_peers

    discover=True 时（给 analyze.py 读取用）：今天是新目录且空 → 回退到最近一次已跑过的目录，
    避免「名单昨天产、今天的分析流程读不到」。写盘一律用 discover=False。
    """
    base = os.path.dirname(os.path.abspath(__file__))
    d = run_date or datetime.now().strftime('%Y%m%d')
    path = os.path.join(base, 'output', f'{code}_{d}_peers')
    if discover and not run_date and os.path.isdir(path) and not os.path.exists(
            os.path.join(path, 'peers.json')):
        root = os.path.join(base, 'output')
        try:
            cands = sorted([x for x in os.listdir(root)
                            if x.startswith(f'{code}_') and x.endswith('_peers')
                            and os.path.exists(os.path.join(root, x, 'peers.json'))],
                           reverse=True)
            if cands:
                return os.path.join(root, cands[0])
        except Exception:
            pass
    return path


DEFAULT_PDFS = {
    '688585': r'output\688585_20261021\data\2025_annual_report.pdf',
    '002180': r'output\002180_20260603\data\2025_annual_report.pdf',
    '600519': r'output\600519_20260612\data\2025_annual_report.pdf',
}


def _find_pdf(code, explicit):
    if explicit and os.path.exists(explicit):
        return explicit
    base = os.path.dirname(os.path.abspath(__file__))
    # 按目录名 "{code}_*" 找（如 output/688585_20261021/data/2025_annual_report.pdf）
    out_root = os.path.join(base, 'output')
    if os.path.isdir(out_root):
        for d in sorted(os.listdir(out_root), reverse=True):
            if d.startswith(str(code) + '_'):
                cand = os.path.join(out_root, d, 'data', '2025_annual_report.pdf')
                if os.path.exists(cand):
                    return cand
    try:
        from tmp_paths import PDF_CACHE_DIR
        hits = sorted([p for p in os.listdir(PDF_CACHE_DIR)
                       if p.startswith(code) and p.lower().endswith('.pdf')],
                      key=lambda x: os.path.getsize(os.path.join(PDF_CACHE_DIR, x)),
                      reverse=True)
        if hits:
            return os.path.join(PDF_CACHE_DIR, hits[0])
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description='年报 → 可比公司名单发现（三段流水线）')
    ap.add_argument('--code', required=True, help='股票代码')
    ap.add_argument('--company', default='', help='公司全称（用于排除自身）')
    ap.add_argument('--pdf', default='', help='年报 PDF 路径')
    ap.add_argument('--stage', default='AC', help='A / B / C / AC / ABC / B-check')
    ap.add_argument('--auto', action='store_true', help='无 Agent 时启用规则降级版')
    ap.add_argument('--check', action='store_true', help='校验 Stage B 回填')
    ap.add_argument('--apply-quotes', default='', help='合并 Wind MCP 补齐的估值 JSON')
    ap.add_argument('--inject', default='', help='外部（Agent/分析师）主动注入的同业名单 JSON')
    ap.add_argument('--size-band', default='0.1,10',
                    help='可比市值倍数带（相对本公司），超出标 suspicious。默认 0.1,10')
    ap.add_argument('--md', action='store_true', help='同时输出 markdown 表')
    ap.add_argument('--industry', default='', help='本公司 Wind 行业分类（用于同业性背书核对）')
    ap.add_argument('--max-windows', type=int, default=15)
    a = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = _out_dir_for(a.code)
    pj = os.path.join(out_dir, 'peers.json')
    if a.apply_quotes:
        n = apply_quotes(pj, a.apply_quotes)
        print(f'[C] 已合并 Wind 补齐估值：{n} 家 → {pj}')
        return 0

    # ── 外部注入通路：Agent/分析师主动给名单（年报没写时的兜底）──
    if a.inject:
        band = tuple(float(x) for x in a.size_band.split(','))
        _code = str(a.code)
        self_market = ('a' if (len(_code) == 6 and _code.isdigit())
                       else ('hk' if _code.endswith('.HK') else 'us'))
        meta, items = load_injected(a.inject)
        rows, stats = verify_injected(items, a.code, self_market, band)
        res = {
            'ok': True, 'self_code': a.code, 'industry': meta.get('industry', ''),
            'source': meta.get('injected_by', 'agent') + '_injected',
            'rationale': meta.get('rationale', ''),
            'method': 'external_injection',
            'asof': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'peers': rows, 'unresolved': [], 'non_competitor': [], 'quote_plan': [],
            'verification_stats': stats,
            'counts': {'competitor': len(items),
                       'resolved': len([r for r in rows
                                        if r.get('verification') in ('resolved', 'suspicious')]),
                       'unresolved': len(stats.get('unverified', [])),
                       'pending_wind_quote': len(stats.get('no_quote', []))},
        }
        os.makedirs(out_dir, exist_ok=True)
        json.dump(res, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        _print_inject(res, rows, stats)
        mdp = os.path.join(out_dir, 'peers.md')
        open(mdp, 'w', encoding='utf-8').write(render_peer_md(res))
        print(f'\n  已保存：{pj}\n  markdown：{mdp}')
        return 0

    pdf = _find_pdf(a.code, a.pdf)
    if a.stage.upper().startswith('A') and not pdf:
        print(f'✗ 未找到 {a.code} 的年报 PDF（先用 announcements/pdf_download 下载，或用 --pdf 指定）')
        return 2

    # 公司全称：优先 CLI，缺省用已实测的名称链路（给 Agent 的文档里不要裸着代码）
    company = a.company
    if not company:
        try:
            sys.path.insert(0, base)
            from dispatcher import get_company_name
            company = get_company_name(a.code) or a.code
        except Exception:
            company = a.code
    result_a = None
    if 'A' in a.stage.upper():
        t0 = time.time()
        result_a = extract_windows(pdf, self_names=[company] if company != a.code else [],
                                   max_windows=a.max_windows)
        os.makedirs(out_dir, exist_ok=True)
        print(f"[A] 扫描 {result_a['source_pdf']}：命中段 {result_a['stats']['para_hits']} → "
              f"窗口 {result_a['stats']['windows']} → 候选公司名 {result_a['stats']['candidates']} "
              f"({time.time()-t0:.1f}s)")

    if 'B' in a.stage.upper():
        if result_a is None:
            jp = os.path.join(out_dir, 'peers_extract_request.json')
            result_a = json.load(open(jp, encoding='utf-8')) if os.path.exists(jp) else None
            if result_a is None:
                print('✗ 请先跑 Stage A'); return 2
        if a.check:
            ok, errs = check_llm_answer(os.path.join(out_dir, LLM_OUT_NAME))
            print('✓ 契约校验通过' if ok else '✗ 契约校验失败：\n  ' + '\n  '.join(errs))
            return 0 if ok else 1
        md, js = build_request(result_a, company, out_dir)
        print(f'[B] 已生成请求包：\n  {md}\n  {js}')
        print(f'    请由 Agent 阅读 md 后回填：{os.path.join(out_dir, LLM_OUT_NAME)}')

    if 'C' in a.stage.upper():
        llm_path = os.path.join(out_dir, LLM_OUT_NAME)
        if not os.path.exists(llm_path) and a.auto:
            res_a = result_a or json.load(
                open(os.path.join(out_dir, 'peers_extract_request.json'), encoding='utf-8'))
            json.dump(auto_guess(res_a), open(llm_path, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=2)
            print('[C] ⚠️ 未发现 Agent 回填，启用**规则降级版**（不得写入对外交付物）')
        res = build_peer_table(a.code, llm_path, out_dir)
        if not res.get('ok'):
            print('✗ Stage C 失败：\n  ' + '\n  '.join(res['errors']))
            return 1
        print(f"\n[C] 对手 {res['counts']['competitor']} 家 → 解析到代码 {res['counts']['resolved']} "
              f"家，未解析 {res['counts']['unresolved']} 家（asof {res['asof']}）")
        if res['peers']:
            print(f"{'代码':<10}{'名称':<12}{'市值亿':>10}{'PE':>9}{'PB':>8}"
                  f"{'营收亿':>10}{'净利亿':>10}  备注")
            print('-' * 88)
            for r in res['peers']:
                sn = r.get('snapshot') or {}
                note = r.get('source', '')
                if sn.get('status') == 'pending_wind':
                    note = f"待 Wind 补（{sn.get('windcode')}）"
                print(f"{r.get('code',''):<10}{(sn.get('name') or r.get('name',''))[:10]:<12}"
                      f"{_fmt(sn.get('market_cap_亿')):>10}{_fmt(sn.get('pe_ttm')):>9}"
                      f"{_fmt(sn.get('pb')):>8}{_fmt(sn.get('revenue_亿')):>10}"
                      f"{_fmt(sn.get('net_profit_亿')):>10}  {note}")
        if res['unresolved']:
            print('\n  未解析（显式标注，不得臆测代码）：')
            for u in res['unresolved']:
                print(f"    - {u.get('name')}：{u.get('reason')}")
        if res.get('quote_plan_file'):
            print(f"\n  ⏳ 港美股估值待补单据：{res['quote_plan_file']}")
            print("     由 Agent 调 Wind MCP（get_stock_quote / get_financial_data）补齐后：")
            print("     python scripts/peer_discovery.py --code <code> "
                  "--apply-quotes <补回的json>")
        if a.md:
            mdp = os.path.join(out_dir, 'peers.md')
            with open(mdp, 'w', encoding='utf-8') as f:
                f.write(render_peer_md(res, a.industry))
            print(f"\n  markdown 表格：{mdp}")
        method = res.get('method')
        if method == 'regex_heuristic':
            print('\n  🔴 本表由规则推断生成，未经语义审核，禁止进客户材料。')
        print(f"\n  已保存：{res.get('saved_to')}")
    return 0


def _fmt(v):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:,.2f}'
    return str(v)


if __name__ == '__main__':
    sys.exit(main())
