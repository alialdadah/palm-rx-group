"""Build generator/drug_catalog.csv: ~200 real drugs the synthetic stores dispense.

Reads the newest data_download/<date>/ folder (run reference/download_reference_data.py first)
and picks drugs from the DPD (marketed products) that the ODB formulary lists as a benefit
with a unit price. Flu vaccines have no ODB price (publicly supplied), so they are taken from
the DPD alone at a price of 0.

Usage:
    python generator/build_drug_catalog.py
"""

import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data_download"
CATALOG_PATH = Path(__file__).resolve().parent / "drug_catalog.csv"

# (group, ATC prefixes, how many DINs to keep)
GROUPS = [
    ("statin", ("C10AA",), 24),
    ("ras", ("C09",), 40),
    ("diabetes", ("A10B",), 28),
    ("other_chronic", ("A02BC", "H03AA", "N06AB"), 40),
    ("antibiotic", ("J01",), 40),
    ("opioid", ("N02A",), 24),
    ("flu_vaccine", ("J07BB",), 4),
]

COLUMNS = [
    "din", "brand_name", "generic_name", "strength", "dosage_form", "atc_code",
    "drug_group", "odb_unit_price", "pack_size", "doses_per_day", "is_narcotic",
]


def latest_download_dir(data_dir=DATA_DIR):
    dated = sorted(p for p in data_dir.iterdir() if p.is_dir()) if data_dir.exists() else []
    if not dated:
        sys.exit(f"No downloads in {data_dir}. Run reference/download_reference_data.py first.")
    return dated[-1]


def read_dpd_table(archive, name):
    """DPD tables are quoted CSV with no header row."""
    with archive.open(name) as f:
        return list(csv.reader(io.TextIOWrapper(f, encoding="latin-1")))


def load_dpd(zip_path):
    """Return {drug_code: {...}} for human drugs in the marketed-products extract."""
    with zipfile.ZipFile(zip_path) as archive:
        drugs = {r[0]: {"din": r[3], "brand_name": r[4].strip()} for r in read_dpd_table(archive, "drug.txt") if r[2] == "Human"}
        tables = {name: read_dpd_table(archive, f"{name}.txt") for name in ("ther", "form", "schedule", "route")}

    for code, drug in drugs.items():
        drug.update(atc_code="", forms=set(), schedules=set(), routes=set())
    for r in tables["ther"]:
        if r[0] in drugs:
            drugs[r[0]]["atc_code"] = r[1]
    for table, key in (("form", "forms"), ("schedule", "schedules"), ("route", "routes")):
        column = 1 if table == "schedule" else 2
        for r in tables[table]:
            if r[0] in drugs:
                drugs[r[0]][key].add(r[column].upper())
    return drugs


def load_odb(xml_path):
    """Return {DIN: {...}} for ODB benefit drugs that have a unit price."""
    odb = {}
    root = ElementTree.parse(xml_path).getroot()
    for generic in root.iter("genericName"):
        for group in generic.iter("pcg9"):
            for drug in group.iter("drug"):
                price = drug.findtext("individualPrice")
                if price and drug.get("notABenefit") != "Y":
                    odb[drug.get("id")] = {
                        "generic_name": generic.findtext("name", "").strip(),
                        "strength": group.findtext("strength", "").strip(),
                        "price": float(price),
                    }
    return odb


def is_oral_solid(drug):
    return any("TABLET" in f or "CAPSULE" in f for f in drug["forms"])


def candidates_for(group, prefixes, dpd, odb):
    found = []
    for drug in dpd.values():
        if not drug["atc_code"].startswith(prefixes):
            continue
        if group == "flu_vaccine":
            if "H5N1" in drug["brand_name"] or "INTRAMUSCULAR" not in drug["routes"]:
                continue
            found.append({**drug, "generic_name": "INFLUENZA VACCINE", "strength": "", "price": 0.0})
        elif drug["din"] in odb and is_oral_solid(drug):
            found.append({**drug, **odb[drug["din"]]})
    return found


def pick(candidates, quota):
    """Round-robin across molecules (ATC codes), cheapest DIN first, so the list stays varied."""
    by_molecule = defaultdict(list)
    for c in sorted(candidates, key=lambda c: (c["atc_code"], c["price"], c["din"])):
        by_molecule[c["atc_code"]].append(c)
    queues = [by_molecule[atc] for atc in sorted(by_molecule)]
    picked = []
    while len(picked) < quota and any(queues):
        for queue in queues:
            if queue and len(picked) < quota:
                picked.append(queue.pop(0))
    return picked


def doses_per_day(group, atc_code):
    if atc_code == "A10BA02":  # metformin
        return 2
    if group == "antibiotic":
        return 3 if atc_code.startswith("J01C") else 2  # penicillins three times a day
    if group == "opioid":
        return 4
    return 1


def catalog_row(group, drug):
    if group == "flu_vaccine":
        pack_size = 10
    else:
        pack_size = 30 if drug["price"] >= 1 else 100
    return {
        "din": drug["din"],
        "brand_name": drug["brand_name"],
        "generic_name": drug["generic_name"],
        "strength": drug["strength"],
        "dosage_form": sorted(drug["forms"])[0] if drug["forms"] else "",
        "atc_code": drug["atc_code"],
        "drug_group": group,
        "odb_unit_price": f"{drug['price']:.4f}",
        "pack_size": pack_size,
        "doses_per_day": doses_per_day(group, drug["atc_code"]),
        "is_narcotic": int(any("NARCOTIC" in s for s in drug["schedules"])),
    }


def build_catalog(download_dir):
    dpd = load_dpd(download_dir / "allfiles.zip")
    odb = load_odb(next(download_dir.glob("*data-extract*.xml")))
    rows = []
    for group, prefixes, quota in GROUPS:
        picked = pick(candidates_for(group, prefixes, dpd, odb), quota)
        if len(picked) < quota:
            print(f"Warning: only {len(picked)} of {quota} {group} drugs available")
        rows += [catalog_row(group, drug) for drug in picked]
    return rows


def main():
    download_dir = latest_download_dir()
    rows = build_catalog(download_dir)
    with open(CATALOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} drugs from {download_dir.name} to {CATALOG_PATH}")


if __name__ == "__main__":
    main()
