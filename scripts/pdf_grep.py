# -*- coding: utf-8 -*-
"""
PDF 关键章节定位：按关键词抓上下文，带页码

为什么做（2026-10-20 教训）：
公告深挖只保留 **5000 字预览**，而关键章节往往在第 10 页以后。
实测《详式权益变动报告书》的「第二节 权益变动的目的」在第 13 页 ——
A 组检查因此误判"未取到动因"，我自己也得手写 fitz 才找到。

本脚本把"长文档定位关键章节"这个反复出现的动作固化为一条命令。

用法:
    python scripts/pdf_grep.py <pdf路径> <关键词> [关键词2 ...]
    python scripts/pdf_grep.py xxx.pdf 权益变动的目的 表决权委托 --ctx 500

输出：每个命中点的页码 + 上下文；另附"疑似章节标题"清单
（形如「第X节 XXX」「一、XXX」），方便直接定位要整段抽取的位置。
"""
import sys
import os
import re
import argparse

try:
    import fitz
except ImportError:
    print('需要 PyMuPDF: pip install pymupdf')
    sys.exit(2)


def load_pages(pdf_path: str):
    doc = fitz.open(pdf_path)
    pages = [(i + 1, p.get_text() or '') for i, p in enumerate(doc)]
    doc.close()
    return pages


def find_heading_lines(pages, pat: str):
    """抓疑似章节标题行，用于快速定位要整段读的位置"""
    out = []
    rx = re.compile(pat)
    for pno, txt in pages:
        for line in txt.split('\n'):
            s = line.strip()
            if len(s) > 60 or not s:
                continue
            if rx.search(s):
                out.append((pno, s))
    return out


def main():
    ap = argparse.ArgumentParser(description='PDF 关键章节定位')
    ap.add_argument('pdf', help='PDF 路径')
    ap.add_argument('keywords', nargs='+', help='关键词（多个）')
    ap.add_argument('--ctx', type=int, default=400, help='上下文长度（默认 400 字）')
    ap.add_argument('--max', type=int, default=3, help='每个关键词最多显示几处')
    ap.add_argument('--headings', default=r'第[一二三四五六七八九十]+[章节]|^[一二三四五六七八九十]+、|^\d+\.\s',
                    help='章节标题识别正则')
    a = ap.parse_args()

    if not os.path.exists(a.pdf):
        print(f'文件不存在: {a.pdf}')
        sys.exit(2)

    pages = load_pages(a.pdf)
    print(f'\nPDF: {os.path.basename(a.pdf)}  ({len(pages)} 页)')

    for kw in a.keywords:
        hits = [(pno, txt) for pno, txt in pages if kw in txt]
        print(f'\n{"=" * 78}\n关键词「{kw}」命中 {len(hits)} 页: '
              f'{[p for p, _ in hits][:12]}{" ..." if len(hits) > 12 else ""}')
        shown = 0
        for pno, txt in hits:
            for m in re.finditer(re.escape(kw), txt):
                s = max(0, m.start() - a.ctx)
                seg = txt[s:m.start() + a.ctx].replace('\n', ' ')
                print(f'  [p{pno}] …{seg}…')
                shown += 1
                break
            if shown >= a.max:
                break

    # 章节标题索引（便于决定去读哪一页）
    print(f'\n{"=" * 78}\n疑似章节标题（定位用）:')
    for pno, s in find_heading_lines(pages, a.headings):
        print(f'  p{pno:>3}  {s[:70]}')


if __name__ == '__main__':
    main()
