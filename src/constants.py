"""Centralized configuration constants for the EPL schedule optimizer."""

# ---------------------------------------------------------------------------
# League structure
# ---------------------------------------------------------------------------
NUM_TEAMS = 18
NUM_ROUNDS = 34          # (NUM_TEAMS - 1) * 2
MATCHES_PER_ROUND = 9    # NUM_TEAMS // 2

# ---------------------------------------------------------------------------
# Rest-day rules (measured in *full* rest days; "days apart" = rest_days + 1)
# ---------------------------------------------------------------------------
MIN_REST_DAYS_LOCAL = 3        # league-to-league: dates at least 4 apart
MIN_REST_DAYS_CAF = 3          # league-to-CAF:    dates at least 4 apart
PREFERRED_REST_DAYS_CAF = 5    # preferred:        dates at least 6 apart

# ---------------------------------------------------------------------------
# Home/away streak cap
# ---------------------------------------------------------------------------
MAX_CONSECUTIVE_HOME = 2
MAX_CONSECUTIVE_AWAY = 2

# ---------------------------------------------------------------------------
# Week load balancing (hard bounds + soft target)
# ---------------------------------------------------------------------------
HARD_MIN_MATCHES_PER_WEEK = 6   # hard lower bound (skipped for tiny weeks)
HARD_MAX_MATCHES_PER_WEEK = 18  # supports midweek + weekend rounds in safe weeks
SOFT_MIN_MATCHES_PER_WEEK = 6
SOFT_MAX_MATCHES_PER_WEEK = 12

# ---------------------------------------------------------------------------
# Day and slot concurrency
# ---------------------------------------------------------------------------
MAX_MATCHES_PER_DAY = 3   # at most 3 league matches on one calendar date
MAX_MATCHES_PER_SLOT = 2  # at most 2 matches at the same kickoff time
MIN_DAYS_BETWEEN_ROUNDS = 1  # 1 forbids same-day round overlap; 2 adds one idle day
MIN_STADIUM_SERVICE_GAP_DAYS = 2  # Updated per request
# ---------------------------------------------------------------------------
# Round window policy
# ---------------------------------------------------------------------------
NON_FINAL_ROUND_BASE_WINDOW_DAYS = 5
NON_FINAL_ROUND_MAX_WINDOW_DAYS = 28
NON_FINAL_ROUND_EPL_FALLBACK_WINDOW_DAYS = 56
NON_FINAL_ROUND_MIN_SLOT_COUNT = NON_FINAL_ROUND_BASE_WINDOW_DAYS * MAX_MATCHES_PER_DAY
NON_FINAL_ROUND_MIN_FEASIBLE_SLOTS_PER_MATCH = MATCHES_PER_ROUND

# ---------------------------------------------------------------------------
# Final-round publication rule
# ---------------------------------------------------------------------------
FINAL_ROUND_NUM = NUM_ROUNDS
ENFORCE_FINAL_ROUND_SINGLE_DAY = True
ENFORCE_FINAL_ROUND_SINGLE_SLOT = True
FINAL_ROUND_SHARED_DATE_IN_FINAL_SCHEDULE = True
FINAL_ROUND_SHARED_SLOT_IN_FINAL_SCHEDULE = True
FINAL_ROUND_MAX_MATCHES_PER_DAY = MATCHES_PER_ROUND
FINAL_ROUND_MAX_MATCHES_PER_SLOT = MATCHES_PER_ROUND

# ---------------------------------------------------------------------------
# Soft-objective weights  (higher = more important)
# ---------------------------------------------------------------------------
W_ROUND_ORDER = 100       # keep rounds in chronological week order
W_WEEK_UNDERLOAD = 50     # penalty per match below SOFT_MIN per week
W_WEEK_OVERLOAD = 50      # penalty per match above SOFT_MAX per week
W_TRAVEL = 1              # per-km travel penalty
W_TIER_MISMATCH = 20      # match-tier vs slot-tier gap
W_CAF_PREFERRED = 10      # bonus for achieving 6-day CAF gap instead of 5

W_EVENING_PREFERENCE = 50     # per-hour penalty for kickoff before 21:00 (encourages 8pm/10pm)
W_SLOT_SPREAD = 500           # penalty for >1 match in same slot on same day (spread across times)

W_STADIUM_MAINTENANCE_OVERLAP = 5_000_000  # penalty for back-to-back stadium use
ALT_STADIUM_RELIEF_PENALTY = 1_000_000     # base penalty for using alternate stadium
OTHER_STADIUM_RELIEF_PENALTY = 3_000_000   # base penalty for using a non-home, non-alt fallback venue
W_HOME_VENUE_DISPLACEMENT = 1              # per-km penalty for moving a home team away from its primary stadium

# ---------------------------------------------------------------------------
# Multi-Objective Normalization Denominators (N_i)
# ---------------------------------------------------------------------------
NORM_STADIUM_MAINTENANCE_OVERLAP = 10
NORM_ALT_STADIUM_RELIEF = 100
NORM_OTHER_STADIUM_RELIEF = 50
NORM_ROUND_ORDER = 200
NORM_HOME_VENUE_DISPLACEMENT = 5000
NORM_WEEK_UNDERLOAD = 50
NORM_WEEK_OVERLOAD = 50
NORM_TRAVEL = 50000
NORM_TIER_MISMATCH = 300
NORM_CAF_PREFERRED = 50
NORM_EVENING_PREFERENCE = 200
NORM_SLOT_SPREAD = 50

# ---------------------------------------------------------------------------
# Multi-Objective Optimization (MOO) Settings
# ---------------------------------------------------------------------------
MOO_MODE = "NORMALIZED_WEIGHTED_SUM"   # choices: "WEIGHTED_SUM", "NORMALIZED_WEIGHTED_SUM"
USE_AHP_WEIGHTS = False

# ---------------------------------------------------------------------------
# Solver limits
# ---------------------------------------------------------------------------
BASELINE_SOLVER_TIME_LIMIT_S = 600   # 5 minutes
REPAIR_SOLVER_TIME_LIMIT_S = 60     # 1 minute (much smaller model)

# ---------------------------------------------------------------------------
# Default random seed
# ---------------------------------------------------------------------------
DEFAULT_SEED = 88  # Updated per request

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
DATA_MODEL_PATH = "data/Data_Model.xlsx"
EXPANDED_CALENDAR_PATH = "data/expanded_calendar.xlsx"

OUTPUT_DIR = "output"
PHASES_DIR = "output/phases"
