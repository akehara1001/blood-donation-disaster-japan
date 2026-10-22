"""
Run the acquisition and derivation scripts in dependency order.

Usage: python code/pipeline/run_pipeline.py

The scripts download the source data (e-Stat API, Reconstruction Agency bulletins, Ministry of Health, Labour
and Welfare documents) into data/raw/ and write the authors' derived data, with Japanese labels, into
data/processed/. code/translate_data.py then writes the English files in data/.
An e-Stat application ID is required: set ESTAT_APP_ID or put it in code/pipeline/estat_appid.txt.
Two documents must be placed by hand in data/raw/mhlw/ before steps 15a and 18a (see README.md).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

ORDER = [
    "01_inventory.py",            # e-Stat table list (network)
    "02c_fetch_population.py",    # Population Estimates by prefecture, sex and 5-year age band (network)
    "02d_denominators.py",        # total population and population aged 15-69
    "03a_donors.py",              # donations by prefecture, item G6230 (network)
    "04b_facility.py",            # medical facilities, for panel.csv only (network)
    "07a_decomposition.py",       # decomposition.csv
    "08a_fetch_reconstruction.py",  # Reconstruction Agency bulletins (network)
    "08b_extract_evacuees.py",    # evacuees outside the prefecture
    "08c_evacuee_fallback.py",    # alternative bulletins where the first is an image (network if not cached)
    "06a_panel.py",               # panel.csv, panel_dictionary.csv
    "11a_pop_decomposition.py",   # pop_decomposition_by_age.csv
    "12a_fetch_mhlw.py",          # Ministry of Health, Labour and Welfare documents (network)
    "15a_four_term.py",           # actual_donors_national.csv (needs a hand-placed document)
    "18a_age_schedule.py",        # age_schedule.csv (needs a hand-placed document)
    "18b_age_standardize.py",     # age_standardized.csv
    "20a_counterfactual.py",      # event_counterfactual.csv
]

if __name__ == "__main__":
    failed = []
    for name in ORDER:
        print(f"== {name}", flush=True)
        r = subprocess.run([sys.executable, str(HERE / name)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(name)
            print(f"   exit code {r.returncode}", flush=True)
    # 20a writes event_counterfactual.csv and then prints a comparison with a file from the authors' audit step,
    # which is not distributed; on a fresh run it stops at that point after the output has been written.
    if failed == ["20a_counterfactual.py"] and (ROOT / "data" / "processed" / "event_counterfactual.csv").exists():
        failed = []
    print("failed:", failed or "none")
    raise SystemExit(1 if failed else 0)
