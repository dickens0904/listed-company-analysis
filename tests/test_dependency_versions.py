# -*- coding: utf-8 -*-
"""
测试：依赖版本锁定验证

确保 setup.py 和 requirements.txt 中的依赖版本都是精确锁定（==），不是范围匹配（>=）。
"""
import unittest
import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDependencyVersions(unittest.TestCase):
    """验证依赖版本锁定"""

    def test_setuppy_requires_use_exact_versions(self):
        """setup.py 的 install_requires 和 extras_require 应使用 == 而非 >="""
        setup_path = PROJECT_ROOT / "setup.py"
        content = setup_path.read_text(encoding="utf-8")

        # 提取所有引号内的依赖声明
        dep_pattern = re.compile(r"['\"]([a-zA-Z][\w-]*)(>=|<=|!=)([\d.]+)['\"]")
        matches = dep_pattern.findall(content)

        # python_requires 中的 >= 是合法的，排除
        bad_deps = [f"{name}{op}{ver}" for name, op, ver in matches
                     if not (name == "python" and op == ">=")]

        self.assertEqual(
            bad_deps, [],
            f"setup.py 中发现未锁定版本的依赖（应使用 ==）: {bad_deps}"
        )

    def test_requirements_txt_use_exact_versions(self):
        """requirements.txt 应使用 == 而非 >="""
        req_path = PROJECT_ROOT / "requirements.txt"
        if not req_path.exists():
            self.skipTest("requirements.txt 不存在")

        content = req_path.read_text(encoding="utf-8")
        bad_lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ">=" in line or "<=" in line:
                bad_lines.append(line)

        self.assertEqual(
            bad_lines, [],
            f"requirements.txt 中发现未锁定版本的行: {bad_lines}"
        )

    def test_setup_and_requirements_versions_match(self):
        """setup.py 和 requirements.txt 中共同依赖的版本应一致"""
        req_path = PROJECT_ROOT / "requirements.txt"
        setup_path = PROJECT_ROOT / "setup.py"

        if not req_path.exists():
            self.skipTest("requirements.txt 不存在")

        # 解析 requirements.txt
        req_versions = {}
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([a-zA-Z][\w-]*)==([\d.]+)$", line)
            if match:
                req_versions[match.group(1).lower()] = match.group(2)

        # 解析 setup.py
        setup_content = setup_path.read_text(encoding="utf-8")
        setup_versions = {}
        for match in re.finditer(r"['\"]([a-zA-Z][\w-]*)==([\d.]+)['\"]", setup_content):
            setup_versions[match.group(1).lower()] = match.group(2)

        # 检查共同依赖版本一致
        common_keys = set(req_versions.keys()) & set(setup_versions.keys())
        mismatches = []
        for key in sorted(common_keys):
            if req_versions[key] != setup_versions[key]:
                mismatches.append(
                    f"{key}: requirements={req_versions[key]}, setup={setup_versions[key]}"
                )

        self.assertEqual(
            mismatches, [],
            f"setup.py 和 requirements.txt 版本不一致: {mismatches}"
        )


if __name__ == "__main__":
    unittest.main()
