"""Tests for the synthetic data generator. They run a small version: 100 patients per store, 2 months."""

import copy
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta

import pytest

from palm_rx_generator import generate
from palm_rx_generator.catalog import load_catalog, load_config

CATALOG = load_catalog()


def small_config(seed=42):
    config = copy.deepcopy(load_config())
    config["seed"] = seed
    config["end_date"] = date(2025, 11, 30)
    for store in config["stores"]:
        store["patients"] = 100
        store["prescribers"] = 10
    return config


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    config = small_config()
    return {"config": config, "out": out, "data": generate(config, CATALOG, out)}


def read(folder, pattern, delimiter=","):
    rows = []
    for path in sorted(folder.glob(pattern)):
        with open(path, encoding="utf-8", newline="") as f:
            rows += list(csv.DictReader(f, delimiter=delimiter))
    return rows


def store_a_movements(folder):
    """Daily stock movements in units, from Store A's files."""
    return {
        "closing": {(r["snapshot_date"], r["din"]): int(r["quantity_on_hand"]) for r in read(folder, "inventory_daily_*.csv")},
        "purchased": [(r["invoice_date"], r["din"], int(r["quantity"])) for r in read(folder, "invoices_*.csv")],
        "dispensed": [(r["dispense_date"], r["din"], int(r["quantity"])) for r in read(folder, "dispensing_*.csv")],
        "adjusted": [(r["adjustment_date"], r["din"], int(r["quantity"])) for r in read(folder, "inventory_adjustments_*.csv")],
    }


def store_b_movements(folder):
    """Daily stock movements converted to units, from Store B's files (packs x pack size)."""
    pack_size = {r["ITEM_CODE"]: int(r["PACK_SIZE"]) for r in read(folder, "ITEMS.txt", "|")}

    def units(code, packs):
        return round(float(packs) * pack_size[code])

    return {
        "closing": {(r["STOCK_DT"], r["ITEM_CODE"]): units(r["ITEM_CODE"], r["ON_HAND_PACKS"]) for r in read(folder, "STOCK_DAILY_*.txt", "|")},
        "purchased": [(r["INV_DT"], r["ITEM_CODE"], units(r["ITEM_CODE"], r["QTY_PACKS"])) for r in read(folder, "PURCHASES_*.txt", "|")],
        "dispensed": [(r["FILL_DT"], r["ITEM_CODE"], units(r["ITEM_CODE"], r["QTY_PACKS"])) for r in read(folder, "RX_FILLS_*.txt", "|")],
        "adjusted": [(r["ADJ_DT"], r["ITEM_CODE"], units(r["ITEM_CODE"], r["ADJ_PACKS"])) for r in read(folder, "STOCK_ADJ_*.txt", "|")],
    }


# --- reproducibility ----------------------------------------------------------


def test_same_seed_gives_identical_files(run, tmp_path):
    generate(small_config(), CATALOG, tmp_path)
    first = {p.relative_to(run["out"]): p.read_bytes() for p in run["out"].rglob("*") if p.is_file()}
    second = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert first.keys() == second.keys()
    assert first == second


def test_different_seed_gives_different_files(run, tmp_path):
    generate(small_config(seed=7), CATALOG, tmp_path)
    assert (run["out"] / "store_a" / "patients.csv").read_bytes() != (tmp_path / "store_a" / "patients.csv").read_bytes()


# --- inventory ----------------------------------------------------------------


@pytest.mark.parametrize("store, movements", [("store_a", store_a_movements), ("store_b", store_b_movements)])
def test_inventory_equation_balances_every_drug_every_day(run, store, movements):
    m = movements(run["out"] / store)
    flows = defaultdict(int)
    for day, item, qty in m["purchased"] + m["adjusted"]:
        flows[(day, item)] += qty
    for day, item, qty in m["dispensed"]:
        flows[(day, item)] -= qty

    checked = 0
    for (day, item), closing in m["closing"].items():
        previous = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        if day == "2025-09-30":
            continue  # opening stock, nothing before it
        opening = m["closing"].get((previous, item), 0)  # a drug first stocked mid-year opens at 0
        assert opening + flows[(day, item)] == closing, f"{store} {item} on {day}"
        checked += 1
    assert checked > 1000


def test_stock_never_goes_negative(run):
    for data in run["data"].values():
        assert min(s.on_hand for s in data.snapshots) >= 0


def test_every_movement_happens_on_a_snapshot_day(run):
    m = store_a_movements(run["out"] / "store_a")
    for day, din, _ in m["purchased"] + m["dispensed"] + m["adjusted"]:
        assert (day, din) in m["closing"]


# --- Store B format -------------------------------------------------------------


def test_store_b_packs_convert_back_to_exact_units(run):
    folder = run["out"] / "store_b"
    pack_size = {r["ITEM_CODE"]: int(r["PACK_SIZE"]) for r in read(folder, "ITEMS.txt", "|")}
    din_for = {r["item_code"]: r["din"] for r in read(folder, "_answer_key_item_to_din.csv")}
    from_file = sorted(
        (int(r["RX_NO"]), int(r["REFILL_NO"]) + 1, din_for[r["ITEM_CODE"]], round(float(r["QTY_PACKS"]) * pack_size[r["ITEM_CODE"]]))
        for r in read(folder, "RX_FILLS_*.txt", "|")
    )
    true_units = sorted((f.rx.rx_number, f.fill_number, f.din, f.quantity) for f in run["data"]["store_b"].fills)
    assert from_file == true_units


def test_store_b_item_codes_are_not_dins(run):
    key = read(run["out"] / "store_b", "_answer_key_item_to_din.csv")
    assert len({r["item_code"] for r in key}) == len(CATALOG)
    assert all(r["item_code"].startswith("LV-") and r["item_code"] != r["din"] for r in key)


# --- prescriptions ------------------------------------------------------------


def test_chronic_refills_follow_days_supply(run):
    config = run["config"]
    max_early = config["chronic"]["early_days"][1]
    gaps = []
    for data in run["data"].values():
        by_therapy = defaultdict(list)
        for f in data.fills:
            if f.kind == "chronic":
                assert f.dispense_date >= config["start_date"]
                by_therapy[f.therapy_id].append(f)
        for fills in by_therapy.values():
            for before, after in zip(fills, fills[1:]):
                gap = (after.dispense_date - before.dispense_date).days
                assert gap >= before.days_supply - max_early
                gaps.append(gap - before.days_supply)
    on_time = sum(0 <= g <= config["chronic"]["on_time_extra_days"][1] for g in gaps) / len(gaps)
    assert 0.5 < on_time < 0.9  # the odds table says 68% on time on average


def test_rx_and_fill_numbers_are_unique_and_increase(run):
    for data in run["data"].values():
        keys = Counter((f.rx.rx_number, f.fill_number) for f in data.fills)
        assert max(keys.values()) == 1
        by_rx = defaultdict(list)
        for f in sorted(data.fills, key=lambda f: f.dispense_date):
            by_rx[f.rx.rx_number].append(f.fill_number)
        assert all(numbers == sorted(numbers) for numbers in by_rx.values())


def test_flu_shots_fall_in_flu_season(run):
    flu = run["config"]["flu"]
    shots = [f for data in run["data"].values() for f in data.fills if f.kind == "flu"]
    assert shots
    for shot in shots:
        assert flu["season_start"] <= shot.dispense_date <= flu["season_end"]
        assert shot.quantity == 1 and shot.prescriber_id == "" and shot.drug_cost == 0


def test_narcotics_are_one_off_fills(run):
    narcotics = {d.din for d in CATALOG if d.is_narcotic}
    for data in run["data"].values():
        for f in data.fills:
            if f.din in narcotics:
                assert f.kind == "acute" and f.fill_number == 1


# --- keys and references --------------------------------------------------------


def test_store_a_ids_are_unique_and_references_exist(run):
    folder = run["out"] / "store_a"
    patients = [r["patient_id"] for r in read(folder, "patients.csv")]
    prescribers = [r["prescriber_id"] for r in read(folder, "prescribers.csv")]
    assert len(set(patients)) == len(patients) and len(set(prescribers)) == len(prescribers)
    catalog_dins = {d.din for d in CATALOG}
    for r in read(folder, "dispensing_*.csv"):
        assert r["patient_id"] in patients
        assert r["din"] in catalog_dins
        assert r["prescriber_id"] in prescribers or r["dispensing_fee"] == "13.00"  # flu shots have no prescriber


def test_store_b_references_exist(run):
    folder = run["out"] / "store_b"
    patients = {r["PT_ID"] for r in read(folder, "PATIENTS.txt", "|")}
    doctors = {r["DR_ID"] for r in read(folder, "DOCTORS.txt", "|")}
    items = {r["ITEM_CODE"] for r in read(folder, "ITEMS.txt", "|")}
    for r in read(folder, "RX_FILLS_*.txt", "|"):
        assert r["PT_ID"] in patients and r["ITEM_CODE"] in items
        assert r["DR_ID"] in doctors or r["DR_ID"] == ""


@pytest.mark.parametrize("store, pattern, delimiter, number, amount, total", [
    ("store_a", "invoices_*.csv", ",", "invoice_number", "line_total", "invoice_total"),
    ("store_b", "PURCHASES_*.txt", "|", "INV_NO", "EXT_COST", "INV_TOTAL"),
])
def test_invoice_total_equals_sum_of_lines(run, store, pattern, delimiter, number, amount, total):
    lines = read(run["out"] / store, pattern, delimiter)
    sums, totals = defaultdict(float), {}
    for line in lines:
        sums[line[number]] += float(line[amount])
        totals[line[number]] = float(line[total])
    assert lines
    for invoice, expected in totals.items():
        assert round(sums[invoice], 2) == expected


def test_some_purchases_cost_more_than_the_odb_price(run):
    prices = {d.din: d.unit_price for d in CATALOG}
    lines = [line for data in run["data"].values() for line in data.invoice_lines if prices[line.din] > 0]
    above = sum(line.unit_cost > prices[line.din] * 1.02 for line in lines)
    assert 0 < above < len(lines) * 0.2


# --- catalog ------------------------------------------------------------------


def test_catalog_covers_the_pqa_adherence_classes():
    groups = Counter(d.group for d in CATALOG)
    for group in ("statin", "ras", "diabetes"):
        assert groups[group] >= 10
    assert all(d.unit_price > 0 for d in CATALOG if d.group != "flu_vaccine")
    assert len({d.din for d in CATALOG}) == len(CATALOG)
    assert all(d.is_narcotic for d in CATALOG if d.group == "opioid")
