"""Source-preserving import and normalization of the supplied trial files."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


COUNTRIES = {"fr": "France", "france": "France", "de": "Germany", "germany": "Germany", "es": "Spain", "spain": "Spain"}
PRODUCTS = {"harvestplus": "Harvest Plus", "rootboost": "Root Boost"}
CROPS = {"potato": "Potato", "potatoes": "Potato", "wheat": "Wheat"}


def normalize_country(value: str) -> str:
    return COUNTRIES.get(value.strip().casefold(), value.strip().title())


def normalize_product(value: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", value.casefold())
    return PRODUCTS.get(key, value.strip().title())


def normalize_crop(value: str) -> str:
    return CROPS.get(value.strip().casefold(), value.strip().title())


def normalize_type(value: str) -> str:
    return value.strip().title()


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value.replace(",", ""))


def _yield_t_ha(value: str | None, unit: str) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if unit == "kg/ha":
        return number / 1000
    if unit == "t/ha":
        return number
    raise ValueError(f"Unsupported yield unit: {unit}")


def _observation(
    *, trial_id: str, crop: str, product: str, country: str, year: str,
    trial_type: str, treated: str | None, control: str | None, unit: str,
    source: str, location: str, excerpt: str,
) -> dict[str, Any]:
    return {
        "trial_id": trial_id.strip().upper(),
        "crop": normalize_crop(crop),
        "product": normalize_product(product),
        "country": normalize_country(country),
        "year": int(year),
        "trial_type": normalize_type(trial_type),
        "treated_yield_t_ha": _yield_t_ha(treated, unit),
        "control_yield_t_ha": _yield_t_ha(control, unit),
        "source": source,
        "location": location,
        "raw_unit": unit,
        "excerpt": excerpt,
    }


def _parse_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"No CSV header: {path.name}")
        observations = []
        for line_number, row in enumerate(reader, start=2):
            if "trial_id" in row:
                fields = {
                    "trial_id": row["trial_id"], "crop": row["crop"],
                    "product": row["product"], "country": row["country"],
                    "year": row["year"], "trial_type": row["trial_type"],
                    "treated": row["treatment_yield"], "control": row["control_yield"],
                    "unit": row["yield_unit"],
                }
            elif "Trial reference" in row:
                fields = {
                    "trial_id": row["Trial reference"], "crop": row["Crop name"],
                    "product": row["Product name"], "country": row["Country code"],
                    "year": row["Season year"], "trial_type": row["Trial category"],
                    "treated": row["Treated yield kg per ha"],
                    "control": row["Untreated yield kg per ha"], "unit": "kg/ha",
                }
            else:
                raise ValueError(f"Unrecognized CSV schema: {path.name}")
            excerpt = ", ".join(f"{key}: {value or 'missing'}" for key, value in row.items())
            observations.append(_observation(**fields, source=path.name, location=f"row {line_number}", excerpt=excerpt))
        return observations


def _extract(text: str, pattern: str, path: Path) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        raise ValueError(f"Missing {pattern} in {path.name}")
    return match.group(1).strip()


def _parse_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    details = text.split("Results", 1)[0]
    results = text.split("Results", 1)[1].split("Notes", 1)[0]
    return _observation(
        trial_id=_extract(text, r"Trial\s+(T\d+)", path),
        crop=_extract(details, r"Crop:\s*([^.]+)", path),
        product=_extract(details, r"Product:\s*([^.]+)", path),
        country=_extract(details, r"(?:Country|Location):\s*([^.]+)", path),
        year=_extract(details, r"Year:\s*(\d{4})", path),
        trial_type=_extract(details, r"Trial type:\s*([^.]+)", path),
        treated=_extract(results, r"(?:Treated|Treatment) yield:\s*([\d.]+)", path),
        control=_extract(results, r"(?:Untreated control|Untreated|Control) yield:\s*([\d.]+)", path),
        unit="t/ha", source=path.name, location="Results section", excerpt=text.strip(),
    )


def _unique(values: list[Any]) -> list[Any]:
    return sorted(set(values), key=str)


class TrialCatalog:
    """Immutable-in-use catalog rebuilt from source files on app startup."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        observations = []
        for path in sorted(data_dir.glob("*.csv")):
            observations.extend(_parse_csv(path))
        for path in sorted(data_dir.glob("*.txt")):
            observations.append(_parse_report(path))
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            grouped[observation["trial_id"]].append(observation)
        self.trials = {trial_id: self._merge(trial_id, rows) for trial_id, rows in sorted(grouped.items())}
        self.sources = {path.name: path for path in data_dir.iterdir() if path.suffix in {".csv", ".txt"} and path.name != "README.md"}

    @staticmethod
    def _merge(trial_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        warnings = []
        metadata = {}
        for key in ("crop", "product", "country", "year", "trial_type"):
            values = _unique([row[key] for row in rows])
            metadata[key] = values[0]
            if len(values) > 1:
                warnings.append(f"Conflicting {key} values: {', '.join(map(str, values))}.")

        treated_values = _unique([row["treated_yield_t_ha"] for row in rows if row["treated_yield_t_ha"] is not None])
        control_values = _unique([row["control_yield_t_ha"] for row in rows if row["control_yield_t_ha"] is not None])
        if len(treated_values) > 1 or len(control_values) > 1:
            status = "conflicting"
            warnings.append("Sources disagree on yield; no single effect is reported.")
        elif not treated_values or not control_values:
            status = "incomplete"
            warnings.append("A treated or control yield is missing; the effect cannot be calculated.")
        else:
            status = "consistent"

        treated = treated_values[0] if len(treated_values) == 1 else None
        control = control_values[0] if len(control_values) == 1 else None
        increase = round(treated - control, 4) if status == "consistent" else None
        percent = round(100 * increase / control, 2) if increase is not None and control else None
        if metadata["trial_type"] == "Demonstration":
            warnings.append("Demonstration evidence; replication and statistical significance are not established.")
        else:
            warnings.append("Statistical significance is not documented in the supplied sources.")

        return {
            "trial_id": trial_id, **metadata, "status": status,
            "treated_yield_t_ha": treated, "control_yield_t_ha": control,
            "increase_t_ha": increase, "increase_pct": percent,
            "observations": rows, "warnings": warnings,
        }

    def search(
        self, *, trial_id: str | None = None, crop: str | None = None, product: str | None = None,
        country: str | None = None, year_from: int | None = None,
        year_to: int | None = None, trial_type: str | None = None,
    ) -> list[dict[str, Any]]:
        trial_id = trial_id.strip().upper() if trial_id else None
        crop = normalize_crop(crop) if crop else None
        product = normalize_product(product) if product else None
        country = normalize_country(country) if country else None
        trial_type = normalize_type(trial_type) if trial_type else None
        return [trial for trial in self.trials.values() if
                (not trial_id or trial["trial_id"] == trial_id) and
                (not crop or trial["crop"] == crop) and
                (not product or trial["product"] == product) and
                (not country or trial["country"] == country) and
                (year_from is None or trial["year"] >= year_from) and
                (year_to is None or trial["year"] <= year_to) and
                (not trial_type or trial["trial_type"] == trial_type)]

    def facets(self) -> dict[str, list[Any]]:
        return {key: _unique([trial[key] for trial in self.trials.values()])
                for key in ("crop", "product", "country", "year", "trial_type")}

    def source_text(self, name: str) -> str | None:
        path = self.sources.get(name)
        return path.read_text(encoding="utf-8-sig") if path else None
