"""Aggregated analytics (Pandas grouped analysis + NumPy summary statistics).

Everything returned from this module is an aggregate. Individual visits are
never exposed, and small cells (fewer than MIN_CELL visits) are suppressed
in age-band outputs.
"""
import numpy as np
import pandas as pd

AGE_ORDER = ["0-12", "13-17", "18-29", "30-44", "45-59", "60-74", "75+"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
VISIT_TYPES = ["Outpatient", "Follow-up", "Scheduled", "Emergency"]
MIN_CELL = 5

COLUMNS = ["visit_id", "patient_id", "visit_date", "visit_type", "department", "age_band", "gender"]
_cache = {"sig": None, "df": None}


# --------------------------------------------------------------- loading
def load_visits(db):
    """Load joined visit data into a DataFrame (cached until the data changes)."""
    sig = (
        db.scalar("SELECT COUNT(*) FROM visits", default=0),
        db.scalar("SELECT MAX(visit_id) FROM visits", default=0),
    )
    if _cache["sig"] == sig and _cache["df"] is not None:
        return _cache["df"]
    rows = db.all(
        "SELECT v.visit_id, v.patient_id, v.visit_date, v.visit_type, "
        "d.department_name AS department, p.age_band, p.gender "
        "FROM visits v "
        "JOIN departments d ON d.department_id = v.department_id "
        "JOIN patients p ON p.patient_id = v.patient_id"
    )
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df["visit_date"] = pd.to_datetime(df["visit_date"].astype(str).str[:10])
    else:
        df["visit_date"] = pd.to_datetime(df["visit_date"])
    _cache.update(sig=sig, df=df)
    return df


def invalidate():
    """Drop the cached DataFrame after records change."""
    _cache.update(sig=None, df=None)


def apply_filters(df, start=None, end=None, department=None, visit_type=None):
    out = df
    if start is not None:
        out = out[out["visit_date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["visit_date"] <= pd.Timestamp(end)]
    if department:
        out = out[out["department"] == department]
    if visit_type:
        out = out[out["visit_type"] == visit_type]
    return out


def window(df, days):
    """Return (start, end) for the last `days` days of data (0 = all data)."""
    if df.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    end = df["visit_date"].max()
    start = df["visit_date"].min() if not days else max(df["visit_date"].min(), end - pd.Timedelta(days=days - 1))
    return start, end


def mask_small(n):
    """Privacy rule: hide counts between 1 and MIN_CELL-1."""
    n = int(n)
    return None if 0 < n < MIN_CELL else n


# --------------------------------------------------------------- helpers
def daily_series(df, start, end):
    idx = pd.date_range(start, end, freq="D")
    if df.empty:
        return pd.Series(0, index=idx, dtype=int)
    return df.groupby("visit_date").size().reindex(idx, fill_value=0).astype(int)


def monthly_series(df, start, end):
    periods = pd.period_range(start, end, freq="M")
    if df.empty:
        return pd.Series(0, index=periods, dtype=int)
    counts = df.groupby(df["visit_date"].dt.to_period("M")).size()
    return counts.reindex(periods, fill_value=0).astype(int)


def weekday_average(daily):
    if daily.empty:
        return pd.Series(0.0, index=range(7))
    return daily.groupby(daily.index.dayofweek).mean().reindex(range(7), fill_value=0.0)


def _pct_change(new, old):
    return None if not old else round((new - old) / old * 100, 1)


# --------------------------------------------------------------- tables
def department_report(df, start, end):
    daily = daily_series(df, start, end)
    n_days = max(len(daily), 1)
    if df.empty:
        return pd.DataFrame(columns=["Department", "Visits", "Share %", "Avg per day",
                                     "Busiest weekday", "Peak month", "Emergency %"])
    rows = []
    total = len(df)
    for name, g in df.groupby("department"):
        d = daily_series(g, start, end)
        wk = weekday_average(d)
        months = g.groupby(g["visit_date"].dt.to_period("M")).size()
        rows.append({
            "Department": name,
            "Visits": int(len(g)),
            "Share %": round(len(g) / total * 100, 1),
            "Avg per day": round(len(g) / n_days, 1),
            "Busiest weekday": WEEKDAYS[int(wk.values.argmax())],
            "Peak month": months.idxmax().strftime("%b %Y"),
            "Emergency %": round((g["visit_type"] == "Emergency").mean() * 100, 1),
        })
    return pd.DataFrame(rows).sort_values("Visits", ascending=False).reset_index(drop=True)


def monthly_report(df, start, end):
    m = monthly_series(df, start, end)
    out = pd.DataFrame({"Month": [p.strftime("%b %Y") for p in m.index], "Visits": m.values})
    first, last = m.index[0], m.index[-1]
    partial = []
    for p in m.index:
        is_partial = (p == first and pd.Timestamp(start) > p.start_time) or \
                     (p == last and pd.Timestamp(end) < p.end_time.normalize())
        partial.append(bool(is_partial))
    out["Partial month"] = partial
    change = pd.Series(m.values, dtype=float).pct_change().mul(100).round(1)
    # a change involving a partial month is not a fair comparison, so leave it blank
    prev_partial = pd.Series(partial).shift(1, fill_value=False)
    change[pd.Series(partial) | prev_partial] = np.nan
    out["Change vs previous month %"] = change
    return out


def age_band_report(df):
    counts = df["age_band"].value_counts().reindex(AGE_ORDER, fill_value=0)
    total = int(counts.sum())
    out = pd.DataFrame({
        "Age band": counts.index,
        "Visits": [mask_small(v) for v in counts.values],
        "Share %": [round(v / total * 100, 1) if total else 0.0 for v in counts.values],
    })
    return out


def age_by_department(df):
    if df.empty:
        return pd.DataFrame(index=[], columns=AGE_ORDER)
    ct = pd.crosstab(df["department"], df["age_band"]).reindex(columns=AGE_ORDER, fill_value=0)
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index]
    return ct


def visit_type_report(df):
    counts = df["visit_type"].value_counts().reindex(VISIT_TYPES, fill_value=0)
    total = int(counts.sum())
    return pd.DataFrame({
        "Visit type": counts.index, "Visits": counts.values.astype(int),
        "Share %": [round(v / total * 100, 1) if total else 0.0 for v in counts.values],
    })


def summary_stats(daily):
    """NumPy summary statistics for daily visit counts."""
    a = np.asarray(daily, dtype=float)
    if a.size == 0:
        return {k: 0 for k in ("mean", "median", "std", "min", "max", "p90", "cv")}
    mean = float(np.mean(a))
    return {
        "mean": round(mean, 1), "median": round(float(np.median(a)), 1),
        "std": round(float(np.std(a)), 1), "min": int(a.min()), "max": int(a.max()),
        "p90": round(float(np.percentile(a, 90)), 1),
        "cv": round(float(np.std(a) / mean * 100), 1) if mean else 0.0,
    }


def workload_flags(df):
    """Compare each department's last 30 days with the 90 days before it.

    An operational load indicator only - it says nothing about patients.
    """
    if df.empty:
        return []
    end = df["visit_date"].max()
    recent_start = end - pd.Timedelta(days=29)
    base_start = recent_start - pd.Timedelta(days=90)
    recent = df[df["visit_date"] >= recent_start]
    base = df[(df["visit_date"] >= base_start) & (df["visit_date"] < recent_start)]
    flags = []
    for name in sorted(df["department"].unique()):
        r = len(recent[recent["department"] == name]) / 30
        b = len(base[base["department"] == name]) / 90
        pct = _pct_change(r, b)
        if pct is None:
            continue
        status = "Elevated" if pct >= 15 else "Lower" if pct <= -15 else "Stable"
        flags.append({"department": name, "recent_avg": round(r, 1), "baseline_avg": round(b, 1),
                      "change_pct": pct, "status": status})
    return sorted(flags, key=lambda f: f["change_pct"], reverse=True)


def weekday_heatmap(df, start, end):
    if df.empty:
        return {"departments": [], "values": [], "max": 0}
    days = pd.date_range(start, end, freq="D")
    n_per_wd = pd.Series(days.dayofweek).value_counts().reindex(range(7), fill_value=1).clip(lower=1)
    ct = pd.crosstab(df["department"], df["visit_date"].dt.dayofweek).reindex(columns=range(7), fill_value=0)
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index]
    avg = ct.div(n_per_wd.values, axis=1).round(1)
    return {"departments": list(avg.index), "values": avg.values.tolist(), "max": float(avg.values.max())}


# --------------------------------------------------------------- payload
def dashboard_payload(df, days=365, admin=False):
    start, end = window(df, days)
    cur = apply_filters(df, start, end)
    daily = daily_series(cur, start, end)
    stats = summary_stats(daily.values)
    n_days = len(daily)

    prev_change = None
    if days:
        prev_start = start - pd.Timedelta(days=days)
        prev = apply_filters(df, prev_start, start - pd.Timedelta(days=1))
        if len(prev) and prev_start >= df["visit_date"].min():
            prev_change = _pct_change(len(cur), len(prev))

    dept = department_report(cur, start, end)
    wk = weekday_average(daily)
    months = monthly_report(cur, start, end)
    ages = age_band_report(cur)
    types = visit_type_report(cur)

    recent = daily.tail(30)
    ma7 = daily.rolling(7, min_periods=1).mean().tail(30)

    payload = {
        "meta": {
            "start": start.strftime("%d %b %Y"), "end": end.strftime("%d %b %Y"),
            "days": n_days, "range": int(days),
        },
        "kpis": {
            "total_visits": int(len(cur)),
            "change_vs_previous": prev_change,
            "avg_daily": stats["mean"],
            "median_daily": stats["median"],
            "std_daily": stats["std"],
            "p90_daily": stats["p90"],
            "unique_patients": int(cur["patient_id"].nunique()) if len(cur) else 0,
            "busiest_department": dept.iloc[0]["Department"] if len(dept) else "-",
            "busiest_department_visits": int(dept.iloc[0]["Visits"]) if len(dept) else 0,
            "peak_weekday": WEEKDAYS[int(wk.values.argmax())] if len(cur) else "-",
            "peak_weekday_avg": round(float(wk.max()), 1) if len(cur) else 0,
            "emergency_share": round(float((cur["visit_type"] == "Emergency").mean() * 100), 1) if len(cur) else 0,
        },
        "pulse": {
            "labels": [d.strftime("%d %b") for d in recent.index],
            "values": recent.values.tolist(),
            "ma7": [round(float(v), 1) for v in ma7.values],
            "peak_label": recent.idxmax().strftime("%d %b") if len(recent) else "-",
            "peak_value": int(recent.max()) if len(recent) else 0,
            "avg": round(float(recent.mean()), 1) if len(recent) else 0,
        },
        "monthly": {
            "labels": [m + (" *" if p else "") for m, p in zip(months["Month"], months["Partial month"])],
            "values": months["Visits"].astype(int).tolist(),
            "partial": months["Partial month"].tolist(),
        },
        "departments": [
            {"name": r["Department"], "visits": int(r["Visits"]), "share": float(r["Share %"]),
             "avg_per_day": float(r["Avg per day"])} for _, r in dept.iterrows()
        ],
        "age_bands": {
            "labels": ages["Age band"].tolist(),
            "values": [v if v is not None else 0 for v in ages["Visits"]],
            "shares": ages["Share %"].tolist(),
            "suppressed": [v is None for v in ages["Visits"]],
        },
        "visit_types": {"labels": types["Visit type"].tolist(), "values": types["Visits"].tolist(),
                        "shares": types["Share %"].tolist()},
        "weekday": {"labels": WEEKDAYS, "values": [round(float(v), 1) for v in wk.values]},
    }
    if admin:
        payload["admin"] = {
            "flags": workload_flags(df),
            "heatmap": weekday_heatmap(cur, start, end),
        }
    return payload
