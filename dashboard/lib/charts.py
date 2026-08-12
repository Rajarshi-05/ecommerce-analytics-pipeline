"""Reusable chart builders.

Every figure here follows the same rules: one y-axis (never a second scale),
categorical colours assigned by fixed slot rather than cycled, thin marks,
recessive grid, and a hover layer. Charts that use a low-contrast slot are
always paired with a table or direct labels by their caller.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.lib.ui import (
    BASELINE,
    CATEGORICAL,
    GRIDLINE,
    INK_MUTED,
    SEQUENTIAL_BLUE,
    STATUS,
    SURFACE,
    compact_brl,
)


def line_series(
    frame: pd.DataFrame,
    x: str,
    series: list[tuple[str, str]],
    y_title: str = "",
    currency: bool = True,
) -> go.Figure:
    """One or more lines on a single shared axis."""
    figure = go.Figure()
    for index, (column, label) in enumerate(series):
        figure.add_trace(go.Scatter(
            x=frame[x], y=frame[column], name=label, mode="lines",
            line=dict(color=CATEGORICAL[index % len(CATEGORICAL)], width=2),
            hovertemplate=f"<b>{label}</b>: %{{y:,.0f}}<extra></extra>",
        ))
    figure.update_layout(
        yaxis=dict(title=y_title, tickformat=",.0f"),
        showlegend=len(series) > 1,
    )
    if currency:
        figure.update_yaxes(tickprefix="R$ ")
    return figure


def bar_ranked(
    frame: pd.DataFrame,
    label_column: str,
    value_column: str,
    top_n: int = 10,
    horizontal: bool = True,
    currency: bool = True,
    color: str = CATEGORICAL[0],
) -> go.Figure:
    """Ranked magnitude comparison with a direct label on every bar."""
    data = frame.nlargest(top_n, value_column).sort_values(value_column)
    text = [compact_brl(v) if currency else f"{v:,.0f}" for v in data[value_column]]

    figure = go.Figure(go.Bar(
        x=data[value_column] if horizontal else data[label_column],
        y=data[label_column] if horizontal else data[value_column],
        orientation="h" if horizontal else "v",
        marker=dict(color=color, line=dict(width=0)),
        text=text, textposition="outside",
        textfont=dict(color=INK_MUTED, size=11),
        hovertemplate="<b>%{y}</b><br>%{x:,.0f}<extra></extra>"
        if horizontal else "<b>%{x}</b><br>%{y:,.0f}<extra></extra>",
        cliponaxis=False,
    ))
    figure.update_traces(marker_cornerradius=4)
    if horizontal:
        figure.update_layout(
            xaxis=dict(showgrid=True, gridcolor=GRIDLINE, showline=False,
                       tickprefix="R$ " if currency else ""),
            yaxis=dict(showgrid=False, showline=False, ticks=""),
            margin=dict(l=8, r=72, t=48, b=8),
            hovermode="closest",
        )
    return figure


def diverging_bar(frame: pd.DataFrame, x: str, y: str, y_title: str = "") -> go.Figure:
    """Signed change around zero. Blue up / red down - the diverging pair."""
    values = frame[y].fillna(0)
    colors = [CATEGORICAL[0] if v >= 0 else STATUS["critical"] for v in values]

    figure = go.Figure(go.Bar(
        x=frame[x], y=values,
        marker=dict(color=colors, line=dict(width=0)),
        hovertemplate="<b>%{x}</b><br>%{y:+.1f}%<extra></extra>",
    ))
    figure.update_traces(marker_cornerradius=3)
    figure.add_hline(y=0, line=dict(color=BASELINE, width=1))
    figure.update_layout(yaxis=dict(title=y_title, ticksuffix="%"), hovermode="closest")
    return figure


def forecast_band(frame: pd.DataFrame) -> go.Figure:
    """Actuals plus forecast with its prediction interval, on one axis."""
    history = frame[~frame["is_forecast"]]
    future = frame[frame["is_forecast"]]

    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=list(future["ds"]) + list(future["ds"])[::-1],
        y=list(future["forecast_upper"]) + list(future["forecast_lower"])[::-1],
        fill="toself", fillcolor="rgba(42,120,214,0.13)",
        line=dict(width=0), hoverinfo="skip",
        name="80% interval", showlegend=True,
    ))
    figure.add_trace(go.Scatter(
        x=history["ds"], y=history["actual_revenue"], name="Actual",
        mode="lines", line=dict(color=INK_MUTED, width=1.4),
        hovertemplate="Actual: R$ %{y:,.0f}<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=future["ds"], y=future["forecast_revenue"], name="Forecast",
        mode="lines", line=dict(color=CATEGORICAL[0], width=2),
        hovertemplate="Forecast: R$ %{y:,.0f}<extra></extra>",
    ))
    if not future.empty:
        figure.add_vline(x=future["ds"].min(), line=dict(color=BASELINE, width=1, dash="dot"))
    figure.update_layout(yaxis=dict(title="Daily revenue", tickprefix="R$ "))
    return figure


def stacked_share(frame: pd.DataFrame, x: str, category: str, value: str) -> go.Figure:
    """Composition over time. A 2px surface gap separates the segments."""
    figure = go.Figure()
    for index, name in enumerate(frame[category].unique()):
        subset = frame[frame[category] == name]
        figure.add_trace(go.Bar(
            x=subset[x], y=subset[value], name=str(name),
            marker=dict(color=CATEGORICAL[index % len(CATEGORICAL)],
                        line=dict(color=SURFACE, width=2)),
            hovertemplate=f"<b>{name}</b>: %{{y:,.0f}}<extra></extra>",
        ))
    figure.update_layout(barmode="stack", yaxis=dict(title="Orders"))
    return figure


def heatmap(frame: pd.DataFrame, x: str, y: str, z: str,
            colorbar_title: str = "") -> go.Figure:
    """Sequential magnitude on a single hue, light to dark."""
    pivot = frame.pivot_table(index=y, columns=x, values=z, aggfunc="mean")
    figure = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns, y=pivot.index,
        colorscale=[[i / (len(SEQUENTIAL_BLUE) - 1), c]
                    for i, c in enumerate(SEQUENTIAL_BLUE)],
        hovertemplate="%{y} · month %{x}<br>%{z:.1f}%<extra></extra>",
        colorbar=dict(title=dict(text=colorbar_title, font=dict(size=11)),
                      thickness=12, len=0.85, outlinewidth=0,
                      tickfont=dict(size=11, color=INK_MUTED)),
        xgap=2, ygap=2,
    ))
    figure.update_layout(
        xaxis=dict(title="Months since first order", showline=False, ticks=""),
        yaxis=dict(title="", autorange="reversed", showgrid=False, showline=False, ticks=""),
        hovermode="closest",
    )
    return figure


def scatter_bubble(frame: pd.DataFrame, x: str, y: str, size: str,
                   label: str, x_title: str = "", y_title: str = "") -> go.Figure:
    """Two measures plus magnitude. One colour - identity comes from the label."""
    sizes = frame[size].fillna(0)
    scale = (sizes / sizes.max() * 46 + 8) if sizes.max() else 12

    figure = go.Figure(go.Scatter(
        x=frame[x], y=frame[y], mode="markers+text",
        text=frame[label], textposition="top center",
        textfont=dict(size=10, color=INK_MUTED),
        marker=dict(size=scale, color=CATEGORICAL[0], opacity=0.72,
                    line=dict(color=SURFACE, width=2)),
        hovertemplate=(f"<b>%{{text}}</b><br>{x_title}: %{{x:,.2f}}"
                       f"<br>{y_title}: %{{y:,.2f}}<extra></extra>"),
    ))
    figure.update_layout(
        xaxis=dict(title=x_title, showgrid=True, gridcolor=GRIDLINE),
        yaxis=dict(title=y_title),
        hovermode="closest",
    )
    return figure
