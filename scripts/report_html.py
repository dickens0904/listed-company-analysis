# -*- coding: utf-8 -*-
"""
HTML报告生成器
从已生成的 report.md 直接转换为 HTML 格式
"""
import os
import re
from datetime import datetime


def md_to_html(md_text):
    """将Markdown文本转换为HTML（支持表格、代码块、标题、引用等）"""
    html_parts = []
    lines = md_text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.startswith('```'):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(_escape_html(lines[i]))
                i += 1
            i += 1  # skip closing ```
            html_parts.append('<pre><code class="language-' + lang + '">' + chr(10).join(code_lines) + '</code></pre>')
            continue

        # 表格
        if '|' in line and i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip()):
            table_lines = []
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            html_parts.append(_render_table(table_lines))
            continue

        # 标题
        if line.startswith('#### '):
            html_parts.append('<h4>' + _inline_format(line[5:]) + '</h4>')
        elif line.startswith('### '):
            html_parts.append('<h3>' + _inline_format(line[4:]) + '</h3>')
        elif line.startswith('## '):
            html_parts.append('<h2>' + _inline_format(line[3:]) + '</h2>')
        elif line.startswith('# '):
            html_parts.append('<h1>' + _inline_format(line[2:]) + '</h1>')

        # 引用块
        elif line.startswith('> '):
            quote_lines = [line[2:]]
            while i + 1 < len(lines) and lines[i + 1].startswith('> '):
                i += 1
                quote_lines.append(lines[i][2:])
            html_parts.append('<blockquote>' + _inline_format(chr(10).join(quote_lines)) + '</blockquote>')

        # 水平线
        elif line.strip() in ('---', '***', '___'):
            html_parts.append('<hr>')

        # 无序列表
        elif re.match(r'^[-*+] ', line):
            list_items = []
            while i < len(lines) and re.match(r'^[-*+] ', lines[i]):
                list_items.append(_inline_format(lines[i][2:]))
                i += 1
            lis = ''.join('<li>' + item + '</li>' for item in list_items)
            html_parts.append('<ul>' + lis + '</ul>')
            continue

        # 有序列表
        elif re.match(r'^\d+\. ', line):
            list_items = []
            while i < len(lines) and re.match(r'^\d+\. ', lines[i]):
                item_text = re.sub(r'^\d+\. ', '', lines[i])
                list_items.append(_inline_format(item_text))
                i += 1
            lis = ''.join('<li>' + item + '</li>' for item in list_items)
            html_parts.append('<ol>' + lis + '</ol>')
            continue

        # 空行
        elif line.strip() == '':
            pass

        # 普通段落
        else:
            para_lines = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(('#', '>', '`', '|', '-', '*', '+')) and not re.match(r'^\d+\. ', lines[i + 1]):
                i += 1
                para_lines.append(lines[i])
            text = ' '.join(para_lines)
            if text.strip().startswith('<') and text.strip().endswith('>'):
                html_parts.append(text)
            else:
                html_parts.append('<p>' + _inline_format(text) + '</p>')

        i += 1

    return '\n'.join(html_parts)


def _escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _inline_format(text):
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


def _render_table(table_lines):
    """将Markdown表格转换为HTML表格，支持对齐和样式优化"""
    if len(table_lines) < 2:
        return '<p>' + _escape_html(table_lines[0]) + '</p>'

    def parse_row(line):
        cells = [c.strip() for c in line.strip('|').split('|')]
        return [('' if c.lower() in ('none', 'nan', 'null') else c) for c in cells]

    def detect_alignment(line):
        """检测对齐方式：:-左对齐，:-:居中，-:右对齐"""
        cells = [c.strip() for c in line.strip('|').split('|')]
        alignments = []
        for cell in cells:
            cell = cell.replace(' ', '')
            if cell.startswith(':') and cell.endswith(':'):
                alignments.append('center')
            elif cell.endswith(':'):
                alignments.append('right')
            else:
                alignments.append('left')
        return alignments

    headers = parse_row(table_lines[0])
    alignments = detect_alignment(table_lines[1]) if len(table_lines) > 1 else ['left'] * len(headers)
    rows = [parse_row(line) for line in table_lines[2:]]

    # 构建colgroup用于列宽控制
    col_widths = []
    for i, h in enumerate(headers):
        col_widths.append('')

    html = ['<div class="table-wrapper"><table>']
    
    # 添加colgroup
    html.append('<colgroup>')
    for w in col_widths:
        if w:
            html.append(f'<col style="width: {w}">')
        else:
            html.append('<col>')
    html.append('</colgroup>')
    
    html.append('<thead><tr>')
    for i, h in enumerate(headers):
        align = alignments[i] if i < len(alignments) else 'left'
        html.append(f'<th style="text-align: {align}">' + _inline_format(h) + '</th>')
    html.append('</tr></thead>')
    
    html.append('<tbody>')
    for row_idx, row in enumerate(rows):
        html.append('<tr>')
        for cell_idx, cell in enumerate(row):
            align = alignments[cell_idx] if cell_idx < len(alignments) else 'left'
            # 检测是否为数字内容，自动右对齐
            if _is_numeric_cell(cell):
                align = 'right'
            html.append(f'<td style="text-align: {align}">' + _inline_format(cell) + '</td>')
        html.append('</tr>')
    html.append('</tbody></table></div>')
    return '\n'.join(html)


def _is_numeric_cell(cell):
    """检测单元格是否为数字内容（金额、百分比、分数等）"""
    import re
    # 移除常见的非数字字符
    cleaned = cell.replace(',', '').replace(' ', '')
    # 匹配数字、金额、百分比、分数
    return bool(re.match(r'^-?[\d,]+\.?\d*[亿万元/%个百分点]?$', cleaned)) or \
           bool(re.match(r'^-?\d+/\d+$', cleaned))


def generate_html_report(results, out_dir):
    """从 report.md 生成 HTML 报告"""
    stock = results.get('stock', '')
    market = results.get('market', 'a')
    market_name = {'a': 'A股', 'hk': '港股', 'us': '美股'}.get(market, market)

    md_path = os.path.join(out_dir, 'report.md')
    if not os.path.exists(md_path):
        raise FileNotFoundError('report.md 不存在: ' + md_path)

    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    title_match = re.match(r'^# (.+)$', md_text, re.MULTILINE)
    page_title = title_match.group(1) if title_match else stock + ' ' + market_name + ' 全景分析报告'

    toc_items = re.findall(r'^## (.+)$', md_text, re.MULTILINE)

    report_content = md_to_html(md_text)

    # 生成目录
    toc_html = '<div class="toc"><h2>目录</h2><ul>'
    for idx, item in enumerate(toc_items):
        toc_html += '<li><a href="#section-' + str(idx) + '">' + item + '</a></li>'
    toc_html += '</ul></div>'

    # 给 h2 添加锚点
    anchor_counter = [0]
    def add_anchor(m):
        idx = anchor_counter[0]
        anchor_counter[0] += 1
        return '<h2 id="section-' + str(idx) + '">' + m.group(1) + '</h2>'
    report_content = re.sub(r'<h2>(.+?)</h2>', add_anchor, report_content)

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    now_full = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    html_content = _HTML_TEMPLATE.replace('{{PAGE_TITLE}}', page_title) \
        .replace('{{STOCK}}', stock) \
        .replace('{{NOW}}', now) \
        .replace('{{NOW_FULL}}', now_full) \
        .replace('{{TOC_HTML}}', toc_html) \
        .replace('{{REPORT_CONTENT}}', report_content)

    report_path = os.path.join(out_dir, 'report.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return report_path


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{PAGE_TITLE}}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
            line-height: 1.8;
            color: #333;
            background: #f0f2f5;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: white; padding: 40px; border-radius: 12px;
            margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        .header h1 { margin: 0 0 12px 0; font-size: 26px; font-weight: 700; }
        .header .meta { font-size: 14px; opacity: 0.85; }
        .toc {
            background: white; padding: 24px 30px; border-radius: 10px;
            margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }
        .toc h2 {
            margin: 0 0 16px 0; font-size: 18px; color: #0f3460;
            border-bottom: 2px solid #0f3460; padding-bottom: 8px;
        }
        .toc ul { list-style: none; padding: 0; columns: 2; column-gap: 30px; }
        .toc li { padding: 4px 0; break-inside: avoid; }
        .toc a { color: #0f3460; text-decoration: none; font-size: 14px; transition: color 0.2s; }
        .toc a:hover { color: #e94560; text-decoration: underline; }
        .content {
            background: white; padding: 40px; border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06); font-size: 15px;
        }
        .content h1 { font-size: 24px; color: #1a1a2e; margin: 30px 0 16px; padding-bottom: 8px; border-bottom: 3px solid #0f3460; }
        .content h2 { font-size: 20px; color: #16213e; margin: 36px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e8e8e8; scroll-margin-top: 20px; }
        .content h3 { font-size: 17px; color: #333; margin: 24px 0 12px; }
        .content h4 { font-size: 15px; color: #555; margin: 20px 0 8px; }
        .content p { margin: 8px 0; text-align: justify; }
        .content table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; table-layout: auto; }
        .content .table-wrapper { overflow-x: auto; max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .content table { border: 1px solid #dde2e8; }
        .content th, .content td { border: 1px solid #e8ecf0; padding: 10px 14px; text-align: left; word-break: break-word; }
        .content th { background: linear-gradient(135deg, #1a1a2e, #0f3460); color: white; font-weight: 600; white-space: nowrap; position: sticky; top: 0; z-index: 1; }
        .content tr:nth-child(even) { background: #f8fafc; }
        .content tr:hover { background: #e8f4fd; transition: background-color 0.2s ease; }
        .content td { vertical-align: top; }
        .content td[style*="text-align: right"] { font-variant-numeric: tabular-nums; }
        .content colgroup col:first-child { min-width: 120px; }
        .content blockquote { border-left: 4px solid #0f3460; margin: 16px 0; padding: 12px 20px; background: #f0f4f8; color: #555; border-radius: 0 6px 6px 0; }
        .content pre { background: #1a1a2e; color: #e0e0e0; padding: 16px; border-radius: 8px; overflow-x: auto; margin: 16px 0; font-size: 13px; }
        .content code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-family: "Cascadia Code", "Fira Code", Consolas, monospace; font-size: 0.9em; }
        .content pre code { background: none; padding: 0; }
        .content ul, .content ol { margin: 8px 0; padding-left: 24px; }
        .content li { margin: 4px 0; }
        .content hr { border: none; border-top: 1px solid #e0e0e0; margin: 24px 0; }
        .content a { color: #0f3460; text-decoration: none; border-bottom: 1px dotted #0f3460; }
        .content a:hover { color: #e94560; }
        .footer { text-align: center; padding: 30px; color: #999; font-size: 12px; }
        .font-toolbar {
            position: fixed; top: 20px; right: 20px; background: white;
            padding: 8px 14px; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.12);
            display: flex; align-items: center; gap: 6px; z-index: 1000; font-size: 13px;
        }
        .font-toolbar button {
            width: 28px; height: 28px; border: 1px solid #ddd; border-radius: 4px;
            background: #f8f9fa; cursor: pointer; font-size: 16px; font-weight: bold;
            color: #333; display: flex; align-items: center; justify-content: center; transition: all 0.15s;
        }
        .font-toolbar button:hover { background: #0f3460; color: white; border-color: #0f3460; }
        .font-toolbar .font-size-display { min-width: 32px; text-align: center; font-weight: 600; color: #0f3460; }
        @media (max-width: 768px) {
            .container { padding: 10px; }
            .header { padding: 20px; }
            .content { padding: 20px; }
            .toc ul { columns: 1; }
            .font-toolbar { top: 10px; right: 10px; }
        }
    </style>
</head>
<body>
    <div class="font-toolbar">
        <button onclick="adjustFont(-1)" title="缩小字号">A-</button>
        <span class="font-size-display" id="fontSizeDisplay">15</span>
        <button onclick="adjustFont(1)" title="放大字号">A+</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{PAGE_TITLE}}</h1>
            <div class="meta">生成时间: {{NOW}} | 股票代码: {{STOCK}}</div>
        </div>
        {{TOC_HTML}}
        <div class="content" id="reportContent">
{{REPORT_CONTENT}}
        </div>
        <div class="footer">
            <p>本报告由上市公司分析系统自动生成，仅供参考，不构成投资建议</p>
            <p>生成时间: {{NOW_FULL}}</p>
        </div>
    </div>
    <script>
        var currentSize = 15;
        function adjustFont(d) {
            currentSize = Math.max(12, Math.min(22, currentSize + d));
            document.getElementById('reportContent').style.fontSize = currentSize + 'px';
            document.getElementById('fontSizeDisplay').textContent = currentSize;
        }
    </script>
</body>
</html>"""


if __name__ == '__main__':
    import json
    import argparse

    parser = argparse.ArgumentParser(description='从report.md生成HTML报告')
    parser.add_argument('--results', required=True, help='results.json文件路径')
    parser.add_argument('--output', required=True, help='输出目录')

    args = parser.parse_args()

    with open(args.results, 'r', encoding='utf-8') as f:
        results = json.load(f)

    os.makedirs(args.output, exist_ok=True)
    report_path = generate_html_report(results, args.output)
    print('HTML报告已生成: ' + report_path)
