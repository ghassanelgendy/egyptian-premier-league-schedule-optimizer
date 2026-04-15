"""Run the actual H8 repair on the real ScheduledMatch objects via main pipeline."""
import sys
sys.path.insert(0, '.')

# Reproduce exactly what main.py does up to Phase 5b
from src.data_loader import load_data
from src.fixture_generator import generate_drr
from src.baseline_solver import solve_baseline
from src.domain_builder import build_domains
from src.caf_audit import caf_audit
from src.h8_repair import count_h8_violations, repair_h8

import pandas as pd
import pickle, os

CACHE = 'debug_schedule_cache.pkl'

data = load_data()

if os.path.exists(CACHE):
    print("Loading cached schedule...")
    with open(CACHE, 'rb') as f:
        accepted = pickle.load(f)
else:
    print("No cache. Run main.py first, then this script re-uses output.")
    sys.exit(1)

print(f"Loaded {len(accepted)} matches.")
combined = list(accepted)
pre = count_h8_violations(combined)
print(f"H8 violations before repair: {pre}")
if pre > 0:
    result = repair_h8(combined, data, max_iters=10)
    post = count_h8_violations(result)
    print(f"H8 violations after repair: {post}")
