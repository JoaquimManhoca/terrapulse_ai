"""Server-side SVG chart builders for the climate analysis page.

Every function returns a raw SVG string that templates include with the
``|safe`` filter. Charts scale to their container width (viewBox), carry
``role="img"`` + ``aria-label`` and need no JavaScript, so they render
offline on low-end phones.
"""

from __future__ import annotations

from html import escape
from xml.sax.saxutils import quoteattr

PADDING = {"top": 14, "right": 16, "bottom": 48, "left": 66}


def _axes(width: int, height: int, y_max: float) -> tuple[float, float]:
    """Pixel helpers: inner plot area and y-scale."""
    x0 = PADDING["left"]
    y0 = height - PADDING["bottom"]
    inner_w = width - x0 - PADDING["right"]
    inner_h = y0 - PADDING["top"]
    return inner_w, inner_h


def _y_scale(height: int, y_max: float) -> tuple[float, float]:
    y0 = height - PADDING["bottom"]
    inner_h = y0 - PADDING["top"]
    peak = y_max if y_max > 0 else 1.0

    def to_y(value: float) -> float:
        return y0 - (max(0.0, min(value, peak)) / peak) * inner_h

    return to_y, inner_h


def _grid(width: int, height: int, y_max: float, steps: int = 4) -> list[str]:
    y0 = height - PADDING["bottom"]
    inner_h = y0 - PADDING["top"]
    parts = []
    for i in range(steps + 1):
        value = y_max * i / steps
        y = y0 - (value / y_max if y_max else 0) * inner_h
        label = f"{value:,.0f}".replace(",", " ")
        parts.append(
            f'<line x1="{PADDING["left"]}" y1="{y:.1f}" x2="{width - PADDING["right"]}" y2="{y:.1f}" class="chart-grid"/>'
        )
        parts.append(
            f'<text x="{PADDING["left"] - 6}" y="{y + 4:.1f}" class="chart-tick" text-anchor="end">{escape(label)}</text>'
        )
    return parts


def _axis_titles(
    width: int,
    height: int,
    x_label: str,
    y_label: str,
    x0: float,
    inner_w: float,
    inner_h: float,
) -> list[str]:
    parts = []
    if y_label:
        cy = PADDING["top"] + inner_h / 2
        parts.append(
            f'<text x="14" y="{cy:.1f}" class="chart-axis-label" text-anchor="middle" transform="rotate(-90 14 {cy:.1f})">{escape(y_label)}</text>'
        )
    if x_label:
        cx = x0 + inner_w / 2
        parts.append(
            f'<text x="{cx:.1f}" y="{height - 6}" class="chart-axis-label" text-anchor="middle">{escape(x_label)}</text>'
        )
    return parts


def bar_chart(
    bars: list[dict],
    width: int = 720,
    height: int = 280,
    aria_label: str = "",
    y_max: float | None = None,
    line: list[tuple[float, float]] | None = None,
    line_label: str = "",
    label_step: int = 1,
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Vertical bar chart with an optional overlay line.

    Each bar: ``{"value", "label", "title", "cls"}``.
    ``line``: list of ``(x_index, y_value)`` in bar coordinates.
    """
    if not bars:
        return ""
    values = [max(0.0, float(b["value"])) for b in bars]
    peak = y_max if y_max is not None else max(values) * 1.08 or 1.0
    inner_w, inner_h = _axes(width, height, peak)
    to_y, _ = _y_scale(height, peak)

    x0 = PADDING["left"]
    slot = inner_w / len(bars)
    bar_w = max(2.0, slot * 0.72)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label={quoteattr(aria_label)} preserveAspectRatio="xMidYMid meet">'
    ]
    parts.extend(_grid(width, height, peak))

    for index, bar in enumerate(bars):
        cx = x0 + slot * (index + 0.5)
        x = cx - bar_w / 2
        y = to_y(bar["value"])
        h = max(1.0, (height - PADDING["bottom"]) - y)
        cls = bar.get("cls") or "chart-bar-fill"
        title = escape(str(bar.get("title") or ""))
        parts.append(
            f'<g><title>{title}</title><rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2" class="{cls}"/></g>'
        )
        if index % label_step == 0:
            parts.append(
                f'<text x="{cx:.1f}" y="{height - PADDING["bottom"] + 16}" class="chart-tick chart-tick-x" text-anchor="middle">{escape(str(bar.get("label") or ""))}</text>'
            )

    if line:
        points = " ".join(
            f"{x0 + slot * (xi + 0.5):.1f},{to_y(yv):.1f}" for xi, yv in line
        )
        parts.append(
            f'<polyline points="{points}" class="chart-line" fill="none"><title>{escape(line_label)}</title></polyline>'
        )
    parts.extend(_axis_titles(width, height, x_label, y_label, x0, inner_w, inner_h))
    parts.append("</svg>")
    return "".join(parts)


def band_chart(
    bands: list[dict],
    width: int = 720,
    height: int = 280,
    aria_label: str = "",
    y_max: float | None = None,
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Monthly climatology: p10-p90 band with median marker per month.

    Each band: ``{"label", "p10", "median", "p90", "title"}``.
    """
    if not bands:
        return ""
    medians = [float(b["median"]) for b in bands]
    peaks = [float(b["p90"]) for b in bands] + [float(b["p10"]) for b in bands]
    peak = y_max if y_max is not None else max(peaks) * 1.1 or 1.0
    inner_w, inner_h = _axes(width, height, peak)
    to_y, _ = _y_scale(height, peak)

    x0 = PADDING["left"]
    slot = inner_w / len(bands)
    band_w = max(8.0, slot * 0.6)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label={quoteattr(aria_label)} preserveAspectRatio="xMidYMid meet">'
    ]
    parts.extend(_grid(width, height, peak))

    for index, band in enumerate(bands):
        cx = x0 + slot * (index + 0.5)
        x = cx - band_w / 2
        y_hi = to_y(band["p90"])
        y_lo = to_y(band["p10"])
        y_med = to_y(band["median"])
        parts.append(
            f'<g><title>{escape(str(band.get("title") or ""))}</title>'
            f'<rect x="{x:.1f}" y="{y_hi:.1f}" width="{band_w:.1f}" height="{max(1.0, y_lo - y_hi):.1f}" rx="4" class="chart-band"/>'
            f'<line x1="{x:.1f}" y1="{y_med:.1f}" x2="{x + band_w:.1f}" y2="{y_med:.1f}" class="chart-med"/>'
            f'<text x="{cx:.1f}" y="{y_med - 6:.1f}" class="chart-value" text-anchor="middle">{escape(str(band.get("label") or ""))}</text>'
            f'<text x="{cx:.1f}" y="{height - PADDING["bottom"] + 16}" class="chart-tick chart-tick-x" text-anchor="middle">{escape(str(band.get("tick") or ""))}</text>'
            f"</g>"
        )
    parts.extend(_axis_titles(width, height, x_label, y_label, x0, inner_w, inner_h))
    parts.append("</svg>")
    return "".join(parts)


def error_bar_chart(
    groups: list[dict],
    width: int = 720,
    height: int = 280,
    aria_label: str = "",
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Mean comparison with 95% CI whiskers.

    Each group: ``{"label", "mean", "ci_low", "ci_high", "cls", "title"}``.
    """
    if not groups:
        return ""
    highs = [float(g["ci_high"]) for g in groups]
    peak = max(highs) * 1.15 or 1.0
    inner_w, inner_h = _axes(width, height, peak)
    to_y, _ = _y_scale(height, peak)

    x0 = PADDING["left"]
    slot = inner_w / len(groups)
    bar_w = max(20.0, slot * 0.4)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label={quoteattr(aria_label)} preserveAspectRatio="xMidYMid meet">'
    ]
    parts.extend(_grid(width, height, peak))

    for index, group in enumerate(groups):
        cx = x0 + slot * (index + 0.5)
        y_mean = to_y(group["mean"])
        y_lo = to_y(group["ci_low"])
        y_hi = to_y(group["ci_high"])
        x = cx - bar_w / 2
        h = max(1.0, (height - PADDING["bottom"]) - y_mean)
        cls = group.get("cls") or "chart-bar-fill"
        parts.append(
            f'<g><title>{escape(str(group.get("title") or ""))}</title>'
            f'<rect x="{x:.1f}" y="{y_mean:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="3" class="{cls}"/>'
            f'<line x1="{cx:.1f}" y1="{y_hi:.1f}" x2="{cx:.1f}" y2="{y_lo:.1f}" class="chart-whisker"/>'
            f'<line x1="{cx - 8:.1f}" y1="{y_hi:.1f}" x2="{cx + 8:.1f}" y2="{y_hi:.1f}" class="chart-whisker"/>'
            f'<line x1="{cx - 8:.1f}" y1="{y_lo:.1f}" x2="{cx + 8:.1f}" y2="{y_lo:.1f}" class="chart-whisker"/>'
            f'<text x="{cx:.1f}" y="{y_mean - 10:.1f}" class="chart-value" text-anchor="middle">{escape(str(group.get("label") or ""))}</text>'
            f'<text x="{cx:.1f}" y="{height - PADDING["bottom"] + 16}" class="chart-tick chart-tick-x" text-anchor="middle">{escape(str(group.get("tick") or ""))}</text>'
            f"</g>"
        )
    parts.extend(_axis_titles(width, height, x_label, y_label, x0, inner_w, inner_h))
    parts.append("</svg>")
    return "".join(parts)


def strip_chart(
    rows: list[dict],
    width: int = 720,
    height: int = 300,
    aria_label: str = "",
    axis_max: float | None = None,
    median: float | None = None,
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Horizontal dot strip per row (e.g. onset day-of-season per season).

    Each row: ``{"label", "value" (may be None), "title", "cls"}``.
    """
    values = [float(r["value"]) for r in rows if r.get("value") is not None]
    if not rows:
        return ""
    peak = axis_max if axis_max is not None else (max(values) * 1.05 if values else 1.0)
    inner_w, inner_h = _axes(width, height, peak)

    row_h = (height - PADDING["bottom"] - PADDING["top"]) / max(1, len(rows))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label={quoteattr(aria_label)} preserveAspectRatio="xMidYMid meet">'
    ]
    y0 = height - PADDING["bottom"]

    x_axis_labels = 6
    for i in range(x_axis_labels + 1):
        value = peak * i / x_axis_labels
        x = PADDING["left"] + inner_w * i / x_axis_labels
        parts.append(
            f'<line x1="{x:.1f}" y1="{PADDING["top"]}" x2="{x:.1f}" y2="{y0}" class="chart-grid"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y0 + 16}" class="chart-tick" text-anchor="middle">{escape(str(_fmt_day(value)))}</text>'
        )

    if median is not None:
        xm = PADDING["left"] + inner_w * min(1.0, median / peak if peak else 0)
        parts.append(
            f'<line x1="{xm:.1f}" y1="{PADDING["top"]}" x2="{xm:.1f}" y2="{y0}" class="chart-line"/>'
        )

    for index, row in enumerate(rows):
        cy = PADDING["top"] + row_h * (index + 0.5)
        parts.append(
            f'<text x="{PADDING["left"] - 6}" y="{cy + 4:.1f}" class="chart-tick" text-anchor="end">{escape(str(row.get("label") or ""))}</text>'
        )
        if row.get("value") is None:
            cx = PADDING["left"] + inner_w * 0.5
            parts.append(
                f'<g><title>{escape(str(row.get("title") or ""))}</title><text x="{cx:.1f}" y="{cy + 4:.1f}" class="chart-missing" text-anchor="middle">&#8212;</text></g>'
            )
            continue
        cx = PADDING["left"] + inner_w * min(1.0, float(row["value"]) / peak if peak else 0)
        cls = row.get("cls") or "chart-dot"
        parts.append(
            f'<g><title>{escape(str(row.get("title") or ""))}</title><circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="{cls}"/></g>'
        )
    parts.extend(
        _axis_titles(
            width,
            height,
            x_label,
            y_label,
            PADDING["left"],
            inner_w,
            inner_h,
        )
    )
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(
    items: list[dict],
    width: int = 720,
    height: int = 300,
    aria_label: str = "",
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Horizontal bars (feature importances). Each item: {"label", "pct", "title"}."""
    if not items:
        return ""
    peak = max(float(i["pct"]) for i in items) * 1.05 or 1.0
    row_h = (height - PADDING["bottom"] - PADDING["top"]) / len(items)
    label_w = 150
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label={quoteattr(aria_label)} preserveAspectRatio="xMidYMid meet">'
    ]
    inner_w = width - label_w - PADDING["right"]
    inner_h = height - PADDING["bottom"] - PADDING["top"]
    for index, item in enumerate(items):
        cy = PADDING["top"] + row_h * (index + 0.5)
        bar_w = inner_w * float(item["pct"]) / peak
        parts.append(
            f'<g><title>{escape(str(item.get("title") or ""))}</title>'
            f'<text x="{label_w - 6}" y="{cy + 4:.1f}" class="chart-tick" text-anchor="end">{escape(str(item.get("label") or ""))}</text>'
            f'<rect x="{label_w}" y="{cy - row_h * 0.32:.1f}" width="{max(1.0, bar_w):.1f}" height="{row_h * 0.64:.1f}" rx="3" class="chart-bar-fill"/>'
            f'<text x="{label_w + bar_w + 6:.1f}" y="{cy + 4:.1f}" class="chart-value">{item["pct"]:.0f}%</text>'
            f"</g>"
        )
    parts.extend(
        _axis_titles(width, height, x_label, y_label, label_w, inner_w, inner_h)
    )
    parts.append("</svg>")
    return "".join(parts)


def _fmt_day(value: float) -> str:
    days = int(round(value))
    month, day = _season_day_to_date(days)
    return f"{day:02d}/{month:02d}"


def _season_day_to_date(day_index: int) -> tuple[int, int]:
    length = (31, 30, 31, 31, 28, 31)  # Oct..Mar
    months = (10, 11, 12, 1, 2, 3)
    remaining = day_index
    for month, size in zip(months, length):
        if remaining < size:
            return month, remaining + 1
        remaining -= size
    return 3, 31
