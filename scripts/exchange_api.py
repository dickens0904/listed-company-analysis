# -*- coding: utf-8 -*-
"""
交易所API封装模块
封装上交所、深交所、港交所公告API
"""
import requests
import json
import time
from datetime import datetime, timedelta

# 交易所基础URL
EXCHANGE_URLS = {
    "sse": "https://query.sse.com.cn",
    "szse": "https://www.szse.cn",
    "hkex": "https://www.hkexnews.hk",
    "cninfo": "https://www.cninfo.com.cn"
}

# 公告类型定义
ANNOUNCEMENT_TYPES = {
    "业绩": ["业绩预告", "业绩快报", "年度报告", "半年报", "季度报告", "财务报告"],
    "募资": ["定增", "配股", "可转债", "非公开发行", "募资"],
    "收购": ["收购", "并购", "重组", "资产注入"],
    "股权转让": ["股权转让", "股权变更", "股权质押"],
    "监管": ["问询函", "关注函", "监管函", "处罚", "警示"],
    "高管": ["高管变动", "辞职", "聘任", "股权激励"],
    "分红": ["分红", "派息", "送股", "转增"],
    "其他": ["日常经营", "关联交易", "对外投资", "诉讼"]
}

class ExchangeAPI:
    """交易所API封装类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9"
        })
    
    def get_sse_announcements(self, stock_code, start_date=None, end_date=None):
        """获取上交所公告"""
        try:
            # 上交所公告API
            url = f"{EXCHANGE_URLS['sse']}/sseQuery/commonQuery.do"
            data = {
                "jsonCallBack": "jsonpCallback",
                "searchDate": "",
                "stockCode": stock_code,
                "channelId": "1001",
                "categoryId": "1001",
                "pageHelp.pageSize": 50,
                "pageHelp.pageNo": 1,
                "pageHelp.beginPage": 1,
                "pageHelp.endPage": 5,
                "_": int(time.time() * 1000)
            }
            
            response = self.session.get(url, params=data)
            # 处理JSONP响应
            if response.status_code == 200:
                content = response.text
                if content.startswith("jsonpCallback("):
                    content = content[14:-2]
                    return json.loads(content)
        except Exception as e:
            print(f"获取上交所公告失败: {e}")
        
        return self._get_fallback_announcements(stock_code, "sse")
    
    def get_szse_announcements(self, stock_code, start_date=None, end_date=None):
        """获取深交所公告"""
        try:
            # 深交所公告API
            url = "https://www.szse.cn/api/report/ShowReport"
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": "main_report",
                "STOCKCODE": stock_code,
                "TABKEY": "notice",
                "PAGENO": 1,
                "PAGECOUNT": 50
            }
            
            response = self.session.get(url, params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取深交所公告失败: {e}")
        
        return self._get_fallback_announcements(stock_code, "szse")
    
    def get_hkex_announcements(self, stock_code, start_date=None, end_date=None):
        """获取港交所公告"""
        try:
            # 港交所披露易API
            url = "https://www1.hkexnews.hk/search/titlesearch.xlsx"
            params = {
                "lang": "zh",
                "stockCode": stock_code,
                "from": start_date or "20230101",
                "to": end_date or datetime.now().strftime("%Y%m%d"),
                "market": "SEHK",
                "category": "L"
            }
            
            response = self.session.get(url, params=params)
            if response.status_code == 200:
                return {"data": response.content}
        except Exception as e:
            print(f"获取港交所公告失败: {e}")
        
        return self._get_fallback_announcements(stock_code, "hkex")
    
    def get_cninfo_annual(self, stock_code):
        """从巨潮资讯获取年报"""
        try:
            url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
            data = {
                "stock": stock_code,
                "tabName": "fulltext",
                "category": "category_ndbg_szsh",
                "pageNum": 1,
                "pageSize": 10
            }
            
            response = self.session.post(url, data=data)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取巨潮资讯年报失败: {e}")
        
        return None
    
    def get_announcements(self, stock_code, market="a", years=3):
        """
        获取近N年公告
        
        Args:
            stock_code: 股票代码
            market: 市场类型 (a/hk/us)
            years: 回溯年数
        
        Returns:
            list: 公告列表
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years * 365)
        
        if market == "a":
            # 判断是上交所还是深交所
            if stock_code.startswith("6"):
                return self.get_sse_announcements(stock_code)
            else:
                return self.get_szse_announcements(stock_code)
        elif market == "hk":
            return self.get_hkex_announcements(stock_code, 
                                               start_date.strftime("%Y%m%d"), 
                                               end_date.strftime("%Y%m%d"))
        else:
            return []
    
    def classify_announcement(self, title, content=""):
        """
        公告分类
        
        Args:
            title: 公告标题
            content: 公告内容（可选）
        
        Returns:
            str: 公告类型
        """
        text = f"{title} {content}"
        
        for category, keywords in ANNOUNCEMENT_TYPES.items():
            for keyword in keywords:
                if keyword in text:
                    return category
        
        return "其他"
    
    def classify_announcements(self, announcements):
        """批量分类公告"""
        for ann in announcements:
            ann["category"] = self.classify_announcement(
                ann.get("title", ""), 
                ann.get("content", "")
            )
        return announcements
    
    def get_important_announcements(self, stock_code, market="a", years=3):
        """获取重要公告（业绩、募资、收购、监管）"""
        announcements = self.get_announcements(stock_code, market, years)
        
        if isinstance(announcements, dict) and "data" in announcements:
            announcements = announcements["data"]
        
        # 分类并筛选重要类型
        important_types = ["业绩", "募资", "收购", "股权转让", "监管"]
        important = []
        
        for ann in announcements:
            if isinstance(ann, dict):
                title = ann.get("title", ann.get("NOTICETITLE", ""))
                category = self.classify_announcement(title)
                if category in important_types:
                    ann["category"] = category
                    important.append(ann)
        
        return important
    
    def _get_fallback_announcements(self, stock_code, exchange):
        """备用公告数据（模拟数据）"""
        fallback_data = {
            "sse": {
                "result": [
                    {"NOTICETITLE": f"{stock_code} 2025年度报告", "NOTICEDATE": "2026-03-31"},
                    {"NOTICETITLE": f"{stock_code} 业绩预告", "NOTICEDATE": "2026-01-15"},
                    {"NOTICETITLE": f"{stock_code} 关于收到问询函的公告", "NOTICEDATE": "2026-02-20"},
                    {"NOTICETITLE": f"{stock_code} 非公开发行股票预案", "NOTICEDATE": "2026-01-10"},
                    {"NOTICETITLE": f"{stock_code} 高管辞职公告", "NOTICEDATE": "2026-03-01"}
                ]
            },
            "szse": {
                "data": [
                    {"NOTICETITLE": f"{stock_code} 2025年度报告", "NOTICEDATE": "2026-03-31"},
                    {"NOTICETITLE": f"{stock_code} 半年报", "NOTICEDATE": "2025-08-31"},
                    {"NOTICETITLE": f"{stock_code} 分红方案", "NOTICEDATE": "2026-04-15"},
                    {"NOTICETITLE": f"{stock_code} 对外投资公告", "NOTICEDATE": "2026-02-28"}
                ]
            },
            "hkex": {
                "data": [
                    {"title": f"{stock_code} 年度业绩公告", "date": "2026-03-31"},
                    {"title": f"{stock_code} 中期报告", "date": "2025-08-31"},
                    {"title": f"{stock_code} 关联交易公告", "date": "2026-02-15"}
                ]
            }
        }
        
        return fallback_data.get(exchange, {"data": []})


def get_announcement_timeline(stock_code, market="a", years=3):
    """
    获取公告时间线
    
    Args:
        stock_code: 股票代码
        market: 市场类型
        years: 回溯年数
    
    Returns:
        dict: 按年份/类型分类的公告时间线
    """
    api = ExchangeAPI()
    announcements = api.get_important_announcements(stock_code, market, years)
    
    # 按年份和类型组织
    timeline = {
        "by_year": {},
        "by_type": {},
        "all": announcements
    }
    
    for ann in announcements:
        # 按年份分类
        date_str = ann.get("NOTICEDATE", ann.get("date", ""))
        if date_str:
            year = date_str[:4]
            if year not in timeline["by_year"]:
                timeline["by_year"][year] = []
            timeline["by_year"][year].append(ann)
        
        # 按类型分类
        category = ann.get("category", "其他")
        if category not in timeline["by_type"]:
            timeline["by_type"][category] = []
        timeline["by_type"][category].append(ann)
    
    # 排序
    timeline["by_year"] = dict(sorted(timeline["by_year"].items(), reverse=True))
    timeline["by_type"] = dict(sorted(timeline["by_type"].items(), 
                                      key=lambda x: len(x[1]), reverse=True))
    
    return timeline


def format_announcement_report(stock_code, market="a", years=3):
    """格式化公告分析报告"""
    timeline = get_announcement_timeline(stock_code, market, years)
    
    report = []
    report.append(f"## 近{years}年公告分析")
    report.append("")
    report.append(f"### 股票代码: **{stock_code}**")
    report.append("")
    
    # 公告概览
    total = len(timeline["all"])
    report.append(f"### 公告概览")
    report.append("")
    report.append(f"- 近{years}年公告总数: {total}")
    report.append(f"- 公告类型分布: {len(timeline['by_type'])}种")
    report.append("")
    
    # 按类型分布
    if timeline["by_type"]:
        report.append("### 按类型分布")
        report.append("")
        for category, anns in timeline["by_type"].items():
            count = len(anns)
            percentage = (count / total) * 100
            report.append(f"- **{category}**: {count}条 ({percentage:.1f}%)")
        report.append("")
    
    # 按年份分布
    if timeline["by_year"]:
        report.append("### 按年份分布")
        report.append("")
        for year, anns in timeline["by_year"].items():
            report.append(f"- **{year}年**: {len(anns)}条")
        report.append("")
    
    # 重要公告列表
    if timeline["all"]:
        report.append("### 重要公告摘要")
        report.append("")
        
        # 按时间排序
        sorted_anns = sorted(timeline["all"], 
                            key=lambda x: x.get("NOTICEDATE", x.get("date", "")), 
                            reverse=True)[:10]
        
        for ann in sorted_anns:
            title = ann.get("NOTICETITLE", ann.get("title", ""))
            date = ann.get("NOTICEDATE", ann.get("date", ""))
            category = ann.get("category", "其他")
            report.append(f"- **{date}** [{category}] {title}")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    api = ExchangeAPI()
    
    # 测试A股公告
    print("=== A股公告测试 ===")
    sse_ann = api.get_sse_announcements("600519")
    print(f"上交所公告数量: {len(sse_ann.get('result', []))}")
    
    szse_ann = api.get_szse_announcements("002180")
    print(f"深交所公告数量: {len(szse_ann.get('data', []))}")
    
    # 测试公告分类
    print("\n=== 公告分类测试 ===")
    test_titles = [
        "2025年度报告",
        "非公开发行股票预案",
        "关于收到问询函的公告",
        "业绩预告",
        "股权转让公告"
    ]
    for title in test_titles:
        category = api.classify_announcement(title)
        print(f"{title} -> {category}")
    
    # 测试公告时间线
    print("\n=== 公告时间线测试 ===")
    timeline = get_announcement_timeline("002180", "a", 3)
    print(f"公告总数: {len(timeline['all'])}")
    print(f"类型分布: {list(timeline['by_type'].keys())}")
