"""
配置模块：读取环境变量和本地配置文件
"""
import os
from pathlib import Path

# Token 文件路径（skill 目录下）
_TOKEN_FILE = Path(__file__).parent.parent / '.tushare_token'
_EM_API_KEY_FILE = Path(__file__).parent.parent / '.em_api_key'

def get_tushare_token() -> str:
    """获取 Tushare Token，优先级：环境变量 > 本地文件"""
    # 1. 尝试从环境变量读取
    token = os.environ.get('TUSHARE_TOKEN')
    if token and len(token) > 20:
        return token
    
    # 2. 尝试从本地文件读取
    if _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text().strip()
        if token and len(token) > 20:
            # 同时设置环境变量，供后续代码使用
            os.environ['TUSHARE_TOKEN'] = token
            return token
    
    return None

def get_em_api_key() -> str:
    """获取东方财富AI SaaS API Key，优先级：环境变量 > 本地文件 > 默认值"""
    # 1. 尝试从环境变量读取
    api_key = os.environ.get('EM_API_KEY')
    if api_key and len(api_key) > 20:
        return api_key
    
    # 2. 尝试从本地文件读取
    if _EM_API_KEY_FILE.exists():
        api_key = _EM_API_KEY_FILE.read_text().strip()
        if api_key and len(api_key) > 20:
            os.environ['EM_API_KEY'] = api_key
            return api_key
    
    return None
