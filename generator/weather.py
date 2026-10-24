"""Stage 1: weather — synthetic ambient temp, humidity, wet-bulb, irradiance."""
import os
import numpy as np
import pandas as pd


def build_weather(minute_df, config, rng):
    """Attach weather columns to the minute-resolution frame."""
    w = config["weather"]
    csv_path = w.get("nasa_power_csv_path")
    if w.get("source") == "nasa_power_csv" and csv_path and os.path.exists(csv_path):
        return _load_nasa_power(minute_df, csv_path)

    doy = minute_df["ts"].dt.dayofyear.to_numpy()
    hour_frac = (minute_df["ts"].dt.hour + minute_df["ts"].dt.minute / 60.0).to_numpy()
    n = len(minute_df)

    # Seasonal component: warmest ~May (doy~125), cooler in monsoon/winter.
    seasonal = w["ambient_temp_c"]["amplitude"] * np.cos(2 * np.pi * (doy - 125) / 365.0)
    monsoon_months = set(w["monsoon_months"])
    is_monsoon = minute_df["ts"].dt.month.isin(monsoon_months).to_numpy()
    seasonal = np.where(is_monsoon, seasonal - 3.0, seasonal)  # monsoon dip

    # Diurnal component: min at ~05:00, max at ~15:00
    diurnal = w["ambient_temp_c"]["daily_amplitude"] * np.sin(2 * np.pi * (hour_frac - 5) / 24.0)
    diurnal = np.clip(diurnal, -w["ambient_temp_c"]["daily_amplitude"], w["ambient_temp_c"]["daily_amplitude"])

    temp = w["ambient_temp_c"]["annual_mean"] + seasonal * 0.5 + diurnal
    temp += rng.normal(0, w["noise_std_temp_c"], n)

    humidity = np.where(
        is_monsoon,
        w["humidity_pct"]["monsoon_mean"] - 10 * np.sin(2 * np.pi * (hour_frac - 5) / 24.0),
        w["humidity_pct"]["dry_season_mean"] - 15 * np.sin(2 * np.pi * (hour_frac - 5) / 24.0),
    )
    humidity += rng.normal(0, w["noise_std_humidity_pct"], n)
    humidity = np.clip(humidity, 10, 100)

    # Stull (2011) approximation for wet-bulb temperature from T and RH
    t = temp
    rh = humidity
    wet_bulb = (
        t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t + rh) - np.arctan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
        - 4.686035
    )

    # Clear-sky-ish irradiance: zero at night, sinusoidal between sunrise/sunset,
    # scaled to approx daily kWh/m2 target, reduced in monsoon by cloud factor.
    daylight = np.clip(np.sin(np.pi * (hour_frac - 6) / 12.0), 0, None)
    base_irr_kw_m2 = 1.0  # peak clear-sky approx
    cloud_factor = np.where(is_monsoon, 0.55, 0.92)
    cloud_noise = rng.uniform(0.85, 1.0, n)
    irradiance = daylight * base_irr_kw_m2 * cloud_factor * cloud_noise
    irradiance = np.where((hour_frac < 6) | (hour_frac > 18), 0.0, irradiance)

    minute_df = minute_df.copy()
    minute_df["ambient_temp_c"] = temp
    minute_df["humidity_pct"] = humidity
    minute_df["wet_bulb_c"] = wet_bulb
    minute_df["irradiance_kw_m2"] = irradiance
    return minute_df


def _load_nasa_power(minute_df, csv_path):
    daily = pd.read_csv(csv_path)
    raise NotImplementedError("NASA POWER CSV loader present but not wired up for this prototype; using synthetic weather instead.")
