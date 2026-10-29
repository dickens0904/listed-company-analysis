# -*- coding: utf-8 -*-
"""
共享类型定义 — Result 模式替代裸 try-except

用法:
    from scripts.types import Result, ok, err

    def fetch_data(stock: str) -> Result[dict, str]:
        try:
            data = api_call(stock)
            return ok(data)
        except Exception as e:
            return err(str(e))
"""
# 从 result_types.py 导入（与 scripts/ 同目录，避免与 stdlib types 冲突）
try:
    from scripts.result_types import Result, ok, err
except ImportError:
    from result_types import Result, ok, err
