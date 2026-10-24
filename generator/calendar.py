"""Stage 1: calendar — shift windows, holidays, maintenance days, minute-resolution frame."""
import datetime as dt
import numpy as np
import pandas as pd


def build_minute_frame(config):
    """Return a DataFrame with one row per minute for 365 days, with calendar columns."""
    start = dt.datetime.strptime(config["start_date"], "%Y-%m-%d")
    n_days = 365
    periods = n_days * 24 * 60
    ts = pd.date_range(start=start, periods=periods, freq="min", tz=config["timezone"])
    # Store as naive local wall-clock timestamps: tz-aware datetimes get silently
    # converted to UTC by SQLite/to_sql on write, which would shift every hour-of-day
    # computation downstream (night/day windows, shift windows, etc.) by +5:30.
    ts = ts.tz_localize(None)
    df = pd.DataFrame({"ts": ts})
    df["date"] = df["ts"].dt.date
    df["dow"] = df["ts"].dt.dayofweek  # Monday=0 ... Sunday=6
    df["time_of_day"] = df["ts"].dt.strftime("%H:%M")
    df["minute_of_day"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute

    holidays = {h["date"] for h in config["calendar"]["holidays_2025"]}
    maint_days = {m["date"] for m in config["calendar"]["planned_maintenance_days"]}
    df["date_str"] = df["ts"].dt.strftime("%Y-%m-%d")
    df["is_holiday"] = df["date_str"].isin(holidays)
    df["is_maintenance_day"] = df["date_str"].isin(maint_days)
    df["is_sunday"] = df["dow"] == 6
    df["is_saturday"] = df["dow"] == 5

    shifts = config["calendar"]["shifts"]
    a_start = _to_minutes(shifts["A"]["start"])
    a_end = _to_minutes(shifts["A"]["end"])
    b_start = _to_minutes(shifts["B"]["start"])
    b_end = _to_minutes(shifts["B"]["end"])

    def shift_for_minute(row):
        if row["is_holiday"] or row["is_maintenance_day"]:
            return "OFF"
        if row["is_sunday"] and config["calendar"]["sunday_off"]:
            return "OFF"
        if row["is_saturday"]:
            rule = config["calendar"]["saturday_rule"]
            if rule == "off":
                return "OFF"
            if rule == "half_day":
                half_shift = config["calendar"]["saturday_half_day_shift"]
                if half_shift == "A" and a_start <= row["minute_of_day"] < a_end:
                    return "A"
                if half_shift == "B" and b_start <= row["minute_of_day"] < b_end:
                    return "B"
                return "OFF"
            # full_day falls through to normal logic below
        m = row["minute_of_day"]
        if a_start <= m < a_end:
            return "A"
        if b_start <= m < b_end:
            return "B"
        return "OFF"

    df["shift"] = df.apply(shift_for_minute, axis=1)
    df["is_production"] = df["shift"] != "OFF"
    df.drop(columns=["date_str"], inplace=True)
    return df


def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)
