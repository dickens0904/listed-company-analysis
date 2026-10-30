# -*- coding: utf-8 -*-
"""
skill_path.py — 跨机器通配定位本机 WorkBuddy skill 目录（2026-10-28）

问题：本机 skill 目录在不同机器/用户下路径不同
（C:\\Users\\dicke\\.workbuddy\\skills vs C:\\Users\\Administrator\\.workbuddy\\skills），
硬编码用户名会踩坑。本模块用「环境变量优先 + expanduser 兜底」通配解析，
任何同步/定位脚本都应经此函数，不再写死具体用户名。

用法：
    from skill_path import resolve_skill_root
    root = resolve_skill_root('listed-company-analysis')
    # Windows → %WORKBUDDY_SKILLS%\\listed-company-analysis
    #          或 %USERPROFILE%\\.workbuddy\\skills\\listed-company-analysis
    # 其他    → $WORKBUDDY_SKILLS/listed-company-analysis
    #          或 ~/.workbuddy/skills/listed-company-analysis

也可命令行直接打印：python scripts/skill_path.py
"""
import os


def resolve_local_skills_dir() -> str:
    """返回本机 skills 总目录（跨机器通配，不依赖具体用户名）。"""
    env = os.environ.get('WORKBUDDY_SKILLS')
    if env:
        return env
    # expanduser 在 Windows 展开为 C:\\Users\\<当前用户>\\.workbuddy
    return os.path.join(os.path.expanduser('~'), '.workbuddy', 'skills')


def resolve_skill_root(name: str = 'listed-company-analysis') -> str:
    """跨机器通配定位某 skill 的本地根目录。"""
    return os.path.join(resolve_local_skills_dir(), name)


if __name__ == '__main__':
    print(resolve_skill_root())
