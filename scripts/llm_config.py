# -*- coding: utf-8 -*-
"""
LLM 配置模块 — 多后端支持
支持三种模式（按优先级自动选择）：
  1. API 模式  — SENSENOVA_API_KEY 已配置 → 直接调用 SenseNova
  2. WorkBuddy 模式 — 文件 IPC → WorkBuddy 助手处理 prompts
  3. Replay 模式 — 已有缓存响应 → 直接读取

用法: 无需修改调用代码，call_llm() 自动选择最佳后端。
"""
import os
import json
import time
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────
LLM_CONFIG = {
    "provider": "sensenova",
    "model": "deepseek-v4-flash",
    "api_key": os.environ.get("SENSENOVA_API_KEY", ""),
    "base_url": "https://token.sensenova.cn/v1",
    "temperature": 0.3,
    "max_tokens": 8192,
    "thinking": {"type": "enabled", "reasoning_effort": "high"},
}

# WorkBuddy 文件 IPC 路径
_WB_DIR = Path(__file__).parent.parent / "output"
_WB_REQUESTS_FILE = _WB_DIR / "_llm_requests.jsonl"
_WB_RESPONSES_FILE = _WB_DIR / "_llm_responses.jsonl"
REQUEST_TIMEOUT = 300  # 等待 WorkBuddy 响应的最大秒数
FORCE_SYNC_WAIT = os.environ.get("LLM_SYNC", "") == "1"  # 设为1时阻塞等待，否则立即返回None


def _call_api(system_prompt, user_prompt, temperature, max_tokens):
    """API 模式：直接调用 SenseNova"""
    from openai import OpenAI
    client = OpenAI(base_url=LLM_CONFIG["base_url"], api_key=LLM_CONFIG["api_key"])
    kwargs = {
        "model": LLM_CONFIG["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature or LLM_CONFIG["temperature"],
        "max_tokens": max_tokens or LLM_CONFIG["max_tokens"],
        "stream": False,
    }
    if LLM_CONFIG.get("thinking"):
        kwargs["extra_body"] = {"thinking": LLM_CONFIG["thinking"]}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def _call_workbuddy(system_prompt, user_prompt, temperature, max_tokens):
    """
    WorkBuddy 模式：写请求到文件，等待 WorkBuddy 助手处理。
    助手通过 write_llm_responses() 写回响应。
    """
    _WB_DIR.mkdir(parents=True, exist_ok=True)

    # 生成唯一 ID
    req_id = f"{os.getpid()}_{int(time.time() * 1000)}_{hash(user_prompt) & 0xFFFF:04x}"

    # 写请求
    request = {
        "id": req_id,
        "system": system_prompt,
        "user": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with open(_WB_REQUESTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(request, ensure_ascii=False) + "\n")

    # 非阻塞模式：写请求后立即返回None，由WorkBuddy助手稍后批量处理
    if not FORCE_SYNC_WAIT:
        print(f"  [WorkBuddy] 请求已记录 (id={req_id})，将在报告阶段批量处理")
        return None

    # 阻塞模式：等待 WorkBuddy 实时响应
    start = time.time()
    while time.time() - start < REQUEST_TIMEOUT:
        if _WB_RESPONSES_FILE.exists():
            with open(_WB_RESPONSES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        resp = json.loads(line.strip())
                        if resp.get("id") == req_id:
                            return resp.get("content", "")
                    except json.JSONDecodeError:
                        continue
        time.sleep(1)

    print(f"  [WorkBuddy] 等待超时 (id={req_id})，将使用降级报告")
    return None


def call_llm(system_prompt, user_prompt, temperature=None, max_tokens=None):
    """
    统一 LLM 调用函数。自动选择最佳后端：
    1. SENSENOVA_API_KEY 已配 → API 模式
    2. 否则 → WorkBuddy 文件 IPC 模式
    """
    # 优先 API 模式
    if LLM_CONFIG["api_key"] and len(LLM_CONFIG["api_key"]) > 10:
        try:
            return _call_api(system_prompt, user_prompt, temperature, max_tokens)
        except Exception as e:
            print(f"  [API] 调用失败: {e}，降级到 WorkBuddy 模式...")

    # WorkBuddy 模式
    try:
        return _call_workbuddy(system_prompt, user_prompt, temperature, max_tokens)
    except Exception as e:
        print(f"  [LLM] 调用失败: {e}")
        return None


def get_pending_requests() -> list:
    """获取所有待处理的 LLM 请求（供 WorkBuddy 助手调用）"""
    if not _WB_REQUESTS_FILE.exists():
        return []
    requests = []
    with open(_WB_REQUESTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                requests.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return requests


def write_response(req_id: str, content: str):
    """写入 LLM 响应（供 WorkBuddy 助手调用）"""
    _WB_DIR.mkdir(parents=True, exist_ok=True)
    with open(_WB_RESPONSES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": req_id, "content": content}, ensure_ascii=False) + "\n")


def clear_requests():
    """清空请求/响应文件（新分析开始前调用）"""
    for f in [_WB_REQUESTS_FILE, _WB_RESPONSES_FILE]:
        if f.exists():
            f.unlink()


# ── 首席分析师提示词模板 ─────────────────────────────────────
ANALYST_PROMPT_TEMPLATE = """你是一位具有20年经验的顶级券商首席分析师，专攻{industry}行业。你的分析风格：
1. 严谨的数据驱动分析
2. 深入的行业洞察
3. 前瞻性的战略判断
4. 专业的风险提示

请对以下上市公司进行深度分析：

## 公司基本信息
{company_info}

## 财务数据
{financial_data}

## 行业背景
{industry_data}

## 治理与风险
{governance_data}

请按照以下框架进行分析：
### 1. 投资亮点（核心竞争优势、增长驱动因素、战略价值）
### 2. 风险提示（经营/财务/行业/治理风险）
### 3. 估值判断（当前估值水平、PE/PB、绝对估值参考）
### 4. 投资建议（买入/持有/减持、目标价、关键催化剂、跟踪要点）

请用专业、客观的语言进行分析，注意数据引用的准确性。
"""


def get_analyst_prompt(company_info, financial_data, industry_data, governance_data, industry="综合"):
    return ANALYST_PROMPT_TEMPLATE.format(
        industry=industry,
        company_info=company_info,
        financial_data=financial_data,
        industry_data=industry_data,
        governance_data=governance_data,
    )
