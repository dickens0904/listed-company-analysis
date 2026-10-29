# -*- coding: utf-8 -*-
"""
生成A股行业PE基准表 (修复版)
- 抑制所有logging输出
- 每行业仅打印1行摘要
- 完成后才写入文件
"""
import sys, os, time, json

# 抑制THSDK logging
import logging
for logger_name in ['thsdk', 'th_cli', 'THSDK']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.CRITICAL + 1)

sys.path.insert(0, r'C:\Users\Administrator\.qclaw\workspace-agent-550df5d1\skills\listed-company-analysis\scripts')
from thsdk_search import ThsdkSearch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, 'data', 'industry_pe_benchmark.json')
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

MAX_STOCKS = 20
PE_MIN, PE_MAX = 0.1, 500
RATE_LIMIT_MS = 60

def weighted_avg_pe(stocks):
    total_cap = sum(s['mktcap'] for s in stocks if s['mktcap'] > 0)
    if total_cap == 0:
        return None
    return round(sum(s['pe'] * s['mktcap'] for s in stocks) / total_cap, 2)

def main():
    sys.stdout.write('[1/3] 获取行业列表...\n')
    sys.stdout.flush()
    ts = ThsdkSearch()
    result = ts.industry_list()
    if not result['success']:
        sys.stdout.write('ERROR: 获取行业列表失败\n')
        return
    industries = result['data']
    sys.stdout.write('  => 共 %d 个行业\n' % len(industries))
    sys.stdout.flush()

    benchmark = {}
    failed = []

    sys.stdout.write('[2/3] 遍历行业获取PE (silent mode)...\n')
    sys.stdout.flush()

    for i, ind in enumerate(industries):
        code = ind['代码'].replace('URFI', '')
        name = ind['名称']

        try:
            cons = ts.block_constituents(code)
            if not cons['success'] or not cons['data']:
                failed.append({'code': code, 'name': name, 'reason': 'no_data'})
                sys.stdout.write('.')
                sys.stdout.flush()
                continue

            valid = []
            for stock in cons['data'][:MAX_STOCKS]:
                scode = stock['代码'][4:]
                time.sleep(RATE_LIMIT_MS / 1000)
                q = ts.quote(scode)
                if not q or not q.get('success'):
                    continue
                pe = q['data'].get('市盈率TTM', 0)
                mkt = q['data'].get('总市值', 0)
                if pe and PE_MIN <= pe <= PE_MAX:
                    valid.append({'name': stock['名称'], 'pe': pe, 'mktcap': mkt})

            if valid:
                w_pe = weighted_avg_pe(valid)
                benchmark[code] = {
                    'name': name, 'ths_code': ind['代码'],
                    'weighted_pe': w_pe, 'sample_count': len(valid),
                    'constituent_count': cons['total'],
                    'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                sys.stdout.write('\n[%d/%d] %s: PE=%.1f, n=%d' % (i+1, len(industries), name, w_pe, len(valid)))
            else:
                failed.append({'code': code, 'name': name, 'reason': 'no_valid_pe'})
                sys.stdout.write('x')
            sys.stdout.flush()

        except Exception as e:
            failed.append({'code': code, 'name': name, 'reason': str(e)})
            sys.stdout.write('E')
            sys.stdout.flush()
            time.sleep(0.5)

    ts.close()

    sys.stdout.write('\n\n[3/3] 写入文件...\n')
    sys.stdout.flush()

    output = {
        'meta': {
            'total': len(industries), 'success': len(benchmark), 'failed': len(failed),
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
        'benchmark': benchmark,
        'failed': failed
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 汇总打印
    sys.stdout.write('\n=== 完成 ===\n')
    sys.stdout.write('成功: %d/%d | 失败: %d\n' % (len(benchmark), len(industries), len(failed)))
    sys.stdout.write('文件: %s\n' % OUTPUT_FILE)
    sys.stdout.write('\n=== 行业PE基准表 ===\n')
    sys.stdout.write('%-6s | %-10s | %-6s | %-5s\n' % ('代码', '行业', '加权PE', '样本'))
    sys.stdout.write('-' * 40 + '\n')
    for code in sorted(benchmark.keys(), key=lambda x: benchmark[x]['weighted_pe'] or 999):
        d = benchmark[code]
        sys.stdout.write('%-6s | %-10s | %-6s | %-5d\n' % (
            code, d['name'],
            '%.1f' % d['weighted_pe'] if d['weighted_pe'] else 'N/A',
            d['sample_count']))
    sys.stdout.flush()

if __name__ == '__main__':
    main()