"""AHP (Analytic Hierarchy Process) weight calculation engine."""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

# Saaty's Random Index (RI) table for consistency check
# RI values for matrices of size 1 to 10
SAATY_RI = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}


def calculate_ahp_weights(matrix: List[List[float]]) -> Tuple[List[float], float]:
    """
    Calculate AHP weights using the Principal Eigenvector method (Power Iteration).
    Returns the normalized weights list and the Consistency Ratio (CR).
    """
    n = len(matrix)
    if n <= 1:
        return [1.0] * n, 0.0

    # 1. Power Iteration to find principal eigenvector
    w = [1.0 / n] * n
    max_iter = 1000
    eps = 1e-6

    for _ in range(max_iter):
        next_w = [0.0] * n
        for i in range(n):
            for j in range(n):
                next_w[i] += matrix[i][j] * w[j]

        # Normalize next_w to sum to 1.0 (L1 norm)
        s = sum(next_w)
        if s > 0:
            next_w = [val / s for val in next_w]
        
        # Check convergence
        diff = sum(abs(next_w[i] - w[i]) for i in range(n))
        w = next_w
        if diff < eps:
            break

    # 2. Estimate maximum eigenvalue (lambda_max)
    # A * w = lambda * w  =>  lambda_i = (A*w)_i / w_i
    lambda_vals = []
    for i in range(n):
        aw_i = sum(matrix[i][j] * w[j] for j in range(n))
        if w[i] > 0:
            lambda_vals.append(aw_i / w[i])
        else:
            lambda_vals.append(0.0)
    
    lambda_max = sum(lambda_vals) / len(lambda_vals)

    # 3. Calculate Consistency Index (CI) and Consistency Ratio (CR)
    ci = (lambda_max - n) / (n - 1) if n > 1 else 0.0
    ri = SAATY_RI.get(n, 1.12)
    cr = ci / ri if ri > 0 else 0.0

    return w, cr


def map_criteria_to_subweights(criteria_weights: List[float]) -> Dict[str, float]:
    """
    Map the 5 high-level criteria weights to the 12 sub-metric weights
    proportionally based on their baseline default ratios.
    
    High-level criteria:
    0: Venue Rest & Integrity (VR)
    1: Travel Efficiency (TE)
    2: Round Chronology (RC)
    3: Weekly Balance (WB)
    4: Broadcasting & Slot Quality (BQ)
    """
    w_vr, w_te, w_rc, w_wb, w_bq = criteria_weights

    # Sub-metric mappings:
    # 1. Venue Rest & Integrity (VR) splits into 4 sub-metrics:
    #    Overlap is very critical (85%), alt relief (7%), other relief (5%), displacement (3%)
    subweights = {
        "W_STADIUM_MAINTENANCE_OVERLAP": w_vr * 0.85,
        "ALT_STADIUM_RELIEF_PENALTY": w_vr * 0.07,
        "OTHER_STADIUM_RELIEF_PENALTY": w_vr * 0.05,
        "W_HOME_VENUE_DISPLACEMENT": w_vr * 0.03,
        
        # 2. Travel Efficiency (TE) maps 100% to travel weight
        "W_TRAVEL": w_te * 1.0,
        
        # 3. Round Chronology (RC) maps 100% to round order weight
        "W_ROUND_ORDER": w_rc * 1.0,
        
        # 4. Weekly Balance (WB) splits 50/50 between underload and overload
        "W_WEEK_UNDERLOAD": w_wb * 0.50,
        "W_WEEK_OVERLOAD": w_wb * 0.50,
        
        # 5. Broadcasting & Slot Quality (BQ) splits into 4 sub-metrics:
        #    Slot spread is most critical (50%), evening kickoffs (25%), tier mismatch (20%), caf rest (5%)
        "W_SLOT_SPREAD": w_bq * 0.50,
        "W_EVENING_PREFERENCE": w_bq * 0.25,
        "W_TIER_MISMATCH": w_bq * 0.20,
        "W_CAF_PREFERRED": w_bq * 0.05,
    }

    return subweights
