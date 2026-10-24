"""Stage 4: Scope 1 / Scope 2 emissions and tariff cost.
Scope 2 = grid kWh x grid factor. Scope 1 = fuel x factor + refrigerant kg x GWP.
Plus a solar avoided-emissions column. All factors are config placeholders —
VERIFY before use (see config.yaml emission_factors / tariff.source_note).
"""
import numpy as np
import pandas as pd


def compute_emissions_15m(grid_kwh, lpg_kg, gas_kg, diesel_litre, refrigerant_leak_kg, solar_kwh, config):
    ef = config["emission_factors"]
    grid_factor = ef["grid_tco2_per_mwh"]["value"] / 1000.0   # tCO2/kWh
    lpg_factor = ef["lpg_kgco2_per_kg"]["value"] / 1000.0      # tCO2/kg
    gas_factor = ef["natural_gas_kgco2_per_kg"]["value"] / 1000.0
    diesel_factor = ef["diesel_kgco2_per_litre"]["value"] / 1000.0
    refrigerant_gwp = ef["refrigerant_gwp"]["r410a"]["value"] / 1000.0  # tCO2e/kg (GWP x kg / 1000)

    scope2_tco2 = grid_kwh * grid_factor
    scope1_tco2 = (
        lpg_kg * lpg_factor
        + gas_kg * gas_factor
        + diesel_litre * diesel_factor
        + refrigerant_leak_kg * refrigerant_gwp
    )
    solar_avoided_tco2 = solar_kwh * grid_factor

    return pd.DataFrame({
        "scope1_tco2": scope1_tco2,
        "scope2_tco2": scope2_tco2,
        "solar_avoided_tco2": solar_avoided_tco2,
    })
