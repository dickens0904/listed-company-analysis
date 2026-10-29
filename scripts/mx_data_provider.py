"""
东方财富AI SaaS数据提供者
封装mx-skills的金融数据查询能力，供listed-company-analysis使用
替代原有的AI解读功能
"""
import asyncio
import json
import os
import sys
import base64
import re
import zipfile
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

# API Key配置
DEFAULT_EM_API_KEY = 'em_2SQfj0wa08v65YPPUmo2kVgpiwcaXLCT'

def get_em_api_key():
    return os.environ.get('EM_API_KEY', DEFAULT_EM_API_KEY).strip()

# ========== 行业研究报告 ==========

class MXIndustryResearchProvider:
    """行业研究报告提供者"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or get_em_api_key()
        # 改用统一tmp目录（避免散落在skill目录下）
        try:
            from scripts.tmp_paths import get_miaoxiang_dir
            self.output_dir = get_miaoxiang_dir() / 'industry_research_report'
        except ImportError:
            self.output_dir = Path.cwd() / 'miaoxiang' / 'industry_research_report'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_url = "https://ai-saas.eastmoney.com/proxy/app-robo-advisor-api/assistant/write/industry/research"
    
    def _safe_filename(self, name, fallback):
        base = Path(str(name or "")).name.strip() or fallback
        invalid = '<>:"/\\|?*'
        out = "".join("_" if ch in invalid else ch for ch in base).strip(" .")
        return out or fallback
    
    def _save_base64_file(self, b64_str, file_path):
        if not b64_str:
            return False
        try:
            raw = base64.b64decode(b64_str)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(raw)
            return True
        except Exception:
            return False
    
    def _extract_docx_text(self, docx_path):
        try:
            with zipfile.ZipFile(docx_path, "r") as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        except Exception:
            return ""
        text = re.sub(r"(?s)<w:t[^>]*>(.*?)</w:t>", r"\1\n", xml)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    
    async def get_industry_report(self, industry_name):
        """获取行业研究报告"""
        import httpx
        
        if not isinstance(industry_name, str) or len(industry_name) > 500:
            return {"error": "字数超出限制"}
        
        try:
            async with httpx.AsyncClient(timeout=1200.0) as client:
                result = await client.post(
                    self.api_url,
                    json={"query": industry_name},
                    headers={
                        "Content-Type": "application/json",
                        "em_api_key": self.api_key,
                    },
                )
                result.raise_for_status()
                result_data_api = result.json()
                
                title = result_data_api["data"]["title"]
                content = result_data_api["data"].get("content") if isinstance(result_data_api.get("data"), dict) else ""
                content = content if isinstance(content, str) else ""
                share_url = result_data_api["data"]["shareUrl"]
                
                safe_base = self._safe_filename(title, "industry_research_report")
                
                pdf_output_path = self.output_dir / f"{safe_base}.pdf"
                pdf_saved = self._save_base64_file(result_data_api["data"]["pdfBase64"], pdf_output_path)
                
                word_output_path = self.output_dir / f"{safe_base}.docx"
                word_saved = self._save_base64_file(result_data_api["data"]["wordBase64"], word_output_path)
                
                if not word_saved or not pdf_saved:
                    return {"error": "保存附件失败"}
                
                truncated_text = content.strip()
                if not truncated_text and word_saved and word_output_path.is_file():
                    truncated_text = self._extract_docx_text(word_output_path)
                
                return {
                    "title": title,
                    "content": truncated_text,
                    "pdf_path": str(pdf_output_path),
                    "docx_path": str(word_output_path),
                    "share_url": share_url,
                }
        
        except Exception as e:
            return {"error": f"调用失败: {e}"}
    
    def get_industry_report_sync(self, industry_name):
        """同步获取行业研究报告"""
        return asyncio.run(self.get_industry_report(industry_name))

# ========== 财报点评 ==========

@dataclass
class EntityInfo:
    class_code: str
    secu_code: str
    market_char: str
    secu_name: str = ""
    
    @property
    def em_code(self):
        if "." in self.secu_code:
            return self.secu_code
        suffix = (self.market_char or "").strip()
        if not suffix:
            raise RuntimeError("缺少 marketChar")
        if suffix and not suffix.startswith("."):
            suffix = f".{suffix}"
        return f"{self.secu_code}{suffix}"

class MXStockEarningsReviewProvider:
    """财报点评提供者"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or get_em_api_key()
        # 改用统一tmp目录
        try:
            from scripts.tmp_paths import get_miaoxiang_dir
            self.output_dir = get_miaoxiang_dir() / 'stock-earnings-review'
        except ImportError:
            self.output_dir = Path.cwd() / 'miaoxiang' / 'stock-earnings-review'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.entity_api = "https://ai-saas.eastmoney.com/proxy/entity/dialogTagsV2"
        self.report_list_api = "https://ai-saas.eastmoney.com/proxy/app-robo-advisor-api/assistant/write/choice/reportList"
        self.comment_api = "https://ai-saas.eastmoney.com/proxy/app-robo-advisor-api/assistant/write/performance/comment"
    
    def _auth_headers(self):
        return {"em_api_key": self.api_key}
    
    def _base_headers(self):
        return {
            "Content-Type": "application/json",
            "em_base_info": json.dumps({"productType": "mx"}, ensure_ascii=False, separators=(",", ":")),
            **self._auth_headers(),
        }
    
    def _save_attachment(self, b64_str, output_dir, filename):
        if not b64_str:
            return None
        try:
            raw = base64.b64decode(b64_str)
            out_path = Path(output_dir) / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(raw)
            return str(out_path)
        except Exception:
            return None
    
    async def _get_entity_info(self, stock_code):
        """获取实体信息"""
        import httpx
        headers = {"Content-Type": "application/json", "em_api_key": self.api_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.entity_api,
                json={"content": stock_code},
                headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return None
            d = data.get("data")
            if isinstance(d, dict):
                if isinstance(d.get("entityMetricList"), list):
                    entity_list = d.get("entityMetricList")
                    first = entity_list[0][0] if entity_list and isinstance(entity_list[0], list) and entity_list[0] else None
                elif isinstance(d.get("entityList"), list) and d.get("entityList"):
                    first = d.get("entityList")[0]
                elif isinstance(d, list) and d and isinstance(d[0], dict):
                    first = d[0]
                else:
                    first = None
            else:
                first = None
            return first
    
    async def _get_report_list(self, entity_info):
        """获取报告列表"""
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.report_list_api,
                json={"query": entity_info.em_code},
                headers=self._base_headers()
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                return None
            return data.get("data", {}).get("reportList", [])
    
    async def get_earnings_review(self, stock_code, report_date=None):
        """获取财报点评"""
        import httpx
        
        try:
            entity_raw = await self._get_entity_info(stock_code)
            if not entity_raw:
                return {"error": f"无法识别股票: {stock_code}"}
            
            entity_info = EntityInfo(
                class_code=entity_raw.get("classCode", "002001"),
                secu_code=entity_raw.get("secuCode", stock_code),
                market_char=entity_raw.get("marketChar", "SH"),
                secu_name=entity_raw.get("secuName", "")
            )
            
            reports = await self._get_report_list(entity_info)
            if not reports:
                return {"error": "未找到财报数据"}
            
            if report_date:
                target_report = next((r for r in reports if r.get("reportDate") == report_date), None)
            else:
                target_report = reports[0] if reports else None
            
            if not target_report:
                return {"error": f"未找到指定日期的财报: {report_date}"}
            
            report_date = target_report.get("reportDate")
            
            async with httpx.AsyncClient(timeout=1200.0) as client:
                resp = await client.post(
                    self.comment_api,
                    json={"query": entity_info.em_code, "reportDate": report_date},
                    headers=self._base_headers()
                )
                resp.raise_for_status()
                raw = resp.json()
            
            code = raw.get("code") if isinstance(raw, dict) else None
            if code not in (0, 200):
                return {"error": f"接口返回异常: {raw.get('message', '未知错误')}"}
            
            data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
            title = str(data.get("title") or "")
            content = str(data.get("content") or "")
            share_url = data.get("shareUrl")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = self.output_dir / f"review_{timestamp}"
            run_dir.mkdir(parents=True, exist_ok=True)
            
            saved_files = {}
            pdf_path = self._save_attachment(data.get("pdfBase64"), run_dir, "review.pdf")
            if pdf_path:
                saved_files["pdf"] = pdf_path
            
            doc_path = self._save_attachment(data.get("wordBase64"), run_dir, "review.docx")
            if doc_path:
                saved_files["word"] = doc_path
            
            xlsx_path = self._save_attachment(data.get("dataSheetBase64"), run_dir, "data.xlsx")
            if xlsx_path:
                saved_files["dataSheet"] = xlsx_path
            
            return {
                "title": title,
                "content": content,
                "share_url": share_url,
                "report_date": report_date,
                "entity_name": entity_info.secu_name,
                "files": saved_files,
            }
        
        except Exception as e:
            return {"error": f"调用失败: {e}"}
    
    def get_earnings_review_sync(self, stock_code, report_date=None):
        """同步获取财报点评"""
        return asyncio.run(self.get_earnings_review(stock_code, report_date))

# ========== 金融数据查询 ==========

class MXFinanceDataProvider:
    """东方财富AI SaaS金融数据提供者"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or get_em_api_key()
        # 改用统一tmp目录
        try:
            from scripts.tmp_paths import get_miaoxiang_dir
            self.output_dir = get_miaoxiang_dir() / 'mx_finance_data'
        except ImportError:
            self.output_dir = Path.cwd() / 'miaoxiang' / 'mx_finance_data'
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def query(self, query_text):
        mx_path = Path(__file__).parent.parent.parent / 'mx-skills' / 'mx-finance-data' / 'scripts'
        if str(mx_path) not in sys.path:
            sys.path.insert(0, str(mx_path))
        
        from get_data import query_mx_finance_data
        
        os.environ['EM_API_KEY'] = self.api_key
        result = await query_mx_finance_data(
            query=query_text,
            output_dir=self.output_dir
        )
        return result
    
    def query_sync(self, query_text):
        return asyncio.run(self.query(query_text))
    
    def get_stock_fundamentals(self, stock_code):
        query = f"{stock_code}的基本面数据"
        return self.query_sync(query)
    
    def get_financial_report(self, stock_code, period='最近一年'):
        query = f"{stock_code}{period}的财务报表"
        return self.query_sync(query)
    
    def get_valuation(self, stock_code):
        query = f"{stock_code}的估值指标"
        return self.query_sync(query)
    
    def get_market_data(self, stock_code):
        query = f"{stock_code}的最新行情"
        return self.query_sync(query)

# ========== 便捷接口 ==========

# 单例实例
_mx_finance_provider = None
_mx_industry_provider = None
_mx_earnings_provider = None

def get_mx_finance_provider():
    global _mx_finance_provider
    if _mx_finance_provider is None:
        _mx_finance_provider = MXFinanceDataProvider()
    return _mx_finance_provider

def get_mx_industry_provider():
    global _mx_industry_provider
    if _mx_industry_provider is None:
        _mx_industry_provider = MXIndustryResearchProvider()
    return _mx_industry_provider

def get_mx_earnings_provider():
    global _mx_earnings_provider
    if _mx_earnings_provider is None:
        _mx_earnings_provider = MXStockEarningsReviewProvider()
    return _mx_earnings_provider

# ========== 降级方案：mx-skills不可用时回退到原有AI分析 ==========

def _fallback_industry_analysis(industry_name):
    """降级：使用本地LLM进行行业分析"""
    try:
        from scripts.llm_config import call_llm
        
        system_prompt = """你是一位资深行业分析师，专注于A股市场行业研究。请基于行业名称提供深度分析报告。"""
        
        user_prompt = f"""请分析【{industry_name}】行业：

1. 行业概况：市场规模、发展趋势
2. 产业链分析：上游、中游、下游
3. 竞争格局：主要玩家、市场份额
4. 投资要点：机会与风险

请输出详细的行业研究报告。"""
        
        content = call_llm(system_prompt, user_prompt, max_tokens=4096)
        return {
            "title": f"{industry_name}行业研究报告",
            "content": content or "行业分析失败",
            "source": "fallback_llm",
            "error": None
        }
    except Exception as e:
        return {"error": f"降级分析失败: {e}"}

def _fallback_earnings_review(stock_code, report_date=None):
    """降级：使用本地LLM进行财报点评"""
    try:
        from scripts.llm_config import call_llm
        
        system_prompt = """你是一位资深财务分析师，擅长解读上市公司财报。请提供专业的财报点评分析。"""
        
        date_str = f"，报告日期：{report_date}" if report_date else ""
        user_prompt = f"""请点评【{stock_code}】的财报{date_str}：

1. 核心财务数据解读：营收、净利润、毛利率等
2. 同比/环比变化分析
3. 亮点与风险提示
4. 投资建议

请输出专业的财报点评报告。"""
        
        content = call_llm(system_prompt, user_prompt, max_tokens=4096)
        return {
            "title": f"{stock_code}财报点评",
            "content": content or "财报点评失败",
            "report_date": report_date,
            "source": "fallback_llm",
            "error": None
        }
    except Exception as e:
        return {"error": f"降级分析失败: {e}"}

# ========== 便捷函数（带降级）==========

def query_finance_data(query_text, fallback=False):
    """查询金融数据"""
    result = get_mx_finance_provider().query_sync(query_text)
    if fallback and 'error' in result:
        return {"error": "金融数据查询失败，无降级方案"}
    return result

def get_industry_report(industry_name, fallback=True):
    """获取行业研究报告（替代原有AI行业分析）
    
    Args:
        industry_name: 行业名称
        fallback: 是否在mx-skills不可用时回退到本地LLM分析
    
    Returns:
        行业研究报告，包含title、content、pdf_path、docx_path等字段
    """
    result = get_mx_industry_provider().get_industry_report_sync(industry_name)
    
    if 'error' in result and fallback:
        print(f"  [mx-skills] 行业研究失败: {result['error']}，回退到本地AI分析")
        return _fallback_industry_analysis(industry_name)
    
    return result

def get_earnings_review(stock_code, report_date=None, fallback=True):
    """获取财报点评（替代原有AI财报解读）
    
    Args:
        stock_code: 股票代码
        report_date: 报告日期（可选）
        fallback: 是否在mx-skills不可用时回退到本地LLM分析
    
    Returns:
        财报点评报告，包含title、content、report_date、files等字段
    """
    result = get_mx_earnings_provider().get_earnings_review_sync(stock_code, report_date)
    
    if 'error' in result and fallback:
        print(f"  [mx-skills] 财报点评失败: {result['error']}，回退到本地AI分析")
        return _fallback_earnings_review(stock_code, report_date)
    
    return result

# ========== 测试函数 ==========

def test_mx_integration():
    """测试所有mx-skills整合"""
    print("=== 测试金融数据查询 ===")
    result = query_finance_data("贵州茅台的最新价")
    print(f"金融数据查询: {'成功' if 'file_path' in result else '失败'}")
    
    print("\n=== 测试行业研究报告 ===")
    result = get_industry_report("半导体行业")
    print(f"行业研究: {'成功' if 'title' in result else '失败'}")
    if 'title' in result:
        print(f"标题: {result['title']}")
    
    print("\n=== 测试财报点评 ===")
    result = get_earnings_review("600519")
    print(f"财报点评: {'成功' if 'title' in result else '失败'}")
    if 'title' in result:
        print(f"标题: {result['title']}")

if __name__ == "__main__":
    test_mx_integration()