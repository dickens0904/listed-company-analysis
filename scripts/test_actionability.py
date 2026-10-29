# -*- coding: utf-8 -*-
"""
test_actionability.py — 公告洪水过滤分类器回归测试
=====================================================
2026-10-19 实跑 002180 暴露：225 条"事件"里 52% 是程序性文件
（进展公告/独立董事意见/核查意见/法律意见书…），把真动作全埋了。
修复 = classify_actionability()。规则易过拟合（本次已踩两次：
  ① `的公告$` 误伤「关于资产收购完成的公告」
  ② `的说明` 误伤「…履行法定程序的完备性…的说明」），
故固化为单测，任何改动必须跑过。

运行：python test_actionability.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))

try:
    from scripts.joint_action_narrative import classify_actionability
except ImportError:
    from joint_action_narrative import classify_actionability


# 必须是「真正的联合动作」才入叙事时间线
MUST_ACTION = [
    "纳思达：关于资产收购完成的公告",
    "奔图科技：关于收购珠海赛纳打印科技股份有限公司少数股权的公告",
    "奔图科技：完成对利盟国际的收购，实现全资控股",
    "国家集成电路产业投资基金股份有限公司关于认购公司非公开发行股票的锁定承诺函",
    "公司拟设立海外研发中心并签署投资协议",
    "纳思达：关于发行股份及支付现金购买资产并募集配套资金暨关联交易预案",
    "奔图科技：关于放弃认购权暨关联交易的公告",
    "公司对外投资设立子公司并签署合资协议",
    "公司拟回购股份并实施股权激励",
]

# 收尾：拿到监管批复本身是程序节点，不是独立动作（批复事实由更早的申报文件承载）
MUST_PROCEDURE_EXTRA = [
    "奔图科技：关于收到中国证券监督管理委员会核准批复的公告",
]

# 必须是「程序性/中介文件」——同一笔交易的副产品，不算独立动作
MUST_PROCEDURE = [
    "艾派克：董事会关于本次交易符合《…》第四条规定的说明",
    "拟发行股份购买资产所涉及的…耗材业务资产组价值评估说明",
    "关于本次重大资产重组履行法定程序的完备性、合规性及提交的法律文件的有效性的说明",
    "发行股份购买资产报告书与预案差异对照表",
    "上市公司并购重组财务顾问专业意见附表第3号——发行股份购买资产",
    "关于收到中国证监会…审核委员会审核…事项的提示性公告",
    "关于筹划重大资产重组停牌前一个交易日前十大股东持股情况的公告",
    "发行股份购买资产实施2019年度利润分配方案后调整股票发行价格和发行数量的公告",
    "关于重大资产重组进展暨继续停牌的公告",
    "关于重组报告书修订说明的公告",
    "关于独立董事意见的公告",
    "华融证券关于…之独立财务顾问核查意见",
    "艾派克：关于重大资产重组的进展公告",
    "北京市金杜律师事务所关于…之法律意见书",
    "关于2014年度重大资产重组购买资产盈利预测实现情况的说明",
]


def main() -> int:
    fails = []
    for t in MUST_ACTION:
        a, role = classify_actionability(t)
        if a != 'action':
            fails.append(f'  ✗ 期望 action 实得 {a}({role}) | {t}')
    for t in MUST_PROCEDURE + MUST_PROCEDURE_EXTRA:
        a, role = classify_actionability(t)
        if a != 'procedure':
            fails.append(f'  ✗ 期望 procedure 实得 {a}({role}) | {t}')

    total = len(MUST_ACTION) + len(MUST_PROCEDURE) + len(MUST_PROCEDURE_EXTRA)
    print('=' * 60)
    print(f'公告洪水过滤 · 分类器回归：{total - len(fails)}/{total} 通过')
    print('=' * 60)
    if fails:
        print('\n'.join(fails))
        print('\n🔴 有用例失败——规则被改坏了，请修正 PROCEDURE_PATTERNS / _ACTION_HINTS')
        return 1
    print('✅ 全过。规则改动请同步更新本文件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())