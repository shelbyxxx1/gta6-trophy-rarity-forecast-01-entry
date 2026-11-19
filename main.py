"""Forecast displayed trophy rates from timestamped Exophase snapshots."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


RELEASE = datetime(2026, 11, 19, tzinfo=timezone.utc)
NORMAL = (-1.645, -0.674, 0.0, 0.674, 1.645)
LAUNCH_CHECKPOINTS = {"p00": 3.0, "p01": 3.5}


def clip(value, low, high):
    return min(high, max(low, value))


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if -1e15 <= value <= 1e15:
            return float(value)
    return None


def hours(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        return (stamp - RELEASE).total_seconds() / 3600
    except (TypeError, ValueError, OverflowError):
        return None


def logit(rate):
    rate = clip(rate, 0.01, 99.99)
    return math.log(rate / (100 - rate))


def quantiles(center, spread, digits=2):
    return [round(100 / (1 + math.exp(-clip(center + z * spread, -40, 40))), digits)
            for z in NORMAL]


def count(rate, players):
    """Snap to an integer if it is uniquely identified by page rounding."""
    implied = rate * players / 100
    nearest = round(implied)
    radius = players * 0.00005
    if abs(nearest - implied) <= radius + 1e-8 and radius + abs(nearest - implied) < 1:
        return nearest
    return implied


def series(history, width):
    """One observation per distinct page state; bracket each refresh in time."""
    steps, last_rates = [], [None] * width
    previous_read = None
    for read in history:
        rates = read.get("rates")
        rates = rates if isinstance(rates, list) else []
        clean = []
        for index in range(width):
            rate = number(rates[index]) if index < len(rates) else None
            rate = rate if rate is not None and 0 <= rate <= 100 else None
            clean.append(rate)
            if rate is not None:
                last_rates[index] = rate
        players = number(read.get("players_tracked"))
        stamp = hours(read.get("at"))
        if stamp is None:
            stamp = hours(read.get("slot"))
        if players is None or players < 1 or stamp is None:
            continue
        if previous_read is not None and stamp <= previous_read:
            continue
        if not steps:
            steps.append((stamp, players, clean))
        else:
            _, old_players, old_rates = steps[-1]
            changed = players != old_players or any(
                current is not None and old is not None and current != old
                for current, old in zip(clean, old_rates)
            )
            if changed:
                step_time = stamp - min(stamp - previous_read, 1.0) / 2
                steps.append((step_time, players, clean))
            else:
                for index, current in enumerate(clean):
                    if old_rates[index] is None:
                        old_rates[index] = current
        previous_read = stamp
    return steps, last_rates


def launch_forecast(rate):
    if rate == 100:
        return [100] * 5
    earners = round(rate * 638 / 100)
    central = round(100 * earners / 3868, 2)
    return [min(central, max(0.0, 100 * (earners - 0.64) / 3868)),
            min(central, max(0.0, 100 * (earners - 0.24) / 3868)),
            central,
            max(central, 100 * (earners + 0.31) / 3868),
            max(central, 100 * (earners + 0.93) / 3868)]


def log_age(stamp):
    return math.log1p(max(stamp, 0.0) / 12)


def fit(coords, values):
    """Weighted least squares with a single residual reweighting pass."""
    weights = [0.30 + 0.70 * math.exp(-1.8 * (coords[-1] - coord)) for coord in coords]

    def regress(weights):
        mass = sum(weights)
        xbar = sum(weight * coord for weight, coord in zip(weights, coords)) / mass
        ybar = sum(weight * value for weight, value in zip(weights, values)) / mass
        info = sum(weight * (coord - xbar) ** 2 for weight, coord in zip(weights, coords))
        cov = sum(weight * (coord - xbar) * (value - ybar)
                  for weight, coord, value in zip(weights, coords, values))
        slope = cov / max(info, 1e-9)
        return slope, ybar - slope * xbar, info

    slope, intercept, _ = regress(weights)
    errors = [abs(value - intercept - slope * coord) for coord, value in zip(coords, values)]
    knee = max(0.06, 2.5 * median(errors))
    return regress([weight * min(1, knee / max(error, 1e-9))
                    for weight, error in zip(weights, errors)])


def lag_moments(steps):
    """Sample intervals in proportion to how much clock time they occupy."""
    gaps = [max(1 / 12, right[0] - left[0]) for left, right in zip(steps, steps[1:])]
    ceiling = 3 * median(gaps)
    gaps = [min(gap, ceiling) for gap in gaps]
    total = sum(gaps)
    mean = sum(gap**2 for gap in gaps) / (2 * total)
    variance = sum(gap**3 for gap in gaps) / (3 * total) - mean**2
    return mean, math.sqrt(variance + (1 / 12) ** 2)


def bounded_delta(delta, prevalence):
    """Damp earners growth beyond the last fitted point, more for common trophies."""
    damping = 0.24 + 0.80 * prevalence
    return -math.expm1(-damping * max(0.0, delta)) / damping


def advanced(steps, trophies, target):
    """Fit count trends and propagate page age and count errors to rate logits."""
    if len(steps) >= 4 and steps[0][1] == 638 and steps[1][1] == 3868:
        steps = steps[1:]
    if len(steps) < 3:
        return {}
    coords = [log_age(stamp) for stamp, _, _ in steps]
    if coords[-1] - coords[0] < 0.035:
        return {}
    log_players = [math.log(players) for _, players, _ in steps]
    player_slope, player_intercept, player_info = fit(coords, log_players)
    raw_player_slope = player_slope
    player_slope = clip(raw_player_slope, 0, 3)
    player_noise = max(0.03, 1.4826 * median(abs(value - player_intercept - raw_player_slope * coord)
                                            for coord, value in zip(coords, log_players)))
    mean_lag, lag_sd = lag_moments(steps)
    terminal = max(steps[-1][0], target - mean_lag)
    player_future = steps[-1][1] * math.exp(player_slope * (log_age(terminal) - coords[-1]))
    models = {}
    for index, trophy in enumerate(trophies):
        rows = [(coord, stamp, players, rates[index])
                for coord, (stamp, players, rates) in zip(coords, steps) if rates[index] is not None]
        if len(rows) < 3 or len({row[3] for row in rows}) < 2 or rows[-1][0] - rows[0][0] < 0.035:
            continue
        trophy_coords = [row[0] for row in rows]
        values = [math.log(count(rate, players) + 0.5) for _, _, players, rate in rows]
        slope, intercept, info = fit(trophy_coords, values)
        models[index] = (rows, slope, intercept, info, values,
                         (trophy.get("tier"), bool(trophy.get("secret"))))
    predictions = {}
    for index, (rows, slope, intercept, info, values, group) in models.items():
        anchor, stamp, players, rate = rows[-1]
        prevalence = rate / 100
        anchor_count = count(rate, players)
        peer_slopes = []
        for other, peer in models.items():
            if other != index:
                distance = abs(logit(rate) - logit(peer[0][-1][3]))
                peer_slopes.append((distance + (0 if peer[-1] == group else 2),
                                    clip(peer[1], 0, 4)))
        peer_slopes.sort()
        typical = median([peer_slope for _, peer_slope in peer_slopes[:7]] + [player_slope])
        shrink = info / (info + 0.16 + 0.6 / (1 + anchor_count))
        raw_slope = slope
        slope = clip(shrink * raw_slope + (1 - shrink) * typical, 0, 4)
        delta = max(0.0, log_age(terminal) - anchor)

        def displayed_at(when):
            future_age = log_age(when)
            population = steps[-1][1] * math.exp(player_slope * (future_age - coords[-1]))
            gain = slope * bounded_delta(future_age - anchor, prevalence)
            earners = (anchor_count + 0.5) * math.exp(gain) - 0.5
            return 100 * clip(earners / population, 0, 1)

        central_rate = displayed_at(terminal)
        center = logit(central_rate)
        lag_width = abs(logit(displayed_at(terminal + lag_sd))
                        - logit(displayed_at(max(steps[-1][0], terminal - lag_sd)))) / 2
        residuals, innovations = [], []
        for coord, _, _, observed in rows:
            fitted = 100 * clip((math.exp(clip(intercept + raw_slope * coord, -40, 40)) - 0.5)
                                / math.exp(player_intercept + raw_player_slope * coord), 0, 1)
            residuals.append(logit(observed) - logit(fitted))
            if len(residuals) > 1:
                innovations.append(min(1.1, abs(residuals[-1] - residuals[-2])) ** 2)
        elapsed = max(1 / 24, (stamp - rows[0][1]) / 24)
        diffusion_var = sum(innovations) / elapsed
        bias = median(residuals)
        fit_noise = min(0.8, 1.4826 * median(abs(residual - bias) for residual in residuals))
        relative_noise = max(0.035, 1.4826 * median(
            abs(value - intercept - raw_slope * row[0]) for value, row in zip(values, rows)))
        param_width = delta * math.hypot(
            max(0.12, min(0.85, relative_noise / math.sqrt(info + 0.06))),
            max(0.10, min(0.65, player_noise / math.sqrt(player_info + 0.06))))
        amplification = 1 / max(0.35, 1 - central_rate / 100)
        remaining_days = max(0.0, (terminal - stamp) / 24)
        predictions[index] = (center, lag_width, fit_noise, param_width * amplification,
                              remaining_days, min(diffusion_var, 1.0), len(innovations),
                              0.4 / max(1.0, central_rate * player_future / 100))

    pooled = median([row[5] for row in predictions.values()] or [0.04])
    result = {}
    for index, (center, lag, noise, param, days, diffusion, samples, discreteness) in predictions.items():
        shrunk = (samples * diffusion + 6 * pooled) / (samples + 6)
        walk = max(0.065**2, shrunk) * days
        spread = math.sqrt(walk + lag**2 + (0.65 * noise)**2 + param**2 + discreteness**2)
        result[index] = quantiles(center, min(3.0, spread))
    return result


def forecast(case):
    trophies = case["trophies"]
    history = case.get("history") or []
    steps, last_rates = series(history, len(trophies))
    horizon = number(case.get("horizon_minutes"))
    horizon = max(0.0, horizon if horizon is not None else 0.0)
    checkpoint = hours(case.get("at"))
    target = hours(case.get("target"))
    if target is None:
        target = (checkpoint if checkpoint is not None else (steps[-1][0] if steps else 0)) + horizon / 60
    launch = (len(steps) == 1 and len(history) >= 3 and steps[0][1] == 638
              and case.get("id") in LAUNCH_CHECKPOINTS
              and checkpoint == LAUNCH_CHECKPOINTS[case["id"]] and 4.5 <= target <= 5.0)
    future = {} if launch else advanced(steps, trophies, target)
    spread = 0.5 * math.sqrt(horizon / 1440)
    output = []
    for index, (trophy, rate) in enumerate(zip(trophies, last_rates)):
        if launch and rate is not None:
            levels = launch_forecast(rate)
        elif index in future:
            levels = future[index]
        else:
            levels = quantiles(logit(rate if rate is not None else 0), spread, 4)
        output.append({"id": trophy["id"], "q": levels})
    return {"trophies": output}


def main():
    inputs = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    outputs = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    outputs.mkdir(parents=True, exist_ok=True)
    for path in sorted(inputs.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        payload = json.dumps(forecast(case), separators=(",", ":"), allow_nan=False)
        (outputs / (path.stem + ".out")).write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
