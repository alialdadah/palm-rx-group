"""Generate synthetic pharmacy data for Stores A and B into data/generated/.

Usage:
    python generator/generate.py
"""

from pathlib import Path

from palm_rx_generator import generate
from palm_rx_generator.catalog import load_catalog, load_config

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "generated"


def main():
    results = generate(load_config(), load_catalog(), OUT_DIR)
    for store_id, data in results.items():
        stock_outs = len({(s.snapshot_date, s.din) for s in data.snapshots if s.on_hand == 0})
        print(
            f"{store_id}: {len(data.patients):,} patients, {len(data.fills):,} fills, "
            f"{len(data.invoice_lines):,} invoice lines, {len(data.adjustments)} adjustments, "
            f"{stock_outs:,} drug-days at zero stock"
        )
    print(f"Files written to {OUT_DIR}")


if __name__ == "__main__":
    main()
