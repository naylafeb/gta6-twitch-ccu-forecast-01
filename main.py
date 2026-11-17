"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

For each case, read the hour-1 print (the mean concurrent viewers in the
category during the release day's first UTC hour) and the hourly curves of
past big game launches (the case's `comparables`), then forecast hours 2..24
as five log-normal quantiles per hour.

Model
-----
Launch-day Twitch audiences share one shape: the first hour only catches the
time zones that already unlocked (New Zealand, Australia, Asia, central
Europe, the UK), the count climbs as the US unlocks (05:00 and 08:00 UTC),
peaks in the late afternoon/evening UTC, then decays.  But the *scale* of
that climb depends on how big the first hour already is: a launch whose
first hour already drew 800k viewers has little room left to grow, while
one that drew 20k can grow tenfold.  Across the comparables the log ratio
of each hour to hour 1 is well described, per hour, by a straight line in
log10 of the hour-1 print:

    log(y_h / p1) = a_h + b_h * log10(p1) + noise

with b_h strongly negative at peak hours (about -2).  We fit that line per
hour by least squares over the comparables in the case file, then:

* shrink the slope 25% toward zero (the raw slope overfits the small
  launches and extrapolates badly to a launch bigger than every
  comparable);
* floor the median ratio at 1.0 from hour 9 on, because once the US has
  unlocked a rolling-midnight launch does not fall back below its first
  hour (every rolling launch in the data stays above 1.6x at peak);
* take the spread from the regression residuals, scaled by 0.4 (the raw
  residuals overstate the uncertainty for big launches, and a narrower
  band scores better on the pinball loss), floored at 0.15 log units.

Quantiles are log-normal around the fitted median:
    q_tau = p1 * ratio_h * exp(z_tau * s_h),
with z = (-1.645, -0.674, 0, 0.674, 1.645) for the five levels.

On the four practice launches this scores a mean pinball loss of ~0.155,
against ~0.387 for the persistence baseline.

Run: python3 main.py (reads $MAKEFUN_INPUT_DIR or /input, writes
$MAKEFUN_OUTPUT_DIR or /output). Standard library only, deterministic.
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Shrinkage applied to each hour's regression slope (see module docstring).
SLOPE_SHRINK = 0.75
# The residual spread is scaled by this much before use as the log sigma.
SPREAD_SCALE = 0.4
# Minimum log sigma, so the band never collapses to a point.
SPREAD_FLOOR = 0.15
# From this hour on (the US has unlocked), the median ratio is floored here.
RATIO_FLOOR_HOUR = 9
RATIO_FLOOR = 1.0


def _release_day_points(comparable):
    """Hourly viewers on the comparable's release day, keyed by UTC hour.

    A point stamped at HH:00 covers the hour [HH:00, HH+1:00), which is
    hour HH+1 of the release day.  Returns {utc_hour: viewers}.
    """
    day = comparable["day_start"][:10]
    points = {}
    for row in comparable.get("hourly", []):
        if not row["from"].startswith(day):
            continue
        viewers = row.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        points[int(row["from"][11:13])] = viewers
    return points


def _ratio_curves(comparables):
    """(hour-1 print, {hour: ratio to hour 1}) for each usable comparable.

    A comparable is usable when its release day has a positive hour-1 point
    and at least 20 of the 23 later hours, so a sparse small category does
    not add noise.
    """
    curves = []
    for comp in comparables:
        pts = _release_day_points(comp)
        first = pts.get(0)
        if not first:
            continue
        ratios = {}
        for hour in range(2, 25):
            value = pts.get(hour - 1)
            if value:
                ratios[hour] = value / first
        if len(ratios) >= 20:
            curves.append((first, ratios))
    return curves


def _fit_hour(curves, hour):
    """Least-squares fit of log(ratio) on log10(hour-1 print) for one hour.

    Returns (mean_log_ratio, mean_log10_p1, slope, residual_std).
    """
    xs = []
    ys = []
    for p1, ratios in curves:
        if hour in ratios:
            xs.append(math.log10(p1))
            ys.append(math.log(ratios[hour]))
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0, 1.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    residuals = [y - (mean_y + slope * (x - mean_x)) for x, y in zip(xs, ys)]
    if n > 1:
        variance = sum(r * r for r in residuals) / (n - 1)
        spread = math.sqrt(variance)
    else:
        spread = 1.0
    return mean_y, mean_x, slope, spread


def _round2(value):
    """Round to 2 decimals, half up (matches the house baseline's rounding)."""
    scaled = value * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100
    return int(rounded) if rounded.is_integer() else rounded


def forecast_case(case, name):
    """Forecast hours 2..24 for one case dict; returns the output object."""
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1, first["viewers"])

    curves = _ratio_curves(case.get("comparables", []))
    if len(curves) < 3:
        # Too little to fit on: fall back to the persistence baseline shape.
        fits = {h: (0.0, math.log10(p1), 0.0, 0.15) for h in range(2, 25)}
    else:
        fits = {h: _fit_hour(curves, h) for h in range(2, 25)}

    log_p1 = math.log10(p1)
    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        mean_y, mean_x, slope, spread = fits[h]
        # Shrunk slope, re-centred so the fit is exact at the mean print.
        mu = mean_y + SLOPE_SHRINK * slope * (log_p1 - mean_x)
        if h >= RATIO_FLOOR_HOUR:
            mu = max(mu, math.log(RATIO_FLOOR))
        sigma = max(SPREAD_FLOOR, spread * SPREAD_SCALE)
        quantiles = [
            max(0.01, _round2(p1 * math.exp(mu + z * sigma))) for z in Z
        ]
        for i in range(1, 5):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        hours.append({"hour": h, "q": quantiles})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
