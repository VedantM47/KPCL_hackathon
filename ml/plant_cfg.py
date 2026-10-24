"""Plant helpers shared by the API and ML modules.

plant_id None / "ALL" means the whole company (the original main meter).
"""

ALL = "ALL"


def norm(plant):
    return None if plant in (None, "", ALL) else plant


def plant_ids(config):
    return [p["plant_id"] for p in config["plants"]]


def asset_plant(config):
    return {a["asset_id"]: a["plant_id"] for a in config["assets"]}


def assets_of(config, plant):
    """Asset ids in a plant (all assets when plant is ALL/None)."""
    plant = norm(plant)
    return {a["asset_id"] for a in config["assets"] if plant is None or a["plant_id"] == plant}


def contract_kva(config, plant):
    plant = norm(plant)
    if plant is None:
        return float(config["tariff"]["contract_demand_kva"])
    for p in config["plants"]:
        if p["plant_id"] == plant:
            return float(p.get("contract_demand_kva", config["tariff"]["contract_demand_kva"]))
    raise KeyError(plant)
