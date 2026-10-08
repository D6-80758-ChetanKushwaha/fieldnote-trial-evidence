"""Build a reproducible, explicitly fictional catalog for app demonstrations."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample-data"
GENERATED_IDS = range(7, 55)
REPORT_IDS = {10, 18, 22, 34, 41, 50}
CONFLICT_OFFSETS = {22: 1.5, 41: -1.0}
MISSING_CONTROL_IDS = {13, 29, 47}

SCHEMA_A = [
    "trial_id", "crop", "product", "country", "year", "trial_type",
    "treatment_yield", "control_yield", "yield_unit",
]
SCHEMA_B = [
    "Trial reference", "Crop name", "Product name", "Country code",
    "Season year", "Trial category", "Treated yield kg per ha",
    "Untreated yield kg per ha",
]
COUNTRIES = [("France", "FR"), ("Germany", "DE"), ("Spain", "ES")]


def _record(number: int) -> dict:
    crop = "Wheat" if number % 2 else "Potato"
    country, code = COUNTRIES[(number - 7) % len(COUNTRIES)]
    control = round(6.2 + (number % 11) * 0.21, 2) if crop == "Wheat" else round(35 + (number % 13) * 0.87, 2)
    percent = ((number * 7) % 17) - 5
    treated = round(control * (1 + percent / 100), 2)
    return {
        "id": f"T{number:02d}", "number": number, "crop": crop,
        "product": "Harvest Plus" if crop == "Wheat" else "Root Boost",
        "country": country, "country_code": code,
        "year": 2018 + (number - 7) % 9,
        "trial_type": "Demonstration" if number % 3 == 0 else "Scientific",
        "treated": treated, "control": control,
    }


def _csv_rows(records: list[dict]) -> tuple[list[dict], list[dict]]:
    rows_a, rows_b = [], []
    for record in records:
        number = record["number"]
        missing = number in MISSING_CONTROL_IDS
        if number % 2:
            in_kg = number % 4 == 1
            factor = 1000 if in_kg else 1
            rows_a.append({
                "trial_id": record["id"],
                "crop": record["crop"].lower() if number % 5 == 0 else record["crop"],
                "product": record["product"].replace(" ", "") if number % 5 == 0 else record["product"],
                "country": record["country_code"] if number % 3 == 0 else record["country"],
                "year": record["year"], "trial_type": record["trial_type"],
                "treatment_yield": f"{record['treated'] * factor:.0f}" if in_kg else f"{record['treated']:.2f}",
                "control_yield": "" if missing else (f"{record['control'] * factor:.0f}" if in_kg else f"{record['control']:.2f}"),
                "yield_unit": "kg/ha" if in_kg else "t/ha",
            })
        else:
            rows_b.append({
                "Trial reference": record["id"], "Crop name": record["crop"].lower(),
                "Product name": record["product"].upper() if number % 4 == 0 else record["product"],
                "Country code": record["country_code"], "Season year": record["year"],
                "Trial category": record["trial_type"].lower(),
                "Treated yield kg per ha": f"{record['treated'] * 1000:.0f}",
                "Untreated yield kg per ha": "" if missing else f"{record['control'] * 1000:.0f}",
            })
    return rows_a, rows_b


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(output_dir: Path, record: dict) -> None:
    number = record["number"]
    treated = round(record["treated"] + CONFLICT_OFFSETS.get(number, 0), 2)
    note = (
        "This synthetic report intentionally disagrees with the spreadsheet treated yield. "
        "The discrepancy is unresolved."
        if number in CONFLICT_OFFSETS else
        "This synthetic report repeats the spreadsheet result in t/ha."
    )
    text = (
        f"Trial {record['id']} synthetic field report\n"
        "Trial details\n"
        f"Crop: {record['crop']}. Product: {record['product']}. "
        f"Country: {record['country']}. Year: {record['year']}.\n"
        f"Trial type: {record['trial_type']}.\n"
        "Results\n"
        f"Treated yield: {treated:.2f} t/ha. Control yield: {record['control']:.2f} t/ha.\n"
        "Notes\n"
        f"{note} All values are fictional. Replication and statistical significance are not documented.\n"
    )
    (output_dir / f"{record['id']}_synthetic_report.txt").write_text(text, encoding="utf-8")


def build_demo_data(output_dir: Path) -> dict:
    """Copy the supplied sample and add 48 synthetic trial records."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in SAMPLE_DIR.iterdir():
        if source.suffix in {".csv", ".txt"}:
            shutil.copyfile(source, output_dir / source.name)

    records = [_record(number) for number in GENERATED_IDS]
    rows_a, rows_b = _csv_rows(records)
    _write_csv(output_dir / "synthetic_trials_a.csv", SCHEMA_A, rows_a)
    _write_csv(output_dir / "synthetic_trials_b.csv", SCHEMA_B, rows_b)
    for record in records:
        if record["number"] in REPORT_IDS:
            _write_report(output_dir, record)

    manifest = {
        "provenance": "fully fictional, deterministic demo data; no internet or real trial data",
        "original_sample_trials": 6,
        "generated_trials": len(records),
        "total_trials": 6 + len(records),
        "generated_trial_ids": [record["id"] for record in records],
        "intentional_conflicts": [f"T{number:02d}" for number in sorted(CONFLICT_OFFSETS)],
        "missing_controls": [f"T{number:02d}" for number in sorted(MISSING_CONTROL_IDS)],
        "generated_reports": [f"T{number:02d}_synthetic_report.txt" for number in sorted(REPORT_IDS)],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(
        "# Synthetic trial demo catalog\n\n"
        "All 54 trial records here are fictional. This folder copies the six supplied fictional "
        "trials and adds 48 deterministic synthetic trials. Do not use these values as real "
        "agronomic evidence or product claims.\n\n"
        "The extra records exercise both supported CSV schemas, kg/ha to t/ha conversion, "
        "aliases, duplicate reports, unresolved conflicts (T22 and T41), and missing "
        "controls (T13, T29, and T47). See `manifest.json` for the full list.\n\n"
        "Rebuild with `python scripts/generate_demo_data.py`. Set `TRIAL_DATA_DIR=demo-data` "
        "when starting the FastAPI server to load this catalog.\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo-data")
    args = parser.parse_args()
    summary = build_demo_data(args.output)
    print(f"Generated {summary['generated_trials']} synthetic trials in {args.output}")
