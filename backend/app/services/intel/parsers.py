"""Потоковые парсеры файлов справочников в том виде, как их отдаёт источник.

`parse_file(source, path)` возвращает `Parsed`: `rows` — генератор пар
`(таблица, строка)`, разбор идёт по мере чтения (CSV — по строкам, XML — через
XMLPullParser кусками). Ошибка формата — `IntelFormatError` с понятным текстом;
она поднимается во время перебора `rows`, поэтому загрузчик откатывает замену.
`file_date` и `count` заполняются по ходу разбора.

Сжатие определяется по сигнатуре файла, а не по расширению: gzip и zip
(из zip берётся первый подходящий файл).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import IO, Any
from xml.etree import ElementTree as ET

from app.models.intel import IntelSource
from app.services.sarif.parser import CVE_RE

CHUNK = 1 << 20
_CVE_FULL = re.compile(rf"^{CVE_RE.pattern}$", re.IGNORECASE)
_BDU_ID = re.compile(r"^BDU:\d{4}-\d{1,20}$")
_CWE_PREFIX = "Comprehensive Categorization: "
CWE_VIEW = "1400"  # MITRE «Comprehensive Categorization» — покрывает все слабости


class IntelFormatError(ValueError):
    """Файл не того формата или битый. Текст показывается администратору."""


Row = tuple[str, dict[str, Any]]


@dataclass
class Parsed:
    rows: Iterator[Row] = field(default_factory=lambda: iter(()))
    file_date: date | None = None
    count: int = 0


# --- открытие файла ---------------------------------------------------------------


# Во сколько раз распакованный файл может быть больше лимита загрузки (SV_INTEL_MAX_MB):
# защита от gzip/zip-бомб. Настоящие справочники сжимаются в 5–15 раз и в лимит укладываются.
UNPACKED_FACTOR = 4
# KEV читается json.load целиком в память — ему отдельный, жёсткий потолок (настоящий файл ~2 МБ)
KEV_MAX_BYTES = 64 * 1024 * 1024


def max_unpacked_bytes() -> int:
    from app.core.config import get_settings

    return get_settings().intel_max_mb * 1024 * 1024 * UNPACKED_FACTOR


def _too_big(limit: int) -> IntelFormatError:
    return IntelFormatError(f"Файл после распаковки больше {limit // (1024 * 1024)} МБ")


class _Limited(io.RawIOBase):
    """Поток, который падает с IntelFormatError, как только прочитано больше `limit` байт."""

    def __init__(self, inner: Any, limit: int) -> None:
        self._inner, self._limit, self._read = inner, limit, 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        data = self._inner.read(len(b))
        self._read += len(data)
        if self._read > self._limit:
            raise _too_big(self._limit)
        b[: len(data)] = data
        return len(data)


@contextmanager
def _open(path: Path, member_suffix: str, limit: int | None = None) -> Iterator[IO[bytes]]:
    limit = limit if limit is not None else max_unpacked_bytes()
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic[:2] == b"\x1f\x8b":
        with gzip.open(path, "rb") as f:
            yield io.BufferedReader(_Limited(f, limit), CHUNK)
    elif magic == b"PK\x03\x04":
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise IntelFormatError(f"Повреждённый zip-архив: {e}") from e
        with zf:
            members = [
                i for i in zf.infolist()
                if not i.is_dir() and i.filename.lower().endswith(member_suffix)
            ]
            if not members:
                raise IntelFormatError(f"В архиве нет файла {member_suffix}")
            if members[0].file_size > limit:  # по заголовку; поток всё равно считаем ниже
                raise _too_big(limit)
            with zf.open(members[0]) as f:
                yield io.BufferedReader(_Limited(f, limit), CHUNK)
    else:
        if path.stat().st_size > limit:
            raise _too_big(limit)
        with open(path, "rb") as f:
            yield f


def _date_prefix(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _cve(value: Any) -> str | None:
    if isinstance(value, str) and _CVE_FULL.match(value.strip()):
        return value.strip().upper()
    return None


def _wrap_read_errors(gen: Iterator[Row]) -> Iterator[Row]:
    """Ошибки чтения сжатого файла и кодировки — тоже ошибка формата."""
    try:
        yield from gen
    except (OSError, EOFError, zipfile.BadZipFile) as e:
        raise IntelFormatError(f"Не удалось прочитать файл: {e}") from e
    except UnicodeDecodeError as e:
        raise IntelFormatError("Файл не в кодировке UTF-8") from e


# --- EPSS -------------------------------------------------------------------------


def _epss(path: Path, parsed: Parsed) -> Iterator[Row]:
    with _open(path, ".csv") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        first = text.readline()
        header_line = first
        if first.startswith("#"):
            # #model_version:v2025.03.14,score_date:2026-11-20T12:55:00Z
            for part in first[1:].strip().split(","):
                key, _, value = part.partition(":")
                if key.strip() == "score_date":
                    parsed.file_date = _date_prefix(value.strip())
            header_line = text.readline()
        header = [h.strip().lower() for h in next(csv.reader([header_line]), [])]
        if not {"cve", "epss", "percentile"} <= set(header):
            raise IntelFormatError(
                "Это не файл EPSS: нужны колонки cve, epss, percentile"
            )
        i_cve, i_epss, i_pct = (header.index(c) for c in ("cve", "epss", "percentile"))
        line_no = 2 if first.startswith("#") else 1
        for rec in csv.reader(text):
            line_no += 1
            if not rec:
                continue
            epss = pct = -1.0
            try:
                cve = _cve(rec[i_cve])
                epss, pct = float(rec[i_epss]), float(rec[i_pct])
            except (IndexError, ValueError):
                cve = None
            if cve is None or not (0 <= epss <= 1 and 0 <= pct <= 1):
                raise IntelFormatError(f"EPSS: неверные данные в строке {line_no}")
            parsed.count += 1
            yield "epss", {
                "cve_id": cve, "epss": epss, "percentile": pct, "score_date": parsed.file_date,
            }


# --- KEV --------------------------------------------------------------------------


def _kev(path: Path, parsed: Parsed) -> Iterator[Row]:
    with _open(path, ".json", min(KEV_MAX_BYTES, max_unpacked_bytes())) as raw:
        try:
            data = json.load(io.TextIOWrapper(raw, encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise IntelFormatError(f"Это не файл KEV: файл не JSON ({e.msg})") from e
    vulns = data.get("vulnerabilities") if isinstance(data, dict) else None
    if not isinstance(vulns, list):
        raise IntelFormatError("Это не файл KEV: нет списка vulnerabilities")
    parsed.file_date = _date_prefix(data.get("dateReleased"))
    for n, v in enumerate(vulns, 1):
        cve = _cve(v.get("cveID")) if isinstance(v, dict) else None
        if cve is None:
            raise IntelFormatError(f"KEV: запись {n} без корректного cveID")
        parsed.count += 1
        yield "kev", {
            "cve_id": cve,
            "date_added": _date_prefix(v.get("dateAdded")),
            "name": v.get("vulnerabilityName") or None,
            "ransomware": str(v.get("knownRansomwareCampaignUse", "")).lower() == "known",
            "due_date": _date_prefix(v.get("dueDate")),
        }


# --- XML: общий потоковый разбор ----------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_events(stream: IO[bytes]) -> Iterator[tuple[str, ET.Element]]:
    """События start/end кусками. DOCTYPE/ENTITY не принимаем (XXE, «миллиард смешков»)."""
    parser = ET.XMLPullParser(events=("start", "end"))
    first = True
    try:
        while chunk := stream.read(CHUNK):
            if first:
                head = chunk[:65536].upper()
                if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
                    raise IntelFormatError("XML с DOCTYPE/ENTITY не поддерживается")
                first = False
            parser.feed(chunk)
            yield from parser.read_events()
        parser.close()
        yield from parser.read_events()
    except ET.ParseError as e:
        raise IntelFormatError(f"Ошибка разбора XML: {e}") from e


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    return elem.text.strip() or None


# --- БДУ ФСТЭК --------------------------------------------------------------------


def _bdu(path: Path, parsed: Parsed) -> Iterator[Row]:
    with _open(path, ".xml") as raw:
        root: ET.Element | None = None
        for event, elem in _xml_events(raw):
            tag = _local(elem.tag)
            if root is None:
                if tag != "vulnerabilities":
                    raise IntelFormatError(
                        "Это не файл БДУ ФСТЭК: ожидался корневой тег vulnerabilities"
                    )
                root = elem
                continue
            if event != "end" or tag != "vul":
                continue
            bdu_id = None
            name = severity = None
            cves: dict[str, None] = {}
            for child in elem:
                ctag = _local(child.tag)
                if ctag == "identifier":
                    bdu_id = _text(child)
                elif ctag == "name":
                    name = _text(child)
                elif ctag == "severity":
                    severity = _text(child)
                elif ctag == "identifiers":
                    for ident in child:
                        if (ident.get("type") or "").upper() == "CVE":
                            cve = _cve(_text(ident))
                            if cve:
                                cves.setdefault(cve, None)
            root.clear()  # уже разобранные записи не держим в памяти
            if not bdu_id or not _BDU_ID.match(bdu_id):
                continue
            parsed.count += 1
            yield "bdu", {"bdu_id": bdu_id, "name": name, "severity": severity}
            for cve in cves:
                yield "bdu_cve", {"bdu_id": bdu_id, "cve_id": cve}


# --- CWE (MITRE) ------------------------------------------------------------------


def _cwe(path: Path, parsed: Parsed) -> Iterator[Row]:
    names: dict[str, str] = {}
    categories: dict[str, str] = {}  # CWE-89 → Injection (по представлению 1400)
    category_ids: set[str] = set()
    with _open(path, ".xml") as raw:
        root_seen = False
        for event, elem in _xml_events(raw):
            tag = _local(elem.tag)
            if not root_seen:
                if tag != "Weakness_Catalog":
                    raise IntelFormatError(
                        "Это не файл CWE: ожидался корневой тег Weakness_Catalog"
                    )
                parsed.file_date = _date_prefix(elem.get("Date"))
                root_seen = True
                continue
            # CWE 4.x — Category, CWE 5.x — Grouping
            if event != "end" or tag not in ("Weakness", "Category", "Grouping"):
                continue
            cid, cname = elem.get("ID"), elem.get("Name")
            if cid and cid.isdigit() and cname:
                key = f"CWE-{cid}"
                if tag != "Weakness":
                    category_ids.add(key)
                    if cname.startswith(_CWE_PREFIX):
                        label = cname[len(_CWE_PREFIX):]
                        for m in elem.iter():
                            if _local(m.tag) == "Has_Member" and m.get("View_ID") == CWE_VIEW:
                                member = m.get("CWE_ID")
                                if member and member.isdigit():
                                    categories.setdefault(f"CWE-{member}", label)
                names[key] = cname
            elem.clear()
    if not any(k not in category_ids for k in names):
        raise IntelFormatError("Это не файл CWE: в нём нет ни одной слабости (Weakness)")
    for key, name in names.items():
        parsed.count += 1
        yield "cwe", {"cwe_id": key, "name": name, "category": categories.get(key)}


_PARSERS = {
    IntelSource.epss: _epss,
    IntelSource.kev: _kev,
    IntelSource.bdu: _bdu,
    IntelSource.cwe: _cwe,
}


def parse_file(source: IntelSource, path: Path) -> Parsed:
    parsed = Parsed()

    def rows() -> Iterator[Row]:
        yield from _wrap_read_errors(_PARSERS[source](Path(path), parsed))
        if parsed.count == 0:
            raise IntelFormatError("В файле нет ни одной записи")

    parsed.rows = rows()
    return parsed
