"""Shared chart theme and formatting.

The palette is a fixed, validated set rather than Plotly's default cycle:
categorical hues are assigned in slot order and never recycled, so a series
keeps its colour when a filter changes how many series are on screen. Several
slots sit below 3:1 against the light surface, so every chart that uses them
also ships direct labels or an accompanying table.

The app is pinned to the light theme in `.streamlit/config.toml` - the palette
was validated against that one surface, and shipping an unvalidated dark
variant would be worse than committing to a single look.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ------------------------------------------------------------------ palette --
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

# Fixed slot order. Assign by index; never cycle past the end - fold extra
# series into "Other" or facet instead.
CATEGORICAL = (
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
)

# Single hue, light to dark. For continuous magnitude only.
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def register_template() -> None:
    pio.templates["eap"] = go.layout.Template(
        layout=go.Layout(
            colorway=list(CATEGORICAL),
            font=dict(family=FONT_FAMILY, size=13, color=INK_SECONDARY),
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            title=dict(font=dict(size=16, color=INK_PRIMARY), x=0, xanchor="left", pad=dict(b=12)),
            margin=dict(l=8, r=8, t=48, b=8),
            xaxis=dict(
                showgrid=False, zeroline=False,
                linecolor=BASELINE, linewidth=1, ticks="outside",
                tickcolor=BASELINE, ticklen=4,
                tickfont=dict(color=INK_MUTED, size=12),
                title=dict(font=dict(color=INK_MUTED, size=12)),
            ),
            yaxis=dict(
                showgrid=True, gridcolor=GRIDLINE, gridwidth=1,
                zeroline=False, showline=False,
                tickfont=dict(color=INK_MUTED, size=12),
                title=dict(font=dict(color=INK_MUTED, size=12)),
            ),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(color=INK_SECONDARY, size=12),
                bgcolor="rgba(0,0,0,0)",
            ),
            hoverlabel=dict(
                bgcolor=SURFACE, bordercolor=BASELINE,
                font=dict(family=FONT_FAMILY, size=12, color=INK_PRIMARY),
            ),
            hovermode="x unified",
            colorscale=dict(sequential=[[i / 6, c] for i, c in enumerate(SEQUENTIAL_BLUE)]),
        )
    )
    pio.templates.default = "eap"


# --------------------------------------------------------------- formatting --
def brl(value: float | int | None, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return f"R$ {value:,.{decimals}f}"


def compact_brl(value: float | int | None) -> str:
    """Abbreviated currency for axis ticks and tiles."""
    if value is None:
        return "-"
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"R$ {value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"R$ {value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"R$ {value / 1e3:.1f}K"
    return f"R$ {value:,.0f}"


def compact(value: float | int | None) -> str:
    if value is None:
        return "-"
    magnitude = abs(value)
    if magnitude >= 1e6:
        return f"{value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:,.0f}"


def pct(value: float | None, decimals: int = 1) -> str:
    return "-" if value is None else f"{value:.{decimals}f}%"


# ------------------------------------------------------------------- layout --
def page_setup(title: str, icon: str = "📊") -> None:
    st.set_page_config(page_title=f"{title} · Olist Analytics",
                       page_icon=icon, layout="wide",
                       initial_sidebar_state="expanded")
    register_template()
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str, question: str | None = None) -> None:
    st.markdown(f"## {title}")
    st.caption(subtitle)
    if question:
        st.markdown(
            f'<div class="question-band"><strong>Business question:</strong> {question}</div>',
            unsafe_allow_html=True,
        )


def section(title: str, note: str | None = None) -> None:
    st.markdown(f"#### {title}")
    if note:
        st.caption(note)


def chart(figure: go.Figure, height: int = 380, **kwargs) -> None:
    figure.update_layout(height=height)
    st.plotly_chart(figure, use_container_width=True, config=_PLOTLY_CONFIG, **kwargs)


def empty_state(what: str, how: str) -> None:
    st.info(f"**{what}**\n\n{how}", icon="⏳")


_PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "responsive": True,
}

_CSS = """
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }
  [data-testid="stMetricValue"] { font-size: 1.7rem; }
  [data-testid="stMetricLabel"] { color: #52514e; }
  .question-band {
      background: #f0efec; border-left: 3px solid #2a78d6;
      padding: 0.65rem 0.9rem; border-radius: 4px;
      margin: 0.4rem 0 1.4rem 0; font-size: 0.9rem; color: #52514e;
  }
  .finding {
      background: #fcfcfb; border: 1px solid rgba(11,11,11,0.10);
      border-left: 3px solid #eb6834;
      padding: 0.9rem 1.1rem; border-radius: 4px; margin: 0.8rem 0 1.4rem 0;
  }
  .finding p { margin: 0.2rem 0; color: #52514e; font-size: 0.92rem; }
  .finding strong { color: #0b0b0b; }
  hr { margin: 1.6rem 0; border-color: #e1e0d9; }
</style>
"""


def finding(headline: str, detail: str) -> None:
    """Callout for an interpreted result - the 'so what' beside the chart."""
    st.markdown(
        f'<div class="finding"><p><strong>{headline}</strong></p><p>{detail}</p></div>',
        unsafe_allow_html=True,
    )
