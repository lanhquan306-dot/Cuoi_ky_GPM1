"""Hàm dựng biểu đồ Plotly dùng chung cho giao diện web."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def pareto_frontier(df: pd.DataFrame, cost: str = "cost_p90_bps", score: str = "comp_score") -> pd.DataFrame:
    """Các mã không bị mã nào khác 'vượt trội' (điểm cao hơn VÀ chi phí thấp hơn)."""
    d = df[[cost, score]].dropna().sort_values([cost, score], ascending=[True, False])
    best, keep = -np.inf, []
    for idx, r in d.iterrows():
        if r[score] > best:
            keep.append(idx)
            best = r[score]
    return df.loc[keep]


def scatter_score_cost(ranked: pd.DataFrame) -> go.Figure:
    d = ranked.dropna(subset=["cost_p90_bps", "comp_score"])
    fig = go.Figure()
    for flag, name, color in ((True, "Đủ điều kiện", "#1f77b4"), (False, "Bị loại", "#b0b0b0")):
        s = d[d["eligible"] == flag]
        fig.add_trace(go.Scatter(x=s["cost_p90_bps"], y=s["comp_score"], mode="markers+text", text=s.index,
                                 textposition="top center", name=name, marker=dict(size=9, color=color),
                                 hovertemplate="%{text}<br>Chi phí P90=%{x:.0f} bps<br>Điểm=%{y:.2f}<extra></extra>"))
    e = d[d["eligible"]]
    if len(e) >= 2:
        f = pareto_frontier(e).sort_values("cost_p90_bps")
        fig.add_trace(go.Scatter(x=f["cost_p90_bps"], y=f["comp_score"], mode="lines", name="Đường biên hiệu quả",
                                 line=dict(dash="dash", color="#d62728")))
    fig.update_layout(xaxis_title="Chi phí vòng P90 (bps) - thấp hơn là tốt", yaxis_title="Điểm yếu tố tổng hợp",
                      height=420, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
    return fig


def contrib_bar(row: pd.Series) -> go.Figure:
    c = {k[len("contrib_"):]: v for k, v in row.items() if str(k).startswith("contrib_") and pd.notna(v)}
    fig = go.Figure(go.Bar(x=list(c.values()), y=list(c.keys()), orientation="h",
                           marker_color=["#2ca02c" if v >= 0 else "#d62728" for v in c.values()]))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10), xaxis_title="Đóng góp vào điểm tổng hợp",
                      title="Đóng góp từng yếu tố")
    return fig


def depth_chart(prices: list[float], vols: list[float], consumed: list[float], title: str) -> go.Figure:
    """Cột độ sâu từng mức; phần bị lệnh 'ăn' tô màu đậm."""
    labels = [f"{p:,.0f}" for p in prices]
    rest = [max(v - c, 0) for v, c in zip(vols, consumed)]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=consumed, name="Phần lệnh của bạn khớp", marker_color="#d62728"))
    fig.add_trace(go.Bar(x=labels, y=rest, name="Còn lại", marker_color="#c7d3e3"))
    fig.update_layout(barmode="stack", title=title, height=300, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis_title="Mức giá (VND)", yaxis_title="Khối lượng (cp)", legend=dict(orientation="h"))
    return fig


def cost_timeseries(ts: pd.Series, cost: pd.Series, p50: float | None, p90: float | None) -> go.Figure:
    fig = go.Figure(go.Scatter(x=ts, y=cost, mode="lines", name="Chi phí vòng", line=dict(color="#1f77b4")))
    for v, nm, col in ((p50, "P50", "#2ca02c"), (p90, "P90", "#d62728")):
        if v is not None and np.isfinite(v):
            fig.add_hline(y=v, line_dash="dash", line_color=col, annotation_text=f"{nm} cửa sổ lọc")
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="bps", xaxis_title="Giờ (UTC+7)")
    return fig


def forward_bar(trades: pd.DataFrame) -> go.Figure:
    d = trades[trades["status"].isin(["OK", "EXIT_PARTIAL"])].sort_values("rank")
    fig = go.Figure(go.Bar(x=d["symbol"], y=d["net_return"] * 100,
                           marker_color=["#1f77b4" if p else "#c7d3e3" for p in d["is_pick"]]))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="Lợi suất ròng (%)",
                      title="Lợi suất sau phí và trượt giá (xanh đậm = mã được chọn)")
    return fig
