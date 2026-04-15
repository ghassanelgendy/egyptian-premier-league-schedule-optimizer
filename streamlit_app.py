"""Streamlit UI for the Egyptian Premier League schedule optimizer.

Goal: make the pipeline observable end-to-end (progress + artifacts) while
reusing the existing CLI-phase functions from `main.py` / `src/*`.
"""

from __future__ import annotations

import io
import json
import os
import time
import calendar
from datetime import date as pydate
from contextlib import redirect_stdout, redirect_stderr
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
    OUTPUT_DIR,
    PHASES_DIR,
    REPAIR_SOLVER_TIME_LIMIT_S,
)


APP_TITLE = "Egyptian Premier League Schedule Optimizer"


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

    class _UIStream:
        def __init__(self, buf: io.StringIO, placeholder: "st.delta_generator.DeltaGenerator"):
            self.buf = buf
            self.placeholder = placeholder

        def write(self, s: str) -> int:
            if not s:
                return 0
            self.buf.write(s)
            # Streamlit UI updates are expensive; keep it simple and update each write.
            self.placeholder.text(self.buf.getvalue())
            return len(s)

        def flush(self) -> None:
            self.placeholder.text(self.buf.getvalue())

    ui_stream = _UIStream(log_buffer, log_box)

    # Capture both stdout and stderr. OR-Tools progress often goes to stderr.
    with redirect_stdout(ui_stream), redirect_stderr(ui_stream):
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
            "04_fixture_framework.csv",
            "05_baseline_feasible_slot_counts.csv",
            "06_baseline_solver_status.json",
            "07_caf_audit.csv",
            "08_repair_feasible_slot_counts.csv",
            "09_repair_solver_status.json",
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


def _render_explore() -> None:
    st.subheader("Explore")
    st.caption(
        "Team-centric view + calendar simulation (uses `data/Data_Model.xlsx` and "
        "`data/expanded_calendar.xlsx` for FIFA/slot context)."
    )

    left, right = st.columns([1, 1])
    with left:
        schedule_source = st.selectbox(
            "Schedule source",
            ["Final schedule", "Baseline (pre-CAF)", "Repaired matches"],
            index=0,
        )
    with right:
        load_inputs = st.toggle("Load authoritative inputs for explanations", value=True)

    df = _read_schedule(schedule_source)
    if df is None:
        st.warning(
            "No schedule file found for this source yet. Run the pipeline first, "
            "or switch to a source that exists."
        )
        return

    data = None
    fifa_dates = set()
    slot_dates = set()
    slots_on_date_count: Dict[pydate, int] = {}

    if load_inputs:
        with st.spinner("Loading workbooks..."):
            data = _load_inputs_cached()
        fifa_dates = set(data.fifa_dates)
        if "_date" in data.slots.columns:
            slot_dates = set(d for d in data.slots["_date"].dropna())
            slots_on_date_count = (
                data.slots["_date"].value_counts(dropna=True).to_dict()
            )

    st.divider()
    team_tab, h2h_tab, cal_tab = st.tabs(["Team chooser", "Team vs Team", "Calendar simulation"])

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

    with cal_tab:
        st.markdown("### Calendar simulation")

        # Determine overall date range from schedule (and slots if loaded).
        schedule_dates = sorted(d for d in df["_Date"].dropna().tolist() if isinstance(d, pydate))
        min_d = schedule_dates[0] if schedule_dates else pydate.today()
        max_d = schedule_dates[-1] if schedule_dates else pydate.today()
        if load_inputs and slot_dates:
            min_d = min(min_d, min(slot_dates))
            max_d = max(max_d, max(slot_dates))

        pick = st.date_input("Pick a day", value=min_d, min_value=min_d, max_value=max_d)

        day_matches = df[df["_Date"] == pick].copy()
        if not day_matches.empty:
            st.success(f"{len(day_matches)} match(es) scheduled on {pick}.")
            st.dataframe(day_matches.drop(columns=["_Date"]), use_container_width=True, height=420)
        else:
            reasons: List[str] = []
            if load_inputs:
                if pick in fifa_dates:
                    reasons.append("This is a **FIFA day** → league matches are forbidden.")
                if slot_dates and pick not in slot_dates:
                    reasons.append("No playable slots exist on this date in `expanded_calendar.xlsx` (outside slot universe).")
                if slot_dates and pick in slot_dates:
                    reasons.append(
                        f"There are **{int(slots_on_date_count.get(pick, 0))} slot row(s)** on this date, "
                        "but none are scheduled in this selected schedule."
                    )
            if not reasons:
                reasons.append("No matches are scheduled on this date in this selected schedule.")

            st.info("No matches on this day.")
            for r in reasons:
                st.write("- " + r)

        st.divider()
        st.markdown("**Month view (counts per day)**")
        month = st.selectbox("Month", options=list(range(1, 13)), index=pick.month - 1)
        year = st.number_input("Year", min_value=2000, max_value=2100, value=pick.year, step=1)

        # Count matches per date
        counts = df["_Date"].value_counts(dropna=True).to_dict()

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
                    if n:
                        label += f" • {n}"
                row[d.strftime("%a")] = label
            rows.append(row)

        cal_df = pd.DataFrame(rows, columns=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        st.dataframe(cal_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Month summary (what’s happening this month)**")

        month_start = pydate(int(year), int(month), 1)
        month_end = pydate(int(year), int(month), calendar.monthrange(int(year), int(month))[1])

        # Daily match counts for the chosen month
        month_counts = {d: int(n) for d, n in counts.items() if isinstance(d, pydate) and month_start <= d <= month_end}
        total_matches = int(sum(month_counts.values()))
        match_days = int(sum(1 for n in month_counts.values() if n > 0))

        fifa_in_month = []
        if load_inputs:
            fifa_in_month = [d for d in fifa_dates if month_start <= d <= month_end]

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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total matches", total_matches)
        c2.metric("Match-days", match_days)
        c3.metric("FIFA days", len(fifa_in_month) if load_inputs else 0)
        c4.metric("Slot-days w/ no matches", slot_days_with_no_matches if load_inputs and slot_dates else 0)

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

        st.markdown("**Solver limits (read-only in this UI)**")
        st.write(f"Baseline time limit: `{BASELINE_SOLVER_TIME_LIMIT_S}s`")
        st.write(f"Repair time limit: `{REPAIR_SOLVER_TIME_LIMIT_S}s`")

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
            # Import inside run to avoid heavy imports on mere browsing.
            from src.data_loader import load_data
            from src.fixture_generator import generate_drr
            from src.slot_domain import build_domains
            from src.baseline_solver import solve_baseline
            from src.caf_audit import caf_audit
            from src.caf_repair_solver import caf_repair
            from src.output_writer import (
                write_final_schedule,
                write_pre_caf_schedule,
                write_rescheduled_matches,
                write_unresolved,
                write_week_round_map,
            )

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
                    write_rescheduled_matches(repaired)
                    write_unresolved(unresolved)
                    write_week_round_map(accepted, repaired)

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

