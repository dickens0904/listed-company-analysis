# -*- coding: utf-8 -*-
"""
peer_compare.py - 同业财务对比 + 估值分析
数据源: 东方财富（RPT_F10_ORG_BASICINFO批量 + RPT_LICO_FN_CPD）
功能:
  1. 按申万三级行业抓取全行业公司列表
  2. 获取各公司最新财务指标（营收/净利/增速/ROE/毛利率/资产负债率/PE/PB）
  3. 目标公司与行业均值/中位数横向对比
  4. 计算目标公司在行业内的分位数排名
  5. 历史分位数（当前PE/PB在近3年/5年的百分位）
用法:
  from peer_compare import PeerComparator
  comp = PeerComparator()
  data = comp.compare('601127')
  print(comp.format_markdown(data))
"""
import requests, json, os, time, sys

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

EM_API = 'http://datacenter-web.eastmoney.com/api/data/v1/get'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'http://data.eastmoney.com/',
    'Accept': 'application/json',
}


class PeerComparator:
    """同业财务对比分析器"""

    # 东方财富 RPT_LICO_FN_CPD 有效字段
    # 东方财富 RPT_LICO_FN_CPD 有效字段（经验证）
    # ⚠️ 无效字段会导致整个API返回null！
    FN_FIELDS = [
        'SECUCODE', 'SECURITY_CODE', 'SECURITY_NAME_ABBR',
        'REPORTDATE',
        'TOTAL_OPERATE_INCOME',   # 营业总收入（单位：元）
        'PARENT_NETPROFIT',       # 归母净利润
        'WEIGHTAVG_ROE',          # 加权ROE
        'YSTZ',                   # 营收同比增速(%)（不是YOYOPERATEREVE）
        'XSMLL',                  # 毛利率(%)（不是GROSS_PROFIT_RATIO）
        # 以下字段已验证为无效（RPT_LICO_FN_CPD）：
        # DEBT_ASSET_RATIO, YOYOPERATEREVE, YOYDEDUCTPROFIT, EST_PE, EST_PB, GROSS_PROFIT_RATIO
        'YOYEPS',                # EPS同比
        'EST_PE',                # 滚动PE（东方财富计算）
        'INDUSTRY_PE',           # 行业PE
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get_sw_industry(self, stock_code):
        """获取目标公司的行业分类
        注意: SWINDUSTRY_NAME2可能为null，改用BOARD_CODE（板块代码）作为同业筛选依据
        """
        secucode = self._format_secucode(stock_code)
        params = {
            'reportName': 'RPT_F10_ORG_BASICINFO',
            'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,SWINDUSTRY_NAME2,CSRC_INDUSTRY_NAME,GROSS_PROFIT_RATIO,BOARD_CODE_BK_2LEVEL,BOARD_NAME_2LEVEL,BOARD_CODE_BK_3LEVEL,BOARD_NAME_1LEVEL,REGIONBK',
            'filter': f'(SECUCODE="{secucode}")',
            'pageNumber': 1, 'pageSize': 5,
            'source': 'WEB', 'client': 'WEB',
        }
        r = self.session.get(EM_API, params=params, timeout=15)
        resp = r.json() if r.content else {}
        if resp is None: resp = {}
        records = resp.get('result', {}).get('data', []) if resp.get('result') else []
        if not records:
            return None, None, {}, None
        rec = records[0] if records else {}
        # SW行业可能为null，改用板块代码BK1262（乘用车）
        sw_industry = rec.get('SWINDUSTRY_NAME2', '') or rec.get('BOARD_CODE_BK_2LEVEL', '') or ''
        csrc_industry = rec.get('CSRC_INDUSTRY_NAME', '')
        board_bk2 = rec.get('BOARD_CODE_BK_2LEVEL', '')  # 如 BK1262 乘用车
        return sw_industry, csrc_industry, rec, board_bk2

    def _get_peer_list(self, sw_industry, fallback_board=None):
        """获取同行业所有公司
        sw_industry以BK开头时说明是板块代码（SWINDUSTRY_NAME2为null时的fallback），
        应改用BOARD_CODE_BK_2LEVEL字段过滤。
        如果SWINDUSTRY_NAME2为空且无fallback，返回空列表。
        """
        if not sw_industry and not fallback_board:
            return []
        params = {
            'reportName': 'RPT_F10_ORG_BASICINFO',
            'columns': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,GROSS_PROFIT_RATIO,BOARD_CODE_BK_2LEVEL,BOARD_NAME_2LEVEL',
            'pageNumber': 1, 'pageSize': 100,
            'source': 'WEB', 'client': 'WEB',
        }
        # 关键逻辑：sw_industry以"BK"开头说明是板块代码fallback，不是申万行业名
        if sw_industry and sw_industry.startswith('BK'):
            industry_filter = f'(BOARD_CODE_BK_2LEVEL="{sw_industry}")'
        elif sw_industry:
            industry_filter = f'(SWINDUSTRY_NAME2="{sw_industry}")'
        elif fallback_board:
            industry_filter = f'(BOARD_CODE_BK_2LEVEL="{fallback_board}")'
        else:
            return []
        if not industry_filter:
            return []
        params['filter'] = industry_filter
        r = self.session.get(EM_API, params=params, timeout=15)
        resp = r.json() if r.content else {}
        if resp is None: resp = {}
        records = resp.get('result', {}).get('data', []) if resp.get('result') else []
        return records or []

    def _get_financials(self, secucode):
        """获取单家公司财务指标（最新一期）"""
        params = {
            'reportName': 'RPT_LICO_FN_CPD',
            'columns': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORTDATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,WEIGHTAVG_ROE,YSTZ,XSMLL',
            'filter': f'(SECUCODE="{secucode}")',
            'pageNumber': 1, 'pageSize': 1,
            'sortColumns': 'REPORTDATE',
            'source': 'WEB', 'client': 'WEB',
        }
        params['columns'] = 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORTDATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,WEIGHTAVG_ROE,YSTZ,XSMLL'
        r = self.session.get(EM_API, params=params, timeout=15)
        resp = r.json() if r.content else {}
        if resp is None: resp = {}
        records = resp.get('result', {}).get('data', []) if resp.get('result') else []
        return records[0] if records else {}

    def _format_secucode(self, stock_code):
        if stock_code.endswith('.SH') or stock_code.endswith('.SZ'):
            return stock_code
        if stock_code.startswith('6'):
            return f'{stock_code}.SH'
        if stock_code[:3] in ['000', '001', '002', '003', '300']:
            return f'{stock_code}.SZ'
        if stock_code.startswith('8') or stock_code.startswith('4'):
            return f'{stock_code}.BJ'
        return f'{stock_code}.SH'

    def _safe_float(self, val, default=None):
        try:
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    def _percentile_rank(self, value, all_values):
        """计算value在all_values中的百分位（值越大排名越前）"""
        if value is None or not all_values:
            return None
        vals = [v for v in all_values if v is not None and v != 0]
        if not vals:
            return None
        rank = sum(1 for v in vals if v <= value)
        return round(rank / len(vals) * 100, 1)

    def compare(self, stock_code, data_dir=None):
        """
        主函数：获取同业对比数据
        返回:
          target: 目标公司数据
          peers: 同业公司列表（含财务指标）
          stats: 行业统计（均值/中位数/最高/最低）
          rank: 目标公司各指标的行业排名
        """
        target_code = self._format_secucode(stock_code)

        # Step 1: 获取目标公司行业分类
        sw_industry, csrc_industry, basic_info, board_bk2 = self._get_sw_industry(stock_code)
        target_fin = self._get_financials(target_code)
        # 毛利率: 基本信息GROSS_PROFIT_RATIO是主营毛利率，用财务XSMLL(29.14)作为合并报表毛利率
        target_gross_margin = (self._safe_float(target_fin.get('XSMLL')) or
                               self._safe_float(basic_info.get('GROSS_PROFIT_RATIO')))

        # Step 2: 获取同业公司列表
        # Step 2: 获取同业公司列表（SW行业为null时用板块代码兜底）
        peers_basic = self._get_peer_list(sw_industry, fallback_board=board_bk2)
        peer_codes = [p.get('SECUCODE') for p in peers_basic if p.get('SECUCODE')]

        # Step 3: 获取同业财务数据（批量，最多20家，控制频率）
        # Step 3: 获取同业财务数据（批量，最多20家，控制频率）
        peer_financials = []
        for p in peers_basic[:20]:
            sc = p.get('SECUCODE', '')
            if sc and sc != target_code:
                fin = self._get_financials(sc)
                if fin:
                    # 毛利率优先用XSMLL（合并报表毛利率），兜底用基本信息GROSS_PROFIT_RATIO
                    fin['gross_margin'] = (self._safe_float(fin.get('XSMLL')) or
                                           self._safe_float(p.get('GROSS_PROFIT_RATIO')))
                    peer_financials.append({**p, **fin})
                time.sleep(0.3)

        # Step 4: 合并目标公司数据
        # Step 4: 合并目标公司数据
        target = {
            'code': stock_code,
            'name': basic_info.get('SECURITY_NAME_ABBR', ''),
            'sw_industry': sw_industry or board_bk2,  # 两者取一
            'csrc_industry': csrc_industry,
            'revenue': self._safe_float(target_fin.get('TOTAL_OPERATE_INCOME')),
            'net_profit': self._safe_float(target_fin.get('PARENT_NETPROFIT')),
            'roe': self._safe_float(target_fin.get('WEIGHTAVG_ROE')),
            'gross_margin': target_gross_margin,  # 合并报表毛利率
            'debt_ratio': self._safe_float(target_fin.get('DEBT_ASSET_RATIO')),
            'revenue_growth': self._safe_float(target_fin.get('YSTZ')),
            'profit_growth': self._safe_float(target_fin.get('YOYDEDUCTPROFIT')),
            'pe': self._safe_float(target_fin.get('EST_PE')),
            'pb': self._safe_float(target_fin.get('EST_PB')),
            'report_date': target_fin.get('REPORTDATE', '未知'),
        }

        # Step 5: 计算各指标的行业数组
        rev_arr = [self._safe_float(p.get('TOTAL_OPERATE_INCOME')) for p in peer_financials
                   if self._safe_float(p.get('TOTAL_OPERATE_INCOME')) is not None]
        roe_arr = [self._safe_float(p.get('WEIGHTAVG_ROE')) for p in peer_financials
                   if self._safe_float(p.get('WEIGHTAVG_ROE')) is not None]
        # 毛利率: 优先用gross_margin(XSMLL)，兜底用GROSS_PROFIT_RATIO
        gm_arr = []
        for p in peer_financials:
            v = self._safe_float(p.get('gross_margin')) or self._safe_float(p.get('GROSS_PROFIT_RATIO'))
            if v is not None:
                gm_arr.append(v)
        # 资产负债率/PE/PB不在RPT_LICO_FN_CPD，跳过
        rg_arr = [self._safe_float(p.get('YSTZ')) for p in peer_financials
                  if self._safe_float(p.get('YSTZ')) is not None]

        # Step 6: 计算统计值
        def safe_mean(arr):
            return round(sum(arr) / len(arr), 2) if arr else None

        def safe_median(arr):
            s = sorted(arr)
            n = len(s)
            return round((s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2), 2) if n else None

        def safe_max(arr):
            return round(max(arr), 2) if arr else None

        def safe_min(arr):
            return round(min(arr), 2) if arr else None

        def robust_mean(arr, trim_pct=0.2):
            """去除首尾极值后的均值（trim_pct: 去除比例），避免极端值拉歪均值"""
            if not arr or len(arr) < 3:
                return safe_mean(arr)
            s = sorted(arr)
            k = max(1, int(len(s) * trim_pct))
            trimmed = s[k:-k] if k < len(s) else s
            return round(sum(trimmed) / len(trimmed), 2) if trimmed else None

        stats = {
            'revenue':        {'mean': safe_mean(rev_arr), 'median': safe_median(rev_arr), 'max': safe_max(rev_arr), 'min': safe_min(rev_arr), 'count': len(rev_arr)},
            'roe':            {'mean': robust_mean(roe_arr, 0.2), 'median': safe_median(roe_arr), 'max': safe_max(roe_arr), 'min': safe_min(roe_arr)},
            'gross_margin':   {'mean': robust_mean(gm_arr, 0.2), 'median': safe_median(gm_arr), 'max': safe_max(gm_arr), 'min': safe_min(gm_arr)},
            'revenue_growth': {'mean': safe_mean(rg_arr), 'median': safe_median(rg_arr), 'max': safe_max(rg_arr), 'min': safe_min(rg_arr)},
        }

        # Step 7: 目标公司各指标分位数
        rank = {
            'revenue':       self._percentile_rank(target['revenue'], rev_arr),
            'roe':           self._percentile_rank(target['roe'], roe_arr),
            'gross_margin':  self._percentile_rank(target['gross_margin'], gm_arr),
            'revenue_growth': self._percentile_rank(target['revenue_growth'], rg_arr),
        }

        result = {
            'target': target,
            'stats': stats,
            'rank': rank,
            'peers': [{
                'code': p.get('SECURITY_CODE', ''),
                'name': p.get('SECURITY_NAME_ABBR', ''),
                'revenue': self._safe_float(p.get('TOTAL_OPERATE_INCOME')),
                'roe': self._safe_float(p.get('WEIGHTAVG_ROE')),
                'gross_margin': self._safe_float(p.get('gross_margin')) or self._safe_float(p.get('GROSS_PROFIT_RATIO')),
                'debt_ratio': None,  # DEBT_ASSET_RATIO not available
                'revenue_growth': self._safe_float(p.get('YSTZ')),
                'pe': None,
                'pb': None,
            } for p in peer_financials],
            'warnings': [],
        }

        if not sw_industry:
            result['warnings'].append('无法获取申万行业分类，同业对比数据不完整')
        if not peer_financials:
            result['warnings'].append('同业财务数据为空，可能接口无返回')

        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            out = os.path.join(data_dir, 'peer_compare.json')
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        return result

    def format_markdown(self, data):
        """格式化为Markdown同业对比报告"""
        t = data.get('target', {})
        s = data.get('stats', {})
        r = data.get('rank', {})
        peers = data.get('peers', [])
        warns = data.get('warnings', [])

        def pct_bar(pct):
            if pct is None:
                return 'N/A'
            bars = int(round(pct / 10))
            return f'{pct:.0f}% █{"█" * bars}{"░" * (10 - bars)}'

        def v(val, unit='', fmt='{:.2f}', raw=False):
            """raw=True: val is in yuan, convert to 亿元; raw=False: val already has unit"""
            if val is None:
                return 'N/A'
            if raw:
                return f'{val / 1e8:.2f}亿'
            return fmt.format(val) + unit

        def vs(v1, v2, lower_better=False):
            """比较目标值与均值，返回定性描述"""
            if v1 is None or v2 is None:
                return 'N/A'
            ratio = v1 / v2 if v2 != 0 else 0
            if abs(ratio - 1) < 0.05:
                return '≈行业平均'
            if lower_better:
                return '✅' if ratio < 0.95 else '⚠️' if ratio < 1.1 else '🔴' if ratio > 1.5 else '❌'
            return '✅' if ratio > 1.05 else '⚠️' if ratio > 0.95 else '❌' if ratio < 0.5 else '⬇️'

        lines = []
        lines.append("## 同业财务对比分析\n")

        # 行业信息
        lines.append(f"**申万行业**: {t.get('sw_industry') or '未知'}")
        lines.append(f"**证监会行业**: {t.get('csrc_industry') or '未知'}")
        lines.append(f"**财务报告期**: {t.get('report_date') or '未知'}")
        lines.append("")

        # 核心指标对比表
        lines.append("### 核心指标对比\n")
        header = "| 指标 | 目标公司 | 行业均值 | 行业中位 | 行业最高 | 行业最低 | 行业分位 | 评价 |"
        lines.append(header)
        lines.append("|------|---------|---------|---------|---------|---------|---------|------|")

        metrics = [
            ('revenue', '营业收入(亿)', False),
            ('roe', '加权ROE(%)', False),
            ('gross_margin', '毛利率(%)', False),
            ('revenue_growth', '营收增速(%)', False),
        ]

        for key, label, lower_better in metrics:
            tv = t.get(key)
            st = s.get(key, {})
            mv = st.get('mean')
            med = st.get('median')
            mx = st.get('max')
            mn = st.get('min')
            pct = r.get(key)
            ev = vs(tv, mv, lower_better)

            # 营收以元存储，需要换算为亿
            if key == 'revenue':
                lines.append(f"| {label} | {v(tv, raw=True)} | {v(mv, raw=True)} | {v(med, raw=True)} | {v(mx, raw=True)} | {v(mn, raw=True)} | {pct_bar(pct)} | {ev} |")
            elif key in ('roe', 'gross_margin', 'revenue_growth'):
                lines.append(f"| {label} | {v(tv, '%') if tv is not None else 'N/A'} | {v(mv, '%') if mv is not None else 'N/A'} | {v(med, '%') if med is not None else 'N/A'} | {v(mx, '%') if mx is not None else 'N/A'} | {v(mn, '%') if mn is not None else 'N/A'} | {pct_bar(pct)} | {ev} |")
            else:
                lines.append(f"| {label} | {v(tv)} | {v(mv)} | {v(med)} | {v(mx)} | {v(mn)} | {pct_bar(pct)} | {ev} |")

        lines.append("")
        lines.append("> **评价说明**: ✅ 显著优于行业 ⚠️ 略优于行业 ≈行业平均 ⬇️ 显著低于行业（低估值） ❌ 明显弱于行业（高估值）\n")

        # 同行列表
        if peers:
            lines.append("### 同业公司一览\n")
            lines.append("| 代码 | 公司 | 营收(亿) | ROE(%) | 毛利率(%) | 营收增速(%) |")
            lines.append("|------|------|---------|--------|----------|---------|")
            for p in sorted(peers, key=lambda x: self._safe_float(x.get('revenue')) or 0, reverse=True)[:20]:
                rev = self._safe_float(p.get('revenue'))
                roe = self._safe_float(p.get('roe'))
                gm = self._safe_float(p.get('gross_margin'))
                rg = self._safe_float(p.get('revenue_growth'))
                rev_str = f'{rev/1e8:.1f}亿' if rev else 'N/A'
                roe_str = f'{roe:.2f}%' if roe is not None else 'N/A'
                gm_str = f'{gm:.2f}%' if gm is not None else 'N/A'
                rg_str = f'{rg:.2f}%' if rg is not None else 'N/A'
                lines.append(f"| {p.get('code','')} | {p.get('name','')} | {rev_str} | {roe_str} | {gm_str} | {rg_str} |")

        # 估值评价
        lines.append("")
        lines.append("### 估值综合评价\n")
        pe_val = t.get('pe')
        pb_val = t.get('pb')
        pe_pct = r.get('pe')
        pb_pct = r.get('pb')

        if pe_val is not None and pb_val is not None:
            if pe_val < 0:
                lines.append(f"- **PE({pe_val:.1f}x)**: 🔴 公司亏损，PE无意义")
                if pb_val > 0:
                    pb_judge = '高估' if pb_pct and pb_pct > 70 else ('低估' if pb_pct and pb_pct < 30 else '合理')
                    lines.append(f"- **PB({pb_val:.2f}x)**: 行业分位{pct_bar(pb_pct)} → {pb_judge}")
            else:
                pe_judge = '高估' if pe_pct and pe_pct > 70 else ('低估' if pe_pct and pe_pct < 30 else '合理')
                pb_judge = '高估' if pb_pct and pb_pct > 70 else ('低估' if pb_pct and pb_pct < 30 else '合理')
                lines.append(f"- **PE({pe_val:.1f}x)**: 行业分位{pct_bar(pe_pct)} → {pe_judge}")
                lines.append(f"- **PB({pb_val:.2f}x)**: 行业分位{pct_bar(pb_pct)} → {pb_judge}")
        elif pe_val is not None:
            if pe_val < 0:
                lines.append(f"- **PE({pe_val:.1f}x)**: 🔴 公司亏损，PE无意义")
            else:
                lines.append(f"- **PE({pe_val:.1f}x)**: 行业均值{s.get('pe',{}).get('mean','N/A')}x，{vs(pe_val, s.get('pe',{}).get('mean'), lower_better=True)}")
        elif pb_val is not None:
            lines.append(f"- **PB({pb_val:.2f}x)**: 行业均值{s.get('pb',{}).get('mean','N/A')}x，{vs(pb_val, s.get('pb',{}).get('mean'), lower_better=True)}")
        else:
            lines.append("- **PE/PB**: 暂无数据")

        # 综合结论
        lines.append("")
        lines.append("### 同业对比结论\n")
        strong = []
        weak = []
        for key, label, _ in metrics:
            pct = r.get(key)
            if pct and pct >= 75:
                pct_val = int(pct)
                if pct_val == 100:
                    strong.append(f"{label}(行业第1顶尖)")
                else:
                    strong.append(f"{label}(超越{pct_val}%同行)")
            elif pct and pct <= 25:
                pct_val = int(pct)
                if pct_val == 0:
                    weak.append(f"{label}(行业垫底)")
                else:
                    weak.append(f"{label}(位于行业后{int(pct_val)}%)")

        if strong:
            lines.append(f"**优势**: {', '.join(strong)}")
        if weak:
            lines.append(f"**短板**: {', '.join(weak)}")
        if not strong and not weak:
            lines.append("各项指标位于行业中位数附近，无显著优劣势")

        if warns:
            lines.append("\n**⚠️ 说明**: " + "; ".join(warns))

        return '\n'.join(lines)

    def format_short(self, data):
        """短格式：用于嵌入主报告"""
        t = data.get('target', {})
        r = data.get('rank', {})
        s = data.get('stats', {})

        pe_val = t.get('pe')
        pb_val = t.get('pb')
        pe_pct = r.get('pe')
        pb_pct = r.get('pb')

        lines = []
        lines.append(f"**行业**: {t.get('sw_industry', '未知')} / {t.get('csrc_industry', '未知')}")
        lines.append(f"**同业家数**: {len(data.get('peers', []))}家")
        if t.get('roe'):
            lines.append(f"**ROE**: {t['roe']:.2f}%（行业均{s.get('roe',{}).get('mean','N/A')}%，分位{r.get('roe', 'N/A')}%）")
        if t.get('gross_margin'):
            lines.append(f"**毛利率**: {t['gross_margin']:.2f}%（行业均{s.get('gross_margin',{}).get('mean','N/A')}%）")
        # PE/PB暂不可用
        pass
        return ' | '.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='同业财务对比')
    parser.add_argument('stock', help='股票代码')
    parser.add_argument('--output', '-o', help='输出JSON路径')
    args = parser.parse_args()

    comp = PeerComparator()
    data = comp.compare(args.stock, data_dir=args.output)
    print(comp.format_markdown(data))


def generate_report_section(data: dict) -> list:
    if not data or not data.get('has_data'):
        return []
    md = data.get('markdown', '')
    if not md:
        return []
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 同业财务对比\n\n", md]
