# -*- coding: utf-8 -*-
"""
测试：结构化日志配置
"""
import unittest
import logging
from scripts.logging_config import get_logger


class TestLoggingConfig(unittest.TestCase):

    def test_get_logger_returns_logger_instance(self):
        """get_logger 应返回 logging.Logger 实例"""
        logger = get_logger("test")
        self.assertIsInstance(logger, logging.Logger)

    def test_logger_name_is_set(self):
        """logger 名称应与传入的一致"""
        logger = get_logger("my-module")
        self.assertEqual(logger.name, "my-module")

    def test_default_logger_name(self):
        """不传参数时应使用默认名称"""
        logger = get_logger()
        self.assertEqual(logger.name, "company-analysis")

    def test_logger_can_log_info(self):
        """logger 应能正常记录 INFO 级别消息"""
        logger = get_logger("test-log")
        # 不抛异常即通过
        logger.info("test message: %s", "hello")

    def test_get_logger_idempotent(self):
        """多次调用 get_logger 应返回相同 logger"""
        l1 = get_logger("idempotent-test")
        l2 = get_logger("idempotent-test")
        self.assertIs(l1, l2)


if __name__ == "__main__":
    unittest.main()
