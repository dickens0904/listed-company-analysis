# -*- coding: utf-8 -*-
"""
websearch.py - 联网搜索模块
使用 web_fetch + Bing CN 搜索公告/新闻/研报

注意：web_search 工具被禁用，用 web_fetch + 搜索引擎替代
"""
import json
import re
from typing import List, Dict, Optional
from urllib.parse import quote

def search_bing(query: str, count: int = 10, filetype: str = None, site: str = None) -> List[Dict]:
    """
    通过 web_fetch 调用 Bing CN 搜索
    
    Args:
        query: 搜索关键词
        count: 返回结果数
        filetype: 文件类型过滤 (如 'pdf')
        site: 站点过滤 (如 'cninfo.com.cn')
    
    Returns:
        [{'title': str, 'url': str, 'snippet': str}, ...]
    
    Note:
        由于 web_fetch 是外部工具，此函数需要通过 run_tool('web_fetch') 调用
        本函数提供 URL 构造和结果解析逻辑
    """
    # 构造搜索URL
    search_query = query
    if filetype:
        search_query += f" filetype:{filetype}"
    if site:
        search_query += f" site:{site}"
    
    # Bing CN 搜索 URL
    bing_url = f"https://cn.bing.com/search?q={quote(search_query)}&count={count}"
    
    return {
        'url': bing_url,
        'method': 'web_fetch',
        'params': {
            'url': bing_url,
            'extractMode': 'markdown'
        }
    }


def search_cninfo_annual(stock_code: str, company_name: str = None) -> Dict:
    """
    构造巨潮资讯年报搜索请求
    
    Args:
        stock_code: 股票代码 (如 '002180')
        company_name: 公司名称 (如 '奔图科技')，可选
    
    Returns:
        构造好的请求参数
    """
    # CNINFO fulltext API
    # 关键发现：stock 参数不生效，必须用 searchkey！
    url = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
    
    # 优先用公司名搜索（更稳定），其次用股票代码
    searchkey = company_name if company_name else stock_code
    
    # 根据股票代码判断交易所
    if stock_code.startswith('6'):
        plate = 'sh'
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        plate = 'sz'
    elif stock_code.startswith('8') or stock_code.startswith('4'):
        plate = 'bj'
    else:
        plate = 'sz'

    params = {
        'url': url,
        'method': 'POST',
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.cninfo.com.cn/new/disclosure/stock',
            'Origin': 'https://www.cninfo.com.cn',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        'data': {
            'tabName': 'fulltext',
            'category': 'category_ndbg_szsh',  # 年报
            'plate': plate,
            'searchkey': searchkey,
            'seDate': '',
            'isHLtitle': 'true',
            'pageSize': '30',
        }
    }
    
    return params


def search_cninfo_periodic(stock_code: str, company_name: str = None,
                            report_type: str = 'semi_annual') -> Dict:
    """
    构造巨潮资讯半年报/季报搜索请求

    Args:
        stock_code: 股票代码
        company_name: 公司名称
        report_type: 'semi_annual' 或 'quarterly'

    Returns:
        构造好的请求参数
    """
    url = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'

    # 半年报/季报的分类码已失效，改用关键词搜索
    suffix_map = {
        'semi_annual': ' 半年度报告',
        'quarterly': ' 季度报告',
    }
    searchkey = (company_name if company_name else stock_code) + suffix_map.get(report_type, '')

    if stock_code.startswith('6'):
        plate = 'sh'
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        plate = 'sz'
    elif stock_code.startswith('8') or stock_code.startswith('4'):
        plate = 'bj'
    else:
        plate = 'sz'

    params = {
        'url': url,
        'method': 'POST',
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.cninfo.com.cn/new/disclosure/stock',
            'Origin': 'https://www.cninfo.com.cn',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        'data': {
            'tabName': 'fulltext',
            'category': '',  # 不用分类码
            'plate': plate,
            'searchkey': searchkey,
            'seDate': '',
            'isHLtitle': 'true',
            'pageSize': '30',
        }
    }

    return params


def parse_cninfo_response(json_data: dict) -> List[Dict]:
    """
    解析 CNINFO API 返回的年报列表
    
    Args:
        json_data: API 返回的 JSON 数据
    
    Returns:
        [{'title': str, 'date': str, 'pdf_url': str, 'announcement_id': str}, ...]
    """
    results = []
    announcements = json_data.get('announcements', [])
    
    for ann in announcements:
        title = ann.get('announcementTitle', '')
        adj_url = ann.get('adjunctUrl', '')
        
        if adj_url:
            results.append({
                'title': title,
                'date': ann.get('announcementTime', ''),
                'pdf_url': f"https://static.cninfo.com.cn/{adj_url}",
                'announcement_id': ann.get('announcementId', ''),
                'sec_code': ann.get('secCode', ''),
            })
    
    return results


def search_csrc_guidance(company_name: str) -> Dict:
    """
    构造证监会辅导报告搜索请求
    
    Args:
        company_name: 公司名称
    
    Returns:
        构造好的请求参数
    """
    # 证监会官网辅导报告搜索
    # 注意：PDF 内容需要 zlib 解压，纯文本提取较困难
    url = f"https://www.csrc.gov.cn/searchwebsite/search"
    
    params = {
        'url': url,
        'method': 'GET',
        'params': {
            'q': company_name,
            'channelid': '273901',  # 辅导公示栏目
        }
    }
    
    return params


def search_eastmoney_announcement(stock_code: str, announcement_type: str = '年报') -> Dict:
    """
    构造东方财富公告搜索请求
    
    Args:
        stock_code: 股票代码
        announcement_type: 公告类型
    
    Returns:
        构造好的请求参数
    """
    secid = f"0.{stock_code}" if stock_code.startswith('0') or stock_code.startswith('3') else f"1.{stock_code}"
    
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    
    params = {
        'url': url,
        'method': 'GET',
        'params': {
            'cb': 'jQuery',  # JSONP 回调
            'sr': '-1',
            'page_size': 30,
            'page_index': 1,
            'ann_type': 'SHA,SZA',  # 沪深A股
            'client_source': 'web',
            'f_node': 0,
            's_node': 0,
            'secid': secid,
        }
    }
    
    return params


def build_search_plan(stock_code: str, company_name: str = None) -> List[Dict]:
    """
    构建完整的搜索计划
    
    Args:
        stock_code: 股票代码
        company_name: 公司名称
    
    Returns:
        搜索任务列表
    """
    tasks = [
        {
            'name': '年报PDF',
            'description': '从巨潮资讯获取年报PDF链接',
            'search': search_cninfo_annual(stock_code, company_name),
            'parser': 'parse_cninfo_response',
        },
        {
            'name': '半年报PDF',
            'description': '从巨潮资讯获取半年报PDF链接',
            'search': search_cninfo_periodic(stock_code, company_name, report_type='semi_annual'),
            'parser': 'parse_cninfo_response',
        },
        {
            'name': '季报PDF',
            'description': '从巨潮资讯获取季报PDF链接',
            'search': search_cninfo_periodic(stock_code, company_name, report_type='quarterly'),
            'parser': 'parse_cninfo_response',
        },
        {
            'name': '公告列表',
            'description': '从东方财富获取公告列表',
            'search': search_eastmoney_announcement(stock_code),
            'parser': 'parse_eastmoney_announcements',
        },
    ]
    
    # 如果有公司名，追加证监会辅导报告搜索
    if company_name:
        tasks.append({
            'name': 'IPO辅导报告',
            'description': '从证监会获取IPO辅导进度',
            'search': search_csrc_guidance(company_name),
            'parser': 'parse_csrc_guidance',
        })
    
    return tasks


# 使用示例
if __name__ == '__main__':
    # 示例：构建搜索计划
    plan = build_search_plan('002180', '奔图科技')
    print(json.dumps(plan, ensure_ascii=False, indent=2))
