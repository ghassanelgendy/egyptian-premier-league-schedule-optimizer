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
MIN_REST_DAYS_CAF = 4          # league-to-CAF:    dates at least 5 apart
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
HARD_MAX_MATCHES_PER_WEEK = 12  # hard upper bound
SOFT_MIN_MATCHES_PER_WEEK = 6
SOFT_MAX_MATCHES_PER_WEEK = 12

# ---------------------------------------------------------------------------
# Slot concurrency (EPL staggered-kickoff style)
# ---------------------------------------------------------------------------
MAX_MATCHES_PER_SLOT = 2  # at most 2 matches at the same kickoff time

# ---------------------------------------------------------------------------
# Soft-objective weights  (higher = more important)
# ---------------------------------------------------------------------------
W_ROUND_ORDER = 100       # keep rounds in chronological week order
W_WEEK_UNDERLOAD = 50     # penalty per match below SOFT_MIN per week
W_WEEK_OVERLOAD = 50      # penalty per match above SOFT_MAX per week
W_TRAVEL = 1              # per-km travel penalty
W_TIER_MISMATCH = 20      # match-tier vs slot-tier gap
W_CAF_PREFERRED = 10      # bonus for achieving 6-day CAF gap instead of 5

# ---------------------------------------------------------------------------
# Solver limits
# ---------------------------------------------------------------------------
BASELINE_SOLVER_TIME_LIMIT_S = 600   # 5 minutes
REPAIR_SOLVER_TIME_LIMIT_S = 60     # 1 minute (much smaller model)

# ---------------------------------------------------------------------------
# Default random seed
# ---------------------------------------------------------------------------
DEFAULT_SEED = 42

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
DATA_MODEL_PATH = "data/Data_Model.xlsx"
EXPANDED_CALENDAR_PATH = "data/expanded_calendar.xlsx"

OUTPUT_DIR = "output"
PHASES_DIR = "output/phases"
