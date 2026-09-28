# Palm Rx Group — Pharmacy Data Platform

> **Disclaimer:** Palm Rx Group is a fictional company. All patient, prescriber and transaction data in this project is synthetic. Drug reference data comes from public Health Canada and Ontario government extracts. Any resemblance to a real pharmacy is coincidental.

A Snowflake + dbt data platform that unifies a fictional network of acquired community pharmacies, each running a different pharmacy management system, into one trusted network-wide model — with a repeatable process for onboarding the next acquisition.

## Stack

Snowflake · dbt · Python · GitHub Actions

## Reference data

Two public government datasets supply the real drug data. They are not stored in this repo. A script downloads them into a local `data_download/` folder at the repo root, which is git-ignored so the files are never committed.

| Dataset | Publisher | Used for | Licence |
| --- | --- | --- | --- |
| [Drug Product Database (DPD)](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/drug-product-database/what-data-extract-drug-product-database.html) | Health Canada | Drug master (`dim_drug`), keyed by DIN | [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) |
| [Ontario Drug Benefit (ODB) Formulary](https://www.ontario.ca/document/ontario-drug-benefit-odb-formulary-comparative-drug-index-cdi-and-monthly-formulary-0) | Ontario Ministry of Health | Reimbursement prices, interchangeable groups | [Open Government Licence – Ontario](https://www.ontario.ca/page/open-government-licence-ontario) |

### Download

Requires Python 3.11+. The script uses only the standard library.

```bash
python reference/download_reference_data.py
```

Each run saves into a folder named for that day, so every monthly download is kept (the ODB price history is built from these):

```text
data_download/
└── 2026-09-28/
    ├── allfiles.zip
    ├── allfiles_ia.zip
    ├── allfiles_ap.zip
    ├── allfiles_dr.zip
    ├── moh-ontario-drug-benefit-odb-formulary-edition-43-data-extract-en-<date>.xml
    ├── moh-ontario-drug-benefit-odb-formulary-edition-43-schema-en-<date>.xsd
    └── manifest.json
```

- Every file is checked after download (zips must open and contain the `drug` table; XML must parse). A failed file is deleted, and the script exits with an error.
- `manifest.json` records each file's source URL, size, SHA-256 checksum and download time.
- Running again on the same day skips files that are already there. Use `--force` to download them again.

To run the tests: `pip install -r requirements.txt`, then `pytest`.

### Health Canada DPD

All four status files are downloaded. Inactive and dormant products are kept because older prescriptions can reference drugs that are no longer marketed.

| File | Contents |
| --- | --- |
| [`allfiles.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles.zip) | Marketed products |
| [`allfiles_ia.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ia.zip) | Inactive (cancelled) products |
| [`allfiles_ap.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ap.zip) | Approved, not yet marketed |
| [`allfiles_dr.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_dr.zip) | Dormant products |

Each zip contains 12 related tables (`drug`, `ingred`, `comp`, `form`, `route`, `package`, `status`, `ther`, `schedule`, `pharm`, `vet`, `biosimilar`) as quoted CSV text files with **no header row**. Files carry a status suffix (`drug.txt`, `drug_ia.txt`, `drug_ap.txt`, `drug_dr.txt`). Column definitions are in Health Canada's read-me on the DPD extract page.

### Ontario ODB Formulary

The download links change every month (the filenames include the date), so the script reads them from the [ODB Formulary / CDI Edition 43 page](https://www.ontario.ca/document/ontario-drug-benefit-odb-formulary-comparative-drug-index-cdi-and-monthly-formulary-0) on each run. When Ontario publishes a new edition, update `ODB_PAGE_URL` in the script.

The XML is nested: therapeutic class → generic name → interchangeable group → drug (DIN, manufacturer, `individualPrice`). The `.xsd` schema describes every element.

> The ODB links on the federal [Open Government Portal](https://open.canada.ca/data/en/dataset/f0ce7406-c685-445e-a627-dec40eda4eb6) point to a retired `health.gov.on.ca` address. Use the ontario.ca page above.

### Manual download (if the script fails)

1. Create a dated folder, e.g. `data_download/2026-09-28/`.
2. Download the four DPD zips from the links in the table above.
3. On the ODB page, scroll to **"XML data extract and schema"** near the bottom, then save **"XML Data Extract"** and **"Schema"** into the same folder.

Running the script afterwards adds these files to `manifest.json` without downloading them again.

`data_download/` is a local staging area only. From here the files are loaded into Snowflake's `RAW.reference` schema.

## Status

🚧 In progress — Phase 1 (setup and MVP).
