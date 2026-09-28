# Palm Rx Group — Pharmacy Data Platform

> **Disclaimer:** Palm Rx Group is a fictional company. All patient, prescriber and transaction data in this project is synthetic. Drug reference data comes from public Health Canada and Ontario government extracts. Any resemblance to a real pharmacy is coincidental.

A Snowflake + dbt data platform that unifies a fictional network of acquired community pharmacies, each running a different pharmacy management system, into one trusted network-wide model — with a repeatable process for onboarding the next acquisition.

## Stack

Snowflake · dbt · Python · GitHub Actions

## Reference data

Two public government datasets supply the real drug data. They are not stored in this repo — download them yourself into a local `data_download/` folder at the repo root. That folder is git-ignored, so the files are never committed.

| Dataset | Publisher | Used for | Licence |
| --- | --- | --- | --- |
| [Drug Product Database (DPD)](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/drug-product-database/what-data-extract-drug-product-database.html) | Health Canada | Drug master (`dim_drug`), keyed by DIN | [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) |
| [Ontario Drug Benefit (ODB) Formulary](https://www.ontario.ca/document/ontario-drug-benefit-odb-formulary-comparative-drug-index-cdi-and-monthly-formulary-0) | Ontario Ministry of Health | Reimbursement prices, interchangeable groups | [Open Government Licence – Ontario](https://www.ontario.ca/page/open-government-licence-ontario) |

### 1. Health Canada DPD

Download all four zip files. The DPD is split by product status, and inactive and dormant products are kept because older prescriptions can reference drugs that are no longer marketed.

| File | Contents |
| --- | --- |
| [`allfiles.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles.zip) | Marketed products |
| [`allfiles_ia.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ia.zip) | Inactive (cancelled) products |
| [`allfiles_ap.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ap.zip) | Approved, not yet marketed |
| [`allfiles_dr.zip`](https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_dr.zip) | Dormant products |

These URLs are fixed, so they can also be downloaded from the terminal (on Windows PowerShell, type `curl.exe` instead of `curl`):

```bash
mkdir data_download
cd data_download
curl -LO https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles.zip
curl -LO https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ia.zip
curl -LO https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_ap.zip
curl -LO https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles_dr.zip
```

Each zip contains 12 related tables (`drug`, `ingred`, `comp`, `form`, `route`, `package`, `status`, `ther`, `schedule`, `pharm`, `vet`, `biosimilar`) as quoted CSV text files with **no header row**. Files carry a status suffix (`drug.txt`, `drug_ia.txt`, `drug_ap.txt`, `drug_dr.txt`). Column definitions are in Health Canada's read-me on the DPD extract page.

### 2. Ontario ODB Formulary

The download link changes every month (the filename includes the date), so get it from the source page:

1. Open the [ODB Formulary / CDI Edition 43 page](https://www.ontario.ca/document/ontario-drug-benefit-odb-formulary-comparative-drug-index-cdi-and-monthly-formulary-0).
2. Scroll to the **"XML data extract and schema"** section near the bottom.
3. Right-click **"XML Data Extract"** → **Save link as…** into `data_download/`.
4. Do the same for **"Schema"** (the `.xsd` file).

The XML is nested: therapeutic class → generic name → interchangeable group → drug (DIN, manufacturer, `individualPrice`). The `.xsd` schema describes every element.

> The ODB links on the federal [Open Government Portal](https://open.canada.ca/data/en/dataset/f0ce7406-c685-445e-a627-dec40eda4eb6) point to a retired `health.gov.on.ca` address. Use the ontario.ca page above.

### Expected files

```text
data_download/
├── allfiles.zip
├── allfiles_ia.zip
├── allfiles_ap.zip
├── allfiles_dr.zip
├── moh-ontario-drug-benefit-odb-formulary-edition-43-data-extract-en-<date>.xml
└── moh-ontario-drug-benefit-odb-formulary-edition-43-schema-en-<date>.xsd
```

`data_download/` is a local staging area only. From here the files are loaded into Snowflake's `RAW.reference` schema.

## Status

🚧 In progress — Phase 1 (setup and MVP).
