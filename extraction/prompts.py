"""Prompt for extracting emission targets from a report.

The JSON structure of the answer is enforced separately via the response schema.
"""

from __future__ import annotations

from shared.db_schema import EXTRACTED_FIELDS


def _metadata_block(metadata: dict) -> str:
    return (
        f"Company: {metadata.get('company')}\n"
        f"Report name: {metadata.get('report_name')}\n"
        f"Reporting year: {metadata.get('reported_year')}\n"
        f"Page count: {metadata.get('report_length')}"
    )


def prompt_extract_targets(metadata: dict) -> str:
    field_names = ", ".join(EXTRACTED_FIELDS)
    return f"""## General Instructions

- You extract quantified greenhouse-gas emission targets from a \
sustainability report.
- Report context:
{_metadata_block(metadata)}
- A quantified emission target requires a metric, a target year, and a \
quantitative statement of the intended change (relative or absolute).
- Statements of intent, measures, or progress figures without an associated \
target are not targets.
- Restrict yourself to general CO2 and greenhouse-gas targets; ignore \
targets for specific gases such as methane, N2O, or SF6.
- Extract each target communicated in the report as its own instance.

## Metric-Specific Instructions

- metric: the emission quantity the target refers to (e.g. "greenhouse gas \
emissions", "carbon dioxide emissions"). Name only the emission quantity \
itself, without scope information (e.g. not "Scope 1 & 2 greenhouse gas \
emissions") and without qualifiers such as "operational" or "intensity" \
(e.g. not "GHG emissions intensity"). For intensity-based targets, still \
name the underlying emission quantity, not "carbon intensity"; the intensity \
nature is captured by is_intensity_based and intensity_denominator.
- is_intensity_based: 1 if the target is intensity-based, 0 if it refers to absolute emissions.
- intensity_denominator: for intensity targets, the reference quantity.
- target_direction: reduction or increase.
- relative_target_value: the intended relative change in percent. A net-zero \
target corresponds to 100. If the report states a range instead of a single \
value (e.g. "5 to 15 percent"), this is still ONE target with ONE value: \
use the lower bound of the range (e.g. 5, not 15, for "5 to 15 percent"). \
Do NOT use the upper bound. Do NOT split a range into two targets, e.g. one \
"low" and one "high" instance; a range describes a single target, not two. \
Do NOT omit the target or leave relative_target_value empty solely because \
it is stated as a range; a range is still a valid, quantified target and \
must be extracted using the lower-bound rule above.
- absolute_target_value / absolute_target_value_unit: the intended absolute \
emission level in the target year and its unit.
- target_year: the year by which the target is to be reached.
- base_year / base_value / base_value_unit: the reference year, the emission \
level in that year, and its unit.
- For all unit fields (absolute_target_value_unit, base_value_unit, \
current_value_unit), include the substance where the report states it \
(e.g. "million tons CO2", not just "million tons").
- annual_change_rate: an annual rate of change, only if the report states it \
explicitly.
- scope_of_application: the organizational or geographic scope the target covers.
- scope_1, scope_2, scope_3: for each, 1 if that scope is included in the \
target, 0 if it is excluded. Also set scopes on established paraphrases: \
direct operations = Scope 1 and 2, value chain = Scope 1, 2 and 3, \
supply chain = Scope 3, use of sold products = Scope 3. Leave all three \
fields empty unless a scope is stated explicitly or via one of the \
paraphrases above. If a statement names the included scopes (e.g. "Scope 1 \
& 2"), set the named scopes to 1 and the others explicitly to 0.
- emission_character: gross or net. Set net when the report states or implies \
that offsets or removals count toward the target (e.g. "reduce or offset", a \
net-zero target, or carbon neutrality); set gross when the report explicitly \
refers to gross emissions.
- current_value / current_value_unit: the emission level in the reporting year \
and its unit.
- current_relative_change: the change achieved so far versus the base value, \
only if stated explicitly. Do not calculate it. Use the same sign convention \
as target_direction: a positive value means progress toward the target (e.g. \
a decrease for a reduction target), a negative value means movement away \
from it (e.g. an increase for a reduction target).
- achievement_rate: the progress achieved relative to the target, only if \
stated explicitly. Do not calculate it. Express it as a fraction between 0 \
and 1, not as a percentage (e.g. 0.7 for "70 percent of the target", not 70).
- achievement_status: the status of the target as stated or clearly implied by \
the report: achieved, failed, or ongoing.

## Recommended Search Words

- emission, greenhouse gas, GHG, CO2, carbon dioxide, carbon footprint
- target, goal, reduce, reduction, commit, pledge, ambition
- net zero, net-zero, carbon neutral, climate neutral
- science based target, base year, baseline
- Scope 1, Scope 2, Scope 3
- Use these as a starting point when scanning the report; targets may also \
be phrased differently.

## Response Requirements

- Report only what the report states; leave anything not stated empty.
- Do not add values that are not contained in the report.
- If the report contains no quantified emission target, return an empty list.
- Every field you fill MUST have a matching evidence entry, and every value \
must be supported by the report.
- For every field you fill, add an entry to the evidence list with:
  - field: the exact field name
  - page: the page number
  - source_type: text, table, or chart
  - text: for source_type text, a short verbatim quote of the source \
location; for source_type table or chart, the caption or title of the \
table or chart, NOT the extracted value; if there is no such caption, \
text stays empty
- If a value appears in several modalities, choose the highest priority: \
text over table over chart.
- Use exactly these field names: {field_names}.
"""
