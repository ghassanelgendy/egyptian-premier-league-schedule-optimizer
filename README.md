# Egyptian Premier League Schedule Optimizer

This repository generates and optimizes a full-season Egyptian Premier League schedule using Google OR-Tools **CP-SAT**.

## Key docs

- [`Documentations/PRD.md`](Documentations/PRD.md): product spec + methodology + inputs/outputs
- [`Documentations/MODEL_EXPLANATION.md`](Documentations/MODEL_EXPLANATION.md): plain-language model overview
- [`Documentations/CODE_DOCUMENTATION.md`](Documentations/CODE_DOCUMENTATION.md): repo/module map

## Quick start (first successful schedule)

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the optimizer (writes outputs under `output/`):

```bash
python -m schedule_optimizer
```

3. (Optional) Run the Streamlit UI:

```bash
python -m streamlit run ui/app.py
```

## If you don’t get an optimized schedule

See [`Documentations/PRD.md`](Documentations/PRD.md) §4.8 for the current highest-probability causes and fixes, including:

- Greedy feasibility rest-day over-blocking vs CP-SAT rest rule
- Need for a fixture-round CP-SAT model before slot assignment (two-level methodology)
