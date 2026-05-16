"""Streamlit UI for the Egyptian Premier League schedule optimizer.

Goal: make the pipeline observable end-to-end (progress + artifacts) while
reusing the existing CLI-phase functions from `main.py` / `src/*`.
"""

from __future__ import annotations

import base64
import io
import html
import json
import os
import sys
import time
import calendar
from datetime import date as pydate
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import altair as alt
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
    MAX_MATCHES_PER_DAY,
    MAX_MATCHES_PER_SLOT,
    MIN_DAYS_BETWEEN_ROUNDS,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    MIN_STADIUM_SERVICE_GAP_DAYS,
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
ICON_PATH = Path("Nile_League.png")
ICONS_DIR = Path("icons")

TEAM_ICON_FILES = {
    "AHL": "egypt_al-ahly_512x512.football-logos.cc.png",
    "ZAM": "egypt_zamalek_512x512.football-logos.cc.png",
    "PYR": "egypt_pyramids_512x512.football-logos.cc.png",
    "MAS": "egypt_al-masry_512x512.football-logos.cc.png",
    "MOD": "egypt_modern-sport_512x512.football-logos.cc.png",
    "SMO": "egypt_smouha_700x700.football-logos.cc.png",
    "ZED": "egypt_zed-fc_512x512.football-logos.cc.png",
    "CER": "egypt_ceramica-cleopatra_700x700.football-logos.cc.png",
    "ENP": "egypt_enppi_512x512.football-logos.cc.png",
    "ITH": "egypt_al-ittihad-alexandria_512x512.football-logos.cc.png",
    "TLG": "egypt_talaea-el-gaish_512x512.football-logos.cc.png",
    "BNK": "egypt_national-bank_512x512.football-logos.cc.png",
    "PHA": "egypt_pharco_512x512.football-logos.cc.png",
    "GOU": "egypt_el-gouna_512x512.football-logos.cc.png",
    "ISM": "egypt_ismaily_512x512.football-logos.cc.png",
    "MAH": "egypt_ghazl-el-mahalla_512x512.football-logos.cc.png",
    "PET": "egypt_petrojet_512x512.football-logos.cc.png",
    "HAR": "egypt_haras-el-hodoud_700x700.football-logos.cc.png",
}

PALETTE = {
    "primary": "#68239e",
    "surface": "#f8f9f7",
    "muted": "#8f67ad",
    "ink": "#232126",
    "border": "#d2cad9",
    "accent": "#75409f",
    "soft": "#ab97ba",
}


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
                "MAX_MATCHES_PER_DAY",
                "Max matches per day",
                MAX_MATCHES_PER_DAY,
                1,
                12,
                1,
                "Hard cap on league matches assigned to one calendar date.",
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
            (
                "MIN_DAYS_BETWEEN_ROUNDS",
                "Min days between rounds",
                MIN_DAYS_BETWEEN_ROUNDS,
                0,
                7,
                1,
                "Minimum calendar-day separation between the last match of one non-postponed round and the first match of the next. Set to 1 to forbid same-day round overlap.",
            ),
            (
                "MIN_STADIUM_SERVICE_GAP_DAYS",
                "Stadium service gap (days)",
                MIN_STADIUM_SERVICE_GAP_DAYS,
                0,
                14,
                1,
                "If positive, non-forced matches may use alt stadiums to give home stadiums rest. Zero keeps the current fixed-venue behavior.",
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


VALIDATION_DASHBOARD_PATHS = {
    "schedule": os.path.join(OUTPUT_DIR, "optimized_schedule.csv"),
    "week_round_map": os.path.join(OUTPUT_DIR, "week_round_map.csv"),
    "caf_queue": os.path.join(OUTPUT_DIR, "caf_postponement_queue.csv"),
    "caf_rescheduled": os.path.join(OUTPUT_DIR, "caf_rescheduled_matches.csv"),
    "caf_unresolved": os.path.join(OUTPUT_DIR, "unresolved_caf_postponements.csv"),
    "round_windows": os.path.join(PHASES_DIR, "03_round_windows.csv"),
    "home_away_patterns": os.path.join(PHASES_DIR, "04_home_away_patterns.csv"),
    "baseline_feasible_slots": os.path.join(PHASES_DIR, "05_baseline_feasible_slot_counts.csv"),
    "baseline_solver_status": os.path.join(PHASES_DIR, "06_baseline_solver_status.json"),
    "caf_audit": os.path.join(PHASES_DIR, "07_caf_audit.csv"),
    "repair_solver_status": os.path.join(PHASES_DIR, "09_repair_solver_status.json"),
    "final_validation": os.path.join(PHASES_DIR, "10_final_validation_report.csv"),
    "team_sequence_validation": os.path.join(PHASES_DIR, "10_team_sequence_validation.csv"),
}


def _file_mtime(path: str) -> Optional[float]:
    if not os.path.exists(path):
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _read_csv_cached(path: str, mtime: Optional[float]) -> Optional[pd.DataFrame]:
    if mtime is None:
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        try:
            return pd.read_csv(path, dtype=str)
        except Exception:
            return None


@st.cache_data(show_spinner=False)
def _read_json_cached(path: str, mtime: Optional[float]) -> Optional[dict]:
    if mtime is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_if_exists(path: str) -> Optional[pd.DataFrame]:
    return _read_csv_cached(path, _file_mtime(path))


def _read_json_if_exists(path: str) -> Optional[dict]:
    return _read_json_cached(path, _file_mtime(path))


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


def _page_icon() -> Optional[str]:
    return str(ICON_PATH) if ICON_PATH.exists() else None


def _team_icon_path(team_id: object) -> Optional[Path]:
    fname = TEAM_ICON_FILES.get(str(team_id).strip().upper())
    if not fname:
        return None
    path = ICONS_DIR / fname
    return path if path.exists() else None


@st.cache_data(show_spinner=False)
def _team_icon_data_uri(team_id: str) -> str:
    path = _team_icon_path(team_id)
    if path is None:
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _team_badge_html(team_id: object, *, size: int = 26) -> str:
    raw_tid = str(team_id).strip().upper() or "TBD"
    tid = html.escape(raw_tid)
    src = _team_icon_data_uri(raw_tid)
    if not src:
        return f"<span class=\"team-fallback-mark\">{tid[:3]}</span><span>{tid}</span>"
    return (
        f"<img class=\"team-inline-logo\" src=\"{src}\" alt=\"{tid}\" "
        f"style=\"width:{size}px;height:{size}px;\" />"
        f"<span>{tid}</span>"
    )


def _render_team_logo(team_id: object, caption: str = "") -> None:
    path = _team_icon_path(team_id)
    if path is None:
        st.caption(caption or str(team_id))
        return
    st.image(path.as_posix(), width=96)
    if caption:
        st.caption(caption)


def _render_theme() -> None:
    st.markdown(
        f"""
<style>
:root {{
  --nile-primary: {PALETTE["primary"]};
  --nile-surface: {PALETTE["ink"]};
  --nile-surface-raised: rgba(210, 202, 217, 0.08);
  --nile-surface-strong: rgba(171, 151, 186, 0.16);
  --nile-text: {PALETTE["surface"]};
  --nile-muted: {PALETTE["muted"]};
  --nile-ink: {PALETTE["ink"]};
  --nile-border: {PALETTE["border"]};
  --nile-accent: {PALETTE["accent"]};
  --nile-soft: {PALETTE["soft"]};
}}

.stApp {{
  background: var(--nile-surface);
  color: var(--nile-text);
}}

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #2f2934 0%, var(--nile-ink) 72%);
  border-right: 1px solid rgba(210, 202, 217, 0.24);
}}

[data-testid="stSidebar"] * {{
  color: var(--nile-text);
}}

h1, h2, h3, h4, h5, h6 {{
  color: var(--nile-text);
  letter-spacing: 0;
}}

p, li, label, span, div {{
  letter-spacing: 0;
}}

[data-testid="stCaptionContainer"], .stMarkdown small {{
  color: var(--nile-soft);
}}

div[data-testid="stMetric"] {{
  background: var(--nile-surface-raised);
  border: 1px solid rgba(210, 202, 217, 0.22);
  border-radius: 8px;
  padding: 12px;
}}

div[data-testid="stMetric"] label,
div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
  color: var(--nile-text);
}}

.stButton > button,
.stDownloadButton > button {{
  background: var(--nile-primary);
  border: 1px solid var(--nile-primary);
  border-radius: 8px;
  color: var(--nile-text);
  font-weight: 700;
}}

.stButton > button:hover,
.stDownloadButton > button:hover {{
  background: var(--nile-accent);
  border-color: var(--nile-accent);
  color: var(--nile-text);
}}

.stButton > button:focus,
.stDownloadButton > button:focus,
button:focus-visible,
input:focus,
textarea:focus {{
  border-color: var(--nile-primary) !important;
  box-shadow: 0 0 0 0.12rem rgba(104, 35, 158, 0.22) !important;
}}

[data-baseweb="tab-list"] {{
  gap: 6px;
  border-bottom: 1px solid rgba(210, 202, 217, 0.20);
}}

[data-baseweb="tab"] {{
  background: transparent !important;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  color: var(--nile-soft);
  padding-bottom: 10px;
}}

[aria-selected="true"][data-baseweb="tab"] {{
  background: transparent !important;
  border-bottom-color: var(--nile-soft);
  color: var(--nile-text);
}}

[data-baseweb="tab-highlight"] {{
  background-color: var(--nile-soft);
  height: 2px;
}}

div[data-testid="stDataFrame"] {{
  border: 1px solid rgba(210, 202, 217, 0.24);
  border-radius: 8px;
  overflow: hidden;
}}

[data-testid="stExpander"],
[data-testid="stStatus"],
[data-testid="stAlert"] {{
  background: var(--nile-surface-raised);
  border-color: rgba(210, 202, 217, 0.24);
  color: var(--nile-text);
}}

[data-testid="stNotification"],
[data-testid="stToast"] {{
  background: #2f2934;
  color: var(--nile-text);
  border: 1px solid rgba(210, 202, 217, 0.24);
}}

code {{
  background: rgba(210, 202, 217, 0.14);
  color: var(--nile-text);
  border-radius: 6px;
}}

.team-inline-logo {{
  display: inline-block;
  object-fit: contain;
  vertical-align: middle;
  margin-right: 7px;
}}

.team-fallback-mark {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(210, 202, 217, 0.18);
  color: var(--nile-text);
  font-size: 0.68rem;
  font-weight: 800;
  margin-right: 7px;
  vertical-align: middle;
}}

hr {{
  border-color: rgba(210, 202, 217, 0.20);
}}

input, textarea, [data-baseweb="select"] > div, [data-baseweb="input"] > div {{
  background-color: #2f2934 !important;
  color: var(--nile-text) !important;
  border-color: rgba(210, 202, 217, 0.28) !important;
}}

[data-baseweb="popover"], [data-baseweb="menu"] {{
  background-color: #2f2934 !important;
  color: var(--nile-text) !important;
}}

.nile-title {{
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 4px;
}}

.nile-title-mark {{
  width: 54px;
  height: 54px;
  border-radius: 8px;
  object-fit: contain;
  background: {PALETTE["surface"]};
  border: 1px solid rgba(210, 202, 217, 0.24);
}}
</style>
""",
        unsafe_allow_html=True,
    )


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
    with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
        result = fn()
    elapsed = time.time() - start
    log_box.code(log_buffer.getvalue(), language="text")
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


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y"})


def _parse_week_list(value: object) -> List[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []

    weeks: List[int] = []
    for raw_part in str(value).split(";"):
        part = raw_part.strip()
        if not part:
            continue
        try:
            weeks.append(int(part))
        except ValueError:
            continue
    return weeks


def _week_span_label(span_count: int) -> str:
    if span_count <= 1:
        return "1 week"
    if span_count == 2:
        return "2 weeks"
    return "3+ weeks"


def _validation_issue_family(check: object) -> str:
    normalized = str(check or "").strip().upper()
    if normalized == "FIFA_DATE":
        return "FIFA"
    if normalized == "CAF_BUFFER":
        return "CAF"
    if normalized == "TEAM_REST":
        return "Rest"
    if normalized == "TEAM_HOME_AWAY_STREAK":
        return "Streak"
    if normalized == "TEAM_ROLLING5_BALANCE":
        return "Rolling 5"
    if normalized in {"TEAM_ROUND_ORDER", "GLOBAL_ROUND_ORDER"}:
        return "Round order"
    if normalized in {"FIXTURE_COUNT", "ORDERED_PAIR_COUNT"}:
        return "Completeness"
    if normalized == "UNRESOLVED_POSTPONEMENTS":
        return "Unresolved queue"
    if normalized == "DAILY_MATCH_CAP":
        return "Daily load"
    if normalized in {"VENUE_SLOT_CONFLICT", "STADIUM_SERVICE_GAP"}:
        return "Venue / stadium"
    return "Other"


def _validation_issue_rows(validation_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if validation_df is None:
        return None
    if validation_df.empty:
        return validation_df.copy()

    normalized = validation_df.copy()
    severity = normalized.get("Severity", pd.Series("", index=normalized.index)).astype(str).str.upper()
    check = normalized.get("Check", pd.Series("", index=normalized.index)).astype(str).str.upper()
    mask = ~((severity == "PASS") & (check == "ALL"))
    return normalized.loc[mask].copy()


def _solver_status_label(status: Optional[dict]) -> str:
    if not status:
        return "Missing"
    if status.get("skipped"):
        return "Skipped"
    return str(status.get("status_name") or status.get("status") or "Unknown")


def _format_wall_time(status: Optional[dict]) -> str:
    if not status:
        return "n/a"
    wall_time = status.get("wall_time_s")
    if wall_time is None:
        wall_time = status.get("elapsed_s")
    if wall_time is None:
        return "n/a"
    try:
        return f"{float(wall_time):,.1f}s"
    except (TypeError, ValueError):
        return str(wall_time)


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _dashboard_file_labels() -> Dict[str, str]:
    return {
        "schedule": "output/optimized_schedule.csv",
        "week_round_map": "output/week_round_map.csv",
        "caf_queue": "output/caf_postponement_queue.csv",
        "caf_rescheduled": "output/caf_rescheduled_matches.csv",
        "caf_unresolved": "output/unresolved_caf_postponements.csv",
        "round_windows": "output/phases/03_round_windows.csv",
        "home_away_patterns": "output/phases/04_home_away_patterns.csv",
        "baseline_feasible_slots": "output/phases/05_baseline_feasible_slot_counts.csv",
        "baseline_solver_status": "output/phases/06_baseline_solver_status.json",
        "caf_audit": "output/phases/07_caf_audit.csv",
        "repair_solver_status": "output/phases/09_repair_solver_status.json",
        "final_validation": "output/phases/10_final_validation_report.csv",
        "team_sequence_validation": "output/phases/10_team_sequence_validation.csv",
    }


def _missing_dashboard_files(available: Dict[str, bool], keys: Iterable[str]) -> List[str]:
    labels = _dashboard_file_labels()
    return [labels[key] for key in keys if not available.get(key, False)]


def _load_validation_dashboard_inputs() -> Dict[str, Any]:
    available = {key: os.path.exists(path) for key, path in VALIDATION_DASHBOARD_PATHS.items()}

    schedule = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["schedule"])
    if schedule is not None:
        schedule = schedule.copy()
        if "Date" in schedule.columns:
            schedule["_Date"] = _try_parse_date_series(schedule["Date"])
        else:
            schedule["_Date"] = pd.Series(dtype="object")
        if "Date_time" in schedule.columns:
            schedule["_DateTime"] = pd.to_datetime(schedule["Date_time"], errors="coerce")
        else:
            schedule["_DateTime"] = pd.Series(dtype="datetime64[ns]")
        if "Round" in schedule.columns:
            schedule["Round"] = pd.to_numeric(schedule["Round"], errors="coerce").astype("Int64")
        if "Travel_km" in schedule.columns:
            schedule["Travel_km"] = pd.to_numeric(schedule["Travel_km"], errors="coerce").fillna(0.0)
        if "Postponed" in schedule.columns:
            schedule["Postponed"] = _coerce_bool_series(schedule["Postponed"])
        else:
            schedule["Postponed"] = False

    week_round_map = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["week_round_map"])
    if week_round_map is not None:
        week_round_map = week_round_map.copy()
        if "Round" in week_round_map.columns:
            week_round_map["Round"] = pd.to_numeric(week_round_map["Round"], errors="coerce").astype("Int64")
        if "Match_Count" in week_round_map.columns:
            week_round_map["Match_Count"] = pd.to_numeric(week_round_map["Match_Count"], errors="coerce")
        if "Calendar_Weeks" in week_round_map.columns:
            week_round_map["_Week_List"] = week_round_map["Calendar_Weeks"].apply(_parse_week_list)
        else:
            week_round_map["_Week_List"] = [[] for _ in range(len(week_round_map))]
        week_round_map["Week_Span_Count"] = week_round_map["_Week_List"].apply(len)
        week_round_map["Week_Span_Band"] = week_round_map["Week_Span_Count"].apply(_week_span_label)

    final_validation = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["final_validation"])
    if final_validation is not None:
        final_validation = final_validation.copy()
        if "Date" in final_validation.columns:
            final_validation["_Date"] = _try_parse_date_series(final_validation["Date"])
        else:
            final_validation["_Date"] = pd.Series(dtype="object")
        if "Round" in final_validation.columns:
            final_validation["Round"] = pd.to_numeric(final_validation["Round"], errors="coerce").astype("Int64")
        if "Severity" in final_validation.columns:
            final_validation["Severity"] = final_validation["Severity"].astype(str).str.upper()
        if "Check" in final_validation.columns:
            final_validation["Check"] = final_validation["Check"].astype(str).str.upper()

    team_sequence = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["team_sequence_validation"])
    if team_sequence is not None:
        team_sequence = team_sequence.copy()
        if "Date" in team_sequence.columns:
            team_sequence["_Date"] = _try_parse_date_series(team_sequence["Date"])
        else:
            team_sequence["_Date"] = pd.Series(dtype="object")
        if "Date_time" in team_sequence.columns:
            team_sequence["_DateTime"] = pd.to_datetime(team_sequence["Date_time"], errors="coerce")
        else:
            team_sequence["_DateTime"] = pd.Series(dtype="datetime64[ns]")
        for numeric_col in [
            "Sequence_Index",
            "Round",
            "Gap_Days_From_Previous",
            "Streak_Length",
            "Rolling5_Home_Count",
        ]:
            if numeric_col in team_sequence.columns:
                team_sequence[numeric_col] = pd.to_numeric(team_sequence[numeric_col], errors="coerce")
        for bool_col in [
            "Postponed",
            "Streak_Violation",
            "Rolling5_Balance_Violation",
            "Round_Inversion",
        ]:
            if bool_col in team_sequence.columns:
                team_sequence[bool_col] = _coerce_bool_series(team_sequence[bool_col])

    feasible_slots = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["baseline_feasible_slots"])
    if feasible_slots is not None:
        feasible_slots = feasible_slots.copy()
        for numeric_col in ["match_idx", "round", "round_window_slot_count", "feasible_slot_count"]:
            if numeric_col in feasible_slots.columns:
                feasible_slots[numeric_col] = pd.to_numeric(feasible_slots[numeric_col], errors="coerce")
        for date_col in ["round_window_start", "round_window_end"]:
            if date_col in feasible_slots.columns:
                feasible_slots[date_col] = _try_parse_date_series(feasible_slots[date_col])
        if "caf_filter_relaxed_for_repair" in feasible_slots.columns:
            feasible_slots["caf_filter_relaxed_for_repair"] = _coerce_bool_series(
                feasible_slots["caf_filter_relaxed_for_repair"]
            )

    caf_audit = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["caf_audit"])
    if caf_audit is not None:
        caf_audit = caf_audit.copy()
        if "round" in caf_audit.columns:
            caf_audit["round"] = pd.to_numeric(caf_audit["round"], errors="coerce")
        for date_col in ["date", "Conflicting_CAF_Date"]:
            if date_col in caf_audit.columns:
                caf_audit[date_col] = _try_parse_date_series(caf_audit[date_col])
        if "caf_violated" in caf_audit.columns:
            caf_audit["caf_violated"] = _coerce_bool_series(caf_audit["caf_violated"])
        if "Repair_Feasible_Slot_Count" in caf_audit.columns:
            caf_audit["Repair_Feasible_Slot_Count"] = pd.to_numeric(
                caf_audit["Repair_Feasible_Slot_Count"], errors="coerce"
            )

    home_away_patterns = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["home_away_patterns"])
    if home_away_patterns is not None:
        home_away_patterns = home_away_patterns.copy()
        for numeric_col in [
            "Home_Count",
            "Away_Count",
            "Max_Home_Streak",
            "Max_Away_Streak",
            "Rolling5_Balance_Violations",
        ]:
            if numeric_col in home_away_patterns.columns:
                home_away_patterns[numeric_col] = pd.to_numeric(home_away_patterns[numeric_col], errors="coerce")

    round_windows = _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["round_windows"])
    if round_windows is not None:
        round_windows = round_windows.copy()
        if "Round" in round_windows.columns:
            round_windows["Round"] = pd.to_numeric(round_windows["Round"], errors="coerce")

    return {
        "available": available,
        "schedule": schedule,
        "week_round_map": week_round_map,
        "final_validation": final_validation,
        "team_sequence": team_sequence,
        "feasible_slots": feasible_slots,
        "caf_audit": caf_audit,
        "home_away_patterns": home_away_patterns,
        "caf_queue": _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["caf_queue"]),
        "caf_rescheduled": _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["caf_rescheduled"]),
        "caf_unresolved": _read_csv_if_exists(VALIDATION_DASHBOARD_PATHS["caf_unresolved"]),
        "round_windows": round_windows,
        "baseline_solver_status": _read_json_if_exists(VALIDATION_DASHBOARD_PATHS["baseline_solver_status"]),
        "repair_solver_status": _read_json_if_exists(VALIDATION_DASHBOARD_PATHS["repair_solver_status"]),
    }


def _build_constraint_counts(validation_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    issues = _validation_issue_rows(validation_df)
    if issues is None or issues.empty:
        return pd.DataFrame(columns=["Family", "Count"])

    counts = (
        issues.assign(Family=issues["Check"].apply(_validation_issue_family))
        .groupby("Family", as_index=False)
        .size()
        .rename(columns={"size": "Count"})
        .sort_values(["Count", "Family"], ascending=[False, True])
    )
    return counts.reset_index(drop=True)


def _build_rest_gap_summary(team_sequence_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    empty = {
        "histogram": pd.DataFrame(columns=["Gap_Days_From_Previous", "Matches"]),
        "by_team": pd.DataFrame(
            columns=["Team_ID", "Min_Gap_Days", "Max_Gap_Days", "Avg_Gap_Days", "Matches_With_Gap"]
        ),
        "min_gap": None,
        "median_gap": None,
        "max_gap": None,
        "long_gap_count": 0,
    }
    if team_sequence_df is None or "Gap_Days_From_Previous" not in team_sequence_df.columns:
        return empty

    gaps = team_sequence_df[["Team_ID", "Gap_Days_From_Previous"]].copy()
    gaps["Gap_Days_From_Previous"] = pd.to_numeric(gaps["Gap_Days_From_Previous"], errors="coerce")
    gaps = gaps.dropna(subset=["Gap_Days_From_Previous"])
    if gaps.empty:
        return empty

    histogram = (
        gaps.groupby("Gap_Days_From_Previous", as_index=False)
        .size()
        .rename(columns={"size": "Matches"})
        .sort_values("Gap_Days_From_Previous")
    )
    by_team = (
        gaps.groupby("Team_ID", as_index=False)
        .agg(
            Min_Gap_Days=("Gap_Days_From_Previous", "min"),
            Max_Gap_Days=("Gap_Days_From_Previous", "max"),
            Avg_Gap_Days=("Gap_Days_From_Previous", "mean"),
            Matches_With_Gap=("Gap_Days_From_Previous", "size"),
        )
        .sort_values(["Max_Gap_Days", "Team_ID"], ascending=[False, True])
        .reset_index(drop=True)
    )
    by_team["Avg_Gap_Days"] = by_team["Avg_Gap_Days"].round(1)

    values = gaps["Gap_Days_From_Previous"]
    return {
        "histogram": histogram,
        "by_team": by_team,
        "min_gap": float(values.min()),
        "median_gap": float(values.median()),
        "max_gap": float(values.max()),
        "long_gap_count": int((values >= 14).sum()),
    }


def _build_feasibility_pressure(feasible_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    empty = {
        "histogram": pd.DataFrame(columns=["Feasible_Slots", "Matches"]),
        "tightest_matches": pd.DataFrame(),
        "round_average": pd.DataFrame(columns=["round", "Avg_Feasible_Slots"]),
        "min_slots": None,
        "median_slots": None,
        "max_slots": None,
        "tight_25": 0,
        "tight_50": 0,
        "tight_100": 0,
    }
    if feasible_df is None or "feasible_slot_count" not in feasible_df.columns:
        return empty

    pressure = feasible_df.copy()
    pressure["feasible_slot_count"] = pd.to_numeric(pressure["feasible_slot_count"], errors="coerce")
    pressure = pressure.dropna(subset=["feasible_slot_count"])
    if pressure.empty:
        return empty

    counts = pressure["feasible_slot_count"]
    histogram = (
        counts.astype(int)
        .value_counts()
        .sort_index()
        .rename_axis("Feasible_Slots")
        .reset_index(name="Matches")
    )
    tightest_columns = [
        col for col in ["match_idx", "round", "home", "away", "feasible_slot_count", "round_window_start", "round_window_end"]
        if col in pressure.columns
    ]
    tightest_matches = (
        pressure.sort_values(["feasible_slot_count", "round", "match_idx"], na_position="last")[tightest_columns]
        .head(15)
        .reset_index(drop=True)
    )
    round_average = pd.DataFrame(columns=["round", "Avg_Feasible_Slots"])
    if "round" in pressure.columns:
        round_average = (
            pressure.groupby("round", as_index=False)
            .agg(Avg_Feasible_Slots=("feasible_slot_count", "mean"))
            .sort_values("round")
        )
        round_average["Avg_Feasible_Slots"] = round_average["Avg_Feasible_Slots"].round(1)

    return {
        "histogram": histogram,
        "tightest_matches": tightest_matches,
        "round_average": round_average,
        "min_slots": float(counts.min()),
        "median_slots": float(counts.median()),
        "max_slots": float(counts.max()),
        "tight_25": int((counts <= 25).sum()),
        "tight_50": int((counts <= 50).sum()),
        "tight_100": int((counts <= 100).sum()),
    }


def _build_round_span_summary(week_round_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    empty = {
        "details": pd.DataFrame(columns=["Round", "Calendar_Weeks", "Match_Count", "Week_Span_Count", "Week_Span_Band"]),
        "band_counts": pd.DataFrame(columns=["Week_Span_Band", "Rounds"]),
        "multi_week_rounds": 0,
        "one_week_rounds": 0,
        "two_week_rounds": 0,
        "three_plus_rounds": 0,
        "max_span": None,
    }
    if week_round_df is None or "Week_Span_Count" not in week_round_df.columns:
        return empty

    details = week_round_df[
        [col for col in ["Round", "Calendar_Weeks", "Match_Count", "Week_Span_Count", "Week_Span_Band"] if col in week_round_df.columns]
    ].copy()
    if "Round" in details.columns:
        details = details.sort_values("Round")

    band_counts = (
        details.groupby("Week_Span_Band", as_index=False)
        .size()
        .rename(columns={"size": "Rounds"})
    )
    if not band_counts.empty:
        band_counts["Week_Span_Band"] = pd.Categorical(
            band_counts["Week_Span_Band"],
            categories=["1 week", "2 weeks", "3+ weeks"],
            ordered=True,
        )
        band_counts = band_counts.sort_values("Week_Span_Band").reset_index(drop=True)

    spans = pd.to_numeric(details.get("Week_Span_Count", pd.Series(dtype=float)), errors="coerce").dropna()
    if spans.empty:
        return empty

    return {
        "details": details.reset_index(drop=True),
        "band_counts": band_counts,
        "multi_week_rounds": int((spans > 1).sum()),
        "one_week_rounds": int((spans == 1).sum()),
        "two_week_rounds": int((spans == 2).sum()),
        "three_plus_rounds": int((spans >= 3).sum()),
        "max_span": int(spans.max()),
    }


def _build_venue_load_summary(schedule_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if schedule_df is None or "Venue_Stadium_ID" not in schedule_df.columns or schedule_df.empty:
        return pd.DataFrame(columns=["Venue_Stadium_ID", "Matches", "Share"])

    total_matches = len(schedule_df)
    venue_load = (
        schedule_df.groupby("Venue_Stadium_ID", as_index=False)
        .size()
        .rename(columns={"size": "Matches"})
        .sort_values(["Matches", "Venue_Stadium_ID"], ascending=[False, True])
        .reset_index(drop=True)
    )
    venue_load["Share"] = venue_load["Matches"] / total_matches
    return venue_load


def _build_monthly_match_volume(schedule_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if schedule_df is None or "_Date" not in schedule_df.columns or schedule_df.empty:
        return pd.DataFrame(columns=["Month", "Matches"])

    dates = pd.to_datetime(schedule_df["_Date"], errors="coerce")
    monthly = (
        pd.DataFrame({"Month": dates.dt.to_period("M"), "Matches": 1})
        .dropna(subset=["Month"])
        .groupby("Month", as_index=False)
        .agg(Matches=("Matches", "sum"))
    )
    if monthly.empty:
        return pd.DataFrame(columns=["Month", "Matches"])

    monthly["Month"] = monthly["Month"].astype(str)
    return monthly.sort_values("Month").reset_index(drop=True)


def _build_validation_badge_rows(
    validation_df: Optional[pd.DataFrame],
    unresolved_count: int,
) -> pd.DataFrame:
    issues = _validation_issue_rows(validation_df)
    checks = pd.Series(dtype=str) if issues is None or issues.empty else issues["Check"].astype(str).str.upper()

    rows: List[Dict[str, Any]] = []
    family_checks = [
        ("FIFA", {"FIFA_DATE"}),
        ("CAF", {"CAF_BUFFER"}),
        ("Rest", {"TEAM_REST"}),
        ("Streak", {"TEAM_HOME_AWAY_STREAK"}),
        ("Completeness", {"FIXTURE_COUNT", "ORDERED_PAIR_COUNT"}),
    ]
    for family, family_check_set in family_checks:
        count = int(checks.isin(family_check_set).sum()) if not checks.empty else 0
        rows.append(
            {
                "Family": family,
                "Status": "PASS" if count == 0 else "ISSUE",
                "Findings": count,
            }
        )

    rows.append(
        {
            "Family": "Unresolved queue",
            "Status": "CLEAR" if unresolved_count == 0 else "OPEN",
            "Findings": unresolved_count,
        }
    )
    return pd.DataFrame(rows)


def _selected_values_from_altair_event(
    event: Any,
    *,
    selection_name: str,
    field_name: str,
) -> List[str]:
    def _normalize_values(value: Any) -> List[str]:
        if value in (None, "", [], {}):
            return []
        if isinstance(value, dict):
            if field_name in value:
                return _normalize_values(value[field_name])
            if "value" in value:
                return _normalize_values(value["value"])
            if "values" in value:
                return _normalize_values(value["values"])
            normalized: List[str] = []
            for nested in value.values():
                normalized.extend(_normalize_values(nested))
            return normalized
        if isinstance(value, (list, tuple, set)):
            normalized = []
            for item in value:
                normalized.extend(_normalize_values(item))
            return normalized
        return [str(value)]

    if event is None:
        return []

    selection_state = getattr(event, "selection", None)
    if not selection_state:
        return []

    selected = selection_state.get(selection_name, {})
    if not selected:
        return []

    values = _normalize_values(selected)
    deduped: List[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _render_clickable_bar_chart(
    chart_df: pd.DataFrame,
    *,
    x_field: str,
    y_field: str,
    selection_field: Optional[str] = None,
    key: str,
    x_title: Optional[str] = None,
    y_title: Optional[str] = None,
    sort: Any = None,
    tooltip_fields: Optional[List[str]] = None,
    height: int = 320,
) -> List[str]:
    if chart_df.empty:
        return []

    selection_field = selection_field or x_field
    selection_name = f"{key}_selection"
    selector = alt.selection_point(name=selection_name, fields=[selection_field])

    tooltip = tooltip_fields or [x_field, y_field]
    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                f"{x_field}:N",
                title=x_title,
                sort=sort,
                axis=alt.Axis(labelAngle=-35, labelLimit=160),
            ),
            y=alt.Y(f"{y_field}:Q", title=y_title),
            color=alt.condition(selector, alt.value(PALETTE["accent"]), alt.value(PALETTE["primary"])),
            tooltip=tooltip,
        )
        .add_params(selector)
        .properties(height=height)
    )

    event = st.altair_chart(
        chart,
        width="stretch",
        key=key,
        on_select="rerun",
        selection_mode=selection_name,
    )
    st.caption("Click a bar to inspect the underlying rows. Shift-click keeps multiple selections.")
    return _selected_values_from_altair_event(
        event,
        selection_name=selection_name,
        field_name=selection_field,
    )


def _render_selected_detail_rows(
    detail_df: pd.DataFrame,
    *,
    filter_field: str,
    selected_values: List[str],
    empty_message: str,
    detail_name: str,
    display_columns: Optional[List[str]] = None,
    height: int = 260,
) -> None:
    if not selected_values:
        st.caption(empty_message)
        return

    filtered = detail_df.loc[detail_df[filter_field].astype(str).isin(selected_values)].copy()
    st.caption(
        f"{detail_name}: showing {len(filtered)} row(s) for selection {', '.join(selected_values[:6])}."
    )
    if filtered.empty:
        st.info("No source rows matched the current chart selection.")
        return

    visible = filtered if not display_columns else filtered[[col for col in display_columns if col in filtered.columns]]
    st.dataframe(visible, use_container_width=True, hide_index=True, height=height)


def _render_validation_dashboard() -> None:
    st.subheader("Validate & Insights")
    st.caption(
        "Read-only validation dashboard over the current artifacts in `output/` and `output/phases/`."
    )

    dashboard_data = _load_validation_dashboard_inputs()
    schedule = dashboard_data["schedule"]

    if schedule is None:
        st.warning(
            "`output/optimized_schedule.csv` is missing. "
            "Schedule-based views will be partial, but other validation artifacts can still be inspected."
        )

    overview_tab, compliance_tab, feasibility_tab, caf_tab, fairness_tab = st.tabs(
        [
            "Overview",
            "Constraint Compliance",
            "Feasibility & Solver Pressure",
            "CAF & Repair",
            "Fairness & Operational Insights",
        ]
    )

    with overview_tab:
        _render_validation_overview(dashboard_data)

    with compliance_tab:
        _render_constraint_compliance(dashboard_data)

    with feasibility_tab:
        _render_feasibility_pressure(dashboard_data)

    with caf_tab:
        _render_caf_repair_dashboard(dashboard_data)

    with fairness_tab:
        _render_fairness_insights(dashboard_data)


def _render_validation_overview(dashboard_data: Dict[str, Any]) -> None:
    required_keys = [
        "schedule",
        "final_validation",
        "baseline_solver_status",
        "repair_solver_status",
        "week_round_map",
    ]
    missing = _missing_dashboard_files(dashboard_data["available"], required_keys)
    if missing:
        st.info("Overview is partially populated because some artifacts are missing: " + ", ".join(missing))

    schedule = dashboard_data["schedule"]
    validation_df = dashboard_data["final_validation"]
    baseline_status = dashboard_data["baseline_solver_status"]
    repair_status = dashboard_data["repair_solver_status"]
    unresolved_df = dashboard_data["caf_unresolved"]
    rest_gap_summary = _build_rest_gap_summary(dashboard_data["team_sequence"])
    round_span_summary = _build_round_span_summary(dashboard_data["week_round_map"])
    monthly_volume = _build_monthly_match_volume(schedule)

    issue_rows = _validation_issue_rows(validation_df)
    issue_count = 0 if issue_rows is None else len(issue_rows)
    postponed_count = 0
    total_matches = 0
    team_count = 0
    round_count = 0
    season_dates: List[pydate] = []
    if schedule is not None:
        postponed_count = int(schedule["Postponed"].sum()) if "Postponed" in schedule.columns else 0
        total_matches = len(schedule)
        if "Home_Team_ID" in schedule.columns and "Away_Team_ID" in schedule.columns:
            team_count = int(
                pd.unique(
                    pd.concat(
                        [
                            schedule["Home_Team_ID"].astype(str),
                            schedule["Away_Team_ID"].astype(str),
                        ],
                        ignore_index=True,
                    )
                ).size
            )
        if "Round" in schedule.columns:
            round_count = int(pd.to_numeric(schedule["Round"], errors="coerce").dropna().nunique())
        season_dates = sorted(d for d in schedule["_Date"].dropna().tolist() if isinstance(d, pydate))
    season_start = season_dates[0] if season_dates else None
    season_end = season_dates[-1] if season_dates else None
    repaired_count = len(dashboard_data["caf_rescheduled"]) if dashboard_data["caf_rescheduled"] is not None else 0
    unresolved_count = len(unresolved_df) if unresolved_df is not None else 0
    if validation_df is None:
        validation_status = "Missing"
    elif issue_count == 0:
        validation_status = "PASS"
    else:
        validation_status = f"{issue_count} issues"

    row1 = st.columns(6)
    row1[0].metric("Total matches", f"{total_matches:,}")
    row1[1].metric("Teams", f"{team_count:,}")
    row1[2].metric("Rounds", f"{round_count:,}")
    row1[3].metric("Season start", season_start.isoformat() if season_start else "n/a")
    row1[4].metric("Season end", season_end.isoformat() if season_end else "n/a")
    row1[5].metric("Validation", validation_status)

    row2 = st.columns(6)
    row2[0].metric("Baseline solver", _solver_status_label(baseline_status), _format_wall_time(baseline_status))
    row2[1].metric("CAF repair", _solver_status_label(repair_status), _format_wall_time(repair_status))
    row2[2].metric("Repaired matches", f"{repaired_count:,}")
    row2[3].metric("Unresolved matches", f"{unresolved_count:,}")
    row2[4].metric("Postponed matches", f"{postponed_count:,}")
    row2[5].metric("Rounds > 1 week", f"{round_span_summary['multi_week_rounds']:,}")

    if repair_status and repair_status.get("skipped"):
        st.caption("CAF repair skipped reason: " + str(repair_status.get("reason") or "n/a"))

    st.divider()
    chart_col, badge_col = st.columns([1.4, 1.0])
    with chart_col:
        st.markdown("**Season timeline density by month**")
        if monthly_volume.empty:
            st.info("No schedule dates were available for monthly density.")
        else:
            selected_months = _render_clickable_bar_chart(
                monthly_volume,
                x_field="Month",
                y_field="Matches",
                key="validation_overview_monthly_volume",
                x_title="Month",
                y_title="Matches",
                tooltip_fields=["Month", "Matches"],
                height=280,
            )
            if schedule is not None:
                month_detail = schedule.copy()
                month_detail["Month"] = pd.to_datetime(month_detail["_Date"], errors="coerce").dt.to_period("M").astype(str)
                _render_selected_detail_rows(
                    month_detail,
                    filter_field="Month",
                    selected_values=selected_months,
                    empty_message="Click a month bar to see the exact scheduled matches in that month.",
                    detail_name="Monthly schedule details",
                    display_columns=[
                        "Month",
                        "Round",
                        "Date",
                        "Date_time",
                        "Home_Team_ID",
                        "Away_Team_ID",
                        "Venue_Stadium_ID",
                        "Postponed",
                    ],
                    height=220,
                )

    with badge_col:
        st.markdown("**Validation badge table**")
        badge_rows = _build_validation_badge_rows(validation_df, unresolved_count)
        st.dataframe(badge_rows, use_container_width=True, hide_index=True)

    if validation_df is None:
        st.warning("Final validation report is missing, so hard-rule status cannot be confirmed here.")
    elif issue_count == 0:
        signals: List[str] = []
        max_gap = rest_gap_summary["max_gap"]
        if max_gap is not None and max_gap >= 14:
            signals.append(f"longest team rest gap is {int(max_gap)} days")
        if round_span_summary["multi_week_rounds"] > 0:
            signals.append(
                f"{round_span_summary['multi_week_rounds']} rounds span more than one week"
            )
        if signals:
            st.info("Validation is clean, but the calendar still shows pressure: " + "; ".join(signals) + ".")
        else:
            st.success("Validation is clean and no major pressure signals surfaced in the overview.")
    else:
        st.warning(f"Validation report contains {issue_count} finding(s). Use the compliance tab for detail.")


def _render_constraint_compliance(dashboard_data: Dict[str, Any]) -> None:
    required_keys = ["final_validation", "team_sequence_validation", "caf_audit"]
    missing = _missing_dashboard_files(dashboard_data["available"], required_keys)
    if missing:
        st.info("Constraint compliance is partial because some artifacts are missing: " + ", ".join(missing))

    validation_df = dashboard_data["final_validation"]
    team_sequence = dashboard_data["team_sequence"]
    caf_audit = dashboard_data["caf_audit"]
    issue_rows = _validation_issue_rows(validation_df)
    constraint_counts = _build_constraint_counts(validation_df)
    rest_gap_summary = _build_rest_gap_summary(team_sequence)

    error_count = 0
    warning_count = 0
    if issue_rows is not None and not issue_rows.empty:
        error_count = int((issue_rows["Severity"] == "ERROR").sum())
        warning_count = int((issue_rows["Severity"] == "WARN").sum())

    max_streak = None
    if team_sequence is not None and "Streak_Length" in team_sequence.columns:
        streak_values = pd.to_numeric(team_sequence["Streak_Length"], errors="coerce").dropna()
        if not streak_values.empty:
            max_streak = int(streak_values.max())

    top_metrics = st.columns(5)
    top_metrics[0].metric("Errors", f"{error_count:,}")
    top_metrics[1].metric("Warnings", f"{warning_count:,}")
    top_metrics[2].metric(
        "Min rest gap",
        "n/a" if rest_gap_summary["min_gap"] is None else f"{int(rest_gap_summary['min_gap'])} days",
    )
    top_metrics[3].metric("Max same-side streak", "n/a" if max_streak is None else f"{max_streak}")
    caf_violation_count = 0
    if caf_audit is not None and "caf_violated" in caf_audit.columns:
        caf_violation_count = int(caf_audit["caf_violated"].sum())
    top_metrics[4].metric("CAF audit violations", f"{caf_violation_count:,}")

    st.divider()
    st.markdown("**Validation findings**")
    if validation_df is None:
        st.warning("`output/phases/10_final_validation_report.csv` is missing.")
    else:
        severity_options = [s for s in validation_df["Severity"].dropna().astype(str).unique().tolist() if s]
        selected_severities = st.multiselect(
            "Severity filter",
            options=severity_options,
            default=severity_options,
            key="validation_findings_severity_filter",
        )
        filtered_findings = validation_df.copy()
        if selected_severities:
            filtered_findings = filtered_findings[
                filtered_findings["Severity"].astype(str).isin(selected_severities)
            ].copy()
        else:
            filtered_findings = filtered_findings.iloc[0:0].copy()
        st.caption(f"Showing {len(filtered_findings)} of {len(validation_df)} validation row(s).")
        st.dataframe(
            filtered_findings.drop(columns=[c for c in ["_Date"] if c in filtered_findings.columns]),
            use_container_width=True,
            hide_index=True,
            height=320,
        )

    st.divider()
    family_col, caf_col = st.columns([1.1, 0.9])
    with family_col:
        st.markdown("**Issue counters by rule family**")
        if constraint_counts.empty:
            st.success("No validation findings were emitted by the hard-rule checks.")
        else:
            selected_families = _render_clickable_bar_chart(
                constraint_counts,
                x_field="Family",
                y_field="Count",
                key="constraint_rule_family_counts",
                x_title="Rule family",
                y_title="Findings",
                tooltip_fields=["Family", "Count"],
                height=260,
            )
            st.dataframe(constraint_counts, use_container_width=True, hide_index=True)
            if issue_rows is not None and not issue_rows.empty:
                issue_detail_df = issue_rows.copy()
                issue_detail_df["Family"] = issue_detail_df["Check"].apply(_validation_issue_family)
                _render_selected_detail_rows(
                    issue_detail_df,
                    filter_field="Family",
                    selected_values=selected_families,
                    empty_message="Click a rule-family bar to see the exact validation findings in that family.",
                    detail_name="Rule-family findings",
                    display_columns=["Family", "Severity", "Check", "Team_ID", "Round", "Date", "Detail"],
                    height=220,
                )

    with caf_col:
        st.markdown("**CAF audit summary**")
        if caf_audit is None:
            st.info("CAF audit artifact is missing.")
        else:
            affected_teams = 0
            if "Affected_Team_ID" in caf_audit.columns and "caf_violated" in caf_audit.columns:
                affected_teams = int(
                    caf_audit.loc[caf_audit["caf_violated"], "Affected_Team_ID"]
                    .dropna()
                    .astype(str)
                    .nunique()
                )
            caf_metrics = st.columns(3)
            caf_metrics[0].metric("Audited matches", f"{len(caf_audit):,}")
            caf_metrics[1].metric("Violations found", f"{caf_violation_count:,}")
            caf_metrics[2].metric("Affected teams", f"{affected_teams:,}")

    st.divider()
    rest_col, streak_col = st.columns([1.1, 0.9])
    with rest_col:
        st.markdown("**Rest-gap distribution**")
        if rest_gap_summary["histogram"].empty:
            st.info("Team sequence validation is missing rest-gap values.")
        else:
            rest_metrics = st.columns(4)
            rest_metrics[0].metric("Min gap", f"{int(rest_gap_summary['min_gap'])} days")
            rest_metrics[1].metric("Median gap", f"{rest_gap_summary['median_gap']:.1f} days")
            rest_metrics[2].metric("Max gap", f"{int(rest_gap_summary['max_gap'])} days")
            rest_metrics[3].metric("Gaps >= 14 days", f"{rest_gap_summary['long_gap_count']:,}")
            rest_histogram = rest_gap_summary["histogram"].copy()
            rest_histogram["Gap_Bucket"] = rest_histogram["Gap_Days_From_Previous"].astype(int).astype(str)
            selected_gaps = _render_clickable_bar_chart(
                rest_histogram,
                x_field="Gap_Bucket",
                y_field="Matches",
                selection_field="Gap_Bucket",
                key="constraint_rest_gap_distribution",
                x_title="Gap days",
                y_title="Matches",
                tooltip_fields=["Gap_Days_From_Previous", "Matches"],
                sort=alt.SortField(field="Gap_Days_From_Previous", order="ascending"),
                height=300,
            )
            if team_sequence is not None:
                rest_detail = team_sequence.dropna(subset=["Gap_Days_From_Previous"]).copy()
                rest_detail["Gap_Bucket"] = (
                    pd.to_numeric(rest_detail["Gap_Days_From_Previous"], errors="coerce")
                    .round()
                    .astype("Int64")
                    .astype(str)
                )
                _render_selected_detail_rows(
                    rest_detail,
                    filter_field="Gap_Bucket",
                    selected_values=selected_gaps,
                    empty_message="Click a rest-gap bar to see which exact matches fall in that bucket.",
                    detail_name="Rest-gap source rows",
                    display_columns=[
                        "Team_ID",
                        "Round",
                        "Date",
                        "Side",
                        "Opponent",
                        "Home_Team_ID",
                        "Away_Team_ID",
                        "Gap_Days_From_Previous",
                        "Postponed",
                    ],
                    height=240,
                )

    with streak_col:
        st.markdown("**Per-team max streak**")
        if team_sequence is None or "Streak_Length" not in team_sequence.columns:
            st.info("Team sequence validation is missing streak data.")
        else:
            streak_summary = (
                team_sequence.groupby("Team_ID", as_index=False)
                .agg(
                    Max_Streak=("Streak_Length", "max"),
                    Streak_Violations=("Streak_Violation", "sum"),
                )
                .sort_values(["Max_Streak", "Team_ID"], ascending=[False, True])
            )
            selected_teams = _render_clickable_bar_chart(
                streak_summary,
                x_field="Team_ID",
                y_field="Max_Streak",
                key="constraint_max_streak_by_team",
                x_title="Team",
                y_title="Max same-side streak",
                tooltip_fields=["Team_ID", "Max_Streak", "Streak_Violations"],
                sort="-y",
                height=300,
            )
            st.dataframe(streak_summary, use_container_width=True, hide_index=True, height=280)
            streak_detail = team_sequence.copy()
            streak_detail = streak_detail.merge(
                streak_summary[["Team_ID", "Max_Streak"]],
                on="Team_ID",
                how="left",
            )
            streak_detail = streak_detail.loc[
                pd.to_numeric(streak_detail["Streak_Length"], errors="coerce")
                == pd.to_numeric(streak_detail["Max_Streak"], errors="coerce")
            ].copy()
            _render_selected_detail_rows(
                streak_detail,
                filter_field="Team_ID",
                selected_values=selected_teams,
                empty_message="Click a team bar to see the matches where that team hit its maximum streak.",
                detail_name="Streak source rows",
                display_columns=[
                    "Team_ID",
                    "Round",
                    "Date",
                    "Side",
                    "Opponent",
                    "Streak_Length",
                    "Streak_Violation",
                    "Postponed",
                ],
                height=220,
            )

    st.divider()
    balance_col, order_col = st.columns([1.1, 0.9])
    with balance_col:
        st.markdown("**Rolling-5 home/away balance**")
        if team_sequence is None or "Rolling5_Home_Count" not in team_sequence.columns:
            st.info("Rolling-5 balance data is unavailable.")
        else:
            rolling = team_sequence.dropna(subset=["Rolling5_Home_Count"]).copy()
            if rolling.empty:
                st.info("No five-match windows have been recorded yet.")
            else:
                balance_summary = (
                    rolling.groupby("Team_ID", as_index=False)
                    .agg(
                        Min_Home_Count=("Rolling5_Home_Count", "min"),
                        Max_Home_Count=("Rolling5_Home_Count", "max"),
                        Balance_Violation_Count=("Rolling5_Balance_Violation", "sum"),
                    )
                    .sort_values(["Balance_Violation_Count", "Team_ID"], ascending=[False, True])
                )
                st.dataframe(balance_summary, use_container_width=True, hide_index=True, height=320)

    with order_col:
        st.markdown("**Round order consistency**")
        if team_sequence is None or "Round_Inversion" not in team_sequence.columns:
            st.info("Round inversion diagnostics are unavailable.")
        else:
            inversion_rows = team_sequence.loc[team_sequence["Round_Inversion"] == True].copy()
            global_order_rows = pd.DataFrame()
            if issue_rows is not None and not issue_rows.empty:
                global_order_rows = issue_rows.loc[issue_rows["Check"] == "GLOBAL_ROUND_ORDER"].copy()
            order_metrics = st.columns(2)
            order_metrics[0].metric("Team inversions", f"{len(inversion_rows):,}")
            order_metrics[1].metric("Global round-order findings", f"{len(global_order_rows):,}")
            if inversion_rows.empty and global_order_rows.empty:
                st.success("No round inversions or global chronology violations were reported.")
            else:
                if not inversion_rows.empty:
                    st.dataframe(
                        inversion_rows[
                            [
                                col
                                for col in ["Team_ID", "Round", "Date", "Opponent", "Postponed"]
                                if col in inversion_rows.columns
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        height=200,
                    )
                if not global_order_rows.empty:
                    st.dataframe(
                        global_order_rows.drop(columns=[c for c in ["_Date"] if c in global_order_rows.columns]),
                        use_container_width=True,
                        hide_index=True,
                        height=160,
                    )

    if validation_df is None:
        return
    if issue_rows is not None and issue_rows.empty:
        margin_notes: List[str] = []
        min_required_gap = MIN_REST_DAYS_LOCAL + 1
        if rest_gap_summary["min_gap"] is not None and int(rest_gap_summary["min_gap"]) <= min_required_gap:
            margin_notes.append(
                f"minimum observed rest gap is {int(rest_gap_summary['min_gap'])} days against a {min_required_gap}-day floor"
            )
        streak_limit = max(MAX_CONSECUTIVE_HOME, MAX_CONSECUTIVE_AWAY)
        if max_streak is not None and max_streak >= streak_limit:
            margin_notes.append(
                f"maximum same-side streak is {max_streak} with configured ceilings {MAX_CONSECUTIVE_HOME} home / {MAX_CONSECUTIVE_AWAY} away"
            )
        if margin_notes:
            st.info("No hard violations, but margin is tight: " + "; ".join(margin_notes) + ".")
        else:
            st.success("No hard violations and the observed margins sit above the strict limits.")
    elif error_count == 0:
        st.warning("No hard errors were found, but warning-level findings remain in the final validation report.")
    else:
        st.error("Hard-rule violations remain in the final validation report.")


def _render_feasibility_pressure(dashboard_data: Dict[str, Any]) -> None:
    required_keys = ["baseline_feasible_slots", "baseline_solver_status"]
    missing = _missing_dashboard_files(dashboard_data["available"], required_keys)
    if missing:
        st.info("Feasibility pressure is partial because some artifacts are missing: " + ", ".join(missing))

    feasible_slots = dashboard_data["feasible_slots"]
    baseline_status = dashboard_data["baseline_solver_status"]
    round_windows = dashboard_data["round_windows"]
    pressure = _build_feasibility_pressure(feasible_slots)

    if feasible_slots is None:
        st.warning("`output/phases/05_baseline_feasible_slot_counts.csv` is missing.")
        return

    row1 = st.columns(6)
    row1[0].metric("Min feasible slots", "n/a" if pressure["min_slots"] is None else f"{int(pressure['min_slots'])}")
    row1[1].metric("Median feasible slots", "n/a" if pressure["median_slots"] is None else f"{pressure['median_slots']:.1f}")
    row1[2].metric("Max feasible slots", "n/a" if pressure["max_slots"] is None else f"{int(pressure['max_slots'])}")
    row1[3].metric("Matches <= 25", f"{pressure['tight_25']:,}")
    row1[4].metric("Matches <= 50", f"{pressure['tight_50']:,}")
    row1[5].metric("Matches <= 100", f"{pressure['tight_100']:,}")

    row2 = st.columns(3)
    row2[0].metric("Solver status", _solver_status_label(baseline_status), _format_wall_time(baseline_status))
    objective = baseline_status.get("objective") if baseline_status else None
    row2[1].metric("Solver objective", "n/a" if objective is None else f"{float(objective):,.0f}")
    row2[2].metric("Matches evaluated", f"{len(feasible_slots):,}")

    st.divider()
    st.markdown("**Feasible-slot histogram**")
    if pressure["histogram"].empty:
        st.info("No feasible-slot counts were available.")
    else:
        feasible_histogram = pressure["histogram"].copy()
        feasible_histogram["Feasible_Bucket"] = feasible_histogram["Feasible_Slots"].astype(int).astype(str)
        selected_slot_buckets = _render_clickable_bar_chart(
            feasible_histogram,
            x_field="Feasible_Bucket",
            y_field="Matches",
            selection_field="Feasible_Bucket",
            key="feasibility_slot_histogram",
            x_title="Feasible slots",
            y_title="Matches",
            tooltip_fields=["Feasible_Slots", "Matches"],
            sort=alt.SortField(field="Feasible_Slots", order="ascending"),
            height=300,
        )
        feasible_detail = feasible_slots.copy()
        feasible_detail["Feasible_Bucket"] = (
            pd.to_numeric(feasible_detail["feasible_slot_count"], errors="coerce")
            .round()
            .astype("Int64")
            .astype(str)
        )
        _render_selected_detail_rows(
            feasible_detail,
            filter_field="Feasible_Bucket",
            selected_values=selected_slot_buckets,
            empty_message="Click a feasible-slot bar to see which matches sit in that slot-count bucket.",
            detail_name="Feasible-slot source rows",
            display_columns=[
                "match_idx",
                "round",
                "home",
                "away",
                "feasible_slot_count",
                "round_window_start",
                "round_window_end",
                "round_window_slot_count",
            ],
            height=220,
        )

    lower_col, upper_col = st.columns([1.0, 1.0])
    with lower_col:
        st.markdown("**Tightest matches**")
        if pressure["tightest_matches"].empty:
            st.info("No match-level feasible-slot rows were available.")
        else:
            st.dataframe(pressure["tightest_matches"], use_container_width=True, hide_index=True, height=340)

    with upper_col:
        st.markdown("**Round-level average feasible slots**")
        if pressure["round_average"].empty:
            st.info("Round-level feasible-slot averages are unavailable.")
        else:
            round_average = pressure["round_average"].copy()
            round_average["Round_Label"] = "Round " + round_average["round"].astype(int).astype(str)
            selected_rounds = _render_clickable_bar_chart(
                round_average,
                x_field="Round_Label",
                y_field="Avg_Feasible_Slots",
                selection_field="Round_Label",
                key="feasibility_round_average",
                x_title="Round",
                y_title="Average feasible slots",
                tooltip_fields=["Round_Label", "Avg_Feasible_Slots"],
                sort=alt.SortField(field="round", order="ascending"),
                height=300,
            )
            st.dataframe(pressure["round_average"], use_container_width=True, hide_index=True, height=340)
            feasible_by_round = feasible_slots.copy()
            feasible_by_round["Round_Label"] = "Round " + pd.to_numeric(
                feasible_by_round["round"], errors="coerce"
            ).astype("Int64").astype(str)
            _render_selected_detail_rows(
                feasible_by_round,
                filter_field="Round_Label",
                selected_values=selected_rounds,
                empty_message="Click a round bar to see the matches contributing to that round average.",
                detail_name="Round-average source rows",
                display_columns=[
                    "Round_Label",
                    "match_idx",
                    "home",
                    "away",
                    "feasible_slot_count",
                    "round_window_start",
                    "round_window_end",
                ],
                height=220,
            )

    if pressure["tight_100"] == 0 and pressure["min_slots"] is not None:
        st.success(
            f"No match fell below 100 feasible slots; the tightest baseline assignment still had {int(pressure['min_slots'])} options."
        )
    elif pressure["tight_50"] > 0:
        st.warning("Some matches were genuinely tight in the baseline domain. Inspect the tightest-match table above.")
    else:
        st.info("Baseline feasibility was workable, but some matches still had noticeably fewer options than the median.")

    st.caption(
        "`output/phases/03_round_windows.csv` is baseline-planning context only. "
        "`output/week_round_map.csv` is the final round-to-week truth."
    )
    if round_windows is not None:
        with st.expander("Preview baseline round windows"):
            st.dataframe(round_windows, use_container_width=True, hide_index=True, height=260)


def _render_caf_repair_dashboard(dashboard_data: Dict[str, Any]) -> None:
    required_keys = [
        "caf_audit",
        "caf_queue",
        "caf_rescheduled",
        "caf_unresolved",
        "repair_solver_status",
    ]
    missing = _missing_dashboard_files(dashboard_data["available"], required_keys)
    if missing:
        st.info("CAF & repair is partial because some artifacts are missing: " + ", ".join(missing))

    caf_audit = dashboard_data["caf_audit"]
    queue_df = dashboard_data["caf_queue"]
    repaired_df = dashboard_data["caf_rescheduled"]
    unresolved_df = dashboard_data["caf_unresolved"]
    repair_status = dashboard_data["repair_solver_status"]

    if caf_audit is None:
        st.warning("`output/phases/07_caf_audit.csv` is missing.")
        return

    audit_total = len(caf_audit)
    violation_count = int(caf_audit["caf_violated"].sum()) if "caf_violated" in caf_audit.columns else 0
    queued_count = len(queue_df) if queue_df is not None else 0
    repaired_count = len(repaired_df) if repaired_df is not None else 0
    unresolved_count = len(unresolved_df) if unresolved_df is not None else 0
    affected_summary = pd.DataFrame()
    if "Affected_Team_ID" in caf_audit.columns and "caf_violated" in caf_audit.columns:
        affected_summary = (
            caf_audit.loc[caf_audit["caf_violated"]]
            .dropna(subset=["Affected_Team_ID"])
            .groupby("Affected_Team_ID", as_index=False)
            .size()
            .rename(columns={"size": "Violating_Matches"})
            .sort_values(["Violating_Matches", "Affected_Team_ID"], ascending=[False, True])
        )

    top_metrics = st.columns(6)
    top_metrics[0].metric("Audited matches", f"{audit_total:,}")
    top_metrics[1].metric("CAF violations found", f"{violation_count:,}")
    top_metrics[2].metric("Queued matches", f"{queued_count:,}")
    top_metrics[3].metric("Repaired matches", f"{repaired_count:,}")
    top_metrics[4].metric("Unresolved matches", f"{unresolved_count:,}")
    top_metrics[5].metric("Repair path", _solver_status_label(repair_status), _format_wall_time(repair_status))

    if repair_status and repair_status.get("skipped"):
        st.info("Repair skipped by design: " + str(repair_status.get("reason") or "No reason recorded."))
    elif violation_count == 0:
        st.success("CAF audit ran and found zero violations, so the repair branch had nothing to do.")

    chart_col, affected_col = st.columns([0.9, 1.1])
    with chart_col:
        st.markdown("**Audit result split**")
        split_df = pd.DataFrame(
            {
                "Audit_Result": ["Non-violating", "Violating"],
                "Matches": [max(audit_total - violation_count, 0), violation_count],
            }
        )
        selected_audit_split = _render_clickable_bar_chart(
            split_df,
            x_field="Audit_Result",
            y_field="Matches",
            key="caf_audit_split_chart",
            x_title="Audit result",
            y_title="Matches",
            tooltip_fields=["Audit_Result", "Matches"],
            height=260,
        )
        audit_detail = caf_audit.copy()
        audit_detail["Audit_Result"] = audit_detail["caf_violated"].map(
            lambda value: "Violating" if bool(value) else "Non-violating"
        )
        _render_selected_detail_rows(
            audit_detail,
            filter_field="Audit_Result",
            selected_values=selected_audit_split,
            empty_message="Click an audit-result bar to see the exact audited matches in that bucket.",
            detail_name="CAF audit source rows",
            display_columns=[
                "Audit_Result",
                "round",
                "home",
                "away",
                "date",
                "caf_violated",
                "violation_reason",
            ],
            height=220,
        )

    with affected_col:
        st.markdown("**Affected teams**")
        if affected_summary.empty:
            st.info("No teams were affected in the current audit output.")
        else:
            st.dataframe(affected_summary, use_container_width=True, hide_index=True, height=260)

    st.divider()
    st.markdown("**Repair outcome funnel**")
    funnel_df = pd.DataFrame(
        {
            "Stage": ["Audited", "Violating", "Queued", "Repaired", "Unresolved"],
            "Matches": [audit_total, violation_count, queued_count, repaired_count, unresolved_count],
        }
    )
    funnel_col, table_col = st.columns([0.9, 1.1])
    with funnel_col:
        selected_stages = _render_clickable_bar_chart(
            funnel_df,
            x_field="Stage",
            y_field="Matches",
            key="caf_repair_funnel_chart",
            x_title="Stage",
            y_title="Matches",
            tooltip_fields=["Stage", "Matches"],
            height=260,
        )
    with table_col:
        st.dataframe(funnel_df, use_container_width=True, hide_index=True, height=220)

    stage_detail_frames: List[pd.DataFrame] = []
    audited_stage = caf_audit.copy()
    audited_stage["Stage"] = "Audited"
    stage_detail_frames.append(audited_stage)
    violating_stage = caf_audit.loc[caf_audit["caf_violated"]].copy()
    violating_stage["Stage"] = "Violating"
    stage_detail_frames.append(violating_stage)
    if queue_df is not None:
        queued_stage = queue_df.copy()
        queued_stage["Stage"] = "Queued"
        stage_detail_frames.append(queued_stage)
    if repaired_df is not None:
        repaired_stage = repaired_df.copy()
        repaired_stage["Stage"] = "Repaired"
        stage_detail_frames.append(repaired_stage)
    if unresolved_df is not None:
        unresolved_stage = unresolved_df.copy()
        unresolved_stage["Stage"] = "Unresolved"
        stage_detail_frames.append(unresolved_stage)

    funnel_details = pd.concat(stage_detail_frames, ignore_index=True, sort=False) if stage_detail_frames else pd.DataFrame()
    if not funnel_details.empty:
        _render_selected_detail_rows(
            funnel_details,
            filter_field="Stage",
            selected_values=selected_stages,
            empty_message="Click a funnel stage to inspect the rows currently represented by that stage.",
            detail_name="CAF funnel source rows",
            display_columns=[
                "Stage",
                "Round",
                "round",
                "Home_Team_ID",
                "Away_Team_ID",
                "home",
                "away",
                "Date",
                "date",
                "Status",
                "Repair_Status",
                "violation_reason",
            ],
            height=220,
        )

    preview_tabs = st.tabs(["Queue", "Repaired", "Unresolved"])
    preview_data = [queue_df, repaired_df, unresolved_df]
    preview_labels = [
        "No CAF postponement queue rows were written.",
        "No repaired CAF matches were written.",
        "No unresolved CAF postponements were written.",
    ]
    for tab, df, empty_message in zip(preview_tabs, preview_data, preview_labels):
        with tab:
            if df is None:
                st.info("Artifact missing.")
            elif df.empty:
                st.info(empty_message)
            else:
                st.dataframe(df, use_container_width=True, hide_index=True, height=280)


def _render_fairness_insights(dashboard_data: Dict[str, Any]) -> None:
    required_keys = ["schedule", "week_round_map", "home_away_patterns", "team_sequence_validation"]
    missing = _missing_dashboard_files(dashboard_data["available"], required_keys)
    if missing:
        st.info("Fairness insights are partial because some artifacts are missing: " + ", ".join(missing))

    schedule = dashboard_data["schedule"]
    round_span_summary = _build_round_span_summary(dashboard_data["week_round_map"])
    venue_load = _build_venue_load_summary(schedule)
    monthly_volume = _build_monthly_match_volume(schedule)
    rest_gap_summary = _build_rest_gap_summary(dashboard_data["team_sequence"])
    travel_stats = None if schedule is None else _build_travel_stats(schedule, None)
    home_away_patterns = dashboard_data["home_away_patterns"]

    st.info("These are optimization-quality signals, not hard-rule validation failures.")
    if schedule is None:
        st.warning("Schedule-based fairness metrics are unavailable until `output/optimized_schedule.csv` exists.")

    travel_range = None
    if travel_stats is not None and not travel_stats.empty:
        travel_range = float(travel_stats["Total_km"].max() - travel_stats["Total_km"].min())
    active_dates = 0
    if schedule is not None and "_Date" in schedule.columns:
        active_dates = int(pd.to_datetime(schedule["_Date"], errors="coerce").dropna().nunique())
    top3_share = 0.0
    if not venue_load.empty:
        top3_share = float(venue_load["Matches"].head(3).sum() / max(len(schedule), 1))

    metrics = st.columns(5)
    metrics[0].metric("Away travel range", "n/a" if travel_range is None else f"{travel_range:,.0f} km")
    metrics[1].metric(
        "Max rest gap",
        "n/a" if rest_gap_summary["max_gap"] is None else f"{int(rest_gap_summary['max_gap'])} days",
    )
    metrics[2].metric("Active match dates", f"{active_dates:,}")
    metrics[3].metric("Top 3 venue share", _format_pct(top3_share))
    metrics[4].metric(
        "Rounds spanning 1 / 2 / 3+ weeks",
        f"{round_span_summary['one_week_rounds']} / {round_span_summary['two_week_rounds']} / {round_span_summary['three_plus_rounds']}",
    )

    travel_col, venue_col = st.columns([1.0, 1.0])
    with travel_col:
        st.markdown("**Per-team away travel**")
        if travel_stats is None or travel_stats.empty:
            st.info("Away-travel statistics are unavailable.")
        else:
            selected_travel_teams = _render_clickable_bar_chart(
                travel_stats,
                x_field="Team_ID",
                y_field="Total_km",
                key="fairness_away_travel_chart",
                x_title="Team",
                y_title="Total away travel km",
                tooltip_fields=["Team_ID", "Total_km", "Away_trips", "Longest_trip_km"],
                sort="-y",
                height=300,
            )
            st.dataframe(
                travel_stats[["Team_ID", "Total_km", "Away_trips", "Avg_km_per_away_trip", "Longest_trip_km"]],
                use_container_width=True,
                hide_index=True,
                height=280,
            )
            if schedule is not None:
                away_detail = schedule.copy()
                _render_selected_detail_rows(
                    away_detail,
                    filter_field="Away_Team_ID",
                    selected_values=selected_travel_teams,
                    empty_message="Click a team bar to see the away fixtures behind that travel total.",
                    detail_name="Away-travel source rows",
                    display_columns=[
                        "Round",
                        "Date",
                        "Home_Team_ID",
                        "Away_Team_ID",
                        "Venue_Stadium_ID",
                        "Travel_km",
                        "Postponed",
                    ],
                    height=220,
                )

    with venue_col:
        st.markdown("**Venue load**")
        if venue_load.empty:
            st.info("Venue load is unavailable.")
        else:
            selected_venues = _render_clickable_bar_chart(
                venue_load,
                x_field="Venue_Stadium_ID",
                y_field="Matches",
                key="fairness_venue_load_chart",
                x_title="Venue",
                y_title="Matches",
                tooltip_fields=["Venue_Stadium_ID", "Matches", "Share"],
                sort="-y",
                height=300,
            )
            venue_table = venue_load.copy()
            venue_table["Share"] = venue_table["Share"].map(lambda value: _format_pct(float(value)))
            st.dataframe(venue_table, use_container_width=True, hide_index=True, height=280)
            if schedule is not None:
                _render_selected_detail_rows(
                    schedule,
                    filter_field="Venue_Stadium_ID",
                    selected_values=selected_venues,
                    empty_message="Click a venue bar to see every match scheduled at that venue.",
                    detail_name="Venue-load source rows",
                    display_columns=[
                        "Round",
                        "Date",
                        "Date_time",
                        "Home_Team_ID",
                        "Away_Team_ID",
                        "Venue_Stadium_ID",
                        "Travel_km",
                    ],
                    height=220,
                )

    st.divider()
    round_col, month_col = st.columns([1.0, 1.0])
    with round_col:
        st.markdown("**Round span chart**")
        if round_span_summary["details"].empty:
            st.info("Round-to-week mapping is unavailable.")
        else:
            round_span_detail = round_span_summary["details"].copy()
            round_span_detail["Round_Label"] = "Round " + round_span_detail["Round"].astype(int).astype(str)
            selected_round_spans = _render_clickable_bar_chart(
                round_span_detail,
                x_field="Round_Label",
                y_field="Week_Span_Count",
                selection_field="Round_Label",
                key="fairness_round_span_chart",
                x_title="Round",
                y_title="Weeks spanned",
                tooltip_fields=["Round_Label", "Calendar_Weeks", "Week_Span_Count", "Match_Count"],
                sort=alt.SortField(field="Round", order="ascending"),
                height=300,
            )
            st.dataframe(round_span_summary["details"], use_container_width=True, hide_index=True, height=280)
            round_schedule_detail = round_span_detail.copy()
            if schedule is not None:
                round_matches = schedule.copy()
                round_matches["Round_Label"] = "Round " + pd.to_numeric(
                    round_matches["Round"], errors="coerce"
                ).astype("Int64").astype(str)
                round_schedule_detail = round_matches.merge(
                    round_span_detail[["Round_Label", "Calendar_Weeks", "Week_Span_Count"]],
                    on="Round_Label",
                    how="left",
                )
            _render_selected_detail_rows(
                round_schedule_detail,
                filter_field="Round_Label",
                selected_values=selected_round_spans,
                empty_message="Click a round bar to see the round rows and, when available, the matches inside that round.",
                detail_name="Round-span source rows",
                display_columns=[
                    "Round_Label",
                    "Calendar_Weeks",
                    "Week_Span_Count",
                    "Date",
                    "Home_Team_ID",
                    "Away_Team_ID",
                    "Venue_Stadium_ID",
                ],
                height=220,
            )

    with month_col:
        st.markdown("**Monthly match volume**")
        if monthly_volume.empty:
            st.info("Monthly schedule density is unavailable.")
        else:
            selected_fairness_months = _render_clickable_bar_chart(
                monthly_volume,
                x_field="Month",
                y_field="Matches",
                key="fairness_monthly_match_volume",
                x_title="Month",
                y_title="Matches",
                tooltip_fields=["Month", "Matches"],
                height=300,
            )
            st.dataframe(monthly_volume, use_container_width=True, hide_index=True, height=280)
            if schedule is not None:
                month_detail = schedule.copy()
                month_detail["Month"] = pd.to_datetime(month_detail["_Date"], errors="coerce").dt.to_period("M").astype(str)
                _render_selected_detail_rows(
                    month_detail,
                    filter_field="Month",
                    selected_values=selected_fairness_months,
                    empty_message="Click a month bar to see the exact fixtures in that month.",
                    detail_name="Monthly-volume source rows",
                    display_columns=[
                        "Month",
                        "Round",
                        "Date",
                        "Home_Team_ID",
                        "Away_Team_ID",
                        "Venue_Stadium_ID",
                    ],
                    height=220,
                )

    st.divider()
    longest_gap_col, pattern_col = st.columns([1.0, 1.0])
    with longest_gap_col:
        st.markdown("**Longest rest-gap teams**")
        if rest_gap_summary["by_team"].empty:
            st.info("Team-level rest-gap summaries are unavailable.")
        else:
            st.dataframe(
                rest_gap_summary["by_team"].head(12),
                use_container_width=True,
                hide_index=True,
                height=320,
            )

    with pattern_col:
        st.markdown("**Home/away pattern summary**")
        if home_away_patterns is None or home_away_patterns.empty:
            st.info("Home/away pattern artifact is unavailable.")
        else:
            pattern_cols = [
                col
                for col in [
                    "Team_ID",
                    "Home_Count",
                    "Away_Count",
                    "Max_Home_Streak",
                    "Max_Away_Streak",
                    "Rolling5_Balance_Violations",
                ]
                if col in home_away_patterns.columns
            ]
            st.dataframe(
                home_away_patterns[pattern_cols].sort_values("Team_ID"),
                use_container_width=True,
                hide_index=True,
                height=320,
            )


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
    home = str(row.get("Home_Team_ID", "") or "TBD")
    away = str(row.get("Away_Team_ID", "") or "TBD")
    round_num = row.get("Round", "")
    time_label = ""
    raw_time = row.get("Date_time", "")
    parsed = pd.to_datetime(raw_time, errors="coerce")
    if pd.notna(parsed):
        time_label = parsed.strftime("%H:%M")

    prefix = f"R{html.escape(str(round_num))} " if str(round_num).strip() else ""
    time_html = f"<span>{html.escape(time_label)}</span>" if time_label else ""
    teams_html = (
        "<div class=\"calendar-match-line\">"
        f"{_team_badge_html(home, size=20)}"
        "<span class=\"calendar-vs\">vs</span>"
        f"{_team_badge_html(away, size=20)}"
        "</div>"
    )
    return f"<div class=\"calendar-match\">{prefix}{teams_html}{time_html}</div>"


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
  color: #ab97ba;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}
.calendar-day {
  min-height: 150px;
  border: 1px solid rgba(210, 202, 217, 0.24);
  border-radius: 8px;
  background: #2f2934;
  padding: 10px;
  overflow: hidden;
}
.calendar-day.outside {
  background: rgba(210, 202, 217, 0.07);
  color: #8f67ad;
}
.calendar-day.matchday {
  border-color: #8f67ad;
  background: rgba(104, 35, 158, 0.24);
}
.calendar-day.blocked {
  border-color: #75409f;
  background: rgba(117, 64, 159, 0.18);
}
.calendar-day.fifa {
  border-color: #8f67ad;
  background: rgba(210, 202, 217, 0.12);
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
  color: #f8f9f7;
}
.calendar-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
}
.calendar-badge {
  border-radius: 6px;
  background: rgba(210, 202, 217, 0.18);
  color: #f8f9f7;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1;
  padding: 4px 5px;
}
.calendar-badge.caf { background: #68239e; color: #f8f9f7; }
.calendar-badge.fifa { background: #8f67ad; color: #f8f9f7; }
.calendar-match {
  border-left: 3px solid #68239e;
  background: rgba(248, 249, 247, 0.10);
  color: #f8f9f7;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.25;
  margin-top: 6px;
  padding: 6px 7px;
}
.calendar-match-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}
.calendar-vs {
  color: #d2cad9;
  font-weight: 700;
}
.calendar-match .team-inline-logo {
  margin-right: 2px;
}
.calendar-match span {
  display: block;
  color: #d2cad9;
  font-size: 0.72rem;
  font-weight: 600;
  margin-top: 2px;
}
.calendar-empty {
  color: #ab97ba;
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
    st.bar_chart(chart_data, use_container_width=True, height=420, color=PALETTE["primary"])

    display_stats = stats.copy()
    display_stats["Icon"] = display_stats["Team_ID"].apply(lambda tid: _team_icon_data_uri(str(tid)))

    st.dataframe(
        display_stats[
            [
                "Team_ID",
                "Icon",
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
        column_config={
            "Icon": st.column_config.ImageColumn("Club", width="small"),
        },
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
    team_tab, h2h_tab, travel_tab, cal_tab, round_tab = st.tabs(
        ["Team chooser", "Team vs Team", "Travel stats", "Calendar", "Round filter"]
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
            chosen_caption = chosen_label or str(chosen_team)
        else:
            # Fallback to IDs seen in schedule only
            ids = sorted(
                set(df.get("Home_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
                | set(df.get("Away_Team_ID", pd.Series([], dtype=str)).dropna().astype(str))
            )
            chosen_team = st.selectbox("Pick a team (ID)", options=ids, index=0 if ids else None)
            chosen_caption = str(chosen_team or "")

        logo_col, filter_col = st.columns([0.18, 0.82], vertical_alignment="center")
        with logo_col:
            _render_team_logo(chosen_team, chosen_caption)

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

        badge_a, badge_b = st.columns(2)
        with badge_a:
            _render_team_logo(team_a, f"Team A: {team_a}")
        with badge_b:
            _render_team_logo(team_b, f"Team B: {team_b}")

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
            st.bar_chart(dist_df.set_index("Weekday")["Matches"], color=PALETTE["primary"])

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
    page_config: Dict[str, Any] = {"page_title": APP_TITLE, "layout": "wide"}
    icon = _page_icon()
    if icon:
        page_config["page_icon"] = icon
    st.set_page_config(**page_config)
    _render_theme()

    if ICON_PATH.exists():
        title_mark, title_copy = st.columns([0.08, 0.92], vertical_alignment="center")
        with title_mark:
            st.image(ICON_PATH.as_posix(), width=58)
        with title_copy:
            st.title(APP_TITLE)
    else:
        st.title(APP_TITLE)
    st.caption(
        "Runs the full pipeline (load → fixtures → baseline → CAF audit → repair) "
        "and renders all PRD-required outputs and phase artifacts."
    )

    with st.sidebar:
        if ICON_PATH.exists():
            st.image(ICON_PATH.as_posix(), width=96)
        st.header("Run configuration")
        seed = st.number_input("DRR seed", min_value=0, max_value=2_000_000_000, value=DEFAULT_SEED, step=1)
        st.text_input("Data model path", value=DATA_MODEL_PATH, disabled=True)
        st.text_input("Expanded calendar path", value=EXPANDED_CALENDAR_PATH, disabled=True)

        st.divider()
        model_config = _render_model_config_controls()

        run_clicked = st.button("Run full pipeline", type="primary")
        st.divider()
        st.markdown("**Tip**: If you only want to browse outputs, don’t run — just use the tabs.")

    tab_explore, tab_run, tab_validate, tab_artifacts, tab_browse = st.tabs(
        ["Explore", "Run & progress", "Validate & Insights", "Artifacts", "Browse files"]
    )

    with tab_run:
        st.subheader("Progress")
        log_buffer = io.StringIO()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            # Streamlit supports only: running | complete | error
            # We treat "not started" as a complete state with a "(waiting)" label.
            status_load = st.status("Phase 1: Load data (waiting)", state="complete")
            status_fixtures = st.status("Phase 2: Generate fixtures (waiting)", state="complete")
            status_domain = st.status("Phase 3a: Build domains (waiting)", state="complete")
            status_baseline = st.status("Phase 3b: Solve baseline (waiting)", state="complete")
            status_audit = st.status("Phase 4: CAF audit (waiting)", state="complete")
            status_write = st.status("Phase 6: Write outputs (waiting)", state="complete")

        with col_b:
            st.markdown("**Live stdout**")
            st.caption(
                "Mirrors stdout and stderr from the pipeline (same as the CLI). "
                "Phases 1–3a are mostly quiet until the baseline solver emits progress."
            )
            log_box = st.empty()
            if "stdout_log" in st.session_state and st.session_state["stdout_log"]:
                log_box.code(st.session_state["stdout_log"], language="text")

        if run_clicked:
            _apply_runtime_model_config(model_config)
            # Import inside run to avoid heavy imports on mere browsing.
            from src.data_loader import load_data
            from src.fixture_generator import generate_drr
            from src.slot_domain import build_domains
            from src.baseline_solver import solve_baseline
            from src.caf_audit import caf_audit
            from src.caf_repair_solver import caf_repair, write_repair_skipped_status
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

                if violations:
                    status_repair = st.status("Phase 5: CAF repair (waiting)", state="complete")
                    repaired, unresolved = _run_phase(
                        "Phase 5: CAF repair",
                        lambda: caf_repair(accepted, violations, data),
                        status_repair,
                        log_box,
                        log_buffer,
                    )
                    st.session_state["stdout_log"] = log_buffer.getvalue()
                else:
                    repaired = []
                    unresolved = []
                    write_repair_skipped_status("No CAF violations found by audit.")
                    st.info("Phase 5 skipped: CAF audit found no violations to repair.")

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

    with tab_validate:
        _render_validation_dashboard()

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

