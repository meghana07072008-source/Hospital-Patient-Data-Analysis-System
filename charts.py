"""Matplotlib charts rendered to PNG (used by the reports page, exports and
as a fallback when the browser cannot load Chart.js).

Uses the object-oriented Figure API (no pyplot) so it is safe in a
multi-threaded Flask server.
"""
import io

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

import analytics as an

INK, TEAL, AQUA, CORAL, AMBER, MUTED, GRID = "#0b2a33", "#0e7c86", "#5fd4c4", "#ff6f59", "#f2b441", "#5d7480", "#e3ebed"
CATEGORICAL = ["#0e7c86", "#5fd4c4", "#3b6fd4", "#f2b441", "#ff6f59", "#8a6fd1", "#2f9e6f", "#d6609b", "#7a8c94", "#b5651d", "#1f4e79", "#a3c644"]
NOTE = "Operational statistics from synthetic data - not clinical advice."


def _fig(width=8.0, height=4.2):
    fig = Figure(figsize=(width, height), dpi=130, facecolor="white")
    ax = fig.subplots()
    ax.set_facecolor("white")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _finish(fig, ax, title, subtitle=None):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=22 if subtitle else 12)
    if subtitle:
        ax.text(0, 1.04, subtitle, transform=ax.transAxes, fontsize=8, color=MUTED)
    fig.text(0.01, 0.005, NOTE, fontsize=6.5, color=MUTED, ha="left", va="bottom")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.25, facecolor="white")
    return buf.getvalue()


def _empty(title):
    fig, ax = _fig()
    ax.text(0.5, 0.5, "No visits match these filters", ha="center", va="center", color=MUTED, transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])
    return _finish(fig, ax, title)


def render(name, df, start, end):
    """Return PNG bytes for chart `name`."""
    if name == "departments":
        return _departments(df, start, end)
    if name == "monthly":
        return _monthly(df, start, end)
    if name == "daily":
        return _daily(df, start, end)
    if name == "age_bands":
        return _age_bands(df)
    if name == "visit_types":
        return _visit_types(df)
    if name == "weekday":
        return _weekday(df, start, end)
    if name == "heatmap":
        return _heatmap(df, start, end)
    raise KeyError(name)


def _departments(df, start, end):
    rep = an.department_report(df, start, end)
    if rep.empty:
        return _empty("Department workload")
    rep = rep.iloc[::-1]
    fig, ax = _fig(8, max(3.4, 0.38 * len(rep) + 1.4))
    colors = [CORAL if d == "Emergency Medicine" else TEAL for d in rep["Department"]]
    bars = ax.barh(rep["Department"], rep["Visits"], color=colors, height=0.62)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    for bar, v in zip(bars, rep["Visits"]):
        ax.text(bar.get_width() + rep["Visits"].max() * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, rep["Visits"].max() * 1.12)
    return _finish(fig, ax, "Department workload", f"Total visits per department, {start:%d %b %Y} to {end:%d %b %Y}")


def _monthly(df, start, end):
    rep = an.monthly_report(df, start, end)
    fig, ax = _fig()
    x = np.arange(len(rep))
    colors = [AQUA if p else TEAL for p in rep["Partial month"]]
    ax.bar(x, rep["Visits"], color=colors, width=0.62)
    ax.plot(x, rep["Visits"], color=INK, linewidth=1.4, marker="o", markersize=3.5)
    ax.set_xticks(x)
    ax.set_xticklabels([m.replace(" ", "\n") for m in rep["Month"]], fontsize=7.5)
    ax.set_ylim(0, max(rep["Visits"].max() * 1.15, 1))
    return _finish(fig, ax, "Monthly visit trend", "Light bars are partial months (month-to-date or window edge)")


def _daily(df, start, end):
    daily = an.daily_series(df, start, end).tail(60)
    fig, ax = _fig()
    ax.fill_between(daily.index, daily.values, color=AQUA, alpha=0.35, linewidth=0)
    ax.plot(daily.index, daily.values, color=TEAL, linewidth=1.6, label="Daily visits")
    ax.plot(daily.index, daily.rolling(7, min_periods=1).mean(), color=CORAL, linewidth=1.4, label="7-day average")
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncols=2)
    fig.autofmt_xdate()
    return _finish(fig, ax, "Daily visits", "Last 60 days of the selected range")


def _age_bands(df):
    rep = an.age_band_report(df)
    fig, ax = _fig(7, 3.8)
    vals = [v if v is not None else 0 for v in rep["Visits"]]
    ax.bar(rep["Age band"], vals, color=TEAL, width=0.62)
    for i, (v, raw) in enumerate(zip(vals, rep["Visits"])):
        ax.text(i, v + max(vals + [1]) * 0.015, "<5" if raw is None else f"{v:,}", ha="center", fontsize=8, color=INK)
    ax.set_ylim(0, max(vals + [1]) * 1.15)
    return _finish(fig, ax, "Visits by age band", "Aggregated bands only - counts under 5 are hidden")


def _visit_types(df):
    rep = an.visit_type_report(df)
    if rep["Visits"].sum() == 0:
        return _empty("Visit types")
    fig = Figure(figsize=(6, 4), dpi=130, facecolor="white")
    ax = fig.subplots()
    cols = [TEAL, AQUA, AMBER, CORAL]
    wedges, _ = ax.pie(rep["Visits"], colors=cols, startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
    ax.legend(wedges, [f"{t}  {s:.1f}%" for t, s in zip(rep["Visit type"], rep["Share %"])],
              loc="center left", bbox_to_anchor=(1, 0.5), frameon=False, fontsize=9)
    ax.set_title("Visit types", loc="left", fontsize=12, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, NOTE, fontsize=6.5, color=MUTED)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.25, facecolor="white")
    return buf.getvalue()


def _weekday(df, start, end):
    wk = an.weekday_average(an.daily_series(df, start, end))
    fig, ax = _fig(7, 3.8)
    colors = [CORAL if i >= 5 else TEAL for i in range(7)]
    ax.bar(an.WEEKDAYS, wk.values, color=colors, width=0.62)
    for i, v in enumerate(wk.values):
        ax.text(i, v + max(wk.max(), 1) * 0.015, f"{v:.1f}", ha="center", fontsize=8, color=INK)
    ax.set_ylim(0, max(wk.max(), 1) * 1.15)
    return _finish(fig, ax, "Average visits by weekday", "Mean visits per day, weekends in coral")


def _heatmap(df, start, end):
    hm = an.weekday_heatmap(df, start, end)
    if not hm["departments"]:
        return _empty("Department by weekday")
    data = np.array(hm["values"])
    fig, ax = _fig(7.5, max(3.6, 0.36 * len(data) + 1.6))
    cmap = LinearSegmentedColormap.from_list("pulse", ["#eef6f6", AQUA, TEAL, INK])
    im = ax.imshow(data, cmap=cmap, aspect="auto")
    ax.set_xticks(range(7))
    ax.set_xticklabels(an.WEEKDAYS)
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels(hm["departments"], fontsize=8)
    ax.yaxis.grid(False)
    for i in range(data.shape[0]):
        for j in range(7):
            ax.text(j, i, f"{data[i, j]:.1f}", ha="center", va="center", fontsize=7,
                    color="white" if data[i, j] > data.max() * 0.45 else INK)
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02).outline.set_visible(False)
    return _finish(fig, ax, "Average daily visits by department and weekday")
