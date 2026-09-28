"""Write a store's data in its own export format, one file per feed per month."""

import csv
from collections import defaultdict


def _write(path, header, rows, delimiter=","):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _write_monthly(folder, name, month_format, header, records, date_of, to_row, delimiter=","):
    by_month = defaultdict(list)
    for record in records:
        by_month[date_of(record).strftime(month_format)].append(to_row(record))
    for month in sorted(by_month):
        _write(folder / name.format(month=month), header, by_month[month], delimiter)


def _money(value):
    return f"{value:.2f}"


def _packs(units, pack_size):
    return f"{units / pack_size:.4f}"


def _invoice_totals(lines, amount):
    totals = defaultdict(float)
    for line in lines:
        totals[line.invoice_number] += amount(line)
    return totals


def _sorted_fills(data):
    return sorted(data.fills, key=lambda f: (f.dispense_date, f.rx.rx_number, f.fill_number))


def write_store_a(data, catalog, folder):
    """Store A: clean CSV, keyed by DIN, quantities in units."""
    _write(
        folder / "patients.csv",
        ["patient_id", "first_name", "last_name", "date_of_birth", "sex", "address_line", "city", "province", "postal_code", "health_card_number", "phone"],
        [[p.patient_id, p.first_name, p.last_name, p.date_of_birth, p.sex, p.address_line, p.city, p.province, p.postal_code, p.health_card_number, p.phone] for p in data.patients],
    )
    _write(
        folder / "prescribers.csv",
        ["prescriber_id", "first_name", "last_name", "license_number"],
        [[p.prescriber_id, p.first_name, p.last_name, p.license_number] for p in data.prescribers],
    )
    _write_monthly(
        folder, "dispensing_{month}.csv", "%Y-%m",
        ["rx_number", "fill_number", "dispense_date", "patient_id", "prescriber_id", "din", "quantity", "days_supply", "drug_cost", "dispensing_fee"],
        _sorted_fills(data), lambda f: f.dispense_date,
        lambda f: [f.rx.rx_number, f.fill_number, f.dispense_date, f.patient_id, f.prescriber_id, f.din, f.quantity, f.days_supply, _money(f.drug_cost), _money(f.fee)],
    )
    _write_monthly(
        folder, "inventory_daily_{month}.csv", "%Y-%m",
        ["snapshot_date", "din", "quantity_on_hand"],
        sorted(data.snapshots, key=lambda s: (s.snapshot_date, s.din)), lambda s: s.snapshot_date,
        lambda s: [s.snapshot_date, s.din, s.on_hand],
    )
    _write_monthly(
        folder, "inventory_adjustments_{month}.csv", "%Y-%m",
        ["adjustment_date", "din", "quantity", "reason"],
        data.adjustments, lambda a: a.adjustment_date,
        lambda a: [a.adjustment_date, a.din, a.quantity, a.reason],
    )
    totals = _invoice_totals(data.invoice_lines, lambda line: line.line_total)
    _write_monthly(
        folder, "invoices_{month}.csv", "%Y-%m",
        ["invoice_number", "invoice_date", "wholesaler", "din", "quantity", "unit_cost", "line_total", "invoice_total"],
        data.invoice_lines, lambda line: line.invoice_date,
        lambda line: [line.invoice_number, line.invoice_date, line.supplier, line.din, line.quantity, f"{line.unit_cost:.4f}", _money(line.line_total), _money(totals[line.invoice_number])],
    )


REASON_CODES = {"expired": "EXP", "damaged": "DMG", "count_correction": "CNT"}


def assign_item_codes(catalog, rng):
    """Store B's own item codes. They are unrelated to DINs, which is what the crosswalk solves."""
    numbers = rng.sample(range(10000, 100000), len(catalog))
    return {drug.din: f"LV-{number:05d}" for drug, number in zip(catalog, numbers)}


def write_store_b(data, catalog, folder, item_codes):
    """Store B: pipe-delimited, upper-case names, local item codes, quantities in packs."""
    drugs = {d.din: d for d in catalog}
    code = item_codes.__getitem__

    def packs(units, din):
        return _packs(units, drugs[din].pack_size)

    _write(
        folder / "PATIENTS.txt",
        ["PT_ID", "SURNAME", "GIVEN_NAME", "DOB", "GENDER", "ADDR", "CITY", "PROV", "POSTAL", "HCN", "PHONE"],
        [[p.patient_id, p.last_name, p.first_name, p.date_of_birth, p.sex, p.address_line, p.city, p.province, p.postal_code, p.health_card_number, p.phone] for p in data.patients],
        "|",
    )
    _write(
        folder / "DOCTORS.txt",
        ["DR_ID", "DR_NAME", "LIC_NO"],
        [[p.prescriber_id, f"{p.last_name}, {p.first_name}".upper(), p.license_number] for p in data.prescribers],
        "|",
    )
    _write(
        folder / "ITEMS.txt",
        ["ITEM_CODE", "ITEM_DESC", "PACK_SIZE"],
        sorted([code(d.din), " ".join(filter(None, [d.brand_name, d.strength.upper()]))[:40], d.pack_size] for d in catalog),
        "|",
    )
    _write_monthly(
        folder, "RX_FILLS_{month}.txt", "%Y%m",
        ["RX_NO", "REFILL_NO", "FILL_DT", "PT_ID", "DR_ID", "ITEM_CODE", "QTY_PACKS", "DAYS_SUPPLY", "DRUG_COST", "FEE"],
        _sorted_fills(data), lambda f: f.dispense_date,
        # Store B counts refills, so the original fill is refill 0.
        lambda f: [f.rx.rx_number, f.fill_number - 1, f.dispense_date, f.patient_id, f.prescriber_id, code(f.din), packs(f.quantity, f.din), f.days_supply, _money(f.drug_cost), _money(f.fee)],
        "|",
    )
    _write_monthly(
        folder, "STOCK_DAILY_{month}.txt", "%Y%m",
        ["STOCK_DT", "ITEM_CODE", "ON_HAND_PACKS"],
        sorted(data.snapshots, key=lambda s: (s.snapshot_date, code(s.din))), lambda s: s.snapshot_date,
        lambda s: [s.snapshot_date, code(s.din), packs(s.on_hand, s.din)],
        "|",
    )
    _write_monthly(
        folder, "STOCK_ADJ_{month}.txt", "%Y%m",
        ["ADJ_DT", "ITEM_CODE", "ADJ_PACKS", "REASON_CD"],
        data.adjustments, lambda a: a.adjustment_date,
        lambda a: [a.adjustment_date, code(a.din), packs(a.quantity, a.din), REASON_CODES[a.reason]],
        "|",
    )

    def ext_cost(line):
        return round(line.packs * round(line.unit_cost * drugs[line.din].pack_size, 2), 2)

    totals = _invoice_totals(data.invoice_lines, ext_cost)
    _write_monthly(
        folder, "PURCHASES_{month}.txt", "%Y%m",
        ["INV_NO", "INV_DT", "SUPPLIER", "ITEM_CODE", "QTY_PACKS", "PACK_COST", "EXT_COST", "INV_TOTAL"],
        data.invoice_lines, lambda line: line.invoice_date,
        lambda line: [line.invoice_number, line.invoice_date, line.supplier, code(line.din), line.packs, _money(line.unit_cost * drugs[line.din].pack_size), _money(ext_cost(line)), _money(totals[line.invoice_number])],
        "|",
    )
    # Not a store export: the true mapping, used to build the dbt crosswalk seed.
    _write(
        folder / "_answer_key_item_to_din.csv",
        ["item_code", "din", "pack_size"],
        sorted([code(d.din), d.din, d.pack_size] for d in catalog),
    )
