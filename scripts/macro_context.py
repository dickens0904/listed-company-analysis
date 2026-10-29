# -*- coding: utf-8 -*-
"""
宏观/板块背景分析模块
为公司分析提供宏观经济锚点和行业周期判断

功能:
1. 宏观PMI/信贷数据（通过AKShare）
2. 板块指数实时行情（判断行业强弱）
3. 行业政策动态（近期重要政策）
4. 板块周期定位（成长期/成熟期/衰退期）
"""
import sys, os, re, time
from datetime import datetime, timedelta
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

sys.stdout.reconfigure(encoding='utf-8')

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False


# ─────────────────────────────────────────────
# 板块指数行情
# ─────────────────────────────────────────────

def fetch_sector_index(market="a"):
    """
    获取主要板块/行业指数实时行情
    market: a(A股) / hk(港股)
    """
    if not HAS_AKSHARE:
        return {"error": "AKShare未安装"}

    try:
        if market == "a":
            # 申万行业指数
            df = ak.sw_index_second_spot_em()
            if df is not None and not df.empty:
                # 取前20个热点板块
                cols = df.columns.tolist()
                # 找涨幅列（通常是第4列或含"涨跌幅"）
                return df.head(20).to_dict("records")
        return {}
    except Exception as e:
        return {"error": str(e)}


def fetch_market_breadth(market="a"):
    """
    市场宽度指标：上涨/下跌家数（判断大盘情绪）
    """
    if not HAS_AKSHARE:
        return {}

    try:
        if market == "a":
            # 尝试获取涨跌停家数
            df_limit = ak.stock_em_zt_pool(date=datetime.now().strftime("%Y%m%d"))
            if df_limit is not None and not df_limit.empty:
                return {
                    "zt_count": len(df_limit),
                    "note": "今日涨停家数",
                }
    except Exception as _sexc:
        record(__name__, 'fetch_market_breadth', _sexc, note='静默降级')
        pass

    try:
        # 备选：东方财富大盘行情
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": "1.000001",  # 上证指数
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58",
        }
        import requests
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json().get("data", {})
            return {
                "index_name": "上证指数",
                "change_pct": data.get("f3", 0),
                "turnover": data.get("f6", 0),
            }
    except Exception:
        return {}


def fetch_macro_indicators():
    """
    关键宏观经济指标（PMI、CPI、信贷等）
    数据源：AKShare
    """
    if not HAS_AKSHARE:
        return {"note": "AKShare未安装，使用公开数据"}

    indicators = {}

    # PMI
    try:
        df_pmi = ak.pmi_statistical()
        if df_pmi is not None and not df_pmi.empty:
            latest = df_pmi.iloc[-1]
            indicators["PMI"] = {
                "latest": f"制造业PMI: {latest.get('制造业', latest.get('PMI', 'N/A'))}",
                "date": str(latest.get('月份', 'N/A')),
            }
    except Exception as e:
        indicators["PMI"] = {"error": str(e)}

    # CPI/PPI
    try:
        df_cpi = ak.cpi_monthly()
        if df_cpi is not None and not df_cpi.empty:
            latest = df_cpi.iloc[-1]
            indicators["CPI"] = {
                "latest": f"CPI: {latest.get('全国居民消费价格', latest.get('当月', 'N/A'))}",
                "date": str(latest.get('月份', 'N/A')),
            }
    except Exception as _sexc:
        record(__name__, 'fetch_macro_indicators', _sexc, note='静默降级')
        pass

    # 社融/信贷
    try:
        df_credit = ak.cnbs_total()
        if df_credit is not None and not df_credit.empty:
            latest = df_credit.iloc[-1]
            indicators["社融"] = {
                "latest": f"社融增量: {latest.get('当月值', 'N/A')}亿元",
                "date": str(latest.get('月份', 'N/A')),
            }
    except Exception as _sexc:
        record(__name__, 'fetch_macro_indicators', _sexc, note='静默降级')
        pass

    return indicators


def fetch_industry_policy_news(industry_name, days=30):
    """
    搜集行业近期重要政策动态
    数据源：百度新闻搜索
    """
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }

        queries = [
            f"{industry_name} 政策 {datetime.now().year}",
            f"{industry_name} 监管 规定 {datetime.now().year}",
            f"{industry_name} 政府文件 {datetime.now().year}",
        ]

        policies = []
        for q in queries[:2]:
            try:
                url = f"https://www.baidu.com/s?wd={q}&rn=5&tn=news"
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    titles = re.findall(
                        r'<h3[^>]*class="[^"]*news-title[^"]*"[^>]*>(.*?)</h3>',
                        resp.text, re.DOTALL
                    )
                    for t in titles[:3]:
                        t_clean = re.sub(r'<[^>]+>', '', t).strip()
                        if t_clean and len(t_clean) > 8:
                            policies.append(t_clean)
            except Exception as _sexc:
                record(__name__, 'fetch_industry_policy_news', _sexc, note='静默降级')
                pass
            time.sleep(0.2)

        # 去重
        seen = set()
        unique = []
        for p in policies:
            if p not in seen and len(p) < 80:
                seen.add(p)
                unique.append(p)

        return unique[:8]

    except Exception as e:
        return {"error": str(e)}


def fetch_cycle_position(industry_name):
    """
    判断行业周期定位（基于公开信号）
    框架：导入期 → 成长期 → 成熟期 → 饱和期/衰退期
    """
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0',
        }
        url = f"https://www.baidu.com/s?wd={industry_name} 行业周期 成熟 衰退 {datetime.now().year}&rn=3"
        resp = requests.get(url, headers=headers, timeout=8)
        text = resp.text if resp.status_code == 200 else ""

        positive_words = ['高速增长', '爆发期', '景气上行', '供不应求', '扩张期', '快速渗透']
        mature_words = ['成熟期', '稳定增长', '增速放缓', '竞争加剧', '洗牌', '饱和']
        decline_words = ['衰退', '产能过剩', '价格战', '亏损']

        pos = sum(1 for w in positive_words if w in text)
        mat = sum(1 for w in mature_words if w in text)
        dec = sum(1 for w in decline_words if w in text)

        if pos > mat and pos > dec:
            position = "🚀 成长期（高速增长）"
        elif mat >= pos and mat >= dec:
            position = "📊 成熟期（增速放缓）"
        elif dec > 0:
            position = "⚠️ 成熟后期/洗牌期"
        else:
            position = "❓ 周期定位不明确"

        return {"position": position, "positive_signals": pos, "mature_signals": mat, "decline_signals": dec}

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def fetch_macro_context(stock_code, market="a", industry_name="", data_dir=None):
    """
    宏观/板块背景综合分析
    """
    result = {
        "stock_code": stock_code,
        "market": market,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 1. 宏观指标
    print("  → 获取宏观指标...")
    result["macro_indicators"] = fetch_macro_indicators()

    # 2. 板块指数
    print("  → 获取板块指数...")
    result["sector_index"] = fetch_sector_index(market)

    # 3. 大盘情绪
    print("  → 分析大盘情绪...")
    result["market_breadth"] = fetch_market_breadth(market)

    # 4. 行业政策（如果有行业名）
    if industry_name:
        print(f"  → 搜集行业政策: {industry_name}...")
        result["industry_policies"] = fetch_industry_policy_news(industry_name)
        result["cycle_position"] = fetch_cycle_position(industry_name)
    else:
        result["industry_policies"] = []
        result["cycle_position"] = {}

    # 保存
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        import json
        out_path = os.path.join(data_dir, "macro_context.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"  ✅ 宏观背景已保存: {out_path}")

    return result


def format_macro_context(data):
    """将宏观数据格式化为Markdown"""
    lines = ["## 宏观/板块背景\n"]

    # 宏观指标
    mi = data.get("macro_indicators", {})
    if mi and "error" not in mi:
        lines.append("### 📊 关键宏观指标\n")
        for key, val in mi.items():
            if isinstance(val, dict) and "error" not in val:
                lines.append(f"- **{key}**：{val.get('latest', 'N/A')}（{val.get('date', 'N/A')}）")
        lines.append("")

    # 板块指数
    si = data.get("sector_index", {})
    if si and "error" not in si and si:
        lines.append("### 📈 热点板块（申万行业）\n")
        if isinstance(si, list):
            for item in si[:10]:
                if isinstance(item, dict):
                    # 找名称和涨跌幅列
                    name = item.get('指数名称', item.get('板块名称', '?'))
                    chg = item.get('涨跌幅', item.get('涨跌幅(%)', '?'))
                    if isinstance(chg, (int, float)):
                        chg_str = f"{chg:+.2f}%"
                    else:
                        chg_str = str(chg)
                    lines.append(f"- {name}: {chg_str}")
        lines.append("")

    # 大盘情绪
    mb = data.get("market_breadth", {})
    if mb and "error" not in mb:
        lines.append("### 🌊 大盘情绪\n")
        for key, val in mb.items():
            if key != "note":
                lines.append(f"- **{key}**：{val}")
        lines.append("")

    # 行业政策
    policies = data.get("industry_policies", [])
    if policies and isinstance(policies, list):
        lines.append("### 📜 近期行业政策动态\n")
        for p in policies[:6]:
            lines.append(f"- {p}")
        lines.append("")

    # 周期定位
    cp = data.get("cycle_position", {})
    if cp and "error" not in cp:
        pos = cp.get("position", "N/A")
        lines.append(f"### 🔄 行业周期定位：**{pos}**\n")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--stock', default='002180')
    parser.add_argument('--market', default='a')
    parser.add_argument('--industry', default='')
    args = parser.parse_args()

    data = fetch_macro_context(args.stock, args.market, args.industry)
    print(format_macro_context(data))
