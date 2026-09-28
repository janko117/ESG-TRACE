# ESG-TRACE: Detecting Temporal (In)consistency in Sustainability Targets

ESG-TRACE (**T**emporal **R**eporting **A**nalysis of **C**ommitment **E**volution) is an LLM-based pipeline that extracts emission targets from corporate sustainability reports, tracks their progress, and detects when companies change or silently drop them over the years.

## Table of Contents

- [About](#about)
- [Pipeline Overview](#pipeline-overview)
- [Target Schema](#target-schema)
- [Pipeline Usage](#pipeline-usage)
- [Future Work](#future-work)
- [License](#license)

## About

Companies communicate their climate ambitions through targets such as *"reduce Scope 1 & 2 emissions by 20 % by 2025"*. Whether a target is actually pursued only becomes visible when several reporting years are compared, because targets are often adjusted or quietly abandoned before their target year. Given the length and number of reports, this comparison is hardly feasible by hand.

ESG-TRACE automates it and detects two patterns of temporal inconsistency:

- **Goalpost shifting:** the target value, target year or base year of a target is changed before the target expires.
- **Target disbanding:** a still-running target is no longer reported.

For each inconsistency, ESG-TRACE also checks whether the report gives a justification. Beyond consistency, it tracks target achievement: for every target and year, it records the reported progress and whether the target is ongoing, achieved or failed.

This repository contributes:

- **A target schema** that describes a sustainability target by its content, its progress and its development over time, making targets comparable across reporting years. Its topic-independent core can be extended to other sustainability topics (see [Target Schema](#target-schema)).
- **The ESG-TRACE pipeline**, which fills this schema automatically from PDF reports and assesses the temporal consistency of every target.

## Pipeline Overview

1. **Target extraction:** Gemini 3.6 Flash reads each full PDF report, including charts and tables, and extracts every quantified emission target into the [target schema](#target-schema), with a page reference for each value.
2. **Temporal analysis:** Missing values are derived, targets are linked across consecutive reporting years into target paths, and each path is checked for goalpost shifting and target disbanding. This step is rule-based, so every result is deterministic and traceable.
3. **Justification extraction:** For each inconsistency, the model searches the report for the company's explanation.

Evaluated on a manually annotated dataset of sustainability reports, ESG-TRACE reaches the following F1-scores:

- 95.2 % for detecting targets
- 87.5 % for extracting their features
- 81.8 % for detecting inconsistencies
- 75.0 % for extracting justifications

## Target Schema

ESG-TRACE records one **target instance** per target and report. The schema separates topic-independent features from features specific to climate targets, so that further sustainability topics can be added without changing the temporal analysis. Every value is stored with its origin (extracted from the report or derived) and, if extracted, with the page and passage it comes from.

<details>
<summary><b>Show all features</b></summary>

| Feature | Description | Values |
|---|---|---|
| **Metadata** | | |
| `company` | Company of the report | text |
| `report_name` | Name of the report document | text |
| `reported_year` | Year the report covers | year |
| `report_length` | Number of pages of the report | integer |
| `extraction_method` | Model used for the extraction | text |
| **Target content (topic-independent)** | | |
| `sustainability_topic` | Topic of the target, following the ESRS topics | `climate_change` |
| `metric_category` | Normalised category of the metric | `GHG`, `CO2` |
| `metric` | Metric as named in the report | text |
| `is_intensity_based` | Target refers to an intensity (e.g. per unit produced) instead of an absolute value | 0 / 1 |
| `intensity_denominator` | Reference quantity of an intensity-based target | text |
| `target_direction` | Direction of the intended change | `reduction`, `increase` |
| `relative_target_value` | Intended relative change in percent | number |
| `absolute_target_value` | Intended absolute value in the target year | number |
| `absolute_target_value_unit` | Unit of the absolute target value | text |
| `target_year` | Year by which the target is to be reached | year |
| `base_year` | Reference year of the target | year |
| `base_value` | Value of the metric in the base year | number |
| `base_value_unit` | Unit of the base value | text |
| `annual_change_rate` | Average intended change per year in percent | number |
| `scope_of_application` | Scope of the target, e.g. business units or regions | text |
| **Target content (climate-specific)** | | |
| `scope_1` | Target covers direct emissions from own sources | 0 / 1 |
| `scope_2` | Target covers indirect emissions from purchased energy | 0 / 1 |
| `scope_3` | Target covers other indirect emissions along the value chain | 0 / 1 |
| `emission_character` | Gross target, or net target where offsets count toward the target | `gross`, `net` |
| **Target status** | | |
| `current_value` | Value of the metric in the reporting year | number |
| `current_value_unit` | Unit of the current value | text |
| `current_relative_change` | Change achieved so far compared with the base value, in percent | number |
| `achievement_rate` | Progress achieved relative to the target (1 = fully achieved) | number |
| `achievement_status` | Status of the target | `ongoing`, `achieved`, `failed` |
| **Temporal consistency** | *determined by comparing reporting years* | |
| `target_id` | ID of the target path within a company | `T1`, `T2`, … |
| `target_version` | Version of the target, incremented with every change | `V1`, `V2`, … |
| `is_new_target` | Target appears for the first time | 0 / 1 |
| `last_mentioned` | Last report in which the target appears | 0 / 1 |
| `goalpost_shifting` | Target value, target year or base year changed compared with the previous year | 0 / 1 |
| `goalpost_shifting_direction` | Direction of the change, based on the annual change rate | `tightening`, `loosening`, `unchanged`, `unclear` |
| `goalpost_shifting_justification` | Justification for the change, quoted from the report | text |
| `target_disbanding` | Still-running target is no longer reported | 0 / 1 |
| `target_disbanding_justification` | Justification for dropping the target, quoted from the report | text |
| `is_consistent` | 0 as soon as goalpost shifting or target disbanding occurs | 0 / 1 |

</details>

## Pipeline Usage

### Setup

You need Python 3.10 or newer and a Gemini API key, which you can create in [Google AI Studio](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/janko117/ESG-TRACE.git
cd ESG-TRACE
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add your key: GEMINI_API_KEY=...
```

By default, the pipeline uses Gemini 3.6 Flash. To use another Gemini model, e.g. `gemini-3.5-flash-lite`, change `MODEL_ID` in [`shared/config.py`](shared/config.py). File paths can be changed there as well.

### Usage

**1. Add the reports.** This repository contains no reports. Download the reports you want to analyse, e.g. from [responsibilityreports.com](https://www.responsibilityreports.com), and save them as `data/reports/<company>/<report_name>.pdf`.

**2. Maintain the report register.** List every report in [`data/report_register/report_register.csv`](data/report_register/report_register.csv):

```csv
company,report_name,reported_year,report_length
Altria Group,NYSE_MO_2018,2018,96
Altria Group,NYSE_MO_2019,2019,84
Altria Group,NYSE_MO_2020,2020,27
```

- `company` must match the folder name, `report_name` the file name without `.pdf`.
- `reported_year` is the year the report covers, `report_length` its number of pages.
- Include at least three consecutive years per company without gaps, since targets are only linked between directly consecutive years.

**3. Extract the targets** via the Gemini Batch API:

```bash
python extraction/extract_targets_batch/batch_submit.py    # upload the reports and start the batch job
python extraction/extract_targets_batch/batch_collect.py   # store the results; run again until the job is done
```

**4. Run the temporal analysis:**

```bash
python temporal_analysis/run_temporal_analysis.py
```

**5. View the results:**

```bash
python temporal_analysis/data_analysis.py
```

This prints a summary per company and all detected inconsistencies with their justifications. All results are stored in `data/databases/pipeline.db`. Check detected inconsistencies against the report before using them further.

## Future Work

- **Other sustainability topics:** The underlying framework is topic-independent. With topic-specific features and an adapted prompt, the pipeline can be applied to targets on water, waste, or social and governance topics.
- **Large-scale analyses:** Compare how consistently companies pursue their targets across regions (e.g. US vs. EU under different regulation), industries and company sizes, or over longer and more recent periods.
- **Dataset creation:** Use the pipeline's output as pre-annotation to build larger annotated datasets much faster than by manual annotation alone.

## License

This project is licensed under the [MIT License](LICENSE).
