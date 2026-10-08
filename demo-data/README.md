# Synthetic trial demo catalog

All 54 trial records here are fictional. This folder copies the six supplied fictional trials and adds 48 deterministic synthetic trials. Do not use these values as real agronomic evidence or product claims.

The extra records exercise both supported CSV schemas, kg/ha to t/ha conversion, aliases, duplicate reports, unresolved conflicts (T22 and T41), and missing controls (T13, T29, and T47). See `manifest.json` for the full list.

Rebuild with `python scripts/generate_demo_data.py`. Set `TRIAL_DATA_DIR=demo-data` when starting the FastAPI server to load this catalog.
