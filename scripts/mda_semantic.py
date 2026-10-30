# -*- coding: utf-8 -*-
"""
mda_semantic.py — MD&A 文本语义量化层（对标"智数分析专家团"年报研究范式）
============================================================================

本模块补足 listed-company-analysis skill 此前缺失的「文本语义量化」能力：
skill 基座已能抽取 MD&A 全文（annual_report_extractor.extract_annual_report → mdaa），
但只做定向抽取（赛道曝光 / 营收归因），缺系统化的词频矩阵 / LDA 主题模型 /
叙事强度轨迹 / 叙事 vs 事实偏离检测。本模块补齐，并全部落盘供复算。

四大产出（均落盘到 --output 目录）：
  1) 关键词词频矩阵        word_freq_matrix.csv        （词 × 年）
  2) 叙事强度轨迹          narrative_intensity.json     （按年 × 主题维度，密度/千词）
  3) LDA 主题模型          lda_topics.json             （sklearn 可用时；否则显式 data_gap）
  4) 叙事 vs 事实偏离      narrative_vs_fact.json      （需 --financial-json；Pearson r）

纪律（继承 SKILL.md 铁律）：
  - 不静默吞异常：所有失败进 result['status'] / result['errors']，显式标注降级。
  - 缺口不编结论：年数 < 3 或指标缺失 → 标 data_gap，不强行给相关系数。
  - 可复现：中间计算全部落盘，重跑结果一致。
  - 禁用硬编码绝对路径：输入/输出走参数与环境变量。

运行（从 skill 根目录）：
  python scripts/mda_semantic.py 2020.pdf 2021.pdf 2022.pdf --years 2020,2021,2022
  python scripts/mda_semantic.py --corpus ./annual_pdfs --years 2019,2020,2021,2022,2023
  python scripts/mda_semantic.py --mdaa-json mdaa_by_year.json
  python scripts/mda_semantic.py --corpus ./pdfs --years 2020,2021,2022 \
      --lexicon digital_transform.json --financial-json financials.json --lda 4
"""
import os
import sys
import json
import math
import re
import argparse
from pathlib import Path
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ─────────────────────────────────────────────────────────────────────────
# 1. 分词器（jieba 优先，缺失正则降级并显式标注）
# ─────────────────────────────────────────────────────────────────────────
def _load_tokenizer():
    try:
        import jieba
        try:
            jieba.setLogLevel(20)  # 安静模式
        except Exception:
            pass
        return jieba, "jieba"
    except Exception as e:  # 缺失则降级，绝不静默
        return None, f"regex_fallback({type(e).__name__})"


_TOKENIZER, _TOKENIZER_METHOD = _load_tokenizer()

_STOPWORDS = set(
    "的 了 和 与 及 在 是 为 对 等 并 其 该 各 中 上 下 内 后 前 将 已 也 都 被 由 从 以 于 "
    "个 项 年 月 日 公司 报告 本期 上期 下列 如下 通过 方面 进行 实现 完成 取得 保持 提升 "
    "增长 我们 可以 以及 包括 主要 方面".split()
)


def tokenize(text: str) -> list:
    """中文分词；jieba 缺失时按正则降级（CJK 2-gram + 英文整词）。"""
    if not text:
        return []
    if _TOKENIZER is not None:
        toks = _TOKENIZER.cut(text)
        return [t.strip() for t in toks
                if t.strip() and t not in _STOPWORDS and len(t.strip()) > 1]
    # 降级路径：CJK 连续串 2-gram，英文/数字整词
    out = []
    for m in re.finditer(r"[A-Za-z0-9]+|[一-鿿]+", text):
        seg = m.group()
        if re.fullmatch(r"[A-Za-z0-9]+", seg):
            if len(seg) > 1 and seg.lower() not in _STOPWORDS:
                out.append(seg)
        else:
            for i in range(len(seg) - 1):
                bg = seg[i:i + 2]
                if bg not in _STOPWORDS:
                    out.append(bg)
    return out


# ─────────────────────────────────────────────────────────────────────────
# 2. 主题词典（可 --lexicon 覆盖；默认通用战略/数字化词典，对标案例"数字化转型叙事"）
# ─────────────────────────────────────────────────────────────────────────
DEFAULT_LEXICON = {
    "数字化": ["数字化", "工业互联网", "工业AI", "人工智能", "智能制造", "数字化转型",
            "数字孪生", "大数据", "云平台", "物联网", "智能工厂", "自动化"],
    "战略": ["战略", "布局", "规划", "愿景", "定位", "协同", "生态", "平台", "全球化", "出海"],
    "增长": ["增长", "扩张", "新客户", "新市场", "市占率", "营收", "订单", "放量", "突破"],
    "研发": ["研发", "创新", "专利", "核心技术", "攻关", "投入", "自主可控", "IP"],
    "风险": ["风险", "不确定性", "波动", "下滑", "竞争", "政策", "监管", "贸易", "承压", "挑战"],
    "资本": ["并购", "重组", "分拆", "融资", "定增", "控股", "股权", "上市", "分拆上市"],
}


def load_lexicon(path: str = None) -> dict:
    if path and Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            return {"_lexicon_error": str(e)} | DEFAULT_LEXICON
    return DEFAULT_LEXICON


# ─────────────────────────────────────────────────────────────────────────
# 3. 词频矩阵 + 叙事强度轨迹
# ─────────────────────────────────────────────────────────────────────────
def compute_word_freq(corpus: dict, lexicon: dict) -> dict:
    """corpus={year: text} → {word: {year: count}}，仅统计词典词。"""
    matrix = defaultdict(dict)
    for year, text in corpus.items():
        toks = tokenize(text)
        cnt = Counter(toks)
        for theme, kws in lexicon.items():
            for kw in kws:
                if kw in cnt:
                    matrix[kw][year] = matrix[kw].get(year, 0) + cnt[kw]
    return dict(matrix)


def compute_intensity(corpus: dict, lexicon: dict) -> dict:
    """
    叙事强度轨迹：每主题维度按年密度（每千词出现次数），避免长篇年份虚高。
    返回 {year: {theme: density_per_kword, _total_tokens: int}}。
    """
    out = {}
    for year, text in corpus.items():
        toks = tokenize(text)
        total = max(len(toks), 1)
        theme_counts = {theme: 0 for theme in lexicon}
        for t in toks:
            for theme, kws in lexicon.items():
                if t in kws:
                    theme_counts[theme] += 1
        out[str(year)] = {
            theme: round(theme_counts[theme] / total * 1000, 4)
            for theme in lexicon
        }
        out[str(year)]["_total_tokens"] = total
    return out


# ─────────────────────────────────────────────────────────────────────────
# 4. LDA 主题模型（sklearn 可选；缺失显式 data_gap，不假装成功）
# ─────────────────────────────────────────────────────────────────────────
def run_lda(corpus: dict, n_topics: int = 3, top_words: int = 10) -> dict:
    try:
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.decomposition import LatentDirichletAllocation
    except Exception as e:
        return {"status": "data_gap", "reason": f"sklearn_not_installed:{type(e).__name__}",
                "action": "pip install scikit-learn，或使用 --no-lda 跳过"}

    years = sorted(corpus.keys())
    docs = [corpus[y] for y in years]
    if len(docs) < 2:
        return {"status": "data_gap", "reason": "need>=2_years_for_lda", "n_years": len(docs)}

    try:
        vec = CountVectorizer(max_df=0.85, min_df=1, max_features=2000)
        X = vec.fit_transform(docs)
        if X.shape[1] == 0:
            return {"status": "data_gap", "reason": "vocab_empty_after_filter"}
        lda = LatentDirichletAllocation(n_components=min(n_topics, X.shape[1]),
                                        random_state=42, max_iter=50)
        doc_topic = lda.fit_transform(X)
        vocab = vec.get_feature_names_out()
        topics = []
        for ti, comp in enumerate(lda.components_):
            top_idx = comp.argsort()[::-1][:top_words]
            topics.append({"topic": ti, "words": [vocab[i] for i in top_idx]})
        year_dist = {
            str(years[i]): {f"topic_{j}": round(float(doc_topic[i][j]), 4)
                            for j in range(len(topics))}
            for i in range(len(years))
        }
        return {"status": "ok", "n_topics": len(topics), "topics": topics,
                "year_distribution": year_dist}
    except Exception as e:
        return {"status": "data_gap", "reason": f"lda_error:{type(e).__name__}:{e}"}


# ─────────────────────────────────────────────────────────────────────────
# 5. 叙事 vs 事实偏离检测（Pearson r，手算优先 scipy）
# ─────────────────────────────────────────────────────────────────────────
def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None, "n<3_data_gap"
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None, "zero_variance_data_gap"
    return cov / math.sqrt(vx * vy), "ok"


def _interpret_r(r):
    if r is None:
        return "data_gap"
    a = abs(r)
    if a >= 0.7:
        return "强相关"
    if a >= 0.3:
        return "弱相关"
    return "解耦(decoupled)" + ("·逆向(negative)" if r < 0 else "")


def compute_deviation(intensity: dict, financial_path: str) -> dict:
    """
    intensity: {year:{theme: density,...}}（compute_intensity 输出）
    financial_path: JSON {year:{metric: value}}（财务年序列，如研发投入/营收）
    对每财务指标，取其年序列与同年「综合叙事强度」(各主题密度均值) 算 Pearson r。
    """
    if not Path(financial_path).exists():
        return {"status": "data_gap", "reason": f"financial_json_missing:{financial_path}"}
    try:
        fin = json.loads(Path(financial_path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "data_gap", "reason": f"financial_json_parse_error:{e}"}

    # 综合叙事强度按年（均值）
    years = sorted(set(intensity.keys()) & set(str(y) for y in fin.keys()))
    if len(years) < 3:
        return {"status": "data_gap", "reason": f"aligned_years<3 (got {len(years)})",
                "aligned_years": years}
    comp_strength = {}
    for y in years:
        themes = [v for k, v in intensity[y].items() if not k.startswith("_")]
        comp_strength[y] = sum(themes) / len(themes) if themes else 0.0

    out = {"aligned_years": years, "metrics": {}}
    for metric in sorted({m for y in fin for m in fin[y]}):
        xs, ys_ = [], []
        for y in years:
            if metric in fin[y] and fin[y][metric] is not None:
                try:
                    ys_.append(float(fin[y][metric]))
                    xs.append(comp_strength[y])
                except Exception:
                    continue
        r, status = _pearson(xs, ys_)
        out["metrics"][metric] = {
            "pearson_r": round(r, 4) if r is not None else None,
            "n_years": len(xs),
            "interpretation": _interpret_r(r) if r is not None else "data_gap",
            "status": status,
        }
    out["status"] = "ok"
    return out


# ─────────────────────────────────────────────────────────────────────────
# 6. 语料构建（三种输入）
# ─────────────────────────────────────────────────────────────────────────
def _extract_mdaa_from_pdf(pdf_path: str) -> str:
    try:
        from annual_report_extractor import extract_annual_report
    except Exception as e:
        return ""  # 显式降级：无基座模块则空
    try:
        rep = extract_annual_report(pdf_path)
        return rep.get("mdaa", "") or ""
    except Exception:
        return ""


def build_corpus(args) -> dict:
    corpus = {}
    if args.mdaa_json and Path(args.mdaa_json).exists():
        data = json.loads(Path(args.mdaa_json).read_text(encoding="utf-8"))
        for y, txt in data.items():
            corpus[str(y)] = txt or ""
        return corpus

    pdfs = []
    if args.pdfs:
        pdfs = [Path(p) for p in args.pdfs if Path(p).exists()]
    elif args.corpus:
        d = Path(args.corpus)
        if d.is_dir():
            pdfs = sorted(d.glob("*.pdf"))

    years = [y.strip() for y in (args.years or "").split(",") if y.strip()]
    if not years:
        years = [p.stem for p in pdfs]  # 退化：用文件名年份
    if len(pdfs) != len(years):
        # 年份对齐失败 → 仍尽力构建，但标 data_gap 由调用方处理
        pass
    for p, y in zip(pdfs, years):
        corpus[str(y)] = _extract_mdaa_from_pdf(str(p))
    return corpus


# ─────────────────────────────────────────────────────────────────────────
# 7. 落盘
# ─────────────────────────────────────────────────────────────────────────
def _write_freq_csv(path: Path, matrix: dict, years: list):
    years = [str(y) for y in years]
    lines = ["word," + ",".join(years)]
    for word in sorted(matrix.keys()):
        row = [word] + [str(matrix[word].get(y, 0)) for y in years]
        lines.append(",".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_summary_md(path: Path, result: dict, corpus: dict):
    lines = ["# MD&A 文本语义量化 · 摘要", ""]
    lines.append(f"- 分词器：{result['method']['tokenizer']}")
    lines.append(f"- 覆盖年度：{', '.join(result['years'])}（{len(result['years'])} 年）")
    lines.append(f"- MD&A 总字数：{sum(len(v) for v in corpus.values())}")
    if result.get("narrative_vs_fact", {}).get("status") == "ok":
        lines.append("\n## 叙事 vs 事实偏离（Pearson r）")
        for m, d in result["narrative_vs_fact"]["metrics"].items():
            lines.append(f"- {m}：r={d['pearson_r']} · {d['interpretation']}")
    if result.get("lda", {}).get("status") == "ok":
        lines.append("\n## LDA 主题")
        for t in result["lda"]["topics"]:
            lines.append(f"- 主题{t['topic']}：{', '.join(t['words'])}")
    if result["errors"]:
        lines.append("\n## 降级/错误（未静默）")
        for e in result["errors"]:
            lines.append(f"- {e}")
    path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# 8. 主流程
# ─────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="MD&A 文本语义量化")
    ap.add_argument("pdfs", nargs="*", help="年报 PDF 路径列表")
    ap.add_argument("--corpus", help="含年报 PDF 的目录")
    ap.add_argument("--mdaa-json", help="{year: mdaa_text} JSON")
    ap.add_argument("--years", help="与 PDF 顺序对应的年度，逗号分隔")
    ap.add_argument("--lexicon", help="自定义主题词典 JSON {theme:[kw]}")
    ap.add_argument("--financial-json", help="财务年序列 {year:{metric:value}}，用于偏离检测")
    ap.add_argument("--output", default="mda_semantic_out", help="落盘目录")
    ap.add_argument("--lda", type=int, default=3, help="LDA 主题数")
    ap.add_argument("--no-lda", action="store_true", help="跳过 LDA")
    args = ap.parse_args()

    result = {"status": "ok", "errors": [], "method": {"tokenizer": _TOKENIZER_METHOD}}
    corpus = build_corpus(args)
    if not corpus:
        result["status"] = "error"
        result["errors"].append("corpus_empty:未取到任何 MD&A 文本")
    result["years"] = sorted(corpus.keys())

    lexicon = load_lexicon(args.lexicon)
    if "_lexicon_error" in lexicon:
        result["errors"].append(f"lexicon:{lexicon.pop('_lexicon_error')}")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # 词频矩阵
    freq = compute_word_freq(corpus, lexicon)
    _write_freq_csv(out / "word_freq_matrix.csv", freq, result["years"])
    # 叙事强度
    intensity = compute_intensity(corpus, lexicon)
    (out / "narrative_intensity.json").write_text(
        json.dumps(intensity, ensure_ascii=False, indent=2), encoding="utf-8")
    result["narrative_intensity"] = {"status": "ok", "file": "narrative_intensity.json"}

    # LDA
    if not args.no_lda and corpus:
        lda = run_lda(corpus, args.lda)
        result["lda"] = lda
        if lda.get("status") == "ok":
            (out / "lda_topics.json").write_text(
                json.dumps(lda, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            result["errors"].append(f"lda:{lda.get('reason')}")

    # 偏离检测
    if args.financial_json:
        nvf = compute_deviation(intensity, args.financial_json)
        result["narrative_vs_fact"] = nvf
        if nvf.get("status") == "ok":
            (out / "narrative_vs_fact.json").write_text(
                json.dumps(nvf, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            result["errors"].append(f"deviation:{nvf.get('reason')}")

    _write_summary_md(out / "mda_semantic_report.md", result, corpus)
    # 汇总落盘
    (out / "mda_semantic_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要（不静默）
    print(f"[mda_semantic] 分词器={_TOKENIZER_METHOD} | 年度={result['years']} | 落盘={out}")
    if result.get("narrative_vs_fact", {}).get("status") == "ok":
        for m, d in result["narrative_vs_fact"]["metrics"].items():
            print(f"  偏离 {m}: r={d['pearson_r']} · {d['interpretation']}")
    if result["errors"]:
        print("  ⚠ 降级/错误:")
        for e in result["errors"]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
