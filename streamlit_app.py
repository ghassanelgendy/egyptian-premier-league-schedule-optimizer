"""Streamlit UI for the Egyptian Premier League schedule optimizer.

Goal: make the pipeline observable end-to-end (progress + artifacts) while
reusing the existing CLI-phase functions from `main.py` / `src/*`.
"""

from __future__ import annotations

import io
import html
import json
import os
import sys
import time
import calendar
from datetime import date as pydate
from contextlib import redirect_stdout
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.constants import (
    BASELINE_SOLVER_TIME_LIMIT_S,
    DATA_MODEL_PATH,
    DEFAULT_SEED,
    EXPANDED_CALENDAR_PATH,
    HARD_MAX_MATCHES_PER_WEEK,
    HARD_MIN_MATCHES_PER_WEEK,
    MATCHES_PER_ROUND,
    MAX_CONSECUTIVE_AWAY,
    MAX_CONSECUTIVE_HOME,
    MAX_MATCHES_PER_SLOT,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    NUM_ROUNDS,
    NUM_TEAMS,
    OUTPUT_DIR,
    PHASES_DIR,
    PREFERRED_REST_DAYS_CAF,
    REPAIR_SOLVER_TIME_LIMIT_S,
    SOFT_MAX_MATCHES_PER_WEEK,
    SOFT_MIN_MATCHES_PER_WEEK,
    W_CAF_PREFERRED,
    W_ROUND_ORDER,
    W_TIER_MISMATCH,
    W_TRAVEL,
    W_WEEK_OVERLOAD,
    W_WEEK_UNDERLOAD,
)


APP_TITLE = "Egyptian Premier League Schedule Optimizer"


MODEL_CONTROL_GROUPS = [
    (
        "League shape",
        [
            ("NUM_TEAMS", "Teams", NUM_TEAMS, 2, 40, 2, "Must match the teams workbook."),
            ("NUM_ROUNDS", "Rounds", NUM_ROUNDS, 1, 80, 1, "Double round-robin uses (teams - 1) * 2."),
            (
                "MATCHES_PER_ROUND",
                "Matches per round",
                MATCHES_PER_ROUND,
                1,
                20,
                1,
                "Usually teams / 2.",
            ),
        ],
    ),
    (
        "Rest and streak rules",
        [
            (
                "MIN_REST_DAYS_LOCAL",
                "Min local rest days",
                MIN_REST_DAYS_LOCAL,
                0,
                14,
                1,
                "League-to-league full rest days.",
            ),
            (
                "MIN_REST_DAYS_CAF",
                "Min CAF rest days",
                MIN_REST_DAYS_CAF,
                0,
                14,
                1,
                "League-to-CAF full rest days.",
            ),
            (
                "PREFERRED_REST_DAYS_CAF",
                "Preferred CAF rest days",
                PREFERRED_REST_DAYS_CAF,
                0,
                21,
                1,
                "Documented preference; only affects code paths that consume it.",
            ),
            (
                "MAX_CONSECUTIVE_HOME",
                "Max consecutive home",
                MAX_CONSECUTIVE_HOME,
                1,
                10,
                1,
                "Maximum home streak.",
            ),
            (
                "MAX_CONSECUTIVE_AWAY",
                "Max consecutive away",
                MAX_CONSECUTIVE_AWAY,
                1,
                10,
                1,
                "Maximum away streak.",
            ),
        ],
    ),
    (
        "Week and slot capacity",
        [
            (
                "HARD_MIN_MATCHES_PER_WEEK",
                "Hard min matches/week",
                HARD_MIN_MATCHES_PER_WEEK,
                0,
                40,
                1,
                "Current solver keeps this available but treats small week fragments softly.",
            ),
            (
                "HARD_MAX_MATCHES_PER_WEEK",
                "Hard max matches/week",
                HARD_MAX_MATCHES_PER_WEEK,
                1,
                60,
                1,
                "Hard upper bound per calendar week.",
            ),
            (
                "SOFT_MIN_MATCHES_PER_WEEK",
                "Soft min matches/week",
                SOFT_MIN_MATCHES_PER_WEEK,
                0,
                40,
                1,
                "Soft lower target for week load.",
            ),
            (
                "SOFT_MAX_MATCHES_PER_WEEK",
                "Soft max matches/week",
                SOFT_MAX_MATCHES_PER_WEEK,
                1,
                60,
                1,
                "Soft upper target for week load.",
            ),
            (
                "MAX_MATCHES_PER_SLOT",
                "Max matches per kickoff slot",
                MAX_MATCHES_PER_SLOT,
                1,
                10,
                1,
                "Concurrent matches allowed in the same kickoff slot.",
            ),
        ],
    ),
    (
        "Objective weights",
        [
            ("W_ROUND_ORDER", "Round order weight", W_ROUND_ORDER, 0, 10000, 1, "Chronological round pressure."),
            (
                "W_WEEK_UNDERLOAD",
                "Week underload weight",
                W_WEEK_UNDERLOAD,
                0,
                10000,
                1,
                "Penalty below soft week minimum.",
            ),
            (
                "W_WEEK_OVERLOAD",
                "Week overload weight",
                W_WEEK_OVERLOAD,
                0,
                10000,
                1,
                "Penalty above soft week maximum.",
            ),
            ("W_TRAVEL", "Travel weight", W_TRAVEL, 0, 1000, 1, "Per-kilometer travel penalty."),
            (
                "W_TIER_MISMATCH",
                "Tier mismatch weight",
                W_TIER_MISMATCH,
                0,
                10000,
                1,
                "Penalty when match tier and slot tier differ.",
            ),
            (
                "W_CAF_PREFERRED",
                "CAF preferred-rest weight",
                W_CAF_PREFERRED,
                0,
                10000,
                1,
                "Documented preference; only affects code paths that consume it.",
            ),
        ],
    ),
    (
        "Solver limits",
        [
            (
                "BASELINE_SOLVER_TIME_LIMIT_S",
                "Baseline solver limit (sec)",
                BASELINE_SOLVER_TIME_LIMIT_S,
                1,
                7200,
                5,
                "CP-SAT baseline solve time limit.",
            ),
            (
                "REPAIR_SOLVER_TIME_LIMIT_S",
                "Repair solver limit (sec)",
                REPAIR_SOLVER_TIME_LIMIT_S,
                1,
                7200,
                5,
                "CAF repair solve/search time limit.",
            ),
        ],
    ),
]


MODEL_MODULES = [
    "src.constants",
    "src.fixture_generator",
    "src.slot_domain",
    "src.baseline_solver",
    "src.caf_audit",
    "src.caf_repair_solver",
    "src.validation",
]


def _read_csv_if_exists(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        # Some CSVs may have date objects or odd formatting; fall back to pandas defaults.
        return pd.read_csv(path, dtype=str)


def _read_json_if_exists(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _file_bytes(path: str) -> Optional[bytes]:
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _safe_asdict(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_safe_asdict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _safe_asdict(v) for k, v in obj.items()}
    return obj


def _render_model_config_controls() -> Dict[str, int]:
    """Render all tweakable model constants and return the selected values."""
    config: Dict[str, int] = {}

    st.markdown("**Model variables**")
    st.caption("Applied to the next pipeline run in this Streamlit session.")

    for group_name, fields in MODEL_CONTROL_GROUPS:
        with st.expander(group_name, expanded=group_name in ("Rest and streak rules", "Solver limits")):
            for name, label, default, min_value, max_value, step, help_text in fields:
                config[name] = int(
                    st.number_input(
                        label,
                        min_value=int(min_value),
                        max_value=int(max_value),
                        value=int(default),
                        step=int(step),
                        help=help_text,
                        key=f"model_cfg::{name}",
                    )
                )

    expected_rounds = (config["NUM_TEAMS"] - 1) * 2
    expected_matches_per_round = config["NUM_TEAMS"] // 2
    if config["NUM_ROUNDS"] != expected_rounds or config["MATCHES_PER_ROUND"] != expected_matches_per_round:
        st.warning(
            "League shape is inconsistent with a double round-robin. "
            f"Expected {expected_rounds} rounds and {expected_matches_per_round} matches per round."
        )

    if config["SOFT_MIN_MATCHES_PER_WEEK"] > config["SOFT_MAX_MATCHES_PER_WEEK"]:
        st.warning("Soft week minimum is above soft week maximum.")
    if config["HARD_MIN_MATCHES_PER_WEEK"] > config["HARD_MAX_MATCHES_PER_WEEK"]:
        st.warning("Hard week minimum is above hard week maximum.")

    return config


def _apply_runtime_model_config(config: Dict[str, int]) -> None:
    """Patch constants into already-imported solver modules before a run."""
    for module_name in MODEL_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for key, value in config.items():
            if hasattr(module, key):
                setattr(module, key, value)


@st.cache_resource(show_spinner=False)
def _load_inputs_cached():
    """Load authoritative inputs once per app session.

    Note: `src.data_loader.load_data()` writes load artifacts to output/ as part of
    its contract. We cache it to avoid repeated side effects.
    """
    from src.data_loader import load_data

    return load_data()


def _try_parse_date_series(s: pd.Series) -> pd.Series:
    dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.date


def _read_schedule(source: str) -> Optional[pd.DataFrame]:
    mapping = {
        "Final schedule": os.path.join(OUTPUT_DIR, "optimized_schedule.csv"),
        "Baseline (pre-CAF)": os.path.join(OUTPUT_DIR, "optimized_schedule_pre_caf.csv"),
        "Repaired matches": os.path.join(OUTPUT_DIR, "caf_rescheduled_matches.csv"),
    }
    df = _read_csv_if_exists(mapping[source])
    if df is None:
        return None
    # Normalize date column name differences.
    if "Date" in df.columns:
        df["_Date"] = _try_parse_date_series(df["Date"])
    elif "Original_Date" in df.columns:
        df["_Date"] = _try_parse_date_series(df["Original_Date"])
    else:
        df["_Date"] = pd.NaT

    # Computed day name (works even if CSV lacks Day_name)
    try:
        df["_Day_Name"] = pd.to_datetime(df["_Date"], errors="coerce").dt.day_name()
    except Exception:
        df["_Day_Name"] = ""
    return df


def _run_phase(
    name: str,
    fn: Callable[[], Any],
    status: "st.status",
    log_box: "st.delta_generator.DeltaGenerator",
    log_buffer: io.StringIO,
) -> Any:
    status.update(label=name, state="running")
    start = time.time()
    with redirect_stdout(log_buffer):
        result = fn()
    elapsed = time.time() - start
    log_box.text(log_buffer.getvalue())
    status.update(label=f"{name} (done in {elapsed:.1f}s)", state="complete")
    return result


def _render_artifacts_section() -> None:
    st.subheader("Artifacts")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Primary outputs (`output/`)**")
        primary = [
            "optimized_schedule_pre_caf.csv",
            "caf_postponement_queue.csv",
            "caf_rescheduled_matches.csv",
            "unresolved_caf_postponements.csv",
            "optimized_schedule.csv",
            "week_round_map.csv",
            "data_load_log.txt",
        ]
        for fname in primary:
            fpath = os.path.join(OUTPUT_DIR, fname)
            exists = os.path.exists(fpath)
            st.write(("✅ " if exists else "— ") + fpath)

    with cols[1]:
        st.markdown("**Diagnostics (`output/phases/`)**")
        phase_files = [
            "01_load_summary.json",
            "02_fifa_summary.csv",
            "03_caf_blocker_summary.csv",
            "03_round_windows.csv",
            "04_fixture_framework.csv",
            "04_home_away_patterns.csv",
            "05_baseline_feasible_slot_counts.csv",
            "06_baseline_solver_status.json",
            "07_caf_audit.csv",
            "08_repair_feasible_slot_counts.csv",
            "09_repair_solver_status.json",
            "10_final_validation_report.csv",
            "10_team_sequence_validation.csv",
        ]
        for fname in phase_files:
            fpath = os.path.join(PHASES_DIR, fname)
            exists = os.path.exists(fpath)
            st.write(("✅ " if exists else "— ") + fpath)

    with st.expander("Preview key tables", expanded=True):
        schedule = _read_csv_if_exists(os.path.join(OUTPUT_DIR, "optimized_schedule.csv"))
        pre = _read_csv_if_exists(os.path.join(OUTPUT_DIR, "optimized_schedule_pre_caf.csv"))
        queue = _read_csv_if_exists(os.path.join(OUTPUT_DIR, "caf_postponement_queue.csv"))
        repaired = _read_csv_if_exists(os.path.join(OUTPUT_DIR, "caf_rescheduled_matches.csv"))
        unresolved = _read_csv_if_exists(os.path.join(OUTPUT_DIR, "unresolved_caf_postponements.csv"))

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["Final schedule", "Baseline (pre-CAF)", "CAF queue", "Repaired", "Unresolved"]
        )
        with tab1:
            if schedule is None:
                st.info("`output/optimized_schedule.csv` not found yet.")
            else:
                st.dataframe(schedule, use_container_width=True, height=420)
        with tab2:
            if pre is None:
                st.info("`output/optimized_schedule_pre_caf.csv` not found yet.")
            else:
                st.dataframe(pre, use_container_width=True, height=420)
        with tab3:
            if queue is None:
                st.info("`output/caf_postponement_queue.csv` not found yet.")
            else:
                st.dataframe(queue, use_container_width=True, height=420)
        with tab4:
            if repaired is None:
                st.info("`output/caf_rescheduled_matches.csv` not found yet.")
            else:
                st.dataframe(repaired, use_container_width=True, height=420)
        with tab5:
            if unresolved is None:
                st.info("`output/unresolved_caf_postponements.csv` not found yet.")
            else:
                st.dataframe(unresolved, use_container_width=True, height=420)

    with st.expander("Download artifacts"):
        root = Path(".")
        out_dir = root / OUTPUT_DIR
        phases_dir = root / PHASES_DIR

        candidates: List[Path] = []
        if out_dir.exists():
            candidates.extend(sorted(out_dir.glob("*.csv")))
            candidates.extend(sorted(out_dir.glob("*.txt")))
            candidates.extend(sorted(out_dir.glob("*.json")))
        if phases_dir.exists():
            candidates.extend(sorted(phases_dir.glob("*.csv")))
            candidates.extend(sorted(phases_dir.glob("*.json")))

        if not candidates:
            st.info("No artifacts found yet. Run the pipeline first.")
        else:
            for p in candidates:
                data = _file_bytes(str(p))
                if data is None:
                    continue
                st.download_button(
                    label=f"Download {p.as_posix()}",
                    data=data,
                    file_name=p.name,
                    mime="application/octet-stream",
                    key=f"dl::{p.as_posix()}",
                )


def _render_run_summary() -> None:
    st.subheader("Run summary")

    load_summary = _read_json_if_exists(os.path.join(PHASES_DIR, "01_load_summary.json"))
    base_status = _read_json_if_exists(os.path.join(PHASES_DIR, "06_baseline_solver_status.json"))
    repair_status = _read_json_if_exists(os.path.join(PHASES_DIR, "09_repair_solver_status.json"))

    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Data load**")
        if load_summary:
            st.json(load_summary)
        else:
            st.info("No load summary yet.")

    with cols[1]:
        st.markdown("**Baseline solver**")
        if base_status:
            st.json(base_status)
        else:
            st.info("No baseline status yet.")

    with cols[2]:
        st.markdown("**CAF repair**")
        if repair_status:
            st.json(repair_status)
        else:
            st.info("No repair status yet.")


def _round_filter_options(df: pd.DataFrame) -> List[Tuple[str, Optional[int]]]:
    rounds = list(range(1, NUM_ROUNDS + 1))
    if "Round" in df.columns:
        parsed = pd.to_numeric(df["Round"], errors="coerce").dropna().astype(int)
        rounds = sorted(set(rounds) | set(parsed.tolist()))
    return [("All rounds", None)] + [(f"Round {r}", r) for r in rounds]


def _filter_by_round(df: pd.DataFrame, selected_round: Optional[int]) -> pd.DataFrame:
    if selected_round is None:
        return df.copy()
    if "Round" not in df.columns:
        return df.iloc[0:0].copy()
    parsed = pd.to_numeric(df["Round"], errors="coerce")
    return df.loc[parsed == selected_round].copy()


def _build_caf_context(data: Any) -> Tuple[set, Dict[pydate, List[str]]]:
    if data is None:
        return set(), {}

    unique_dates = set(getattr(data, "unique_caf_dates", set()) or set())
    by_date: Dict[pydate, List[str]] = {}
    caf_blockers = getattr(data, "caf_blockers", pd.DataFrame())
    if caf_blockers is None or caf_blockers.empty:
        for d in unique_dates:
            by_date.setdefault(d, []).append("CAF")
        return unique_dates, by_date

    for _, row in caf_blockers.iterrows():
        d = row.get("_caf_date")
        if not isinstance(d, pydate):
            continue
        team = str(row.get("team_id", "") or "").strip()
        competition = str(row.get("competition_name", "") or row.get("competition", "") or "CAF").strip()
        round_name = str(row.get("round", "") or "").strip()
        label_bits = [part for part in [team, competition, round_name] if part]
        by_date.setdefault(d, []).append(" ".join(label_bits) if label_bits else "CAF")
        unique_dates.add(d)

    return unique_dates, by_date


def _match_label(row: pd.Series) -> str:
    home = html.escape(str(row.get("Home_Team_ID", "") or "TBD"))
    away = html.escape(str(row.get("Away_Team_ID", "") or "TBD"))
    round_num = row.get("Round", "")
    time_label = ""
    raw_time = row.get("Date_time", "")
    parsed = pd.to_datetime(raw_time, errors="coerce")
    if pd.notna(parsed):
        time_label = parsed.strftime("%H:%M")

    prefix = f"R{html.escape(str(round_num))} " if str(round_num).strip() else ""
    time_html = f"<span>{html.escape(time_label)}</span>" if time_label else ""
    return f"<div class=\"calendar-match\">{prefix}{home} vs {away}{time_html}</div>"


def _empty_day_reason(
    d: pydate,
    *,
    load_inputs: bool,
    fifa_dates: set,
    slot_dates: set,
    slots_on_date_count: Dict[pydate, int],
    caf_by_date: Dict[pydate, List[str]],
    selected_round: Optional[int],
    all_schedule_counts: Dict[pydate, int],
) -> str:
    if load_inputs and d in fifa_dates:
        return "FIFA window"
    if load_inputs and d in caf_by_date:
        teams = sorted({item.split()[0] for item in caf_by_date[d] if item})
        if teams:
            return "CAF blocked: " + ", ".join(teams[:4])
        return "CAF blocked"
    if slot_dates and d not in slot_dates:
        return "No playable slot"
    if selected_round is not None and all_schedule_counts.get(d, 0) > 0:
        return f"No Round {selected_round} match"
    if slot_dates and d in slot_dates:
        return f"No match ({int(slots_on_date_count.get(d, 0))} slot rows)"
    return "No match"


def _render_month_grid(
    df: pd.DataFrame,
    all_df: pd.DataFrame,
    *,
    year: int,
    month: int,
    load_inputs: bool,
    fifa_dates: set,
    slot_dates: set,
    slots_on_date_count: Dict[pydate, int],
    caf_by_date: Dict[pydate, List[str]],
    selected_round: Optional[int],
) -> None:
    matches_by_date: Dict[pydate, List[pd.Series]] = {}
    sort_cols = [c for c in ["_Date", "Date_time"] if c in df.columns]
    source_df = df.sort_values(by=sort_cols, na_position="last") if sort_cols else df
    for _, row in source_df.iterrows():
        d = row.get("_Date")
        if isinstance(d, pydate):
            matches_by_date.setdefault(d, []).append(row)

    all_schedule_counts = all_df["_Date"].value_counts(dropna=True).to_dict()
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    styles = """
<style>
.month-calendar {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}
.calendar-weekday {
  color: #475569;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}
.calendar-day {
  min-height: 150px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
  padding: 10px;
  overflow: hidden;
}
.calendar-day.outside {
  background: #f3f4f6;
  color: #94a3b8;
}
.calendar-day.matchday {
  border-color: #0f766e;
  background: #f6fffb;
}
.calendar-day.blocked {
  border-color: #dc2626;
  background: #fff7f7;
}
.calendar-day.fifa {
  border-color: #2563eb;
  background: #f8fbff;
}
.calendar-day-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 8px;
}
.calendar-day-number {
  font-weight: 800;
  color: #0f172a;
}
.calendar-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
}
.calendar-badge {
  border-radius: 6px;
  background: #e2e8f0;
  color: #334155;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1;
  padding: 4px 5px;
}
.calendar-badge.caf { background: #fee2e2; color: #991b1b; }
.calendar-badge.fifa { background: #dbeafe; color: #1e40af; }
.calendar-match {
  border-left: 3px solid #0f766e;
  background: #ecfdf5;
  color: #0f172a;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.25;
  margin-top: 6px;
  padding: 6px 7px;
}
.calendar-match span {
  display: block;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 600;
  margin-top: 2px;
}
.calendar-empty {
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.25;
}
@media (max-width: 900px) {
  .month-calendar { gap: 5px; }
  .calendar-day { min-height: 118px; padding: 7px; }
  .calendar-match, .calendar-empty { font-size: 0.72rem; }
  .calendar-weekday { font-size: 0.7rem; }
}
</style>
"""
    cells: List[str] = [styles, "<div class=\"month-calendar\">"]
    for name in weekday_names:
        cells.append(f"<div class=\"calendar-weekday\">{name}</div>")

    for week in weeks:
        for d in week:
            day_matches = matches_by_date.get(d, [])
            classes = ["calendar-day"]
            if d.month != month:
                classes.append("outside")
            if day_matches:
                classes.append("matchday")
            if load_inputs and d in caf_by_date:
                classes.append("blocked")
            if load_inputs and d in fifa_dates:
                classes.append("fifa")

            badges: List[str] = []
            if day_matches:
                badges.append(f"<span class=\"calendar-badge\">{len(day_matches)}</span>")
            if load_inputs and d in fifa_dates:
                badges.append("<span class=\"calendar-badge fifa\">FIFA</span>")
            if load_inputs and d in caf_by_date:
                badges.append("<span class=\"calendar-badge caf\">CAF</span>")

            body = "".join(_match_label(row) for row in day_matches)
            if not day_matches and d.month == month:
                reason = _empty_day_reason(
                    d,
                    load_inputs=load_inputs,
                    fifa_dates=fifa_dates,
                    slot_dates=slot_dates,
                    slots_on_date_count=slots_on_date_count,
                    caf_by_date=caf_by_date,
                    selected_round=selected_round,
                    all_schedule_counts=all_schedule_counts,
                )
                body = f"<div class=\"calendar-empty\">{html.escape(reason)}</div>"

            cells.append(
                "<div class=\"{classes}\">"
                "<div class=\"calendar-day-header\">"
                "<div class=\"calendar-day-number\">{day}</div>"
                "<div class=\"calendar-badges\">{badges}</div>"
                "</div>"
                "{body}"
                "</div>".format(
                    classes=" ".join(classes),
                    day=d.day,
                    badges="".join(badges),
                    body=body,
                )
            )

    cells.append("</div>")
    st.markdown("".join(cells), unsafe_allow_html=True)


def _team_label_lookup(data: Any) -> Dict[str, str]:
    if data is None or not hasattr(data, "teams"):
        return {}

    lookup: Dict[str, str] = {}
    teams = data.teams
    if "Team_ID" not in teams.columns:
        return lookup

    for _, row in teams.iterrows():
        team_id = str(row.get("Team_ID", "") or "").strip()
        team_name = str(row.get("Team_Name", "") or "").strip()
        if team_id:
            lookup[team_id] = f"{team_id} - {team_name}" if team_name else team_id
    return lookup


def _build_travel_stats(df: pd.DataFrame, data: Any) -> Optional[pd.DataFrame]:
    if "Away_Team_ID" not in df.columns or "Travel_km" not in df.columns:
        return None

    travel = df[["Away_Team_ID", "Travel_km"]].copy()
    travel["Team_ID"] = travel["Away_Team_ID"].astype(str)
    travel["Travel_km"] = pd.to_numeric(travel["Travel_km"], errors="coerce").fillna(0.0)

    stats = (
        travel.groupby("Team_ID", as_index=False)
        .agg(
            Total_km=("Travel_km", "sum"),
            Away_trips=("Travel_km", "size"),
            Avg_km_per_away_trip=("Travel_km", "mean"),
            Longest_trip_km=("Travel_km", "max"),
        )
    )

    if data is not None and hasattr(data, "teams") and "Team_ID" in data.teams.columns:
        all_teams = pd.DataFrame({"Team_ID": data.teams["Team_ID"].astype(str)})
        stats = all_teams.merge(stats, on="Team_ID", how="left")
        for col in ["Total_km", "Away_trips", "Avg_km_per_away_trip", "Longest_trip_km"]:
            stats[col] = stats[col].fillna(0)

    label_lookup = _team_label_lookup(data)
    stats["Team"] = stats["Team_ID"].map(label_lookup).fillna(stats["Team_ID"])
    stats["Total_km"] = stats["Total_km"].round(1)
    stats["Avg_km_per_away_trip"] = stats["Avg_km_per_away_trip"].round(1)
    stats["Longest_trip_km"] = stats["Longest_trip_km"].round(1)
    stats["Away_trips"] = stats["Away_trips"].astype(int)

    return stats.sort_values("Total_km", ascending=False).reset_index(drop=True)


def _render_travel_stats(df_full: pd.DataFrame, data: Any, schedule_source: str) -> None:
    st.markdown("### Team travel")
    st.caption(
        "Season totals use `Travel_km` from the schedule output and assign each trip to `Away_Team_ID`."
    )

    stats = _build_travel_stats(df_full, data)
    if stats is None:
        st.warning("This schedule source needs `Away_Team_ID` and `Travel_km` columns to calculate travel.")
        return
    if stats.empty:
        st.info("No travel rows found in this schedule source.")
        return

    total_km = float(stats["Total_km"].sum())
    avg_team_km = float(stats["Total_km"].mean())
    leader = stats.iloc[0]
    total_trips = int(stats["Away_trips"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("League travel km", f"{total_km:,.0f}")
    c2.metric("Average per team", f"{avg_team_km:,.0f}")
    c3.metric("Most travel", str(leader["Team_ID"]), f"{float(leader['Total_km']):,.0f} km")
    c4.metric("Away trips counted", f"{total_trips:,}")

    sort_col, view_col = st.columns([1, 1])
    with sort_col:
        sort_by = st.selectbox(
            "Sort travel stats by",
            ["Total_km", "Avg_km_per_away_trip", "Longest_trip_km", "Away_trips"],
            format_func=lambda value: value.replace("_", " "),
        )
    with view_col:
        top_n = st.selectbox("Teams shown in chart", ["All", "Top 5", "Top 10"], index=0)

    sorted_stats = stats.sort_values(sort_by, ascending=False).reset_index(drop=True)
    if top_n != "All":
        sorted_stats = sorted_stats.head(int(top_n.split()[-1]))

    chart_data = sorted_stats.set_index("Team")["Total_km"]
    st.bar_chart(chart_data, use_container_width=True, height=420)

    st.dataframe(
        stats[
            [
                "Team_ID",
                "Team",
                "Total_km",
                "Away_trips",
                "Avg_km_per_away_trip",
                "Longest_trip_km",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    csv_bytes = stats.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download season travel stats (CSV)",
        data=csv_bytes,
        file_name=f"{schedule_source.lower().replace(' ', '_')}_season_travel_km.csv",
        mime="text/csv",
    )


def _render_explore() -> None:
    st.subheader("Explore")
    st.caption(
        "Team-centric view + calendar simulation (uses `data/Data_Model.xlsx` and "
        "`data/expanded_calendar.xlsx` for FIFA/slot context)."
    )

    left, middle, right = st.columns([1, 1, 1])
    with left:
        schedule_source = st.selectbox(
            "Schedule source",
            ["Final schedule", "Baseline (pre-CAF)", "Repaired matches"],
            index=0,
        )
    df_full = _read_schedule(schedule_source)
    if df_full is None:
        st.warning(
            "No schedule file found for this source yet. Run the pipeline first, "
            "or switch to a source that exists."
        )
        return

    round_options = _round_filter_options(df_full)
    round_labels = [label for label, _ in round_options]
    with middle:
        round_label = st.selectbox("Round filter", round_labels, index=0)
        selected_round = dict(round_options)[round_label]
    with right:
        load_inputs = st.toggle("Load authoritative inputs for explanations", value=True)

    df = _filter_by_round(df_full, selected_round)
    if selected_round is not None and "Round" not in df_full.columns:
        st.warning("This schedule source has no `Round` column, so the round filter cannot be applied.")

    st.caption(f"Showing {len(df)} of {len(df_full)} match rows from {schedule_source}.")

    data = None
    fifa_dates = set()
    slot_dates = set()
    slots_on_date_count: Dict[pydate, int] = {}
    unique_caf_dates = set()
    caf_by_date: Dict[pydate, List[str]] = {}

    if load_inputs:
        with st.spinner("Loading workbooks..."):
            data = _load_inputs_cached()
        fifa_dates = set(data.fifa_dates)
        unique_caf_dates, caf_by_date = _build_caf_context(data)
        if "_date" in data.slots.columns:
            slot_dates = set(d for d in data.slots["_date"].dropna())
            slots_on_date_count = (
                data.slots["_date"].value_counts(dropna=True).to_dict()
            )

    st.divider()
    round_tab, team_tab, h2h_tab, travel_tab, cal_tab = st.tabs(
        ["Round filter", "Team chooser", "Team vs Team", "Travel stats", "Calendar"]
    )

    with round_tab:
        st.markdown("### Round filter")
        if selected_round is None:
            st.caption("Pick a round above to isolate one of the 34 rounds.")
            if "Round" in df_full.columns:
                parsed = pd.to_numeric(df_full["Round"], errors="coerce")
                round_counts = (
                    df_full.assign(_Round_Num=parsed)
                    .dropna(subset=["_Round_Num"])
                    .groupby("_Round_Num")
                    .size()
                    .reset_index(name="Matches")
                )
                round_counts["_Round_Num"] = round_counts["_Round_Num"].astype(int)
                round_counts.rename(columns={"_Round_Num": "Round"}, inplace=True)
                st.dataframe(round_counts, use_container_width=True, hide_index=True, height=420)
        elif df.empty:
            st.warning(f"No matches found for Round {selected_round} in {schedule_source}.")
        else:
            sort_cols = [c for c in ["_Date", "Date_time"] if c in df.columns]
            round_matches = (df.sort_values(by=sort_cols, na_position="last") if sort_cols else df).copy()
            if "_Day_Name" in round_matches.columns:
                round_matches.insert(0, "Day_Name", round_matches["_Day_Name"])
            st.write(f"**Round {selected_round}**: {len(round_matches)} match(es)")
            st.dataframe(
                round_matches.drop(columns=[c for c in ["_Date", "_Day_Name"] if c in round_matches.columns]),
                use_container_width=True,
                height=520,
            )

    with team_tab:
        st.markdown("### Team chooser")

        teams_df = None
        if data is not None:
            teams_df = data.teams.copy()
            teams_df["label"] = teams_df["Team_ID"].astype(str) + " — " + teams_df["Team_Name"].astype(str)
            options = teams_df["label"].tolist()
            label_to_id = dict(zip(options, teams_df["Team_ID"].tolist()))
            default_label = options[0] if options else None
            chosen_label = st.selectbox("Pick a team", options=options, index=0 if default_label else None)
            chosen_team = label_to_id.get(chosen_label, "")
        else:
            # Fallback to IDs seen in schedule only
            ids = sorted(
                set(df.get("Home_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
                | set(df.get("Away_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
            )
            chosen_team = st.selectbox("Pick a team (ID)", options=ids, index=0 if ids else None)

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            include_home = st.toggle("Include home", value=True)
        with c2:
            include_away = st.toggle("Include away", value=True)
        with c3:
            sort_by = st.selectbox("Sort by", ["Date", "Round"], index=0)

        mask = pd.Series([False] * len(df))
        if include_home and "Home_Team_ID" in df.columns:
            mask = mask | (df["Home_Team_ID"].astype(str) == str(chosen_team))
        if include_away and "Away_Team_ID" in df.columns:
            mask = mask | (df["Away_Team_ID"].astype(str) == str(chosen_team))
        team_matches = df.loc[mask].copy()

        if sort_by == "Date":
            team_matches = team_matches.sort_values(by=["_Date"], na_position="last")
        else:
            if "Round" in team_matches.columns:
                team_matches = team_matches.sort_values(by=["Round"], na_position="last")

        # Ensure day name is visible in the per-team table
        if "_Day_Name" in team_matches.columns:
            team_matches.insert(
                0,
                "Day_Name",
                team_matches["_Day_Name"],
            )

        st.write(f"**Matches for team `{chosen_team}`**: {len(team_matches)}")
        st.dataframe(team_matches.drop(columns=[c for c in ["_Date", "_Day_Name"] if c in team_matches.columns]),
                     use_container_width=True, height=520)

        csv_bytes = team_matches.drop(columns=[c for c in ["_Date", "_Day_Name"] if c in team_matches.columns]).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download filtered matches (CSV)",
            data=csv_bytes,
            file_name=f"{schedule_source.lower().replace(' ', '_')}_{chosen_team}_matches.csv",
            mime="text/csv",
        )

    with h2h_tab:
        st.markdown("### Team vs Team")
        st.caption("Shows all matches between two chosen teams (both directions).")

        if data is not None:
            teams_df = data.teams.copy()
            teams_df["label"] = teams_df["Team_ID"].astype(str) + " — " + teams_df["Team_Name"].astype(str)
            options = teams_df["label"].tolist()
            label_to_id = dict(zip(options, teams_df["Team_ID"].tolist()))

            col1, col2 = st.columns(2)
            with col1:
                a_label = st.selectbox("Team A", options=options, index=0, key="h2h_team_a")
            with col2:
                b_label = st.selectbox("Team B", options=options, index=1 if len(options) > 1 else 0, key="h2h_team_b")
            team_a = label_to_id.get(a_label, "")
            team_b = label_to_id.get(b_label, "")
        else:
            ids = sorted(
                set(df.get("Home_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
                | set(df.get("Away_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
            )
            col1, col2 = st.columns(2)
            with col1:
                team_a = st.selectbox("Team A (ID)", options=ids, index=0 if ids else None, key="h2h_team_a_fallback")
            with col2:
                team_b = st.selectbox("Team B (ID)", options=ids, index=1 if len(ids) > 1 else 0, key="h2h_team_b_fallback")

        if not team_a or not team_b:
            st.info("Pick two teams to view head-to-head matches.")
        elif str(team_a) == str(team_b):
            st.warning("Pick two different teams.")
        else:
            # Match either direction:
            # (A home vs B away) OR (B home vs A away)
            if "Home_Team_ID" not in df.columns or "Away_Team_ID" not in df.columns:
                st.error("This schedule file is missing `Home_Team_ID` / `Away_Team_ID` columns.")
            else:
                a = str(team_a)
                b = str(team_b)
                mask = (
                    ((df["Home_Team_ID"].astype(str) == a) & (df["Away_Team_ID"].astype(str) == b))
                    | ((df["Home_Team_ID"].astype(str) == b) & (df["Away_Team_ID"].astype(str) == a))
                )
                h2h = df.loc[mask].copy()
                h2h = h2h.sort_values(by=["_Date"], na_position="last")

                if "_Day_Name" in h2h.columns:
                    h2h.insert(0, "Day_Name", h2h["_Day_Name"])

                st.write(f"**Head-to-head `{a}` vs `{b}`**: {len(h2h)} match(es)")
                st.dataframe(
                    h2h.drop(columns=[c for c in ["_Date", "_Day_Name"] if c in h2h.columns]),
                    use_container_width=True,
                    height=520,
                )

                csv_bytes = h2h.drop(columns=[c for c in ["_Date", "_Day_Name"] if c in h2h.columns]).to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download head-to-head (CSV)",
                    data=csv_bytes,
                    file_name=f"{schedule_source.lower().replace(' ', '_')}_h2h_{a}_vs_{b}.csv",
                    mime="text/csv",
                )

    with travel_tab:
        _render_travel_stats(df_full, data, schedule_source)

    with cal_tab:
        st.markdown("### Calendar")

        # Determine overall date range from schedule (and slots if loaded).
        filtered_schedule_dates = sorted(d for d in df["_Date"].dropna().tolist() if isinstance(d, pydate))
        all_schedule_dates = sorted(d for d in df_full["_Date"].dropna().tolist() if isinstance(d, pydate))
        schedule_dates = filtered_schedule_dates or all_schedule_dates
        min_d = schedule_dates[0] if schedule_dates else pydate.today()
        max_d = schedule_dates[-1] if schedule_dates else pydate.today()
        if load_inputs and slot_dates:
            min_d = min(min_d, min(slot_dates))
            max_d = max(max_d, max(slot_dates))

        if "calendar_year" not in st.session_state or "calendar_month" not in st.session_state:
            st.session_state["calendar_year"] = min_d.year
            st.session_state["calendar_month"] = min_d.month

        nav_left, nav_title, nav_right = st.columns([1, 2, 1])
        with nav_left:
            if st.button("< Previous month", use_container_width=True):
                current = pydate(int(st.session_state["calendar_year"]), int(st.session_state["calendar_month"]), 1)
                prev_month_end = current - pd.Timedelta(days=1)
                st.session_state["calendar_year"] = prev_month_end.year
                st.session_state["calendar_month"] = prev_month_end.month
        with nav_right:
            if st.button("Next month >", use_container_width=True):
                current = pydate(int(st.session_state["calendar_year"]), int(st.session_state["calendar_month"]), 1)
                next_month_start = current + pd.DateOffset(months=1)
                st.session_state["calendar_year"] = next_month_start.year
                st.session_state["calendar_month"] = next_month_start.month

        current_year = int(st.session_state["calendar_year"])
        current_month = int(st.session_state["calendar_month"])
        with nav_title:
            st.markdown(
                f"#### {calendar.month_name[current_month]} {current_year}"
                + (f" - Round {selected_round}" if selected_round is not None else "")
            )

        default_pick = pydate(current_year, current_month, 1)
        if default_pick < min_d:
            default_pick = min_d
        elif default_pick > max_d:
            default_pick = max_d

        pick = st.date_input("Inspect day", value=default_pick, min_value=min_d, max_value=max_d)

        day_matches = df[df["_Date"] == pick].copy()
        if not day_matches.empty:
            st.success(f"{len(day_matches)} match(es) scheduled on {pick}.")
            st.dataframe(day_matches.drop(columns=["_Date"]), use_container_width=True, height=420)
        else:
            reasons: List[str] = []
            if load_inputs:
                if pick in fifa_dates:
                    reasons.append("This is a **FIFA day** → league matches are forbidden.")
                if pick in caf_by_date:
                    reasons.append("This date is **CAF blocked** for: " + ", ".join(caf_by_date[pick][:6]))
                if slot_dates and pick not in slot_dates:
                    reasons.append("No playable slots exist on this date in `expanded_calendar.xlsx` (outside slot universe).")
                if slot_dates and pick in slot_dates:
                    reasons.append(
                        f"There are **{int(slots_on_date_count.get(pick, 0))} slot row(s)** on this date, "
                        "but none are scheduled in this selected schedule."
                    )
            if selected_round is not None and int(df_full["_Date"].value_counts(dropna=True).to_dict().get(pick, 0)) > 0:
                reasons.append(f"Other rounds have matches on this date, but Round {selected_round} does not.")
            if not reasons:
                reasons.append("No matches are scheduled on this date in this selected schedule.")

            st.info("No matches on this day.")
            for r in reasons:
                st.write("- " + r)

        st.divider()
        st.markdown("**Month view**")
        month = st.selectbox(
            "Jump to month",
            options=list(range(1, 13)),
            index=current_month - 1,
            format_func=lambda m: calendar.month_name[int(m)],
        )
        year = st.number_input("Year", min_value=2000, max_value=2100, value=current_year, step=1)
        if int(month) != current_month or int(year) != current_year:
            st.session_state["calendar_month"] = int(month)
            st.session_state["calendar_year"] = int(year)

        # Count matches per date
        counts = df["_Date"].value_counts(dropna=True).to_dict()

        _render_month_grid(
            df,
            df_full,
            year=int(year),
            month=int(month),
            load_inputs=load_inputs,
            fifa_dates=fifa_dates,
            slot_dates=slot_dates,
            slots_on_date_count=slots_on_date_count,
            caf_by_date=caf_by_date,
            selected_round=selected_round,
        )

        st.markdown("**Compact count table**")
        cal = calendar.Calendar(firstweekday=0)  # Monday
        weeks = cal.monthdatescalendar(int(year), int(month))
        rows: List[Dict[str, str]] = []
        for w in weeks:
            row: Dict[str, str] = {}
            for d in w:
                label = ""
                if d.month != int(month):
                    label = ""
                else:
                    n = int(counts.get(d, 0))
                    label = f"{d.day}"
                    if load_inputs and d in fifa_dates:
                        label += " (FIFA)"
                    if load_inputs and d in caf_by_date:
                        label += " (CAF)"
                    if n:
                        label += f" • {n}"
                row[d.strftime("%a")] = label
            rows.append(row)

        cal_df = pd.DataFrame(rows, columns=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        st.dataframe(cal_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Month summary**")

        month_start = pydate(int(year), int(month), 1)
        month_end = pydate(int(year), int(month), calendar.monthrange(int(year), int(month))[1])

        # Daily match counts for the chosen month
        month_counts = {d: int(n) for d, n in counts.items() if isinstance(d, pydate) and month_start <= d <= month_end}
        total_matches = int(sum(month_counts.values()))
        match_days = int(sum(1 for n in month_counts.values() if n > 0))

        fifa_in_month = []
        caf_in_month = []
        if load_inputs:
            fifa_in_month = [d for d in fifa_dates if month_start <= d <= month_end]
            caf_in_month = [d for d in unique_caf_dates if month_start <= d <= month_end]

        slot_days_in_month = []
        slot_rows_in_month = 0
        slot_days_with_no_matches = 0
        if load_inputs and slot_dates:
            slot_days_in_month = sorted(d for d in slot_dates if month_start <= d <= month_end)
            slot_rows_in_month = int(
                sum(int(slots_on_date_count.get(d, 0)) for d in slot_days_in_month)
            )
            slot_days_with_no_matches = int(
                sum(1 for d in slot_days_in_month if int(month_counts.get(d, 0)) == 0)
            )

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total matches", total_matches)
        c2.metric("Match-days", match_days)
        c3.metric("FIFA days", len(fifa_in_month) if load_inputs else 0)
        c4.metric("CAF dates", len(caf_in_month) if load_inputs else 0)
        c5.metric("Slot-days w/ no matches", slot_days_with_no_matches if load_inputs and slot_dates else 0)

        busiest = sorted(month_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        if busiest:
            st.markdown("**Busiest dates**")
            st.dataframe(
                pd.DataFrame(
                    [{"Date": d, "Day": d.strftime("%A"), "Matches": n} for d, n in busiest]
                ),
                use_container_width=True,
                hide_index=True,
            )

        # Weekday distribution
        if month_counts:
            weekday_dist: Dict[str, int] = {}
            for d, n in month_counts.items():
                weekday_dist[d.strftime("%A")] = weekday_dist.get(d.strftime("%A"), 0) + int(n)
            st.markdown("**Matches by weekday**")
            dist_df = pd.DataFrame(
                [{"Weekday": k, "Matches": v} for k, v in weekday_dist.items()]
            ).sort_values("Matches", ascending=False)
            st.bar_chart(dist_df.set_index("Weekday")["Matches"])

        # Optional detailed day-status table (good for "why empty" debugging)
        with st.expander("Daily status table"):
            days = [month_start + pd.Timedelta(days=i) for i in range((month_end - month_start).days + 1)]
            day_rows = []
            for d_ts in days:
                d = d_ts.date() if hasattr(d_ts, "date") else d_ts  # robustness
                mcount = int(month_counts.get(d, 0))
                row = {
                    "Date": d,
                    "Day": d.strftime("%A"),
                    "Matches": mcount,
                }
                if load_inputs:
                    row["Is_FIFA"] = d in fifa_dates
                    row["Is_CAF"] = d in unique_caf_dates
                    row["CAF_Blockers"] = "; ".join(caf_by_date.get(d, []))
                    row["Slot_rows"] = int(slots_on_date_count.get(d, 0)) if slot_dates else 0
                    row["In_slot_universe"] = (d in slot_dates) if slot_dates else False
                day_rows.append(row)
            st.dataframe(pd.DataFrame(day_rows), use_container_width=True, height=520)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(
        "Runs the full pipeline (load → fixtures → baseline → CAF audit → repair) "
        "and renders all PRD-required outputs and phase artifacts."
    )

    with st.sidebar:
        st.header("Run configuration")
        seed = st.number_input("DRR seed", min_value=0, max_value=2_000_000_000, value=DEFAULT_SEED, step=1)
        st.text_input("Data model path", value=DATA_MODEL_PATH, disabled=True)
        st.text_input("Expanded calendar path", value=EXPANDED_CALENDAR_PATH, disabled=True)

        st.divider()
        model_config = _render_model_config_controls()

        run_clicked = st.button("Run full pipeline", type="primary")
        st.divider()
        st.markdown("**Tip**: If you only want to browse outputs, don’t run — just use the tabs.")

    tab_run, tab_explore, tab_artifacts, tab_browse = st.tabs(
        ["Run & progress", "Explore", "Artifacts", "Browse files"]
    )

    with tab_run:
        st.subheader("Progress")
        log_buffer = io.StringIO()
        log_box = st.empty()

        # Always show current logs from session_state if present.
        if "stdout_log" in st.session_state and st.session_state["stdout_log"]:
            log_box.text(st.session_state["stdout_log"])

        col_a, col_b = st.columns([1, 1])
        with col_a:
            # Streamlit supports only: running | complete | error
            # We treat "not started" as a complete state with a "(waiting)" label.
            status_load = st.status("Phase 1: Load data (waiting)", state="complete")
            status_fixtures = st.status("Phase 2: Generate fixtures (waiting)", state="complete")
            status_domain = st.status("Phase 3a: Build domains (waiting)", state="complete")
            status_baseline = st.status("Phase 3b: Solve baseline (waiting)", state="complete")
            status_audit = st.status("Phase 4: CAF audit (waiting)", state="complete")
            status_repair = st.status("Phase 5: CAF repair (waiting)", state="complete")
            status_write = st.status("Phase 6: Write outputs (waiting)", state="complete")

        with col_b:
            st.markdown("**Live stdout**")
            st.caption("This mirrors the CLI prints so you can see each phase evolve.")

        if run_clicked:
            _apply_runtime_model_config(model_config)
            # Import inside run to avoid heavy imports on mere browsing.
            from src.data_loader import load_data
            from src.fixture_generator import generate_drr
            from src.slot_domain import build_domains
            from src.baseline_solver import solve_baseline
            from src.caf_audit import caf_audit
            from src.caf_repair_solver import caf_repair
            from src.output_writer import (
                write_final_schedule,
                write_postponement_queue,
                write_pre_caf_schedule,
                write_rescheduled_matches,
                write_unresolved,
                write_week_round_map,
            )
            from src.validation import write_validation_reports

            t0 = time.time()

            try:
                data = _run_phase("Phase 1: Load data", load_data, status_load, log_box, log_buffer)
                st.session_state["stdout_log"] = log_buffer.getvalue()

                matches = _run_phase(
                    f"Phase 2: Generate DRR fixtures (seed={int(seed)})",
                    lambda: generate_drr(data, int(seed)),
                    status_fixtures,
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                domains = _run_phase(
                    "Phase 3a: Build slot domains",
                    lambda: build_domains(data, matches),
                    status_domain,
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                baseline = _run_phase(
                    "Phase 3b: Solve baseline",
                    lambda: solve_baseline(data, matches, domains),
                    status_baseline,
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                if baseline is None:
                    status_baseline.update(label="Phase 3b: Solve baseline (INFEASIBLE)", state="error")
                    st.error("Baseline solver returned infeasible. Check `output/phases/06_baseline_solver_status.json`.")
                    return

                _run_phase(
                    "Write baseline schedule (pre-CAF)",
                    lambda: write_pre_caf_schedule(baseline),
                    st.status("Write pre-CAF schedule (waiting)", state="complete"),
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                accepted, violations = _run_phase(
                    "Phase 4: CAF audit",
                    lambda: caf_audit(baseline, data),
                    status_audit,
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                repaired, unresolved = _run_phase(
                    "Phase 5: CAF repair",
                    lambda: caf_repair(accepted, violations, data),
                    status_repair,
                    log_box,
                    log_buffer,
                )
                st.session_state["stdout_log"] = log_buffer.getvalue()

                def _write_all() -> None:
                    write_final_schedule(accepted, repaired, violations)
                    write_postponement_queue(violations, repaired, unresolved)
                    write_rescheduled_matches(repaired)
                    write_unresolved(unresolved)
                    write_week_round_map(accepted, repaired)
                    write_validation_reports(accepted, repaired, unresolved, data)

                _run_phase("Phase 6: Write final outputs", _write_all, status_write, log_box, log_buffer)
                st.session_state["stdout_log"] = log_buffer.getvalue()

                elapsed = time.time() - t0
                st.success(
                    f"Pipeline complete in {elapsed:.1f}s. "
                    f"Baseline={len(baseline)} | Violations={len(set(v.match.match_idx for v in violations))} "
                    f"| Repaired={len(repaired)} | Unresolved={len(unresolved)}"
                )

            except Exception as e:
                st.session_state["stdout_log"] = log_buffer.getvalue()
                st.exception(e)

        st.divider()
        _render_run_summary()

    with tab_explore:
        _render_explore()

    with tab_artifacts:
        _render_artifacts_section()

    with tab_browse:
        st.subheader("Browse `output/` and `output/phases/`")
        st.caption("Quick way to inspect any artifact in a table or raw view.")

        root = Path(".")
        options: List[Path] = []
        out_dir = root / OUTPUT_DIR
        phases_dir = root / PHASES_DIR
        if out_dir.exists():
            options.extend(sorted(out_dir.glob("*.*")))
        if phases_dir.exists():
            options.extend(sorted(phases_dir.glob("*.*")))

        if not options:
            st.info("No files found yet under `output/` or `output/phases/`.")
        else:
            selected = st.selectbox(
                "Select a file",
                options=options,
                format_func=lambda p: p.as_posix(),
            )
            if selected.suffix.lower() == ".csv":
                df = _read_csv_if_exists(selected.as_posix())
                if df is None:
                    st.error("Could not read CSV.")
                else:
                    st.dataframe(df, use_container_width=True, height=520)
            elif selected.suffix.lower() == ".json":
                st.json(_read_json_if_exists(selected.as_posix()))
            else:
                content = None
                try:
                    content = selected.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    b = _file_bytes(selected.as_posix())
                    if b is not None:
                        content = b.decode("utf-8", errors="replace")
                if content is None:
                    st.error("Could not read file.")
                else:
                    st.text_area("File contents", value=content, height=520)


if __name__ == "__main__":
    main()

