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
        'requests==2.33.1',
        'pandas==3.0.2',
        'PyMuPDF==1.27.2.2',
        'akshare==1.18.53',
        'thsdk==1.7.18',
    ],
    extras_require={
        'full': [
            'pdfplumber==0.11.9',
            'matplotlib==3.10.8',
        ],
    },
    entry_points={
        'console_scripts': [
            'company-analysis=analyze:main',
        ],
    },
)
