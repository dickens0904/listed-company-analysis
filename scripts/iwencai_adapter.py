#!/usr/bin/env python3
"""
iwencai API 适配器
封装 hithink-event-query skill 的调用，统一查询语法，解析事件数据

支持的查询类型（已验证返回详细数据）：
- 机构调研: 返回详细调研记录（调研日期、方式、接待人员、内容等）
- 增发配股: 返回详细增发记录（预案公告日、发行对象、募集资金等）

不支持或数据质量低的查询类型：
- 业绩预告: 仅返回基本股票信息
- 股权质押: 仅返回基本股票信息
- 监管函: 仅返回基本股票信息
- 限售解禁: 仅返回基本股票信息
- 其他重大事项: 仅返回基本股票信息
"""

import json
import subprocess
import time
import os
from pathlib import Path
from typing import Dict, List, Any


def _resolve_skills_dir() -> Path:
    """从环境变量 SKILLS_DIR 或 WorkBuddy 默认路径获取技能目录"""
    env = os.environ.get("SKILLS_DIR")
    if env:
        return Path(env)
    home = Path(os.path.expanduser("~"))
    for base in [home / ".workbuddy" / "skills", home / ".qclaw" / "skills"]:
        if base.exists():
            return base
    raise FileNotFoundError("无法找到技能目录，请设置 SKILLS_DIR 环境变量")


def _resolve_hithink_cli() -> str:
    """动态解析 hithink-* skill CLI 脚本路径

    2026-10-19 审计修复：原签名是 `_resolve_hithink_cli(event_key: str)`（必填），
    但函数体从未使用 event_key，且唯一调用处 `_resolve_hithink_cli()` 未传参
    → TypeError: missing 1 required positional argument: 'event_key'
    → institutional_visit / seasoned_offerings / shareholders_meeting 三个维度全废。
    event_key 确认为历史遗留的死参数，已移除。
    """
    skills_dir = _resolve_skills_dir()
    cli = skills_dir / "hithink-event-query" / "scripts" / "cli.py"
    if cli.exists():
        return str(cli)
    raise FileNotFoundError(f"hithink-event-query CLI 未找到: {cli}")


# 查询语法：股票代码和事件类型之间必须有空格
QUERY_TEMPLATE = "{stock_code} {event_type}"

# 事件数据的关键字段（用于判断API是否返回了事件数据）
EVENT_FIELD_MAP = {
    "机构调研": ["调研日期", "方式", "接待人员", "内容", "公告日期"],
    "增发配股": ["预案公告日", "目的", "进度", "发行对象", "增发价格"],
    "股东大会": ["公告日期"],  # 仅返回公告日期，数据不完整
}

# 请求超时（秒）
DEFAULT_TIMEOUT = 30

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def log(msg: str, level: str = "INFO"):
    """简单的日志输出"""
    prefix = {
        "INFO": "ℹ️",
        "WARN": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
    }.get(level, "ℹ️")
    print(f"[{prefix}] {msg}")


def query_iwencai(
    stock_code: str,
    event_type: str,
    limit: int = 10,
    page: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
    retry: int = MAX_RETRIES,
) -> Dict[str, Any]:
    """
    查询 iwencai 获取事件数据
    
    Args:
        stock_code: 股票代码（如 "002180" 或 "002180.SZ"）
        event_type: 事件类型（"机构调研"、"增发配股" 等）
        limit: 返回条数（默认10）
        page: 页码（默认1）
        timeout: 请求超时时间（秒，默认30）
        retry: 重试次数（默认3）
    
    Returns:
        字典，包含：
        - success: bool（是否成功）
        - data: list（事件数据列表，成功时）
        - error: str（错误信息，失败时）
        - note: str（附加说明，如"该事件类型无详细数据"）
    """
    # 标准化股票代码（去掉后缀如 .SZ .SH）
    stock_code_clean = stock_code.split(".")[0]
    
    # 构造查询字符串（关键：必须有空格）
    query = QUERY_TEMPLATE.format(
        stock_code=stock_code_clean,
        event_type=event_type
    )
    
    log(f"查询: {query} (limit={limit}, page={page})", "INFO")
    
    # 检查 CLI 是否存在（动态路径解析）
    try:
        skill_cli = _resolve_hithink_cli()
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    
    # 构造命令行
    cmd = [
        "python",
        str(skill_cli),
        "--query", query,
        "--limit", str(limit),
        "--page", str(page),
        "--timeout", str(timeout),
    ]
    
    # 重试循环
    for attempt in range(1, retry + 1):
        try:
            log(f"执行命令 (尝试 {attempt}/{retry})...", "DEBUG")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,  # 额外5秒缓冲
            )
            
            # 检查返回码
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "未知错误"
                log(f"命令执行失败: {error_msg}", "ERROR")
                
                if attempt < retry:
                    log(f"{RETRY_DELAY}秒后重试...", "WARN")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return {
                        "success": False,
                        "error": f"命令执行失败（已重试{retry}次）: {error_msg}",
                    }
            
            # 解析JSON输出
            try:
                response = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                log(f"JSON解析失败: {e}", "ERROR")
                log(f"原始输出: {result.stdout[:500]}", "DEBUG")
                
                if attempt < retry:
                    log(f"{RETRY_DELAY}秒后重试...", "WARN")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return {
                        "success": False,
                        "error": f"JSON解析失败（已重试{retry}次）: {str(e)}",
                    }
            
            # 检查API返回状态
            if not response.get("success"):
                error_msg = response.get("error", "API返回失败")
                log(f"API返回失败: {error_msg}", "ERROR")
                return {
                    "success": False,
                    "error": f"API返回失败: {error_msg}",
                    "response": response,
                }
            
            # 提取数据
            datas = response.get("datas", [])
            
            if not datas:
                log("未查询到数据", "WARN")
                return {
                    "success": True,
                    "data": [],
                    "note": "未查询到符合条件的数据",
                }
            
            # 检查是否返回了事件数据（不仅仅是基本股票信息）
            event_fields = EVENT_FIELD_MAP.get(event_type, [])
            
            if not event_fields:
                # 未知的事件类型，无法判断是否有事件数据
                log(f"未知事件类型: {event_type}，跳过事件数据检查", "WARN")
                return {
                    "success": True,
                    "data": datas,
                }
            
            # 检查第一条数据是否包含事件字段
            first_item = datas[0]
            has_event_data = any(field in first_item for field in event_fields)
            
            if not has_event_data:
                # 仅返回了基本股票信息，没有事件数据
                log(f"事件类型 '{event_type}' 仅返回基本股票信息，无详细事件数据", "WARN")
                return {
                    "success": True,
                    "data": [],
                    "note": f"事件类型 '{event_type}' 无详细数据（仅返回基本股票信息）",
                }
            
            # 成功获取事件数据
            log(f"成功获取 {len(datas)} 条事件数据", "INFO")
            return {
                "success": True,
                "data": datas,
                "raw_response": response,  # 包含分页信息等
            }
            
        except subprocess.TimeoutExpired:
            log(f"命令超时（{timeout}秒）", "ERROR")
            
            if attempt < retry:
                log(f"{RETRY_DELAY}秒后重试...", "WARN")
                time.sleep(RETRY_DELAY)
                continue
            else:
                return {
                    "success": False,
                    "error": f"命令超时（已重试{retry}次，超时{timeout}秒）",
                }
        
        except Exception as e:
            log(f"未知错误: {e}", "ERROR")
            
            if attempt < retry:
                log(f"{RETRY_DELAY}秒后重试...", "WARN")
                time.sleep(RETRY_DELAY)
                continue
            else:
                return {
                    "success": False,
                    "error": f"未知错误（已重试{retry}次）: {str(e)}",
                }
    
    # 不应到达此处
    return {"success": False, "error": "重试次数已用尽"}


def get_institutional_visits(
    stock_code: str,
    months: int = 12,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    获取机构调研记录
    
    Args:
        stock_code: 股票代码
        months: 查询最近N个月的数据（默认12个月）
        limit: 返回条数（默认50）
    
    Returns:
        字典，包含 success, data, error, note 字段
        data 中的每条记录包含：
        - 调研日期
        - 方式（业绩说明会/现场调研/线上会议）
        - 接待人员
        - 地点
        - 机构家数
        - 内容（完整的经营情况和Q&A记录）
        - 公告日期
    """
    log(f"获取机构调研记录: {stock_code} (最近{months}个月)", "INFO")
    
    result = query_iwencai(stock_code, "机构调研", limit=limit)
    
    if not result["success"]:
        return result
    
    # 过滤日期（如果API不支持时间过滤，需手动过滤）
    # 注意：iwencai API可能不支持时间范围参数，需手动过滤
    datas = result["data"]
    
    if months > 0 and datas:
        # 计算时间阈值
        from datetime import datetime, timedelta
        threshold = datetime.now() - timedelta(days=months * 30)
        threshold_str = threshold.strftime("%Y%m%d")
        
        # 过滤
        filtered = []
        for item in datas:
            visit_date = item.get("调研日期", "")
            if visit_date >= threshold_str:
                filtered.append(item)
        
        log(f"时间过滤: {len(datas)} → {len(filtered)} 条", "INFO")
        result["data"] = filtered
    
    return result


def get_seasoned_offerings(
    stock_code: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    获取增发配股记录
    
    Args:
        stock_code: 股票代码
        limit: 返回条数（默认20）
    
    Returns:
        字典，包含 success, data, error, note 字段
        data 中的每条记录包含：
        - 预案公告日
        - 目的（支付对价/项目融资/补充流动资金等）
        - 进度（董事会预案/股东大会通过/证监会核准/已实施）
        - 预案募集金额
        - 发行对象（完整的投资者名单）
        - 增发价格
        - 发行数量
        - 募集资金
        - 募集资金净额
        - 上市日
        - 公告日期
    """
    log(f"获取增发配股记录: {stock_code}", "INFO")
    
    result = query_iwencai(stock_code, "增发配股", limit=limit)
    
    if not result["success"]:
        return result
    
    # 增发配股是历史性数据，无需时间过滤
    log(f"获取到 {len(result['data'])} 条增发配股记录", "INFO")
    
    return result


def get_shareholders_meeting(
    stock_code: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    获取股东大会记录
    
    Args:
        stock_code: 股票代码
        limit: 返回条数（默认20）
    
    Returns:
        字典，包含 success, data, error, note 字段
        data 中的每条记录包含：
        - 会议日期
        - 会议类型（年度/临时）
        - 议案标题
        - 议案摘要
        - 决议公告日
        - 公告日期
    """
    log(f"获取股东大会记录: {stock_code}", "INFO")
    
    result = query_iwencai(stock_code, "股东大会", limit=limit)
    
    if not result["success"]:
        return result
    
    log(f"获取到 {len(result['data'])} 条股东大会记录", "INFO")
    
    return result


def test_connection() -> bool:
    """
    测试 iwencai API 连接
    
    Returns:
        bool: 连接正常返回True，否则False
    """
    log("测试 API 连接...", "INFO")
    
    result = query_iwencai("002180", "机构调研", limit=1)
    
    if result["success"]:
        log("API 连接正常", "INFO")
        return True
    else:
        log(f"API 连接失败: {result.get('error')}", "ERROR")
        return False


if __name__ == "__main__":
    # 简单测试
    print("=" * 60)
    print("iwencai_adapter.py - 测试")
    print("=" * 60)
    
    # 测试1: 连接测试
    print("\n[测试1] API 连接测试")
    if not test_connection():
        print("❌ API 连接失败，请检查：")
        print("  1. hithink-event-query skill 是否已安装")
        print("  2. IWENCAI_API_KEY 环境变量是否已设置")
        exit(1)
    
    # 测试2: 机构调研
    print("\n[测试2] 机构调研 - 002180")
    result = get_institutional_visits("002180", months=12, limit=3)
    if result["success"]:
        print(f"✅ 成功获取 {len(result['data'])} 条记录")
        if result["data"]:
            first = result["data"][0]
            print(f"   最新调研: {first.get('调研日期')} | 机构家数: {first.get('机构家数')}")
    else:
        print(f"❌ 失败: {result.get('error')}")
    
    # 测试3: 增发配股
    print("\n[测试3] 增发配股 - 002180")
    result = get_seasoned_offerings("002180", limit=3)
    if result["success"]:
        print(f"✅ 成功获取 {len(result['data'])} 条记录")
        if result["data"]:
            first = result["data"][0]
            print(f"   最新增发: {first.get('预案公告日')} | 募集资金: {first.get('募集资金')}")
    else:
        print(f"❌ 失败: {result.get('error')}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
