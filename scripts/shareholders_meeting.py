#!/usr/bin/env python3
"""
股东大会分析模块 (shareholders_meeting)
分析上市公司股东大会情况，包括会议时间、议案、决议等

数据来源: 公告数据 (从announcements中提取)

输出字段:
- meeting_count: 股东大会次数
- latest_meeting: 最近会议记录
- all_meetings: 所有会议记录
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


def _extract_meetings_from_announcements(announcements_data):
    """从公告数据中提取股东大会信息"""
    critical = announcements_data.get('critical_announcements', [])
    major = announcements_data.get('major_announcements', [])
    routine = announcements_data.get('routine_announcements', [])
    all_anns = critical + major + routine

    meeting_anns = []
    for a in all_anns:
        title = a.get('title', '')
        if '股东大会' in title or '股东会' in title:
            meeting_anns.append(a)

    meeting_anns.sort(key=lambda x: x.get('date', ''), reverse=True)

    meetings = []
    for a in meeting_anns:
        title = a.get('title', '')
        date = a.get('date', '')[:10]

        meeting_type = '其他'
        if '年度股东大会' in title:
            meeting_type = '年度股东大会'
        elif '临时股东大会' in title:
            meeting_type = '临时股东大会'
        elif '第一次' in title:
            meeting_type = '第一次临时股东大会'
        elif '第二次' in title:
            meeting_type = '第二次临时股东大会'

        is_resolution = '决议公告' in title
        is_notice = '通知' in title or '召开' in title
        is_legal = '法律意见书' in title

        meetings.append({
            'date': date,
            'title': title,
            'type': meeting_type,
            'is_resolution': is_resolution,
            'is_notice': is_notice,
            'is_legal': is_legal,
            'importance_tag': a.get('importance_tag', ''),
        })

    return meetings


def analyze_shareholders_meeting(
    stock_code: str,
    limit: int = 20,
    announcements_data=None,
) -> Dict[str, Any]:
    """
    分析股东大会记录

    Args:
        stock_code: 股票代码
        limit: 返回条数（默认20）
        announcements_data: 公告数据（从results.json获取）

    Returns:
        字典，包含分析结果
    """
    if announcements_data:
        meetings = _extract_meetings_from_announcements(announcements_data)
        source = "announcements"
    else:
        try:
            from scripts.iwencai_adapter import get_shareholders_meeting
            result = get_shareholders_meeting(stock_code, limit=limit)
            if result.get("success"):
                meetings = result.get("data", [])
                source = "iwencai"
            else:
                meetings = []
                source = "iwencai_failed"
        except Exception:
            meetings = []
            source = "iwencai_failed"

    if not meetings:
        return {
            "success": True,
            "meeting_count": 0,
            "latest_meeting": None,
            "all_meetings": [],
            "source": source,
        }

    meeting_count = len(meetings)
    latest_meeting = meetings[0] if meetings else None

    resolutions = [m for m in meetings if m.get('is_resolution')]
    notices = [m for m in meetings if m.get('is_notice')]

    return {
        "success": True,
        "meeting_count": meeting_count,
        "resolution_count": len(resolutions),
        "notice_count": len(notices),
        "latest_meeting": latest_meeting,
        "all_meetings": meetings[:limit],
        "source": source,
    }


def generate_report(data: Dict[str, Any]) -> str:
    """生成股东大会分析报告"""
    if not data.get("success"):
        return f"## 股东大会分析\n\n❌ 分析失败: {data.get('error', '未知错误')}\n"
    
    meeting_count = data.get("meeting_count", 0)
    
    if meeting_count == 0:
        return "## 股东大会分析\n\n无股东大会记录\n"
    
    md = "## 股东大会分析\n\n"
    
    # 1. 会议统计
    md += f"**会议次数**: {meeting_count} 次\n\n"
    
    # 2. 最近会议
    latest = data.get("latest_meeting", {})
    if latest:
        md += "**最近会议**:\n"
        md += f"- 会议日期: {latest.get('会议日期', latest.get('公告日期', 'N/A'))}\n"
        
        # 议案内容
        proposals = latest.get('议案标题') or latest.get('议案摘要') or latest.get('内容')
        if proposals:
            proposals_str = str(proposals)[:200]
            md += f"- 议案摘要: {proposals_str}\n"
        
        md += "\n"
    
    # 3. 历史会议列表
    md += "**历史会议记录**:\n"
    for i, m in enumerate(data.get("all_meetings", [])[:5], 1):
        date = m.get('会议日期', m.get('公告日期', 'N/A'))
        proposals = m.get('议案标题') or m.get('议案摘要') or m.get('内容')
        proposals_str = str(proposals)[:30] if proposals else 'N/A'
        
        md += f"- {i}. {date} | {proposals_str}\n"
    
    return md


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python shareholders_meeting.py <股票代码>")
        sys.exit(1)
    
    stock_code = sys.argv[1]
    
    print("=" * 60)
    print(f"股东大会分析: {stock_code}")
    print("=" * 60)
    
    result = analyze_shareholders_meeting(stock_code)
    
    if result["success"]:
        print(f"\n✅ 分析成功!")
        print(f"   会议次数: {result['meeting_count']}")
        
        if result.get("latest_meeting"):
            latest = result["latest_meeting"]
            print(f"\n   最近会议:")
            print(f"   - 会议日期: {latest.get('会议日期')}")
    else:
        print(f"\n❌ 分析失败: {result.get('error')}")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = generate_report(data)
    return ["\n" + md]