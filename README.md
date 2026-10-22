# Blood donation after the Great East Japan Earthquake: data and code

This repository holds the derived data, the numeric registry and the analysis code for the paper

> Blood donation after the Great East Japan Earthquake and the Fukushima nuclear accident: a 20-year decomposition of all 47 Japanese prefectures

Status: under review at *Vox Sanguinis*.

Authors: Akemi Hara, Akihiko Ozaki, Kenji Gonda, Osamu Hasegawa, Toyoaki Sawano, Tomohiro Kurokawa, Kazuhiko Ikeda, Takuro Saito, Hiroaki Shimmura, Suguru Tokiwa, Hitoshi Ohto.

## Sources and terms of use

All source data are official public statistics and documents published by Japanese government bodies. They may be reused with attribution of the source.

| Data | Source |
|---|---|
| Annual donations by prefecture, FY2005 to FY2024 | Statistics Bureau of Japan, System of Social and Demographic Statistics, item G6230 (statsDataId 0000010107), via the e-Stat API. The Bureau republishes figures of the Japanese Red Cross Society. |
| Population by prefecture, sex and 5-year age band, 1 October | Statistics Bureau of Japan, Population Estimates (four census-based series), via the e-Stat API |
| Evacuees living outside their prefecture | Reconstruction Agency, bulletins on the number of evacuees (https://www.reconstruction.go.jp/topics/cat-11/cat-29/cat-150/hinanshasuu/) |
| National donations by age group; national counts of individual donors | Japanese Red Cross Society tables submitted to the Ministry of Health, Labour and Welfare: document of 12 September 2012 (https://www.mhlw.go.jp/stf/shingi/2r9852000002krnp-att/2r9852000002krsx.pdf) and "Kenketsu no genjo" (Current state of blood donation), 11 July 2025 |
| Medical facilities (panel.csv only; not used in the paper) | Statistics Bureau of Japan, System of Social and Demographic Statistics (statsDataId 0000010109), via the e-Stat API |
| Suspension and resumption of collection in 2011 (Table S1) | Compiled by the authors from reference [11] of the paper, the record of the six Tohoku blood centres (Japanese Red Cross Tohoku Block Blood Center, 2012) |
| Events and classification (Table S4) | Compiled by the authors from the sources listed under Table S4 of the paper |

## What is not included

The record of the six Tohoku blood centres (reference [11]) may not be reproduced without permission. The repository contains neither the record nor images of its pages, only the dates and facts that the authors compiled from it (data/ts_ops_days.csv), with the citation. The raw downloads (e-Stat responses and PDF documents) are not included; the scripts in code/pipeline/ download them again.

## Files

### data/

All values are as used in the paper. Changes are in log points: 100 times the difference in natural logarithms from the FY2005 to FY2009 geometric-mean baseline. Prefectures are identified by `pref_code` (00000 is Japan as a whole) and named in `pref_name`. Fiscal years run from 1 April to 31 March.

| File | Content |
|---|---|
| `decomposition.csv` | Main analysis file, 48 regions by 20 fiscal years. `D_donors` donations; `P_persons` total population; `P1569_persons` population aged 15 to 69; `s_share_15_69` share aged 15 to 69; `r_donations_per_capita_15_69` donations per resident aged 15 to 69; `dln_D` = `dln_P` + `dln_s` + `dln_r` (change in donations and its population-size, eligible-age-share and donation-rate components); `index_geo_base` index of donations (baseline = 100). |
| `age_standardized.csv` | Fixed age-schedule calculation. `schedule` A, B and C use the national rates of FY2011, FY2024 and FY2010. `E_expected` expected donations; `SDR` = D/E; `dln_age_structure` age-composition component; `dln_SDR` age-controlled rate; `dln_r_crude` = `dln_age_structure` + `dln_SDR`. |
| `age_schedule.csv` | National donation rates by age group (`w_rate`), with the donations and population they come from. |
| `population_denominators.csv` | Total population, population aged 15 to 69 and aged 65 and over, in thousands. |
| `population_age.csv` | Population by prefecture, sex and 5-year age band, in thousands (used for the age standardisation and for the population aged 20 to 69). |
| `pop_decomposition_by_age.csv` | Exact additive decomposition of `dln_P` by age band (arithmetic-mean baseline). |
| `evacuees_outside_prefecture.csv` | Evacuees from Fukushima, Miyagi and Iwate living outside their prefecture, by bulletin; `as_of` is the date of the count and `publish_date` the date of the bulletin. |
| `actual_donors_national.csv` | National counts of individual donors, FY2023 and FY2024. |
| `event_counterfactual.csv` | One-year comparisons of the 13 prefecture-event observations with two comparison sets (not used in the paper's tables). |
| `panel.csv`, `panel_dictionary.csv` | Prefecture-year panel combining the files above with medical-facility counts; the dictionary defines each column. |
| `ts_ops_days.csv` | Table S1: suspension and resumption of collection in the six Tohoku prefectures in 2011, with the source in each row. |
| `ts_events.csv` | Table S4: the six events, the class of each prefecture and the fiscal year assigned to each observation. |

### registry/

`numbers_v15.csv` lists every number in the abstract, highlights, main text, table footnotes and figure legends of the paper, and every numeric cell of Tables 1 and 2 and Supplementary Tables S2, S3, S5, S6 and S7. Columns: `value` as printed; `location` (section and line numbers of the revised manuscript, or table, row and column); `kind` (computed, table, record, external or structural); `source` data file; `column_or_computation`; `reproduced` value from the code below; `match`.

### code/

| File | Purpose |
|---|---|
| `pipeline/` | Download the source data and build the authors' derived data (Japanese labels) in data/processed/. Run `pipeline/run_pipeline.py`; the order of the scripts is listed there. Code comments are in Japanese. |
| `translate_data.py` | Write the English files in data/ from data/processed/. Only labels and notes are translated; the script checks that every numeric column is unchanged. |
| `reproduce_tables.py` | Compute every table and the plotted values of every figure of the paper from data/. Output: output/tables/ and output/figure_data/. |
| `make_figures.py` | Draw Figures 2 to 5, S1 and S2 from output/figure_data/ and data/decomposition.csv. Figure 1 is a map and is not drawn here. |

## Reproducing the results

Python 3.11 or later with the packages in `requirements.txt`.

From the files in data/:

```
python code/reproduce_tables.py
python code/make_figures.py
```

From the original sources:

1. Obtain an e-Stat application ID (https://www.e-stat.go.jp/api/) and set it in the environment variable `ESTAT_APP_ID`, or write it in `code/pipeline/estat_appid.txt`. The ID is never written into the code.
2. Save the Japanese Red Cross Society document "Kenketsu no genjo" of 11 July 2025, published by the Ministry of Health, Labour and Welfare, as `data/raw/mhlw/mhlw_kenketsu_no_genjo_current.pdf`. The other documents are downloaded by the scripts.
3. Run `python code/pipeline/run_pipeline.py`, then `python code/translate_data.py data/processed data`, then the two commands above.

Step 20a writes `event_counterfactual.csv` and then prints a comparison with a file from the authors' audit step, which is not distributed; on a fresh run it stops at that point after its output has been written, and `run_pipeline.py` accepts this.

## Licence

The code is released under the MIT License and the data under the Creative Commons Attribution 4.0 International licence (CC BY 4.0). See `LICENSE`.

## Citation

Please cite the paper above; the reference will be added when it is published.
