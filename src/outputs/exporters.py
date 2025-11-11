import csv
import json
import logging
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
from xml.etree.ElementTree import Element, SubElement, ElementTree

LOGGER = logging.getLogger("outputs.exporters")

def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def export_json(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    LOGGER.info("Wrote JSON to %s", path)

def export_csv(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    if not records:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("")
        LOGGER.info("Wrote empty CSV to %s", path)
        return

    fieldnames = sorted(
        {key for rec in records for key in rec.keys()}
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
    LOGGER.info("Wrote CSV to %s", path)

def export_excel(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    df = pd.DataFrame.from_records(records)
    df.to_excel(path, index=False)
    LOGGER.info("Wrote Excel to %s", path)

def export_xml(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    root = Element("epcRecords")

    for rec in records:
        item = SubElement(root, "epcRecord")
        for key, value in rec.items():
            child = SubElement(item, key)
            if isinstance(value, (dict, list)):
                child.text = json.dumps(value, ensure_ascii=False)
            elif value is None:
                child.text = ""
            else:
                child.text = str(value)

    tree = ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    LOGGER.info("Wrote XML to %s", path)

def export_rss(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    channel_title = "EPC Updates"
    channel_link = "https://find-energy-certificate.service.gov.uk"
    channel_desc = "Updates from EPC Data Scraper."

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = channel_title
    SubElement(channel, "link").text = channel_link
    SubElement(channel, "description").text = channel_desc
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    for rec in records:
        item = SubElement(channel, "item")
        title = rec.get("address") or rec.get("id") or "EPC record"
        link = rec.get("url") or channel_link
        description = f"Rating: {rec.get('rating')}, Postcode: {rec.get('postCode')}"
        guid = rec.get("id") or f"anon-{id(rec)}"

        SubElement(item, "title").text = title
        SubElement(item, "link").text = link
        SubElement(item, "description").text = description
        SubElement(item, "guid").text = str(guid)

    tree = ElementTree(rss)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    LOGGER.info("Wrote RSS feed to %s", path)

def export_html(records: List[Dict[str, Any]], path: Path) -> None:
    _ensure_dir(path)
    with path.open("w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n<html><head><meta charset='utf-8'>\n")
        f.write("<title>EPC Results</title>\n")
        f.write(
            "<style>body{font-family:Arial,Helvetica,sans-serif;margin:20px;}table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ccc;padding:6px;font-size:13px;}th{background:#f4f4f4;}</style>\n"
        )
        f.write("</head><body>\n")
        f.write("<h1>EPC Results</h1>\n")

        if not records:
            f.write("<p>No records.</p>")
        else:
            fields = sorted({key for rec in records for key in rec.keys()})
            f.write("<table>\n<thead><tr>")
            for field in fields:
                f.write(f"<th>{escape(field)}</th>")
            f.write("</tr></thead>\n<tbody>\n")

            for rec in records:
                f.write("<tr>")
                for field in fields:
                    val = rec.get(field)
                    if isinstance(val, (dict, list)):
                        text = json.dumps(val, ensure_ascii=False)
                    elif val is None:
                        text = ""
                    else:
                        text = str(val)
                    f.write(f"<td>{escape(text)}</td>")
                f.write("</tr>\n")

            f.write("</tbody></table>\n")

        f.write("</body></html>")
    LOGGER.info("Wrote HTML table to %s", path)

def export_all(
    records: List[Dict[str, Any]],
    output_dir: Path,
    base_name: str,
    formats: Iterable[str],
) -> None:
    format_set = {fmt.lower() for fmt in formats}
    output_dir.mkdir(parents=True, exist_ok=True)

    if "json" in format_set:
        export_json(records, output_dir / f"{base_name}.json")
    if "csv" in format_set:
        export_csv(records, output_dir / f"{base_name}.csv")
    if "excel" in format_set or "xlsx" in format_set:
        export_excel(records, output_dir / f"{base_name}.xlsx")
    if "xml" in format_set:
        export_xml(records, output_dir / f"{base_name}.xml")
    if "rss" in format_set:
        export_rss(records, output_dir / f"{base_name}.rss.xml")
    if "html" in format_set:
        export_html(records, output_dir / f"{base_name}.html")