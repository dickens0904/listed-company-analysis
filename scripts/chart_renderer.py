# -*- coding: utf-8 -*-
"""
chart_renderer.py — 研报图表生成器

生成 HTML/CSS 图表（基于内联 Chart.js），直接嵌入研究报告。
支持：营收趋势/估值带/盈利预测瀑布图/同业对比柱状图。

用法:
    from chart_renderer import ChartRenderer
    cr = ChartRenderer()
    html = cr.render_all(projection_data, peer_data, multi_year_data)
"""
import json
from datetime import datetime


class ChartRenderer:
    def __init__(self):
        self.charts = []

    def _chart_html(self, chart_id: str, config: dict) -> str:
        """生成单个 Chart.js 图表的 HTML 片段"""
        cfg_json = json.dumps(config, ensure_ascii=False)
        return f'''
<div class="chart-container" style="margin:20px 0; max-width:800px;">
    <canvas id="{chart_id}" style="max-height:400px;"></canvas>
</div>
<script>
new Chart(document.getElementById("{chart_id}"), {cfg_json});
</script>'''

    def revenue_trend(self, historical: dict, projection: dict) -> str:
        """营收历史+预测趋势图"""
        labels = historical.get("years", []) + projection.get("years", [])
        hist_data = historical.get("revenue_yi", [])
        proj_data = [None] * (len(historical.get("years", [])) - 1) + [hist_data[-1]] + projection.get("revenue_yi", [])
        # pad historical
        hist_padded = hist_data + [None] * len(projection.get("years", []))

        config = {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": "历史营收（亿元）",
                        "data": hist_padded,
                        "borderColor": "#1a73e8", "backgroundColor": "rgba(26,115,232,0.1)",
                        "borderWidth": 3, "pointRadius": 5, "fill": False
                    },
                    {
                        "label": "预测营收（亿元）",
                        "data": proj_data,
                        "borderColor": "#e8710a", "backgroundColor": "rgba(232,113,10,0.2)",
                        "borderWidth": 2, "borderDash": [5,5], "pointRadius": 5, "fill": False
                    },
                ]
            },
            "options": {
                "responsive": True,
                "plugins": {"title": {"display": True, "text": "营业收入历史与预测", "font": {"size": 16}}},
                "scales": {"y": {"title": {"display": True, "text": "亿元"}}}
            }
        }
        return self._chart_html("revenue_chart", config)

    def eps_projection(self, projection: dict) -> str:
        """EPS预测柱状图"""
        labels = projection.get("years", [])
        eps_data = projection.get("eps", [])

        config = {
            "type": "bar",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": "预测EPS（元/股）",
                    "data": eps_data,
                    "backgroundColor": ["#4caf50", "#2196f3", "#9c27b0"],
                    "borderRadius": 4,
                }]
            },
            "options": {
                "responsive": True,
                "plugins": {"title": {"display": True, "text": "每股收益预测 (EPS)", "font": {"size": 16}}},
            }
        }
        return self._chart_html("eps_chart", config)

    def peer_comparison(self, peers: list, stock_code: str) -> str:
        """同业对比柱状图（PE/PB）"""
        names = [p.get("name", p.get("code", ""))[:6] for p in peers[:8]]
        pe_vals = [p.get("pe", 0) for p in peers[:8]]
        pb_vals = [p.get("pb", 0) for p in peers[:8]]

        config = {
            "type": "bar",
            "data": {
                "labels": names,
                "datasets": [
                    {"label": "PE(TTM)", "data": pe_vals, "backgroundColor": "#e74c3c", "yAxisID": "y"},
                    {"label": "PB", "data": pb_vals, "backgroundColor": "#3498db", "yAxisID": "y1"},
                ]
            },
            "options": {
                "responsive": True,
                "plugins": {"title": {"display": True, "text": f"同业估值对比 (PE/PB)", "font": {"size": 16}}},
                "scales": {
                    "y": {"position": "left", "title": {"display": True, "text": "PE"}},
                    "y1": {"position": "right", "title": {"display": True, "text": "PB"}, "grid": {"drawOnChartArea": False}},
                }
            }
        }
        return self._chart_html("peer_chart", config)

    def valuation_band(self, historical_pe: list, current_pe: float) -> str:
        """历史PE估值带"""
        if not historical_pe:
            return ""
        labels = [f"PE{i+1}" for i in range(len(historical_pe))]
        pe_sorted = sorted([p for p in historical_pe if p > 0])

        config = {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": "历史PE",
                        "data": historical_pe + [current_pe],
                        "borderColor": "#95a5a6", "pointRadius": 3, "fill": False,
                    },
                    {
                        "label": "当前PE",
                        "data": [None] * len(historical_pe) + [current_pe],
                        "borderColor": "#e74c3c", "pointRadius": 8, "pointBackgroundColor": "#e74c3c",
                    },
                ]
            },
            "options": {
                "responsive": True,
                "plugins": {"title": {"display": True, "text": f"历史PE估值带 (当前: {current_pe:.1f}倍)", "font": {"size": 16}}},
            }
        }
        return self._chart_html("val_band_chart", config)

    def render_all(self, projection: dict = None, peers: list = None,
                   historical: dict = None) -> str:
        """生成所有图表的HTML（嵌入研报用）"""
        charts_html = ['<div class="research-charts"><h2>📊 数据可视化</h2>']
        charts_html.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>')

        if historical and projection:
            charts_html.append(self.revenue_trend(historical, projection))
            charts_html.append(self.eps_projection(projection))
        if peers:
            charts_html.append(self.peer_comparison(peers, ""))
        if historical:
            current_pe = historical.get("pe_ttm", 0)
            if current_pe > 0:
                charts_html.append(self.valuation_band(
                    [historical.get(f"pe_{y}", 15) for y in historical.get("years", [])[:5]], current_pe))

        charts_html.append('</div>')
        return "\n".join(charts_html)


if __name__ == "__main__":
    cr = ChartRenderer()
    # Test with dummy data
    test_hist = {"years": ["2021","2022","2023","2024","2025"], "revenue_yi": [1095,1276,1506,1741,1721]}
    test_proj = {"years": ["2026E","2027E","2028E"], "revenue_yi": [1843,1972,2110], "eps": [70.5,76.2,82.0]}
    print(cr.revenue_trend(test_hist, test_proj))
    print(cr.eps_projection(test_proj))
