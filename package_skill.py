#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 listed-company-analysis skill 并覆盖同步到「龙头计划」目录。

触发：用户说「同步到龙头计划里」即运行本脚本（python package_skill.py）。
机制：git add -A -> write-tree（临时树，不落 commit）-> git archive --prefix
      -> 覆盖目标 zip -> git reset -q。保留工作区改动、不污染 git 历史。
依赖：skill 目录须是 git 仓库；目标目录已存在。
"""
import os
import sys
import zipfile
import subprocess

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_ZIP = r"D:\BaiduSyncdisk\财中金控\项目库\龙头计划\listed-company-analysis.zip"
PREFIX = "listed-company-analysis/"

# 这些路径若出现在包里即视为事故（凭据 / 缓存 / 开发草稿）
FORBIDDEN_SUBSTR = (".tushare_token", ".em_api_key", "/.tmp/", "/output/", "/.git/",
                    "/_dev_scratch/", "/samples/", "/.trae/")


def _run(cmd):
    r = subprocess.run(cmd, cwd=SKILL_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"❌ 命令失败: {' '.join(cmd)}\n{r.stderr}\n")
        sys.exit(1)
    return r.stdout.strip()


def main():
    if not os.path.isdir(os.path.join(SKILL_DIR, ".git")):
        sys.stderr.write("❌ skill 目录不是 git 仓库，无法 git archive\n")
        sys.exit(1)
    # 1) 暂存工作区（含未提交改动与未追踪文件）
    _run(["git", "add", "-A"])
    tree = _run(["git", "write-tree"])
    print(f"✅ write-tree: {tree}")
    # 2) 归档（尊重 .gitattributes export-ignore + .gitignore）
    _run(["git", "archive", "--format=zip", "--prefix", PREFIX, "-o", TARGET_ZIP, tree])
    # 3) 还原 index（保留工作区、不落 commit）
    _run(["git", "reset", "-q"])
    # 4) 校验
    with zipfile.ZipFile(TARGET_ZIP) as z:
        names = z.namelist()
    size = os.path.getsize(TARGET_ZIP)
    bad = [n for n in names if any(s in n for s in FORBIDDEN_SUBSTR)]
    print(f"✅ 已覆盖: {TARGET_ZIP}")
    print(f"   条目数: {len(names)}  体积: {size/1024:.0f} KB")
    if bad:
        sys.stderr.write(f"❌ 包内混入禁用项（{len(bad)} 个），已中断:\n  "
                          + "\n  ".join(bad[:20]) + "\n")
        sys.exit(1)
    print("✅ 无凭据/缓存/开发草稿混入")
    print("✅ 同步完成")


if __name__ == "__main__":
    main()
