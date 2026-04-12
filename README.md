<div align="center">

  <h1>⚽ Egyptian Premier League Schedule Optimizer</h1>
  
  <p>
    <strong>A mathematical optimization model to restore schedule integrity and fairness to the Egyptian Premier League.</strong>
  </p>

  <p>
    <img src="https://img.shields.io/badge/status-active-green.svg" alt="Status" />
  </p>

</div>

<br />

## 📖 About The Project

The **Egyptian Premier League Schedule Optimizer** is an automated decision-support system designed to address the chronic scheduling challenges facing Egyptian football. 

Recent seasons have suffered from severe overlaps and logistical congestion. This project utilizes **mathematical optimization techniques** to generate a conflict-free, fair, and commercially optimal season calendar. The ultimate goal is to facilitate the restoration of the standard **18-team format** within the requisite timeline.

## 🔑 Key Objectives

* **Eliminate Congestion:** Address season overlaps to ensure a smooth timeline.
* **Fairness:** Guarantee equal rest periods and fair home/away distribution.
* **Feasibility:** Ensure the schedule works within real-world constraints.
* **Automation:** Replace manual scheduling with a data-driven algorithmic approach.

## ⚙️ How It Works

The model evaluates a complex set of constraints to ensure the schedule is viable and realistic:

* **🏟️ Stadium Capacities:** Accounts for stadium sharing, pitch availability, and maintenance schedules.
* **🛡️ Security Restrictions:** Adheres to local security guidelines for match pairings and crowd control.
* **🌍 International Breaks:** Integrates FIFA windows and national team commitments without conflict.
* **🏆 Continental Participation:** Dynamically adjusts for CAF Champions League and Confederation Cup fixtures.
* **🇪🇬 Domestic Cup Integration:** Seamlessly fits Egypt Cup matches into the calendar structure.

## Run the optimizer

Requirements: Python 3.11+ recommended (3.14 tested), all workbooks under `data/` and `data/Sources/` as in [Documentations/PRD.md](Documentations/PRD.md).

```bash
pip install -r requirements.txt
python -m schedule_optimizer
```

Outputs:

- `output/optimized_schedule.csv` — full season with `Travel_km` and `Slot_tier`
- `output/week_round_map.csv` — DRR round index to calendar `Week_Num`
- `output/data_load_log.txt` — every input file/sheet touched

Optional: `EPL_CAF_BUFFER_DAYS=3` uses a ±3 day buffer around each `cont_blockers` anchor (default **1**; ±3 is often infeasible with the current blocker density).

### Web UI (Streamlit)

```bash
pip install -r requirements.txt
python -m streamlit run ui/app.py
```

On Windows, if `streamlit` is not recognized as a command, always use `python -m streamlit` (or `py -m streamlit`) so the correct Python environment is used.

The UI previews every `.xlsx` / `.csv` under `data/`, can optionally include `past seasons data/`, runs the same optimizer as the CLI, shows solver statistics, and lets you **pick a club on the Dashboard** to view its **full-season** fixtures. In-app **Code documentation** tab renders [Documentations/CODE_DOCUMENTATION.md](Documentations/CODE_DOCUMENTATION.md).

<br />

---

## 🔗 Project Link

[https://github.com/zennary04/Egyptian-Premier-League-Schedule-Optimizer](https://github.com/zennary04/Egyptian-Premier-League-Schedule-Optimizer)
