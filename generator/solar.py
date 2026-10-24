"""Stage 2: SOLAR-SASWAD-01 — clear-sky irradiance x panel efficiency x temp derate,
capped by inverter rating. Lower output Jun-Sep (monsoon cloud cover)."""
import numpy as np
import pandas as pd


def simulate_solar(minute_df, asset_cfg, irradiance_kw_m2, ambient_temp_c, plant_load_kw, rng):
    n = len(minute_df)
    rated_kwp = asset_cfg["rated_kwp"]
    panel_eff = asset_cfg["panel_efficiency"]
    inverter_kw = asset_cfg["inverter_kw"]
    temp_coeff = asset_cfg["temp_derate_coeff"]

    panel_area_m2 = rated_kwp / panel_eff
    cell_temp_c = ambient_temp_c + irradiance_kw_m2 * 25.0   # assumed NOCT-style heating
    temp_derate = 1.0 + temp_coeff * np.maximum(cell_temp_c - 25.0, 0.0)
    temp_derate = np.clip(temp_derate, 0.6, 1.0)

    gen_kw = irradiance_kw_m2 * panel_area_m2 * panel_eff * temp_derate
    gen_kw = np.minimum(gen_kw, inverter_kw)
    gen_kw = np.maximum(gen_kw, 0.0)

    self_consumed_kw = np.minimum(gen_kw, plant_load_kw)
    exported_kw = gen_kw - self_consumed_kw

    return pd.DataFrame({
        "kW_generated": gen_kw,
        "kW_self_consumed": self_consumed_kw,
        "kW_exported": exported_kw,
    })
