"""Tests for download_reference_data.py. No network calls: fetch is replaced with a fake."""

import json
import zipfile

import pytest

import download_reference_data as drd

XML_URL = "https://ontario.ca/files/2026-09/moh-ontario-drug-benefit-odb-formulary-edition-43-data-extract-en-2026-09-25.xml"
XSD_URL = "https://www.ontario.ca/files/2023-09/moh-ontario-drug-benefit-odb-formulary-edition-43-schema-en-2021-04-22.xsd"


def page(*hrefs):
    links = "".join(f'<a href="{h}">link</a>' for h in hrefs)
    return f"<html><body>{links}</body></html>"


# --- find_odb_links ---------------------------------------------------------


def test_find_odb_links_returns_extract_and_schema():
    assert drd.find_odb_links(page(XML_URL, XSD_URL)) == (XML_URL, XSD_URL)


def test_find_odb_links_resolves_relative_links():
    html = page("/files/2026-09/odb-data-extract-en-2026-09-25.xml", "/files/odb-schema-en.xsd")
    xml_url, xsd_url = drd.find_odb_links(html)
    assert xml_url == "https://www.ontario.ca/files/2026-09/odb-data-extract-en-2026-09-25.xml"
    assert xsd_url == "https://www.ontario.ca/files/odb-schema-en.xsd"


def test_find_odb_links_ignores_same_file_linked_twice():
    duplicate = XML_URL.replace("https://ontario.ca", "https://www.ontario.ca")
    assert drd.find_odb_links(page(XML_URL, duplicate, XSD_URL)) == (XML_URL, XSD_URL)


def test_find_odb_links_fails_when_extract_missing():
    with pytest.raises(ValueError, match="data extract"):
        drd.find_odb_links(page(XSD_URL))


def test_find_odb_links_fails_when_two_different_extracts():
    older = XML_URL.replace("2026-09-25", "2026-08-28")
    with pytest.raises(ValueError, match="data extract"):
        drd.find_odb_links(page(XML_URL, older, XSD_URL))


# --- validate ---------------------------------------------------------------


def make_zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, '"1","2"\n')
    return path


def test_validate_accepts_dpd_zip(tmp_path):
    drd.validate(make_zip(tmp_path / "allfiles_ia.zip", ["drug_ia.txt", "ingred_ia.txt"]))


def test_validate_rejects_zip_without_drug_table(tmp_path):
    with pytest.raises(ValueError, match="drug"):
        drd.validate(make_zip(tmp_path / "allfiles.zip", ["ingred.txt"]))


def test_validate_rejects_file_that_is_not_a_zip(tmp_path):
    bad = tmp_path / "allfiles.zip"
    bad.write_text("<html>Page not found</html>")
    with pytest.raises(ValueError, match="zip"):
        drd.validate(bad)


def test_validate_accepts_odb_extract(tmp_path):
    xml = tmp_path / "extract.xml"
    xml.write_text('<?xml version="1.0"?><extract createDate="2026-09-22"></extract>')
    drd.validate(xml)


def test_validate_rejects_xml_with_wrong_root(tmp_path):
    xml = tmp_path / "extract.xml"
    xml.write_text("<html></html>")
    with pytest.raises(ValueError, match="extract"):
        drd.validate(xml)


def test_validate_rejects_malformed_xml(tmp_path):
    xml = tmp_path / "extract.xml"
    xml.write_text("<extract>")
    with pytest.raises(ValueError, match="XML"):
        drd.validate(xml)


def test_validate_accepts_schema(tmp_path):
    xsd = tmp_path / "schema.xsd"
    xsd.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
    drd.validate(xsd)


# --- download_sources -------------------------------------------------------


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replace the network fetch with one that writes a valid file and records each call."""
    calls = []

    def fetch(url, dest):
        calls.append(url)
        if dest.suffix == ".zip":
            make_zip(dest, ["drug.txt"])
        else:
            dest.write_text("<extract/>")

    monkeypatch.setattr(drd, "fetch", fetch)
    return calls


SOURCES = [
    ("https://example.test/allfiles.zip", "allfiles.zip"),
    ("https://example.test/data-extract.xml", "data-extract.xml"),
]


def test_download_sources_fetches_and_writes_manifest(tmp_path, fake_fetch):
    failures = drd.download_sources(tmp_path, SOURCES, force=False)

    assert failures == []
    assert fake_fetch == [url for url, _ in SOURCES]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    entry = manifest["files"]["allfiles.zip"]
    assert entry["url"] == "https://example.test/allfiles.zip"
    assert entry["bytes"] == (tmp_path / "allfiles.zip").stat().st_size
    assert len(entry["sha256"]) == 64
    assert entry["downloaded_at"]


def test_download_sources_skips_existing_files(tmp_path, fake_fetch):
    drd.download_sources(tmp_path, SOURCES, force=False)
    first_manifest = json.loads((tmp_path / "manifest.json").read_text())
    fake_fetch.clear()

    drd.download_sources(tmp_path, SOURCES, force=False)

    assert fake_fetch == []
    # A skipped file keeps the details recorded when it was first downloaded.
    assert json.loads((tmp_path / "manifest.json").read_text()) == first_manifest


def test_download_sources_records_existing_files_missing_from_manifest(tmp_path, fake_fetch):
    # e.g. files downloaded by hand before the script existed
    make_zip(tmp_path / "allfiles.zip", ["drug.txt"])

    drd.download_sources(tmp_path, SOURCES[:1], force=False)

    assert fake_fetch == []
    entry = json.loads((tmp_path / "manifest.json").read_text())["files"]["allfiles.zip"]
    assert entry["url"] == "https://example.test/allfiles.zip"
    assert len(entry["sha256"]) == 64
    assert entry["downloaded_at"] is None


def test_download_sources_force_downloads_again(tmp_path, fake_fetch):
    drd.download_sources(tmp_path, SOURCES, force=False)
    fake_fetch.clear()

    drd.download_sources(tmp_path, SOURCES, force=True)

    assert fake_fetch == [url for url, _ in SOURCES]


def test_download_sources_removes_invalid_file_and_reports_it(tmp_path, monkeypatch):
    monkeypatch.setattr(drd, "fetch", lambda url, dest: dest.write_text("<html>error page</html>"))

    failures = drd.download_sources(tmp_path, SOURCES[:1], force=False)

    assert failures == ["allfiles.zip"]
    assert not (tmp_path / "allfiles.zip").exists()
    assert "allfiles.zip" not in json.loads((tmp_path / "manifest.json").read_text())["files"]


def test_download_sources_reports_network_errors(tmp_path, monkeypatch):
    def broken_fetch(url, dest):
        raise OSError("connection reset")

    monkeypatch.setattr(drd, "fetch", broken_fetch)

    assert drd.download_sources(tmp_path, SOURCES, force=False) == ["allfiles.zip", "data-extract.xml"]
