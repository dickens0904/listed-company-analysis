# -*- coding: utf-8 -*-
"""
result_types.py — 共享类型定义（Result 模式）
注意：文件名避免与 stdlib "types" 冲突，故命名为 result_types

用法:
    from scripts.result_types import Result, ok, err

    def fetch_data(stock: str) -> "Result[dict, str]":
        try:
            data = api_call(stock)
            return ok(data)
        except Exception as e:
            return err(str(e))
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True)
class Result(Generic[T, E]):
    """成功/失败的显式包装，替代裸 try-except + dict 返回。"""
    value: T | None = None
    error: E | None = None
    is_ok: bool = True

    def unwrap(self) -> T:
        if not self.is_ok:
            raise RuntimeError(f"unwrap() on Err: {self.error}")
        return self.value  # type: ignore[return-value]

    def unwrap_or(self, default: T) -> T:
        return self.value if self.is_ok else default  # type: ignore[return-value]


def ok(value: T) -> Result[T, Any]:
    return Result(value=value, is_ok=True)


def err(error: E) -> Result[Any, E]:
    return Result(error=error, is_ok=False)
