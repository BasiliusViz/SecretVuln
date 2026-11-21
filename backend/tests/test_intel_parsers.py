"""Парсеры справочников: EPSS, KEV, БДУ, CWE — нормальные, сжатые, битые и чужие файлы."""

from __future__ import annotations

import gzip
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from app.models.intel import IntelSource
from app.services.intel.parsers import IntelFormatError, parse_file

FIX = Path(__file__).parent / "fixtures" / "intel"


def _rows(source: IntelSource, path: Path):
    parsed = parse_file(source, path)
    rows = list(parsed.rows)
    return parsed, rows


def _table(rows, name):
    return [r for t, r in rows if t == name]


def test_epss_csv():
    parsed, rows = _rows(IntelSource.epss, FIX / "epss.csv")
    epss = _table(rows, "epss")
    assert len(epss) == 3
    assert epss[0] == {
        "cve_id": "CVE-2021-44228", "epss": 0.94358, "percentile": 0.99962,
        "score_date": date(2026, 11, 20),
    }
    assert parsed.file_date == date(2026, 11, 20)


def test_epss_gzip(tmp_path):
    gz = tmp_path / "epss_scores-2026-11-20.csv.gz"
    with open(FIX / "epss.csv", "rb") as src, gzip.open(gz, "wb") as dst:
        shutil.copyfileobj(src, dst)
    _, rows = _rows(IntelSource.epss, gz)
    assert len(_table(rows, "epss")) == 3


def test_epss_bad_header():
    with pytest.raises(IntelFormatError, match="колон"):
        _rows(IntelSource.epss, FIX / "epss_bad_header.csv")


def test_epss_bad_value(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("cve,epss,percentile\nCVE-2021-1,abc,0.1\n", encoding="utf-8")
    with pytest.raises(IntelFormatError, match="строк"):
        _rows(IntelSource.epss, p)


def test_epss_empty(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("#score_date:2026-11-20\ncve,epss,percentile\n", encoding="utf-8")
    with pytest.raises(IntelFormatError, match="нет ни одной записи"):
        _rows(IntelSource.epss, p)


def test_kev_json():
    parsed, rows = _rows(IntelSource.kev, FIX / "kev.json")
    kev = _table(rows, "kev")
    assert parsed.file_date == date(2026, 11, 19)
    assert kev[0] == {
        "cve_id": "CVE-2021-44228",
        "date_added": date(2021, 12, 10),
        "name": "Apache Log4j2 Remote Code Execution Vulnerability",
        "ransomware": True,
        "due_date": date(2021, 12, 24),
    }
    assert kev[1]["ransomware"] is False


def test_kev_wrong_format():
    with pytest.raises(IntelFormatError, match="KEV"):
        _rows(IntelSource.kev, FIX / "kev_wrong.json")


def test_kev_not_json():
    with pytest.raises(IntelFormatError):
        _rows(IntelSource.kev, FIX / "epss.csv")


def test_bdu_xml():
    _, rows = _rows(IntelSource.bdu, FIX / "bdu.xml")
    bdu = _table(rows, "bdu")
    links = _table(rows, "bdu_cve")
    assert [b["bdu_id"] for b in bdu] == ["BDU:2021-05969", "BDU:2014-00001", "BDU:2015-00002"]
    assert bdu[0]["name"] == "Уязвимость библиотеки журналирования Apache Log4j"
    assert bdu[0]["severity"].startswith("Критический")
    # только CVE и только из identifiers; GHSA и CWE не попадают
    assert links == [
        {"bdu_id": "BDU:2021-05969", "cve_id": "CVE-2021-44228"},
        {"bdu_id": "BDU:2014-00001", "cve_id": "CVE-2014-0160"},
    ]


def test_bdu_zip(tmp_path):
    z = tmp_path / "vulxml.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIX / "bdu.xml", "export/export.xml")
    _, rows = _rows(IntelSource.bdu, z)
    assert len(_table(rows, "bdu")) == 3


def test_bdu_truncated():
    with pytest.raises(IntelFormatError, match="XML"):
        _rows(IntelSource.bdu, FIX / "bdu_truncated.xml")


def test_bdu_foreign_file():
    # файл CWE вместо БДУ
    with pytest.raises(IntelFormatError, match="БДУ"):
        _rows(IntelSource.bdu, FIX / "cwe.xml")


def test_xml_doctype_rejected():
    with pytest.raises(IntelFormatError, match="DOCTYPE"):
        _rows(IntelSource.bdu, FIX / "xxe.xml")


def test_cwe_xml():
    parsed, rows = _rows(IntelSource.cwe, FIX / "cwe.xml")
    cwe = {r["cwe_id"]: r for r in _table(rows, "cwe")}
    assert parsed.file_date == date(2024, 11, 19)
    assert cwe["CWE-89"]["category"] == "Injection"
    assert cwe["CWE-89"]["name"].startswith("Improper Neutralization")
    assert cwe["CWE-502"]["category"] == "Resource Control"
    # категории тоже справочные записи (сканеры иногда ссылаются на них), без категории
    assert cwe["CWE-16"] == {"cwe_id": "CWE-16", "name": "Configuration", "category": None}


def test_cwe_zip(tmp_path):
    z = tmp_path / "cwec_v4.16.xml.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIX / "cwe.xml", "cwec_v4.16.xml")
    _, rows = _rows(IntelSource.cwe, z)
    assert len(_table(rows, "cwe")) >= 3


def test_cwe_foreign_file():
    with pytest.raises(IntelFormatError, match="CWE"):
        _rows(IntelSource.cwe, FIX / "bdu.xml")


def test_zip_without_xml(tmp_path):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(IntelFormatError, match="архив"):
        _rows(IntelSource.cwe, z)


def test_cwe_v5_groupings():
    parsed, rows = _rows(IntelSource.cwe, FIX / "cwe5.xml")
    cwe = {r["cwe_id"]: r for r in _table(rows, "cwe")}
    assert parsed.file_date == date(2026, 10, 28)
    assert cwe["CWE-89"]["category"] == "Injection"
