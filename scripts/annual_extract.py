# -*- coding: utf-8 -*-
"""
annual_extract.py - 年报PDF关键章节自动提取

用途：从上市公司年报PDF全文中提取20个关键章节，
      补全API数据缺口（关联交易、客户/供应商、产能等）。

依赖：PyMuPDF (fitz)
用法：
    from annual_extract import AnnualReportExtractor
    
    extractor = AnnualReportExtractor('report.pdf')
    sections = extractor.extract_all()
    for name, content in sections.items():
        print(f"### {name}")
        print(content[:500])
        print()

    # 或提取到文件
    extractor.extract_to_file('output.md')
    
    # 或提取单个章节
    audit = extractor.extract_section('audit')
"""

import os
import re
import sys
import json
try:
    import fitz
    _HAS_FITZ = True
except ImportError:
    fitz = None
    _HAS_FITZ = False

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class AnnualReportExtractor:
    """年报PDF关键章节提取器（支持中文/英文年报自动识别）"""

    # 乱码判断：仅当同时满足 ASCII>阈值 AND 中文字符极少时才判为乱码
    # 纯英文年报（如港股腾讯）ASCII~99.4%，但内容正常，不应判为乱码
    # 只有混合乱码（CJK随机替换导致）才需触发fallback
    GARBLE_ASCII_PCT = 98          # 上调阈值，英文/数字为主的年报不受影响
    GARBLE_CHINESE_MIN = 100       # 中文字符少于100个 → 英文年报，不判乱码

    # 乱码表格提取：关键词扫描优先 + 页码范围兜底
    # 每个section含中文关键词（A股/中文年报用）和英文关键词（港股/英文年报用）
    TABLE_PAGE_RANGES = {
        'rd_spending':         {'keywords_cn': ['研发投入合计', '研发费用', '研发人员'],          'keywords_en': ['R&D expenses', 'research and development', 'R&D'],                   'pages': (100, 145), 'pct': 35},
        'production_sales':    {'keywords_cn': ['产销量情况', '主要产品', '主营业务'],           'keywords_en': ['production volume', 'sales volume', 'output and sales'],          'pages': (15, 35),   'pct': 35},
        'capacity':            {'keywords_cn': ['产能状况', '设计产能', '产能利用率'],           'keywords_en': ['production capacity', 'annual production', 'designed capacity'],  'pages': (175, 200), 'pct': 35},
        'top10_shareholders':  {'keywords_cn': ['前十名股东', '股东总数', '前10名股东'],        'keywords_en': ['Substantial Shareholders', 'Shareholders', 'share capital'],       'pages': (90, 125),  'pct': 35},
        'dividend':            {'keywords_cn': ['利润分配', '资本公积金转增', '分红预案'],       'keywords_en': ['dividend', 'final dividend', 'Dividend'],                           'pages': (45, 65),   'pct': 30},
    }

    # 乱码章节（需要表格fallback）
    TABLE_FALLBACK_SECTIONS = {'rd_spending', 'production_sales',
                                'capacity', 'top10_shareholders', 'dividend'}
    
    # ============================================================
    # 中文年报章节定义（A股、中文年报）
    # ============================================================
    SECTIONS_CN = {
        'audit': {
            'name': '审计意见',
            'starts': ['审计意见'],
            'ends': ['二、财务报表', '合并资产负债表', '形成审计意见的基础'],
            'max_chars': 8000,
            'description': '审计机构/意见类型/关键审计事项'
        },
        'dividend': {
            'name': '利润分配方案',
            'starts': ['利润分配及资本公积金转增股本预案'],
            'ends': ['(二)现金分红政策的专项说明', '最近三个会计年度'],
            'max_chars': 3000,
            'description': '每股派息/分红率/送转股'
        },
        'financial_key_data': {
            'name': '主要会计数据',
            'starts': ['主要会计数据', '本报告期主要会计数据'],
            'ends': ['主要财务指标', '本报告期主要财务指标', '非经常性损益'],
            'max_chars': 8000,
            'description': '营收/净利/扣非净利/现金流/ROE/资产负债率等关键数据'
        },
        'balance_sheet_key': {
            'name': '资产负债表关键数据',
            'starts': ['资产负债表'],
            'ends': ['利润表', '现金流量表', '所有者权益变动表'],
            'max_chars': 5000,
            'description': '总资产/总负债/资产负债率'
        },
        'top5_customers': {
            'name': '前五名客户',
            'starts': ['前五名客户销售额'],
            'ends': ['前五名供应商采购额', '报告期内向单个客户的销售比例'],
            'max_chars': 5000,
            'description': '客户集中度/关联销售'
        },
        'top5_suppliers': {
            'name': '前五名供应商',
            'starts': ['前五名供应商采购额'],
            'ends': ['报告期内向单个供应商的采购比例', '研发投入', '前五名客户'],
            'max_chars': 8000,
            'description': '供应商名称/采购额/占比/关联关系（重点：关联采购需标注）'
        },
        'actual_controller': {
            'name': '实际控制人',
            'starts': ['实际控制人'],
            'ends': ['不存在实际控制人', '控股股东、实际控制人'],
            'max_chars': 5000,
            'description': '控制权结构/一致行动人'
        },
        'top10_shareholders': {
            'name': '前十名股东',
            'starts': ['前十名股东、'],
            'ends': ['前十名流通股东', '前十名有限售条件'],
            'max_chars': 8000,
            'description': '股权结构/机构持仓'
        },
        'contingent': {
            'name': '或有事项',
            'starts': ['资产负债表日存在的重要或有事项'],
            'ends': ['其他资产负债表日后事项', '资产负债表日后事项'],
            'max_chars': 3000,
            'description': '担保/承诺/未决诉讼'
        },
        'post_events': {
            'name': '资产负债表日后事项',
            'starts': ['资产负债表日后事项'],
            'ends': ['销售退回', '其他资产负债表日后事项'],
            'max_chars': 5000,
            'description': '利润分配/重大调整/新发事项'
        },
        'litigation': {
            'name': '重大诉讼仲裁',
            'starts': ['重大诉讼', '重大诉讼、仲裁事项'],
            'ends': ['上市公司及其董事', '涉嫌违法违规'],
            'max_chars': 5000,
            'description': '重大诉讼/仲裁案件'
        },
        'litigation_detail': {
            'name': '诉讼仲裁详情与金额',
            'starts': ['重大诉讼', '重大诉讼、仲裁事项', '诉讼事项', '仲裁事项'],
            'ends': ['上市公司及其董事', '涉嫌违法违规', '或有事项'],
            'max_chars': 10000,
            'description': '诉讼/仲裁案件原告被告/案号/金额/法院/进展'
        },
        'rd_spending': {
            'name': '研发投入',
            'starts': ['研发投入合计', '(1).研发投入情况表'],
            'ends': ['(2).研发人员情况表', '情况说明'],
            'max_chars': 5000,
            'description': '费用化/资本化比例/研发人员'
        },
        'production_sales': {
            'name': '产销量明细',
            'starts': ['产销量情况分析表'],
            'ends': ['重大采购合同', '成本分析表'],
            'max_chars': 5000,
            'description': '产量/销量/库存/产销率'
        },
        'capacity': {
            'name': '产能状况',
            'starts': ['产能状况'],
            'ends': ['在建产能', '产能计算标准'],
            'max_chars': 5000,
            'description': '工厂/设计产能/利用率'
        },
        'subsidiaries': {
            'name': '主要控股参股公司',
            'starts': ['主要控股参股公司分析'],
            'ends': ['公司控制的结构化主体', '报告期内取得和处置子公司'],
            'max_chars': 8000,
            'description': '子公司财务/新设子公司'
        },
        'guarantee': {
            'name': '担保情况',
            'starts': ['担保情况'],
            'ends': ['非标准意见审计报告', '公司对会计政策'],
            'max_chars': 3000,
            'description': '对外担保/互保'
        },
        'cip': {
            'name': '在建工程',
            'starts': ['重要在建工程项目本期变动情况'],
            'ends': ['本期计提在建工程减值准备', '工程累计投入'],
            'max_chars': 5000,
            'description': '项目预算/进度/资金来源'
        },
        'goodwill': {
            'name': '商誉',
            'starts': ['商誉账面原值'],
            'ends': ['商誉减值准备', '(2).'],
            'max_chars': 3000,
            'description': '商誉形成/减值'
        },
        'lt_equity': {
            'name': '长期股权投资',
            'starts': ['重要的合营企业或联营企业'],
            'ends': ['重要合营企业的主要财务信息'],
            'max_chars': 5000,
            'description': '联营/合营企业明细'
        },
        'gov_subsidy': {
            'name': '政府补助',
            'starts': ['计入当期损益的政府补助'],
            'ends': ['非金融企业持有金融资产', '十二、与金融工具'],
            'max_chars': 3000,
            'description': '补助金额/性质'
        },
        'new_subsidiaries': {
            'name': '新设/处置子公司',
            'starts': ['报告期内取得和处置子公司'],
            'ends': ['处置子公司情况详见', '其他说明'],
            'max_chars': 5000,
            'description': '新设公司/新赛道布局'
        },
        'auditor_change': {
            'name': '会计师事务所变更',
            'starts': ['聘任、解聘会计师事务所'],
            'ends': ['面临退市风险', '破产重整'],
            'max_chars': 5000,
            'description': '换所原因/审计费用'
        },
    }

    # ============================================================
    # 英文年报章节定义（港股、美股、境外上市公司）
    # 来源：腾讯控股(00700) 2025年报全文关键词分析
    # 页码基于腾讯282页年报，其他英文年报可能略有差异
    # ============================================================
    SECTIONS_EN = {
        'audit': {
            'name': '审计意见',
            'starts': ['independent auditor'],       # P129
            'ends': ['Consolidated Income Statement', 'Consolidated Balance Sheet',
                     'Consolidated Statement of', 'Report on'],
            'max_chars': 10000,
            'description': "Auditor's name/opinion/type (腾讯: PWC普华永道)"
        },
        'dividend': {
            'name': '利润分配方案',
            'starts': ['final dividend'],            # P7Chairman's/P65
            'ends': ['Operations', 'Business Review', 'Management Discussion'],
            'max_chars': 5000,
            'description': 'Dividend per share/HKD rate (腾讯: HKD5.30)'
        },
        'top5_customers': {
            'name': '前五名客户',
            'starts': ['MAJOR CUSTOMERS AND SUPPLIERS', 'MAJOR CUSTOMERS AND'],  # P15 P266
            'ends': ['NOTE', 'SEGMENT INFORMATION', 'DIRECTORS REPORT', 'REPORT OF THE DIRECTORS'],
            'max_chars': 5000,
            'description': 'Customer concentration/related sales (腾讯: 第一大3.4%/前五6.5%)'
        },
        'top5_suppliers': {
            'name': '前五名供应商',
            'starts': ['FIVE LARGEST SUPPLIERS', 'five largest suppliers', 'MAJOR SUPPLIERS'],
            'ends': ['DIRECTORS', 'NOTE', 'SEGMENT', 'REPORT'],
            'max_chars': 5000,
            'description': 'Supplier concentration/related purchases (腾讯: 第一大4.4%/前五18.8%)'
        },
        'actual_controller': {
            'name': '实际控制人',
            'starts': ['Substantial Shareholders', 'Controlling Shareholder', 'Ultimate Beneficial'],
            'ends': ['Directors', 'Board of Directors', 'Chief Executive'],
            'max_chars': 5000,
            'description': 'Control structure/beneficial ownership'
        },
        'top10_shareholders': {
            'name': '前十名股东',
            'starts': ['Substantial Shareholders', 'Shareholdings', 'SHAREHOLDERS'],  # P79
            'ends': ['Connected Transaction', 'Related Party', 'Corporate Governance'],
            'max_chars': 10000,
            'description': 'Equity structure/top holders (腾讯: MIH/Naspers/Prosus)'
        },
        'contingent': {
            'name': '或有事项',
            'starts': ['Contingent'],                # P145 (near Goodwill)
            'ends': ['Commitments', 'Capital Commitment', 'Subsequent Event'],
            'max_chars': 5000,
            'description': 'Litigation/commitments/guarantees'
        },
        'post_events': {
            'name': '资产负债表日后事项',
            'starts': ['Subsequent Event', 'Event after the reporting period'],
            'ends': ['Contingent', 'Commitments', 'Note'],
            'max_chars': 5000,
            'description': 'Post-balance sheet events/new issuance'
        },
        'litigation': {
            'name': '重大诉讼仲裁',
            'starts': ['Litigation', 'Legal Proceedings', 'lawsuit'],
            'ends': ['Note', 'Contingent', 'Director'],
            'max_chars': 5000,
            'description': 'Major lawsuits/arbitration cases'
        },
        'rd_spending': {
            'name': '研发投入',
            'starts': ['R&D expenses', 'research and development', 'Research and development'],  # P11
            'ends': ['Other Income', 'Administrative Expense', 'Selling Expense'],
            'max_chars': 5000,
            'description': 'R&D expense amount/capitalisation ratio'
        },
        'production_sales': {
            'name': '产销量明细',
            'starts': ['production volume', 'sales volume', 'output and sales'],
            'ends': ['Research', 'R&D', 'cost analysis'],
            'max_chars': 5000,
            'description': 'Production/sales/inventory/yield rate'
        },
        'capacity': {
            'name': '产能状况',
            'starts': ['production capacity', 'annual production', 'designed capacity'],
            'ends': ['Construction in Progress', 'CIP', 'Capital expenditure'],
            'max_chars': 5000,
            'description': 'Factory/design capacity/utilisation rate'
        },
        'related_party': {
            'name': '关联交易',
            'starts': ['Related party transaction', 'related party transactions', 'Related party'],  # P266
            'ends': ['Auditor', 'Balance Sheet', 'Cash Flow', 'Note '],
            'max_chars': 10000,
            'description': 'Related party transactions/connected transactions'
        },
        'subsidiaries': {
            'name': '主要控股参股公司',
            'starts': ['SUBSIDIARIES', 'Principal subsidiaries', 'subsidiaries of the Company', 'subsidiary'],  # P28附近
            'ends': ['Associate', 'Joint Venture', 'Investments', 'associate', 'ASSOCIATE'],
            'max_chars': 20000,
            'description': 'Subsidiary financials/new subsidiaries'
        },
        'guarantee': {
            'name': '担保情况',
            'starts': ['Guarantee', 'financial guarantee', ' pledge'],
            'ends': ['Contingent', 'Litigation', 'Commitment'],
            'max_chars': 5000,
            'description': 'External guarantees/mutual guarantees'
        },
        'cip': {
            'name': '在建工程',
            'starts': ['Capital commitments', 'Construction in progress', 'CIP'],
            'ends': ['Intangible asset', 'Goodwill', 'commitment'],
            'max_chars': 5000,
            'description': 'Project budget/progress/capital source'
        },
        'goodwill': {
            'name': '商誉',
            'starts': ['Goodwill'],                  # P145
            'ends': ['Intangible asset', 'Impairment', 'Contingent'],
            'max_chars': 5000,
            'description': 'Goodwill formation/impairment test'
        },
        'lt_equity': {
            'name': '长期股权投资',
            'starts': ['Associate', 'Joint venture', 'Associates and joint ventures'],  # P266
            'ends': ['Current asset', 'Cash', 'Related party'],
            'max_chars': 5000,
            'description': 'Associate/joint venture details'
        },
        'gov_subsidy': {
            'name': '政府补助',
            'starts': ['Government grant', 'subsidy', 'tax rebate'],
            'ends': ['Other income', 'R&D', 'Finance cost'],
            'max_chars': 5000,
            'description': 'Subsidy amount/nature'
        },
        'new_subsidiaries': {
            'name': '新设/处置子公司',
            'starts': ['Acquisition', 'Disposal', 'subsidiary acquired or disposed'],
            'ends': ['Note', 'Financial statement', 'Auditor'],
            'max_chars': 5000,
            'description': 'New subsidiaries/disposals'
        },
        'auditor_change': {
            'name': '会计师事务所变更',
            'starts': ['Auditor', 'appointment of auditor', 'resignation of auditor'],
            'ends': ['Going concern', 'Disclaimer', 'Qualified opinion'],
            'max_chars': 5000,
            'description': 'Auditor change reason/fees'
        },
    }

    # 外部调用统一用 SECTIONS（运行时由 __init__ 决定语言）
    # 默认中文，无PDF路径时CLI也不调用 extract_all()，故安全
    SECTIONS = SECTIONS_CN
    
    def __init__(self, pdf_path=None, text_path=None):
        """
        初始化提取器（语言自动检测）

        Args:
            pdf_path: PDF文件路径（自动提取全文）
            text_path: 已提取的全文txt路径（跳过PDF解析）

        语言检测逻辑：
            1. 从PDF前5页提取文本，统计中文字符数
            2. 中文字符>=100 → 中文年报 → 使用SECTIONS_CN
            3. 中文字符<100  → 英文年报 → 使用SECTIONS_EN
            4. 乱码判断：中文年报用ASCII>85%，英文年报用ASCII>98%
              （英文年报天然ASCII>95%，不能仅凭ASCII占比判乱码）
        """
        self.text = ''
        self.doc = None
        self.lang = None  # 'cn' or 'en'
        
        if not _HAS_FITZ:
            self.text = '[PyMuPDF not installed - PDF extraction disabled]'
            return

        # ── 步骤1：打开PDF并检测语言 ──────────────────────────
        pdf_to_open = None
        if pdf_path and os.path.exists(pdf_path):
            pdf_to_open = pdf_path
        elif text_path and os.path.exists(text_path):
            pdf_dir = os.path.dirname(text_path)
            for cand in ['annual_report.pdf', 'report.pdf', '2025_annual_report.pdf']:
                cand_pdf = os.path.join(pdf_dir, cand)
                if os.path.exists(cand_pdf):
                    pdf_to_open = cand_pdf
                    break

        if pdf_to_open:
            self.doc = fitz.open(pdf_to_open)
            # 语言检测：从前5页统计中文字符数
            cn_chars = 0
            for pn in range(min(5, len(self.doc))):
                page_text = self.doc[pn].get_text('text')
                cn_chars += sum(1 for c in page_text if 0x4E00 <= ord(c) <= 0x9FFF)
            self.lang = 'cn' if cn_chars >= 100 else 'en'
            # 选择章节集
            AnnualReportExtractor.SECTIONS = (
                AnnualReportExtractor.SECTIONS_CN
                if self.lang == 'cn'
                else AnnualReportExtractor.SECTIONS_EN
            )
        elif text_path and os.path.exists(text_path):
            with open(text_path, 'r', encoding='utf-8') as f:
                raw = f.read()
            cn_chars = sum(1 for c in raw if 0x4E00 <= ord(c) <= 0x9FFF)
            self.lang = 'cn' if cn_chars >= 100 else 'en'
            AnnualReportExtractor.SECTIONS = (
                AnnualReportExtractor.SECTIONS_CN
                if self.lang == 'cn'
                else AnnualReportExtractor.SECTIONS_EN
            )
            if not self._is_garbled(raw):
                self.text = raw
        else:
            AnnualReportExtractor.SECTIONS = AnnualReportExtractor.SECTIONS_CN  # 默认中文

        # ── 步骤2：提取全文（仅当text为空时从PDF提取）────────────
        if not self.text and pdf_to_open:
            self.text = self._extract_text(pdf_to_open)
            # 英文年报：文本可直接使用（PyMuPDF英文提取正常），不触发乱码检测
            # 中文年报：保留原有乱码检测（ASCII>85%→清空→表格fallback）
            if self.lang == 'cn' and self._is_garbled(self.text):
                self.text = ''

        # ── 步骤3：英文年报建立搜索索引（大写化，加速匹配）───────
        # PyMuPDF提取的英文年报标题通常全大写，搜索前先upper()化
        self._text_upper = self.text.upper() if self.text else ''

    def _is_garbled(self, text):
        """
        判定文本是否乱码

        策略（双重保险）：
          1. CJK占比 <0.1% 且 ASCII>98% → 英文年报 → 保留文本
          2. CJK占比 >=0.1% → 有一定中文 → 按ASCII占比判断（>85%为乱码）
          3. CJK=0（纯英文）→ 不触发乱码

        为什么不用绝对CJK数量（<100）？
          因为腾讯英文年报全文含~600个CJK字符（如公司名"腾讯"、页脚中文），
          远超过100，但CJK/全文=0.1%，实际是纯英文年报，不应判为乱码。
        """
        if not text:
            return True
        total = len(text)
        ascii_cnt = sum(1 for c in text if ord(c) < 128)
        cn_cnt = sum(1 for c in text if 0x4E00 <= ord(c) <= 0x9FFF)
        ascii_pct = ascii_cnt / total * 100
        cn_ratio = cn_cnt / total

        # 条件1：CJK占比极低（<0.1%）→ 英文年报，不判乱码
        if cn_ratio < 0.001:
            return False
        # 条件2：CJK占比正常 → 有中文内容，按ASCII占比判断
        return ascii_pct > self.GARBLE_ASCII_PCT

    def _find_pages_with_keyword(self, keywords, page_range=None, max_pages=8):
        """在PDF页中搜索关键词，返回匹配的页码列表"""
        if not self.doc:
            return []
        results = []
        total = len(self.doc)
        start = page_range[0] - 1 if page_range else 0
        end = min(total, page_range[1]) if page_range else total
        for kw in keywords:
            for pn in range(start, end):
                if any(pn + 1 == r[0] for r in results):
                    continue
                text = self.doc[pn].get_text('text')
                if kw in text:
                    results.append((pn + 1, kw))
                    if len(results) >= max_pages:
                        break
            if len(results) >= max_pages:
                break
        return results

    def _get_table_pages(self, page_range, min_pct=35, top_n=5):
        """找出page_range中高数字密度的页面"""
        if not self.doc:
            return []
        results = []
        total_pages = len(self.doc)
        for pn in range(max(0, page_range[0]-1), min(total_pages, page_range[1])):
            page = self.doc[pn]
            text = page.get_text('text')
            if not text.strip():
                continue
            num_ratio = sum(1 for c in text
                           if c.isdigit() or c in '.,%-+()') / max(len(text), 1) * 100
            if num_ratio >= min_pct:
                results.append((pn+1, round(num_ratio, 1)))
        results.sort(key=lambda x: -x[1])
        return results[:top_n]

    def _extract_tables_from_pages(self, page_nums, max_rows=25):
        """从指定页提取表格，返回markdown格式"""
        if not self.doc:
            return ''
        lines = []
        for pn in page_nums:
            page = self.doc[pn-1]
            for tbl in page.find_tables():
                data = tbl.extract()
                if not data or len(data) < 2:
                    continue
                merged = self._merge_span_rows(data)
                col_n = max(len(r) for r in merged)
                sep = '|' + '|'.join(['---'] * col_n) + '|'
                hdr = '|' + '|'.join(
                    str(merged[0][j]).strip() if j < len(merged[0]) else ''
                    for j in range(col_n)) + '|'
                lines.append(f'**第{pn}页**')
                lines.append(hdr)
                lines.append(sep)
                for row in merged[1:min(len(merged), max_rows)]:
                    cells = '|' + '|'.join(
                        str(row[j]).strip() if j < len(row) else ''
                        for j in range(col_n)) + '|'
                    lines.append(cells)
                lines.append('')
        return '\n'.join(lines)

    def _merge_span_rows(self, data):
        """合并跨列占位符行（-- 或空）"""
        if not data:
            return data
        merged = [list(data[0])]
        for row in data[1:]:
            first = str(row[0]).strip() if row else ''
            if len(first) < 3 or first in ('--', '-'):
                for j, val in enumerate(row):
                    if j < len(merged[-1]) and str(val).strip():
                        merged[-1][j] = str(merged[-1][j]).strip() + ' ' + str(val).strip()
                    elif str(val).strip():
                        merged[-1].append(str(val).strip())
            else:
                merged.append(list(row))
        return merged

    def _extract_fallback_table(self, section_key):
        """乱码章节（表格页）：关键词扫描 → 数字密度排序 → 表格提取"""
        cfg = self.TABLE_PAGE_RANGES.get(section_key)
        if not cfg:
            return '[无表格fallback配置]'

        # 自动选择语言对应的关键词
        kw_key = f'keywords_{self.lang}' if self.lang else 'keywords_cn'
        keywords = cfg.get(kw_key, cfg.get('keywords_cn', []))

        # Step 1: 关键词扫描
        kw_pages = self._find_pages_with_keyword(keywords, max_pages=12)

        # Step 2: 为关键词命中页计算数字密度
        scored = []
        seen = set()
        for pn, kw in kw_pages:
            if pn in seen:
                continue
            text = self.doc[pn - 1].get_text('text')
            num_ratio = sum(1 for c in text if c.isdigit() or c in '.,%-+()') \
                       / max(len(text), 1) * 100
            scored.append((pn, kw, round(num_ratio, 1)))
            seen.add(pn)

        # Step 3: 兜底：页码范围数字密度扫描（补充页）
        fallback = self._get_table_pages(cfg['pages'], cfg['pct'], top_n=5)
        for pn, ratio in fallback:
            if pn not in seen:
                scored.append((pn, '数字密度', ratio))
                seen.add(pn)

        if not scored:
            return f'[关键词 {keywords} 未在PDF中找到，数字密度扫描也无结果]'

        # Step 4: 数字密度排序，取前6页
        scored.sort(key=lambda x: -x[2])
        top_pages = [p[0] for p in scored[:6]]

        result = self._extract_tables_from_pages(top_pages)
        return result if result else '[表格提取无结果]'

    def _extract_text(self, pdf_path):
        """用PyMuPDF提取PDF全文"""
        
        doc = fitz.open(pdf_path)
        text = ''
        for i, page in enumerate(doc):
            text += f'--- 第{i+1}页 ---\n'
            text += page.get_text('text')
            text += '\n'
        doc.close()
        return text
    
    def _extract_between(self, start_marker, end_markers, max_chars=5000):
        """
        从start_marker到第一个end_marker之间的内容

        英文年报特殊处理：PyMuPDF提取的英文PDF标题通常全大写，
        搜索时对英文年报（self.lang=='en'）使用大写匹配。
        原文 self.text 保持不变，返回内容也从 self.text 切片。
        """
        # 搜索用：大写文本 + 大写关键词（英文年报）或原样（中文年报）
        search_text = self._text_upper if self.lang == 'en' else self.text
        sm = start_marker.upper() if self.lang == 'en' else start_marker
        ems = [e.upper() for e in end_markers] if self.lang == 'en' else end_markers

        idx = search_text.find(sm)
        if idx < 0:
            return f"[未找到: {start_marker}]"

        end_idx = len(self.text)  # 原文切片用字符数
        for em in ems:
            eidx = search_text.find(em, idx + len(sm))
            if 0 <= eidx < end_idx:
                end_idx = eidx

        chunk = self.text[idx:end_idx]
        if len(chunk) > max_chars:
            chunk = chunk[:max_chars] + "\n...[截断]..."
        return chunk
    
    def extract_section(self, section_key):
        """提取单个章节，支持乱码表格fallback"""
        if section_key not in self.SECTIONS:
            return f"[未知章节: {section_key}]"

        cfg = self.SECTIONS[section_key]
        text_result = self._extract_between(
            cfg['starts'][0], cfg['ends'], cfg['max_chars']
        )

        # 乱码章节：文本提取失败时fallback到表格
        if (section_key in self.TABLE_FALLBACK_SECTIONS
                and self.doc is not None
                and (text_result.startswith('[未找到') or not text_result.strip())):
            table_result = self._extract_fallback_table(section_key)
            return (f"⚠️ 文本乱码，已从PDF表格提取\n\n"
                    + table_result)

        return text_result
    
    def search_keyword(self, keyword, context_chars=200, max_results=20):
        """全文搜索关键词，返回带上下文的匹配"""
        pattern = re.escape(keyword) + r'[^\n]{0,' + str(context_chars) + '}'
        matches = list(re.finditer(pattern, self.text))
        
        results = []
        for m in matches[:max_results]:
            start = max(0, m.start() - 50)
            end = min(len(self.text), m.end() + 50)
            snippet = self.text[start:end].replace('\n', ' ')
            results.append(f"...{snippet}...")
        
        return results
    
    def extract_financial_metrics(self):
        """
        从年报PDF提取关键财务指标
        提取：扣非净利润、资产负债率、营收、净利等
        
        Returns:
            dict: {'扣非净利润': 'xx亿元', '资产负债率': 'xx%', ...}
        """
        metrics = {}
        
        # 提取扣非净利润（扣除非经常性损益的净利润）
        deduct_patterns = [
            r'扣除非经常性损益[的]?净利润[^\d]*([\d,.]+)\s*[亿万元]',
            r'归属于上市公司股东的扣除非经常性损益的净利润[^\d]*([\d,.]+)\s*[亿万元]',
            r'扣非净利润[^\d]*([\d,.]+)\s*[亿万元]',
            r'扣除非经常性损益后的净利润[^\d]*([\d,.]+)\s*[亿万元]',
        ]
        for pat in deduct_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['扣非净利润'] = m.group(1)
                break
        
        # 提取资产负债率
        debt_ratio_patterns = [
            r'资产负债率[^\d]*([\d,.]+)\s*%',
            r'负债率为[^\d]*([\d,.]+)\s*%',
            r'资产负债比率[^\d]*([\d,.]+)\s*%',
        ]
        for pat in debt_ratio_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['资产负债率'] = m.group(1) + '%'
                break
        
        # 提取营业收入
        revenue_patterns = [
            r'营业收入[^\d]*([\d,.]+)\s*[亿万元]',
            r'营业总收入[^\d]*([\d,.]+)\s*[亿万元]',
        ]
        for pat in revenue_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['营业收入'] = m.group(1)
                break
        
        # 提取净利润
        net_profit_patterns = [
            r'归属于上市公司股东的净利润[^\d]*([\d,.]+)\s*[亿万元]',
            r'净利润[^\d]*([\d,.]+)\s*[亿万元]',
        ]
        for pat in net_profit_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['净利润'] = m.group(1)
                break
        
        # 提取总资产
        assets_patterns = [
            r'资产总计[^\d]*([\d,.]+)\s*[亿万元]',
            r'总资产[^\d]*([\d,.]+)\s*[亿万元]',
        ]
        for pat in assets_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['总资产'] = m.group(1)
                break
        
        # 提取总负债
        liabilities_patterns = [
            r'负债合计[^\d]*([\d,.]+)\s*[亿万元]',
            r'总负债[^\d]*([\d,.]+)\s*[亿万元]',
        ]
        for pat in liabilities_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['总负债'] = m.group(1)
                break
        
        # 提取加权ROE
        roe_patterns = [
            r'加权平均净资产收益率[^\d]*([\d,.]+)\s*%',
            r'加权净资产收益率[^\d]*([\d,.]+)\s*%',
            r'净资产收益率[^\d]*([\d,.]+)\s*%',
        ]
        for pat in roe_patterns:
            m = re.search(pat, self.text)
            if m:
                metrics['加权ROE'] = m.group(1) + '%'
                break
        
        return metrics
    
    def extract_all(self):
        """提取所有20个章节"""
        results = {}
        for key, cfg in self.SECTIONS.items():
            results[key] = {
                'name': cfg['name'],
                'description': cfg['description'],
                'content': self.extract_section(key)
            }
        return results
    
    def extract_to_file(self, output_path):
        """提取所有章节到Markdown文件"""
        sections = self.extract_all()
        lang_tag = '🇨🇳 中文年报' if self.lang == 'cn' else '🇭🇰 英文年报（港股）'

        lines = [f'# 年报PDF关键章节提取  {lang_tag}\n']
        lines.append(f'总页数估计：约{self.text.count("--- 第")}页')
        lines.append(f'文本大小：{len(self.text):,}字符')
        lines.append(f'语言检测：{self.lang}\n')
        lines.append('---\n')
        
        for key, data in sections.items():
            lines.append(f"## {data['name']}（{key}）\n")
            lines.append(f"> {data['description']}\n")
            lines.append(data['content'])
            lines.append('\n---\n')
        
        content = '\n'.join(lines)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return output_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='年报PDF关键章节提取')
    parser.add_argument('--pdf', help='PDF文件路径')
    parser.add_argument('--text', help='已提取的全文txt路径')
    parser.add_argument('--output', '-o', default='annual_extract_output.md', help='输出文件路径')
    parser.add_argument('--section', '-s', help='只提取指定章节（如audit,dividend）')
    parser.add_argument('--search', help='全文搜索关键词')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有可提取章节')
    
    args = parser.parse_args()
    
    if args.list:
        print("可提取的20个章节：\n")
        for key, cfg in AnnualReportExtractor.SECTIONS.items():
            print(f"  {key:20s} {cfg['name']:15s} - {cfg['description']}")
        sys.exit(0)
    
    extractor = AnnualReportExtractor(pdf_path=args.pdf, text_path=args.text)
    
    if not extractor.text:
        print("错误：请指定 --pdf 或 --text 参数")
        sys.exit(1)
    
    if args.search:
        results = extractor.search_keyword(args.search)
        print(f"搜索 '{args.search}'：找到 {len(results)} 条结果\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. {r}\n")
    elif args.section:
        content = extractor.extract_section(args.section)
        print(f"=== {args.section} ===\n")
        print(content)
    else:
        path = extractor.extract_to_file(args.output)
        print(f"提取完成: {path}")
        print(f"文本大小: {len(extractor.text):,} 字符")
