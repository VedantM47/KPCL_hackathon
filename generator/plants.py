"""Per-plant meters: splits the single whole-company main meter into one meter
per plant (Hadapsar / Saswad / Nashik).

The simulation models one combined incomer, so the split is an allocation, not
a separate physical simulation:
  - kW, kVA and cost for each plant = main-meter value x that plant's share of
    the metered asset load in the same interval. This keeps the plants summing
    exactly to the main meter, and it spreads the unmetered-loss fraction and
    the solar self-consumption credit across plants in proportion to load
    (i.e. as if solar were wheeled/virtually net-metered across the sites).
  - Scope 2 follows the same share (grid kWh x grid factor).
  - Scope 1 follows asset ownership: furnace LPG -> the furnace's plant, VAM gas
    and refrigerant top-ups -> their plants, outage diesel -> by load share.
  - Solar avoided emissions go to the plant that owns the PV array.

All of this is an assumption layer on a simulated dataset — see README.
"""
import numpy as np
import pandas as pd

from generator import emissions as em

NON_LOAD_ASSETS = {"MAIN-METER", "SOLAR-SASWAD-01"}


def _asset_kw(df15):
    if "kW" in df15.columns:
        return df15["kW"].to_numpy()
    if "kW_electrical" in df15.columns:
        return df15["kW_electrical"].to_numpy()
    return None


def build_plant_meter(assets_15m, main_meter_15m, grid_kwh_15, lpg_kg_15, gas_kg_15, diesel_litre_15,
                      refrigerant_leak_kg_15, solar_kwh_15, config):
    asset_plant = {a["asset_id"]: a["plant_id"] for a in config["assets"]}
    plant_ids = [p["plant_id"] for p in config["plants"]]
    n = len(main_meter_15m)

    gross = {p: np.zeros(n) for p in plant_ids}
    for aid, df15 in assets_15m.items():
        if aid in NON_LOAD_ASSETS or aid not in asset_plant:
            continue
        kw = _asset_kw(df15)
        if kw is not None:
            gross[asset_plant[aid]] += np.nan_to_num(kw)
    total = sum(gross.values())
    equal = 1.0 / len(plant_ids)
    share = {p: np.where(total > 1e-9, gross[p] / np.where(total > 1e-9, total, 1.0), equal) for p in plant_ids}

    main_kw = main_meter_15m["kW"].to_numpy()
    main_kva = main_meter_15m["kVA"].to_numpy()
    cost = main_meter_15m["cost_rs"].to_numpy()
    pf = main_meter_15m["pf"].to_numpy()

    def owner_zeros(asset_id):
        owner = asset_plant.get(asset_id)
        return {p: (1.0 if p == owner else 0.0) for p in plant_ids}

    furnace_owner, vam_owner = owner_zeros("FURNACE-HT-01"), owner_zeros("CHILLER-VAM-01")
    scr_owner = owner_zeros("CHILLER-SCR-01")

    frames = []
    for p in plant_ids:
        e = em.compute_emissions_15m(
            grid_kwh_15 * share[p], lpg_kg_15 * furnace_owner[p], gas_kg_15 * vam_owner[p],
            diesel_litre_15 * share[p], refrigerant_leak_kg_15 * scr_owner[p],
            solar_kwh_15 * share[p], config)
        frames.append(pd.DataFrame({
            "ts": main_meter_15m["ts"].to_numpy(), "plant_id": p,
            "kW": main_kw * share[p], "kVA": main_kva * share[p], "pf": pf,
            "metered_load_kw": gross[p], "cost_rs": cost * share[p],
            "scope1_tco2": e["scope1_tco2"].to_numpy(), "scope2_tco2": e["scope2_tco2"].to_numpy(),
            "solar_avoided_tco2": e["solar_avoided_tco2"].to_numpy(),
        }))
    return pd.concat(frames, ignore_index=True)
