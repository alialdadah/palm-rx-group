import csv
import tomllib
from pathlib import Path

from .models import Drug

GENERATOR_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = GENERATOR_DIR / "drug_catalog.csv"
CONFIG_PATH = GENERATOR_DIR / "config.toml"


def load_config(path=CONFIG_PATH):
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_catalog(path=CATALOG_PATH):
    with open(path, encoding="utf-8", newline="") as f:
        return [
            Drug(
                din=r["din"],
                brand_name=r["brand_name"],
                generic_name=r["generic_name"],
                strength=r["strength"],
                dosage_form=r["dosage_form"],
                atc_code=r["atc_code"],
                group=r["drug_group"],
                unit_price=float(r["odb_unit_price"]),
                pack_size=int(r["pack_size"]),
                doses_per_day=int(r["doses_per_day"]),
                is_narcotic=r["is_narcotic"] == "1",
            )
            for r in csv.DictReader(f)
        ]


def by_group(catalog):
    groups = {}
    for drug in catalog:
        groups.setdefault(drug.group, []).append(drug)
    return groups
