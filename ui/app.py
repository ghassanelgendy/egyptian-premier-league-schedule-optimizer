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
import time

from schedule_optimizer.paths import DATA, OUTPUT, REPO_ROOT
from schedule_optimizer.pipeline import OptimizationResult, run_optimization
from calendar_board import load_day_ledger_csv, render_day_detail, render_month_calendar
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

    with st.sidebar.expander("Solver & DRR", expanded=False):
        phase1_tl = st.number_input(
            "Phase 1 time limit (seconds)",
            min_value=5.0,
            max_value=1200.0,
            value=30.0,
            step=5.0,
            help="Feasibility pass: stop after first solution within this wall time.",
        )
        phase2_tl = st.number_input(
            "Phase 2 time limit (seconds, 0 = unlimited)",
            min_value=0.0,
            max_value=7200.0,
            value=0.0,
            step=30.0,
            help="Optimization pass. 0 leaves CP-SAT unbounded (can run a long time).",
        )
        drr_ntries = st.slider(
            "DRR seeds to score (auto mode)",
            min_value=1,
            max_value=48,
            value=12,
            help="Ignored when a fixed DRR seed is set below.",
        )
        drr_seed_ui = st.number_input(
            "DRR seed (0 = auto, try many seeds)",
            min_value=0,
            max_value=2_147_483_647,
            value=0,
            step=1,
            help="Non-zero fixes the double round-robin draw for reproducibility.",
        )
        cont_mult = st.slider(
            "Continental postpone penalty ×",
            min_value=1.0,
            max_value=15.0,
            value=4.0,
            step=0.5,
            help="Extra weight on week-slippage for matches involving CL/CC clubs.",
        )
        write_out = st.checkbox("Write outputs (CSV + phases/)", value=True)

    with st.sidebar.expander("CP-SAT objective weights", expanded=False):
        st.markdown(
            """
**Phase 2 only** — the solver minimizes one sum of penalties. **Larger weight ⇒ stronger pull** on that goal vs others.

- **Travel** is always in the objective (not listed here): each match adds `round(Travel_km × 10)` for whichever slot you pick. Travel does not depend on *which* allowed slot you choose today, so weights mainly trade off **TV windows**, **week stickiness**, and **double use of a slot**.

**Typical priority** (default sizes): T1 vs T1 prime night ≫ avoid double slot ≫ weekend for any T1 ≫ tier mismatch ≫ week slip.
            """
        )
        max_mslot = st.selectbox(
            "Max matches per slot index",
            options=[1, 2],
            index=1,
            help="Hard cap on how many league matches may share the same calendar row (slot index). "
            "2 allows two; overlap weight below penalizes actually using the second.",
        )
        w_slot_ov = st.number_input(
            "w_slot_overlap",
            min_value=0,
            value=1_000_000,
            step=100_000,
            help="Added once per slot where **two** matches are scheduled on the same slot index. "
            "Keep this **large** so the solver only doubles up a slot if it must for feasibility.",
        )
        w_tier_m = st.number_input(
            "w_tier_mismatch",
            min_value=0,
            value=1_000,
            step=100,
            help="If Slot_tier is **worse** than the match’s minimum club tier: pay weight × (slot_tier − match_tier). "
            "Higher = push big matches toward better kickoff windows.",
        )
        w_top_nd = st.number_input(
            "w_top_tier_non_prime_day",
            min_value=0,
            value=5_000,
            step=500,
            help="For **match tier 1** only: extra penalty if the day is **not** Friday or Saturday (still soft).",
        )
        w_post_w = st.number_input(
            "w_postpone_week_distance",
            min_value=0,
            value=50_000,
            step=5_000,
            help="If the match is not in its **nominal calendar week** for that round: pay weight × |week_order gap| "
            "× continental multiplier for CL/CC games (see Continental slider).",
        )
        w_t1_pn = st.number_input(
            "w_t1vst1_not_prime_night",
            min_value=0,
            value=50_000_000,
            step=1_000_000,
            help="For **both clubs tier 1**: penalty unless the slot is **prime night** (Fri/Sat + latest kickoff that date). "
            "Default is huge so these fixtures win the best windows unless impossible.",
        )

    run_btn = st.sidebar.button("▶ Run optimization", type="primary", use_container_width=True)

    if run_btn:
        status_box = st.empty()
        details_box = st.empty()
        t0 = time.perf_counter()
        last_push = {"t": 0.0}

        def _ui_progress(ev: dict) -> None:
            # Throttle UI updates to avoid spamming Streamlit rerenders.
            now = time.perf_counter() - t0
            if now - last_push["t"] < 0.25 and ev.get("stage") not in ("solve_done", "solution"):
                return
            last_push["t"] = now
            stage = str(ev.get("stage", ""))
            if stage == "solution":
                obj = ev.get("objective")
                bound = ev.get("best_bound")
                status_box.markdown(
                    f"**Working:** phase {ev.get('phase')} · new solution #{ev.get('solutions')} "
                    f"· obj={obj} · bound={bound}"
                )
            else:
                status_box.markdown(f"**Working:** `{stage}`")
            details_box.json(ev)

        with st.spinner("Running CP-SAT (live status below)…"):
            st.session_state["last_result"] = run_optimization(
                caf_buffer_days=int(caf_buffer),
                time_limit_s=None if float(phase2_tl) <= 0 else float(phase2_tl),
                phase1_time_limit_s=float(phase1_tl),
                drr_tries=int(drr_ntries),
                drr_seed=None if int(drr_seed_ui) == 0 else int(drr_seed_ui),
                cont_postpone_mult=float(cont_mult),
                write_outputs=bool(write_out),
                max_matches_per_slot=int(max_mslot),
                w_slot_overlap=int(w_slot_ov),
                w_tier_mismatch=int(w_tier_m),
                w_top_tier_non_prime_day=int(w_top_nd),
                w_postpone_week_distance=int(w_post_w),
                w_t1vst1_not_prime_night=int(w_t1_pn),
                progress_cb=_ui_progress,
            )

    st.markdown('<p class="hero">Egyptian Premier League · Schedule Optimizer</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="subhero">Integer assignment over your Excel/CSV calendar · travel minimization · constraints from PRD</p>',
        unsafe_allow_html=True,
    )

    tab_dash, tab_cal, tab_model, tab_data, tab_sched, tab_docs = st.tabs(
        [
            "Dashboard",
            "Full calendar",
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

            if stats.get("phase1_time_s") is not None or stats.get("phase2_time_s") is not None:
                p1 = float(stats.get("phase1_time_s") or 0.0)
                p2 = float(stats.get("phase2_time_s") or 0.0)
                st.caption(f"Phase 1 (feasible) time: {p1:.1f}s · Phase 2 (optimize) time: {p2:.1f}s")

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
            with st.expander("DRR & continental weighting (last run)"):
                st.write(
                    {
                        "DRR strict-domain min/sum (pre-solve)": (
                            stats.get("drr_strict_domain_min"),
                            stats.get("drr_strict_domain_sum"),
                        ),
                        "Cont. postpone objective mult": stats.get("cont_postpone_objective_mult"),
                        "DRR selection": stats.get("drr_selection"),
                    }
                )
            with st.expander("Optimizer options (last run)"):
                st.json(stats.get("optimizer_options") or {})
        else:
            st.warning(res.message)
            if res.log_lines:
                with st.expander("Load / solve log"):
                    st.code("\n".join(res.log_lines[-80:]), language="text")

    with tab_cal:
        st.subheader("Season calendar (data-backed)")
        st.caption(
            "Uses `output/phases/03b_season_day_ledger.csv` from the last optimization run "
            "and the active `optimized_schedule.csv` (or in-memory result)."
        )
        ledger_path = OUTPUT / "phases" / "03b_season_day_ledger.csv"
        ledger = load_day_ledger_csv(ledger_path)
        sched_cal = _schedule_dataframe()
        if ledger is None or ledger.empty:
            st.warning(
                f"No day ledger at `{ledger_path.relative_to(REPO_ROOT)}`. "
                "Run **Run optimization** in the sidebar once (writes all `output/phases/*` artifacts)."
            )
        else:
            ym_list = sorted({(d.year, d.month) for d in ledger["Date"].dropna().tolist()})
            labels = [f"{y}-{m:02d}" for y, m in ym_list]
            idx = st.selectbox("Month", options=list(range(len(labels))), format_func=lambda i: labels[i])
            y, m = ym_list[idx]
            if "calendar_pick" not in st.session_state:
                st.session_state["calendar_pick"] = None
            render_month_calendar(year=y, month=m, ledger=ledger, sched=sched_cal)
            st.divider()
            render_day_detail(d=st.session_state.get("calendar_pick"), ledger=ledger, sched=sched_cal)
            st.caption("Tip: pick a month, click a day number, then read the detail block below.")

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
