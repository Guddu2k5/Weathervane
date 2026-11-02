"""Climate trend: ordinary least squares on annual mean temperature.

We fit ``mean_temperature ~ year`` with scikit-learn's LinearRegression and
derive a 95% confidence interval for the slope from the t-distribution. If the
interval includes zero we say so instead of claiming a trend.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression

from .history import BASELINE, History

MIN_YEARS = 15
MIN_COVERAGE = 0.9  # a year needs >= 90% valid days to count


def climate_trend(hist: History, current_year: int) -> Optional[dict]:
    tmean = hist.tmean
    years, means = [], []
    for year in range(int(hist.years.min()), current_year):  # exclude the partial current year
        mask = hist.years == year
        total = int(mask.sum())
        if total == 0:
            continue
        values = tmean[mask]
        valid = np.isfinite(values)
        if valid.sum() < MIN_COVERAGE * total or total < 360:
            continue
        years.append(year)
        means.append(float(values[valid].mean()))

    n = len(years)
    if n < MIN_YEARS:
        return None

    x = np.array(years, dtype=float).reshape(-1, 1)
    y = np.array(means, dtype=float)
    model = LinearRegression().fit(x, y)
    slope = float(model.coef_[0])
    r2 = float(model.score(x, y))

    residuals = y - model.predict(x)
    dof = n - 2
    sxx = float(((x[:, 0] - x[:, 0].mean()) ** 2).sum())
    se = float(np.sqrt((residuals ** 2).sum() / dof / sxx)) if sxx > 0 and dof > 0 else float("nan")
    if not np.isfinite(se) or se == 0:
        return None
    t_crit = float(stats.t.ppf(0.975, dof))
    p_value = float(2 * stats.t.sf(abs(slope / se), dof))
    ci_low, ci_high = slope - t_crit * se, slope + t_crit * se

    if p_value < 0.05 and slope > 0:
        verdict = "warming"
    elif p_value < 0.05 and slope < 0:
        verdict = "cooling"
    else:
        verdict = "inconclusive"

    base = [m for yr, m in zip(years, means) if BASELINE[0] <= yr <= BASELINE[1]]
    first, last = years[0], years[-1]
    return {
        "first_year": first,
        "last_year": last,
        "n_years": n,
        "slope_per_decade": round(slope * 10, 2),
        "ci_low_per_decade": round(ci_low * 10, 2),
        "ci_high_per_decade": round(ci_high * 10, 2),
        "total_change": round(slope * (last - first), 2),
        "r2": round(r2, 3),
        "p_value": round(p_value, 4),
        "verdict": verdict,
        "baseline_mean": round(float(np.mean(base)), 1) if base else None,
        "series": [{"year": yr, "mean": round(m, 2)} for yr, m in zip(years, means)],
        "line": [
            {"year": first, "value": round(float(model.predict([[first]])[0]), 2)},
            {"year": last, "value": round(float(model.predict([[last]])[0]), 2)},
        ],
    }
