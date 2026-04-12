"""
Egyptian Premier League Schedule Optimizer — Streamlit UI.

Run from repository root:
    python -m streamlit run ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from schedule_optimizer.paths import DATA, OUTPUT, REPO_ROOT
from schedule_optimizer.pipeline import OptimizationResult, run_optimization
from data_browser import describe_path, excel_sheet_names, list_tabular_files, load_csv, load_excel_sheet

DOCS_PATH = REPO_ROOT / "Documentations" / "CODE_DOCUMENTATION.md"
MODEL_PATH = REPO_ROOT / "Documentations" / "MODEL_EXPLANATION.md"

st.set_page_config(
    page_title="EPL Schedule Optimizer",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CUSTOM_CSS = """
<style>
    :root {
        --bg: #0a1628;
        --card: #121f35;
        --accent: #00c853;
        --accent2: #69f0ae;
        --text: #e8eef7;
        --muted: #8b9bb4;
    }
    .stApp { background: linear-gradient(165deg, #071018 0%, #0a1628 40%, #0d1f2d 100%); color: var(--text); }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0d1b2a, #0a1628) !important; border-right: 1px solid #1a2d45; }
    [data-testid="stHeader"] { background: rgba(10,22,40,0.92); border-bottom: 1px solid #1a2d45; }
    div[data-testid="stMetric"] {
        background: var(--card);
        border: 1px solid #1f3555;
        border-radius: 14px;
        padding: 1rem;
        box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    }
    .hero {
        font-size: 2.1rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        background: linear-gradient(90deg, #e8eef7, var(--accent2));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.25rem;
    }
    .subhero { color: var(--muted); font-size: 1.05rem; margin-bottom: 1.5rem; }
</style>
"""


def _inject_css() -> None:
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _load_teams() -> pd.DataFrame:
    p = DATA / "Sources" / "teams_data.xlsx"
    return pd.read_excel(p, sheet_name="Teams")


def _load_schedule_if_exists() -> pd.DataFrame | None:
    p = OUTPUT / "optimized_schedule.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


def _schedule_dataframe() -> pd.DataFrame | None:
    """Latest schedule: in-memory result from last run, else CSV on disk."""
    res = st.session_state.get("last_result")
    if isinstance(res, OptimizationResult) and res.success and res.schedule_df is not None:
        return res.schedule_df.copy()
    return _load_schedule_if_exists()


def _team_list(teams: pd.DataFrame) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _, row in teams.iterrows():
        tid = str(row.get("Team_ID", "")).strip()
        if not tid or tid.lower() == "nan":
            continue
        name = str(row.get("Team_Name", tid))
        if name.lower() == "nan":
            name = tid
        out.append((tid, name))
    return out


def _club_button(tid: str, tname: str, selected: bool) -> None:
    """Primary (green) style when selected, secondary otherwise (Streamlit >= 1.33)."""
    try:
        clicked = st.button(
            tid,
            key=f"pick_club_{tid}",
            use_container_width=True,
            help=tname,
            type="primary" if selected else "secondary",
        )
    except TypeError:
        clicked = st.button(
            tid,
            key=f"pick_club_{tid}",
            use_container_width=True,
            help=tname,
        )
    if clicked:
        st.session_state["dashboard_club"] = tid


def _render_club_picker(teams: pd.DataFrame) -> str | None:
    """Clickable club buttons; returns selected Team_ID (or None if no teams)."""
    pairs = _team_list(teams)
    if not pairs:
        return None

    if "dashboard_club" not in st.session_state:
        st.session_state["dashboard_club"] = pairs[0][0]

    st.caption("Click a club to highlight it (green) and load its full season below.")
    ncols = 6
    for i in range(0, len(pairs), ncols):
        cols = st.columns(ncols)
        for j, col in enumerate(cols):
            if i + j >= len(pairs):
                break
            tid, tname = pairs[i + j]
            sel = st.session_state["dashboard_club"] == tid
            with col:
                st.caption(tname[:22] + ("..." if len(tname) > 22 else ""))
                _club_button(tid, tname, sel)

    return str(st.session_state.get("dashboard_club") or pairs[0][0])


def _club_season_table(sched: pd.DataFrame, club_id: str) -> pd.DataFrame:
    h = sched["Home_Team_ID"].astype(str)
    a = sched["Away_Team_ID"].astype(str)
    mask = (h == club_id) | (a == club_id)
    sub = sched.loc[mask].copy()
    if sub.empty:
        return sub

    def role(row) -> str:
        return "Home" if str(row["Home_Team_ID"]) == club_id else "Away"

    def opponent(row) -> str:
        return str(row["Away_Team_ID"]) if str(row["Home_Team_ID"]) == club_id else str(row["Home_Team_ID"])

    sub["H_A"] = sub.apply(role, axis=1)
    sub["Opponent"] = sub.apply(opponent, axis=1)
    sub["Date_time"] = pd.to_datetime(sub["Date_time"], errors="coerce")
    cols = [
        c
        for c in [
            "Round",
            "Calendar_Week_Num",
            "Date",
            "Date_time",
            "H_A",
            "Opponent",
            "Venue_Stadium_ID",
            "Travel_km",
            "Slot_tier",
            "Is_FIFA",
            "Is_CAF",
            "Is_SuperCup",
        ]
        if c in sub.columns
    ]
    return sub[cols].sort_values("Date_time", na_position="last")


def _head_to_head_table(sched: pd.DataFrame, team_a: str, team_b: str) -> pd.DataFrame:
    """All rows where the two teams meet (home/away in either direction)."""
    h = sched["Home_Team_ID"].astype(str)
    a = sched["Away_Team_ID"].astype(str)
    mask = ((h == team_a) & (a == team_b)) | ((h == team_b) & (a == team_a))
    sub = sched.loc[mask].copy()
    if sub.empty:
        return sub
    sub["Date_time"] = pd.to_datetime(sub["Date_time"], errors="coerce")
    keep = [
        c
        for c in (
            "Round",
            "Calendar_Week_Num",
            "Date",
            "Date_time",
            "Home_Team_ID",
            "Away_Team_ID",
            "Venue_Stadium_ID",
            "Travel_km",
            "Slot_tier",
        )
        if c in sub.columns
    ]
    return sub[keep].sort_values("Date_time", na_position="last")


def main() -> None:
    _inject_css()
    st.sidebar.markdown("### ⚽ Controls")
    st.sidebar.caption("CP-SAT optimizer · data from `data/`")

    caf_buffer = st.sidebar.slider(
        "CAF blocker buffer (days each side)",
        min_value=0,
        max_value=5,
        value=1,
        help="Days before/after each continental blocker anchor. Higher = stricter (often infeasible at 3+).",
    )
    time_limit = st.sidebar.slider("Solver time limit (seconds)", 30, 600, 180, 30)

    run_btn = st.sidebar.button("▶ Run optimization", type="primary", use_container_width=True)

    if run_btn:
        with st.spinner("Running CP-SAT (may take a few minutes)…"):
            st.session_state["last_result"] = run_optimization(
                caf_buffer_days=int(caf_buffer),
                time_limit_s=float(time_limit),
                write_outputs=True,
            )

    st.markdown('<p class="hero">Egyptian Premier League · Schedule Optimizer</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="subhero">Integer assignment over your Excel/CSV calendar · travel minimization · constraints from PRD</p>',
        unsafe_allow_html=True,
    )

    tab_dash, tab_model, tab_data, tab_sched, tab_docs = st.tabs(
        [
            "Dashboard",
            "Model explanation",
            "Data library",
            "Schedule",
            "Code documentation",
        ]
    )

    teams = _load_teams()

    with tab_dash:
        st.subheader("Clubs")
        club_id = _render_club_picker(teams)

        st.subheader("Club season")
        sched = _schedule_dataframe()
        if sched is None or sched.empty:
            st.info(
                "No schedule loaded yet. Run **Run optimization** in the sidebar, "
                "or place `output/optimized_schedule.csv` in the project."
            )
        elif club_id:
            name_map = dict(_team_list(teams))
            full_name = name_map.get(club_id, club_id)
            st.markdown(f"**{club_id}** — {full_name} · all fixtures in the optimized calendar")
            club_df = _club_season_table(sched, club_id)
            if club_df.empty:
                st.warning("No fixtures for this club in the current schedule file.")
            else:
                st.dataframe(club_df, use_container_width=True, height=480)
                st.caption(
                    f"{len(club_df)} matches for this club in the optimized schedule "
                    f"(each team plays 2*(n-1) league games in a double round-robin)."
                )

        st.subheader("Head-to-head (two teams)")
        if sched is None or sched.empty:
            st.caption("Load a schedule first to search fixtures between two clubs.")
        else:
            ids = [p[0] for p in _team_list(teams)]
            nm = dict(_team_list(teams))

            def _fmt(tid: str) -> str:
                return f"{tid} - {nm.get(tid, tid)}"

            c_a, c_b = st.columns(2)
            with c_a:
                a_pick = st.selectbox(
                    "First team",
                    options=ids,
                    format_func=_fmt,
                    key="h2h_select_a",
                )
            rest = [x for x in ids if x != a_pick]
            with c_b:
                b_pick = st.selectbox(
                    "Second team",
                    options=rest if rest else ids,
                    format_func=_fmt,
                    key="h2h_select_b",
                )
            h2h_df = _head_to_head_table(sched, a_pick, b_pick)
            if h2h_df.empty:
                st.info("No rows in this schedule for that pair (check team IDs).")
            else:
                st.markdown(f"**{a_pick}** vs **{b_pick}** — {len(h2h_df)} meeting(s) in this schedule (home and away legs).")
                st.dataframe(h2h_df, use_container_width=True, height=220)

        st.subheader("Simulation")

        res: OptimizationResult | None = st.session_state.get("last_result")
        if res is None:
            res = OptimizationResult(
                success=False,
                exit_code=-1,
                message="Click **Run optimization** in the sidebar to simulate.",
            )

        if res.schedule_df is not None and res.success:
            c1, c2, c3, c4, c5 = st.columns(5)
            df = res.schedule_df
            stats = res.stats
            c1.metric("Matches", stats.get("matches", len(df)))
            c2.metric("Total travel (km)", f"{stats.get('total_travel_km', 0):,.0f}")
            c3.metric("Mean travel / match", f"{stats.get('mean_travel_km_per_match', 0):.1f}")
            c4.metric("Solver", res.solver_status or "—")
            c5.metric("Wall time (s)", f"{res.wall_time_s:.1f}")

            if res.objective_scaled is not None:
                st.caption(
                    f"Objective (internal units): {res.objective_scaled:,.0f} · ≈ km ×10 scale"
                )

            with st.expander("Distribution: Slot tier (1 = best prime window)"):
                st.bar_chart(
                    pd.Series(res.stats.get("slot_tier_counts", {}), name="matches").sort_index()
                )

            with st.expander("Assignment difficulty"):
                st.write(
                    {
                        "Feasible slots per match (min)": stats.get("feasible_slots_min"),
                        "Feasible slots per match (max)": stats.get("feasible_slots_max"),
                        "Feasible slots per match (mean)": round(stats.get("feasible_slots_mean", 0), 1),
                        "CAF buffer days": stats.get("caf_buffer_days"),
                    }
                )
        else:
            st.warning(res.message)
            if res.log_lines:
                with st.expander("Load / solve log"):
                    st.code("\n".join(res.log_lines[-80:]), language="text")

    with tab_model:
        if MODEL_PATH.exists():
            st.markdown(MODEL_PATH.read_text(encoding="utf-8"))
        else:
            st.error("Missing Documentations/MODEL_EXPLANATION.md")

    with tab_data:
        st.subheader("Data files")
        incl_past = st.checkbox("Include `past seasons data/` CSVs", value=False)
        roots = [DATA]
        if incl_past:
            roots.append(REPO_ROOT / "past seasons data")
        st.caption("Reads `.xlsx` and `.csv` from selected folders (recursive).")
        files = list_tabular_files(roots)
        labels = [str(p.relative_to(REPO_ROOT)) for p in files]
        choice = st.selectbox("Select file", options=range(len(labels)), format_func=lambda i: labels[i])
        path = files[choice]
        info = describe_path(path)
        st.write(f"**{info['relative']}** · {info['size_bytes']:,} bytes")

        if path.suffix.lower() == ".csv":
            preview = load_csv(path, nrows=400)
            st.dataframe(preview, use_container_width=True, height=420)
        else:
            sheets = excel_sheet_names(path)
            sh = st.selectbox("Sheet", sheets)
            preview = load_excel_sheet(path, sh, nrows=400)
            st.dataframe(preview, use_container_width=True, height=420)

    with tab_sched:
        df = _load_schedule_if_exists()
        if df is None:
            st.info("No `output/optimized_schedule.csv` yet. Run optimization from the Dashboard tab.")
        else:
            rounds = sorted(df["Round"].unique())
            r_filter = st.multiselect("Rounds", options=rounds, default=rounds[:6])
            view = df[df["Round"].isin(r_filter)] if r_filter else df
            st.dataframe(view, use_container_width=True, height=520)
            st.download_button(
                "Download CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="optimized_schedule.csv",
                mime="text/csv",
            )

    with tab_docs:
        if DOCS_PATH.exists():
            st.markdown(DOCS_PATH.read_text(encoding="utf-8"))
        else:
            st.error("Missing CODE_DOCUMENTATION.md")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Outputs: `{OUTPUT.relative_to(REPO_ROOT)}`")


if __name__ == "__main__":
    main()
