# -*- coding: utf-8 -*-
"""
us_financial_extractor.py - 从10-K HTML提取美股财务数据
"""
import os
import re
import json
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# 常见财务科目映射（10-K HTML标签多样化，需多模式匹配）
FINANCIAL_PATTERNS = {
    'revenue': [
        r'Revenue[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Total\s+net\s+sales[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Net\s+revenues[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Total\s+revenue[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
    ],
    'net_income': [
        r'Net\s+income[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Net\s+earnings[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Net\s+profit[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
    ],
    'total_assets': [
        r'Total\s+assets[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Total\s+Assets[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
    ],
    'total_equity': [
        r"Stockholders['']?\s+equity[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)",
        r'Total\s+equity[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
    ],
    'cash': [
        r'Cash\s+and\s+cash\s+equivalents[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
        r'Cash[^<]*</td>\s*<td[^>]*>\s*\$?([\d,]+)',
    ],
    'eps_basic': [
        r'Basic\s+earnings\s+per\s+share[^<]*</td>\s*<td[^>]*>\s*\$?([\d.]+)',
        r'Earnings\s+per\s+share[^<]*</td>\s*<td[^>]*>\s*\$?([\d.]+)',
    ],
    'shares_outstanding': [
        r'Shares\s+outstanding[^<]*</td>\s*<td[^>]*>\s*([\d,]+)',
        r'Weighted-average\s+shares\s+outstanding[^<]*</td>\s*<td[^>]*>\s*([\d,]+)',
    ],
}

# 公司治理关键词
GOVERNANCE_KEYWORDS = {
    'board_independence': [
        r'(\d+)\s+independent\s+director',
        r'(\d+)\s+of\s+our\s+(\d+)\s+director[s]?\s+are\s+independent',
    ],
    'audit_committee': [
        r'Audit\s+Committee',
        r'audit\s+committee',
    ],
    'compensation_committee': [
        r'Compensation\s+Committee',
    ],
    'nomination_committee': [
        r'Nominating\s+Committee',
        r'Nomination\s+Committee',
    ],
    'ceo_chairman_separate': [
        r'Chairman\s+of\s+the\s+Board.*CEO',
        r'Chief\s+Executive\s+Officer.*Chairman',
    ],
}


def extract_number(text: str, patterns: List[str]) -> Optional[float]:
    """从HTML文本中提取数字"""
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        if matches:
            # 取第一个匹配
            val = matches[0] if isinstance(matches[0], str) else matches[0][0]
            # 清理数字格式
            val = val.replace(',', '').replace('$', '').strip()
            try:
                return float(val)
            except:
                continue
    return None


def parse_us_10k_html(html_path: str) -> Dict:
    """
    解析美股10-K HTML文件，提取财务数据
    
    Returns:
        {
            'success': bool,
            'financials': {...},
            'governance': {...},
            'warnings': []
        }
    """
    result = {
        'success': False,
        'financials': {},
        'governance': {},
        'warnings': []
    }
    
    if not os.path.exists(html_path):
        result['warnings'].append(f'文件不存在: {html_path}')
        return result
    
    try:
        with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()
    except Exception as e:
        result['warnings'].append(f'读取文件失败: {e}')
        return result
    
    print(f"[INFO] 解析10-K HTML: {html_path} ({len(html)//1024}KB)")
    
    # 提取财务数据
    for key, patterns in FINANCIAL_PATTERNS.items():
        val = extract_number(html, patterns)
        if val is not None:
            result['financials'][key] = val
            print(f"[OK] {key}: {val:,.0f}")
        else:
            result['warnings'].append(f'未找到: {key}')
    
    # 提取治理信息
    for key, patterns in GOVERNANCE_KEYWORDS.items():
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                result['governance'][key] = matches
                print(f"[OK] {key}: {matches}")
                break
    
    # 尝试提取财报日期
    date_match = re.search(r'For\s+the\s+fiscal\s+year\s+ended\s+(\w+\s+\d+,\s+\d+)', html, re.IGNORECASE)
    if date_match:
        result['fiscal_year_end'] = date_match.group(1)
        print(f"[OK] 财年截止: {result['fiscal_year_end']}")
    
    # 提取公司名称
    company_match = re.search(r'<title>([^<]+)\s*-\s*10-K', html, re.IGNORECASE)
    if company_match:
        result['company_name'] = company_match.group(1).strip()
        print(f"[OK] 公司名称: {result['company_name']}")
    
    if result['financials'] or result['governance']:
        result['success'] = True
    
    return result


def extract_financial_table_from_html(html: str, table_keywords: List[str]) -> pd.DataFrame:
    """
    从HTML中提取财务报表表格
    
    Args:
        html: HTML文本
        table_keywords: 表格关键词（如 'CONSOLIDATED BALANCE SHEETS'）
    
    Returns:
        DataFrame或None
    """
    # 查找表格标题位置
    for keyword in table_keywords:
        idx = html.find(keyword)
        if idx < 0:
            continue
        
        # 从标题位置向后提取table标签
        table_start = html.find('<table', idx)
        if table_start < 0 or table_start > idx + 500:
            continue
        
        table_end = html.find('</table>', table_start)
        if table_end < 0:
            continue
        
        table_html = html[table_start:table_end+8]
        
        # 使用pandas解析HTML表格
        try:
            dfs = pd.read_html(f"<html><body>{table_html}</body></html>")
            if dfs:
                return dfs[0]
        except Exception as _sexc:
            record(__name__, 'extract_financial_table_from_html', _sexc, note='静默降级')
            pass
    
    return None


def calculate_us_governance_score(governance_data: Dict) -> int:
    """
    计算美股公司治理评分（简化版）
    
    评分维度：
    - 独立董事比例 (40分)
    - 委员会完整性 (30分)
    - CEO/董事长分设 (30分)
    """
    score = 0
    
    # 独立董事比例（假设从matches中提取）
    if 'board_independence' in governance_data:
        matches = governance_data['board_independence']
        if matches:
            # 尝试解析独立董事数量
            try:
                if len(matches[0]) >= 2:
                    independent = int(matches[0][0])
                    total = int(matches[0][1])
                    ratio = independent / total if total > 0 else 0
                    score += int(ratio * 40)
            except:
                score += 20  # 默认中等分
    
    # 委员会完整性
    committees = ['audit_committee', 'compensation_committee', 'nomination_committee']
    committee_count = sum(1 for c in committees if c in governance_data)
    score += committee_count * 10
    
    # CEO/董事长分设（如果在matches中出现"separate"关键词）
    if 'ceo_chairman_separate' in governance_data:
        score += 30
    
    return min(score, 100)


# ============================================
# 测试
# ============================================
if __name__ == '__main__':
    import sys
    
    # 查找已下载的10-K HTML
    test_files = [
        r"output/test_us/AAPL_2025_10K.html",
        r"output/600519_20260427/annual_report.pdf",
    ]
    
    for test_file in test_files:
        if os.path.exists(test_file):
            print("\n" + "=" * 60)
            print(f"测试文件: {test_file}")
            print("=" * 60)
            
            if test_file.endswith('.html'):
                result = parse_us_10k_html(test_file)
                print("\n结果:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
                
                if result.get('governance'):
                    score = calculate_us_governance_score(result['governance'])
                    print(f"\n治理评分: {score}/100")
            else:
                print("PDF文件，需要使用annual_extract.py处理")
    
    if not any(os.path.exists(f) for f in test_files):
        print("\n未找到测试文件，请先运行financial_pdf_downloader.py下载10-K")
