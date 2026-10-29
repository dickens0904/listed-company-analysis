# -*- coding: utf-8 -*-
"""
测试：Result 类型
"""
import unittest
from scripts.types import Result, ok, err


class TestResult(unittest.TestCase):

    def test_ok_holds_value(self):
        """ok() 包装的 Result 应持有值且 is_ok=True"""
        r = ok(42)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.value, 42)
        self.assertIsNone(r.error)

    def test_err_holds_error(self):
        """err() 包装的 Result 应持有 error 且 is_ok=False"""
        r = err("boom")
        self.assertFalse(r.is_ok)
        self.assertEqual(r.error, "boom")
        self.assertIsNone(r.value)

    def test_unwrap_returns_value(self):
        """unwrap() 在 ok 时应返回值"""
        self.assertEqual(ok("hello").unwrap(), "hello")

    def test_unwrap_raises_on_err(self):
        """unwrap() 在 err 时应抛出 RuntimeError"""
        r = err("not found")
        with self.assertRaises(RuntimeError) as ctx:
            r.unwrap()
        self.assertIn("not found", str(ctx.exception))

    def test_unwrap_or_returns_value_on_ok(self):
        """unwrap_or() 在 ok 时返回实际值"""
        self.assertEqual(ok(10).unwrap_or(0), 10)

    def test_unwrap_or_returns_default_on_err(self):
        """unwrap_or() 在 err 时返回默认值"""
        self.assertEqual(err("x").unwrap_or(0), 0)

    def test_frozen(self):
        """Result 是不可变的"""
        r = ok(1)
        with self.assertRaises(AttributeError):
            r.value = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
