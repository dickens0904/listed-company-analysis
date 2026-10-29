# -*- coding: utf-8 -*-
"""
上市公司全景分析 - 安装配置
"""
from setuptools import setup, find_packages

setup(
    name='listed-company-analysis',
    version='1.1.0',
    description='上市公司全景分析工具（A股+港股+美股，15维度，THSDK v2集成）',
    author='龙小新',
    python_requires='>=3.8',
    packages=find_packages(),
    install_requires=[
        'requests>=2.31,<3',
        'pandas>=2.0,<3',          # 原 3.0.2 不存在，已修正
        'PyMuPDF>=1.24',
        'pdfplumber>=0.11',
        'PyPDF2>=3.0',
        'akshare>=1.14',
        'openai>=1.50.0',
        'beautifulsoup4>=4.12',    # 2026-10-22 补：原声明遗漏
        'httpx>=0.27',             # 2026-10-22 补：原声明遗漏
    ],
    extras_require={
        'full': [
            'matplotlib>=3.7',
            # 以下为外部/私有依赖，按需手动安装，不自动拉取：
            # 'cloakbrowser>=0.3.28', 'playwright>=1.40.0', 'playwright-stealth>=1.0.6',
            # 'thsdk==1.7.18'  # 同花顺私有 SDK，非 PyPI
        ],
    },
    entry_points={
        'console_scripts': [
            'company-analysis=analyze:main',
        ],
    },
)
