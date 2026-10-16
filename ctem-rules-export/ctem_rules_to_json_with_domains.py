#!/usr/bin/env python3
"""Convert the Rules sheet in a CTEM tagging workbook to Logic App JSON.

Accepts both the original template and the version with an assetDomain column.
Requires Python 3.9+; uses only the standard library.
"""

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
FIELDS = {
    "computerDnsName": ("contains", "startsWith", "endsWith"),
    "osPlatform": ("contains", "startsWith", "endsWith", "equals"),
    "lastIpAddress": ("startsWith",),
    "rbacGroupName": ("contains", "startsWith", "endsWith", "equals"),
    "machineTags": ("equals",),
    "onboardingStatus": ("equals",),
    "managedBy": ("equals",),
    "isAadJoined": ("equals",),
}
DOMAINS = (
    "Hybrid cloud Linux/Unix", "Hybrid cloud Windows", "Hybrid cloud Other",
    "Network", "Workplace", "OT", "IOT", "SaaS",
)
FILTER_HEADERS = [f"{field}.{op}" for field, ops in FIELDS.items() for op in ops]
OLD_HEADERS = ["tag", *FILTER_HEADERS]
NEW_HEADERS = ["tag", "assetDomain", *FILTER_HEADERS]
CELL_REF = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


def excel_column(reference):
    match = CELL_REF.fullmatch(reference)
    if not match:
        raise ValueError(f"Invalid Excel cell reference: {reference}")
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def read_rules_sheet(path):
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                       for si in root.findall("m:si", NS)]

        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next((s for s in wb.findall("m:sheets/m:sheet", NS)
                      if s.get("name") == "Rules"), None)
        if sheet is None:
            raise ValueError("Workbook has no sheet named 'Rules'.")
        rel_id = sheet.get(f"{{{NS['r']}}}id")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel = next((r for r in relationships.findall("p:Relationship", NS)
                    if r.get("Id") == rel_id), None)
        if rel is None:
            raise ValueError("Could not resolve the Rules worksheet.")
        target = rel.get("Target", "").lstrip("/")
        sheet_path = target if target.startswith("xl/") else "xl/" + target
        from posixpath import normpath
        root = ET.fromstring(archive.read(normpath(sheet_path)))

        rows = []
        for row in root.findall("m:sheetData/m:row", NS):
            values = {}
            for cell in row.findall("m:c", NS):
                typ = cell.get("t")
                if cell.find("m:f", NS) is not None:
                    raise ValueError(f"Formula in {cell.get('r')} is not allowed; enter text values.")
                value = cell.find("m:v", NS)
                inline = cell.find("m:is", NS)
                if typ == "s" and value is not None:
                    text = strings[int(value.text)]
                elif typ == "inlineStr" and inline is not None:
                    text = "".join(t.text or "" for t in inline.findall(".//m:t", NS))
                elif typ == "b" and value is not None:
                    text = "true" if value.text == "1" else "false" if value.text == "0" else ""
                elif value is not None:
                    text = value.text or ""
                else:
                    text = ""
                values[excel_column(cell.get("r"))] = text.strip()
            rows.append((int(row.get("r")), values))
        return rows


def convert(rows):
    if not rows:
        raise ValueError("The Rules sheet is empty.")
    header_row, first = rows[0]
    if header_row != 1:
        raise ValueError("Rules headers must be in row 1.")
    if [first.get(i, "") for i in range(len(NEW_HEADERS))] == NEW_HEADERS:
        headers = NEW_HEADERS
        has_domain = True
    elif [first.get(i, "") for i in range(len(OLD_HEADERS))] == OLD_HEADERS:
        headers = OLD_HEADERS
        has_domain = False
    else:
        raise ValueError("Rules row 1 must use the original headers or the assetDomain template headers.")
    if any(value for col, value in first.items() if col >= len(headers)):
        raise ValueError("Unexpected extra header in Rules row 1.")

    rules = []
    tag_domains = {}
    first_filter_col = 2 if has_domain else 1
    for row_number, values in rows[1:]:
        if any(value for col, value in values.items() if col >= len(headers)):
            raise ValueError(f"Row {row_number}: unexpected value beyond the last filter column.")
        tag = values.get(0, "")
        domain = values.get(1, "") if has_domain else ""
        criteria = [(headers[col], value) for col, value in values.items()
                    if first_filter_col <= col < len(headers) and value]
        if not tag and not domain and not criteria:
            continue
        if not tag:
            raise ValueError(f"Row {row_number}: tag is required when a domain or filter is filled.")
        if has_domain:
            if domain not in DOMAINS:
                raise ValueError(f"Row {row_number}: select a valid assetDomain for '{tag}'.")
            previous = tag_domains.setdefault(tag, domain)
            if previous != domain:
                raise ValueError(f"Row {row_number}: tag '{tag}' maps to both '{previous}' and '{domain}'.")
        if not criteria:
            raise ValueError(f"Row {row_number}: tag '{tag}' has no filters and would match every machine.")
        rule = {"tag": tag}
        if has_domain:
            rule["assetDomain"] = domain
        for header, value in criteria:
            field, operator = header.split(".", 1)
            if field == "isAadJoined":
                if value.lower() not in ("true", "false"):
                    raise ValueError(f"Row {row_number}: isAadJoined.equals must be true or false.")
                value = value.lower() == "true"
            rule.setdefault(field, {})[operator] = value
        rules.append(rule)
    if not rules:
        raise ValueError("No complete rules found on the Rules sheet.")
    return {"rules": rules}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="Filled .xlsx template")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: workbook name with .json)")
    args = parser.parse_args()
    output = args.output or args.workbook.with_suffix(".json")
    try:
        payload = convert(read_rules_sheet(args.workbook))
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, IndexError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Wrote {len(payload['rules'])} rule(s) to {output}")


if __name__ == "__main__":
    main()
