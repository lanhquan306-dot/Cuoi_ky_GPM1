"""Hàm dựng biểu đồ Plotly dùng chung cho giao diện web."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# Bảng màu / typography đồng bộ với giao diện Tailwind của index.html.
FONT = "Inter, 'Segoe UI', system-ui, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace"
INK = "#173655"
MUTED = "#74879f"
GRID = "#e8f2fc"
AXIS = "#d5e8fb"
BLUE = "#3f97f0"
VIOLET = "#8b7cf6"
RED = "#ef7fa6"
GREEN = "#2fbfa0"
AMBER = "#f2b36b"
SLATE = "#cbdcf0"
REST = "#e3eefb"


def _polish(
    fig: go.Figure,
    *,
    height: int,
    title: str | None = None,
    x_title: str | None = None,
    y_title: str | None = None,
    show_legend: bool = False,
    x_grid: bool = True,
    y_grid: bool = True,
    x_zeroline: bool = False,
) -> go.Figure:
    """Khung style tối giản: nền trong suốt, lưới mảnh, font đồng bộ, tự co giãn."""
    fig.update_layout(
        template="none",
        height=height,
        autosize=True,
        margin=dict(l=6, r=14, t=48 if title else 16, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=MUTED),
        colorway=[BLUE, VIOLET, GREEN, RED, AMBER],
        showlegend=show_legend,
        hoverlabel=dict(bgcolor="#1b3d63", bordercolor="#ffffff",
                        font=dict(family=FONT, size=12, color="#ffffff")),
        hovermode="closest",
    )
    if title:
        fig.update_layout(
            title=dict(text=title, x=0, xanchor="left", y=0.98,
                       font=dict(family=FONT, size=13, color=INK))
        )
    if show_legend:
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                        bgcolor="rgba(0,0,0,0)", font=dict(size=11, color=MUTED))
        )
    fig.update_xaxes(
        title=dict(text=x_title, font=dict(size=11, color=MUTED)) if x_title else None,
        showgrid=x_grid, gridcolor=GRID, griddash="dot", zeroline=x_zeroline,
        zerolinecolor=AXIS, showline=True, linecolor=AXIS, linewidth=1,
        ticks="outside", ticklen=4, tickcolor=AXIS,
        tickfont=dict(family=MONO, size=10.5, color=MUTED), automargin=True,
    )
    fig.update_yaxes(
        title=dict(text=y_title, font=dict(size=11, color=MUTED)) if y_title else None,
        showgrid=y_grid, gridcolor=GRID, griddash="dot", zeroline=False,
        showline=False, linecolor=AXIS, linewidth=1,
        ticks="outside", ticklen=4, tickcolor=AXIS,
        tickfont=dict(family=MONO, size=10.5, color=MUTED), automargin=True,
    )
    return fig


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
    # Vẽ mã bị loại trước để mã đủ điều kiện nằm trên cùng.
    for flag, name, color in ((False, "Bị loại", SLATE), (True, "Đủ điều kiện", BLUE)):
        s = d[d["eligible"] == flag]
        fig.add_trace(
            go.Scatter(
                x=s["cost_p90_bps"], y=s["comp_score"], mode="markers+text", text=s.index,
                textposition="top center", textfont=dict(family=MONO, size=9, color="#9db1c6"),
                name=name, marker=dict(size=9, color=color, line=dict(width=1.5, color="#ffffff")),
                hovertemplate="<b>%{text}</b><br>Chi phí P90: %{x:,.0f} bps"
                              "<br>Điểm yếu tố: %{y:.2f}<extra></extra>",
                cliponaxis=False,
            )
        )
    e = d[d["eligible"]]
    if len(e) >= 2:
        f = pareto_frontier(e).sort_values("cost_p90_bps")
        fig.add_trace(
            go.Scatter(
                x=f["cost_p90_bps"], y=f["comp_score"], mode="lines", name="Đường biên hiệu quả",
                line=dict(dash="dash", width=2, color=VIOLET),
                hovertemplate="Biên hiệu quả<br>%{x:,.0f} bps · điểm %{y:.2f}<extra></extra>",
            )
        )
    _polish(
        fig, height=430, show_legend=True,
        x_title="Chi phí vòng P90 (bps) — thấp hơn là tốt",
        y_title="Điểm yếu tố tổng hợp",
    )
    return fig


def contrib_bar(row: pd.Series) -> go.Figure:
    c = {k[len("contrib_"):]: v for k, v in row.items() if str(k).startswith("contrib_") and pd.notna(v)}
    fig = go.Figure(
        go.Bar(
            x=list(c.values()), y=list(c.keys()), orientation="h",
            marker=dict(color=[GREEN if v >= 0 else RED for v in c.values()], line=dict(width=0)),
            hovertemplate="%{y}: %{x:+.3f}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line_width=1, line_color=AXIS)
    _polish(
        fig, height=300, title="Đóng góp từng yếu tố",
        x_title="Đóng góp vào điểm tổng hợp", x_zeroline=True, y_grid=False,
    )
    return fig


def depth_chart(prices: list[float], vols: list[float], consumed: list[float], title: str) -> go.Figure:
    """Cột độ sâu từng mức; phần bị lệnh 'ăn' tô màu đậm."""
    labels = [f"{p:,.0f}" for p in prices]
    rest = [max(v - c, 0) for v, c in zip(vols, consumed)]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels, y=consumed, name="Phần lệnh của bạn khớp",
            marker=dict(color=RED, line=dict(width=0)),
            hovertemplate="%{x} VND<br>Khớp: %{y:,.0f} cp<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels, y=rest, name="Còn lại",
            marker=dict(color=REST, line=dict(width=0)),
            hovertemplate="%{x} VND<br>Còn lại: %{y:,.0f} cp<extra></extra>",
        )
    )
    fig.update_layout(barmode="stack", bargap=0.42)
    _polish(
        fig, height=330, title=title, show_legend=True,
        x_title="Mức giá (VND)", y_title="Khối lượng (cp)", x_grid=False,
    )
    return fig


def cost_timeseries(ts: pd.Series, cost: pd.Series, p50: float | None, p90: float | None) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=ts, y=cost, mode="lines", name="Chi phí vòng",
            line=dict(color=BLUE, width=2), fill="tozeroy", fillcolor="rgba(63,151,240,0.10)",
            hovertemplate="%{x|%H:%M:%S}<br>%{y:,.1f} bps<extra></extra>",
        )
    )
    for v, nm, col in ((p50, "P50", GREEN), (p90, "P90", RED)):
        if v is not None and np.isfinite(v):
            fig.add_hline(
                y=v, line_dash="dash", line_width=1.5, line_color=col,
                annotation_text=f" {nm} · {v:,.1f} bps", annotation_position="top left",
                annotation_font=dict(family=MONO, size=10, color=col),
            )
    _polish(
        fig, height=300, title="Chi phí vòng theo thời gian",
        x_title="Giờ (UTC+7)", y_title="bps",
    )
    fig.update_xaxes(tickformat="%H:%M", ticklabelmode="instant", hoverformat="%d/%m %H:%M")
    fig.update_layout(hovermode="x unified")
    return fig


def forward_bar(trades: pd.DataFrame) -> go.Figure:
    d = trades[trades["status"].isin(["OK", "EXIT_PARTIAL"])].sort_values("rank")
    fig = go.Figure(
        go.Bar(
            x=d["symbol"], y=d["net_return"] * 100,
            marker=dict(color=[BLUE if p else SLATE for p in d["is_pick"]], line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Lợi suất ròng: %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_width=1, line_color=AXIS)
    _polish(
        fig, height=320, title="Lợi suất sau phí & trượt giá (xanh = mã được chọn)",
        x_title="Mã", y_title="Lợi suất ròng (%)", x_grid=False,
    )
    fig.update_xaxes(type="category", tickfont=dict(family=MONO, size=10))
    return fig
