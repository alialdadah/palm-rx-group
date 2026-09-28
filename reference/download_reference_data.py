"""Download the Health Canada DPD and Ontario ODB reference extracts.

Each run saves into data_download/<today's date>/ with a manifest.json recording
where every file came from, its size and its SHA-256 checksum. Files already in
today's folder are skipped unless --force is passed.

Usage:
    python reference/download_reference_data.py [--force]
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree

DATA_DIR = Path(__file__).resolve().parents[1] / "data_download"

DPD_BASE_URL = "https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/"
DPD_FILES = ["allfiles.zip", "allfiles_ia.zip", "allfiles_ap.zip", "allfiles_dr.zip"]

# The ODB file links change every month, so they are read from this page on each run.
# Update this URL when Ontario publishes a new formulary edition.
ODB_PAGE_URL = "https://www.ontario.ca/document/ontario-drug-benefit-odb-formulary-comparative-drug-index-cdi-and-monthly-formulary-0"

# ontario.ca rejects requests that don't look like they come from a browser, and
# canada.ca never responds to requests without an Accept header (urllib sends none).
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; palm-rx-reference-downloader)", "Accept": "*/*"}
TIMEOUT_SECONDS = 60
RETRIES = 3

log = logging.getLogger("download_reference_data")


def _retry(action, description):
    """Run action(), retrying network errors with a growing wait (2s, 4s)."""
    for attempt in range(1, RETRIES + 1):
        try:
            return action()
        except OSError as error:
            if attempt == RETRIES:
                raise
            wait = 2**attempt
            log.warning("%s failed (%s), retrying in %ss", description, error, wait)
            time.sleep(wait)


def _open(url):
    return urlopen(Request(url, headers=HEADERS), timeout=TIMEOUT_SECONDS)


def fetch(url, dest):
    """Download url to dest. Writes to a .part file first so a failed download never looks complete."""
    part = dest.with_name(dest.name + ".part")

    def download():
        try:
            with _open(url) as response, open(part, "wb") as out:
                shutil.copyfileobj(response, out)
        except OSError:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)

    _retry(download, f"Downloading {dest.name}")


def fetch_text(url):
    def read():
        with _open(url) as response:
            return response.read().decode("utf-8", errors="replace")

    return _retry(read, f"Fetching {url}")


def find_odb_links(html):
    """Return (data extract .xml URL, schema .xsd URL) found in the ODB page HTML."""
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+\.(?:xml|xsd))["']""", html, re.IGNORECASE)

    # The same file can be linked more than once (e.g. ontario.ca and www.ontario.ca),
    # so links are de-duplicated by file name.
    by_name = {}
    for href in hrefs:
        url = urljoin(ODB_PAGE_URL, href)
        by_name.setdefault(url.rsplit("/", 1)[-1].lower(), url)

    def only_one(description, suffix, marker):
        found = [url for name, url in by_name.items() if name.endswith(suffix) and marker in name]
        if len(found) != 1:
            raise ValueError(f"Expected 1 ODB {description} link on the page, found {len(found)}: {found}")
        return found[0]

    return only_one("data extract", ".xml", "data-extract"), only_one("schema", ".xsd", "schema")


def validate(path):
    """Raise ValueError if the downloaded file isn't what we expect (e.g. an HTML error page)."""
    if path.suffix == ".zip":
        if not zipfile.is_zipfile(path):
            raise ValueError(f"{path.name} is not a valid zip file")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not any(n.startswith("drug") and n.endswith(".txt") for n in names):
                raise ValueError(f"{path.name} has no drug*.txt table: {names}")
            if archive.testzip() is not None:
                raise ValueError(f"{path.name} is corrupt")
    elif path.suffix in (".xml", ".xsd"):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as error:
            raise ValueError(f"{path.name} is not valid XML: {error}") from error
        if path.suffix == ".xml" and root.tag != "extract":
            raise ValueError(f"{path.name} root element is <{root.tag}>, expected <extract>")


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _manifest_entry(url, path, downloaded_at):
    return {"url": url, "bytes": path.stat().st_size, "sha256": _sha256(path), "downloaded_at": downloaded_at}


def download_sources(run_dir, sources, force):
    """Download each (url, file name) into run_dir and update its manifest. Returns failed file names."""
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    files = json.loads(manifest_path.read_text())["files"] if manifest_path.exists() else {}
    failures = []

    for url, name in sources:
        dest = run_dir / name
        if dest.exists() and not force:
            log.info("Skipping %s (already downloaded today; use --force to replace)", name)
            if name not in files:
                # Placed here by hand, so the download time is unknown.
                files[name] = _manifest_entry(url, dest, downloaded_at=None)
            continue
        try:
            log.info("Downloading %s", name)
            fetch(url, dest)
            validate(dest)
        except (OSError, ValueError) as error:
            log.error("Failed: %s: %s", name, error)
            dest.unlink(missing_ok=True)
            files.pop(name, None)
            failures.append(name)
            continue
        files[name] = _manifest_entry(url, dest, datetime.now(timezone.utc).isoformat(timespec="seconds"))

    manifest_path.write_text(json.dumps({"files": files}, indent=2, sort_keys=True) + "\n")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="download again even if today's files exist")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    run_dir = DATA_DIR / date.today().isoformat()
    sources = [(DPD_BASE_URL + name, name) for name in DPD_FILES]
    failures = []

    try:
        xml_url, xsd_url = find_odb_links(fetch_text(ODB_PAGE_URL))
        sources += [(url, url.rsplit("/", 1)[-1]) for url in (xml_url, xsd_url)]
    except (OSError, ValueError) as error:
        log.error("Could not find the ODB files on %s: %s", ODB_PAGE_URL, error)
        failures.append("ODB links")

    failures += download_sources(run_dir, sources, args.force)

    if failures:
        log.error("Finished with failures: %s", ", ".join(failures))
        return 1
    log.info("All reference files saved to %s", run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
