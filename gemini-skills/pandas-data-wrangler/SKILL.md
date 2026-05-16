---
name: pandas-data-wrangler
description: Schema definitions and data transformation patterns for the project's authoritative Excel and CSV files.
---

# pandas-data-wrangler

Schema definitions and data transformation patterns for the project's authoritative Excel and CSV files.

## Instructions

- Use this skill when modifying `src/data_loader.py` or performing data transformations.
- Refer to `references/schemas.md` for required columns and sheets in authoritative workbooks.
- Ensure all IDs are stripped and uppercased during normalization.
- Handle `Cont_Flag` values (`CL`, `CC`) correctly for CAF teams.

## Reference Files

- `references/schemas.md`: Detailed schema for `Data_Model.xlsx` and `expanded_calendar.xlsx`.
