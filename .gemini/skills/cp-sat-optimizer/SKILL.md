---
name: cp-sat-optimizer
description: Specialized guidance for debugging and optimizing OR-Tools CP-SAT models in the EPL scheduling context.
---

# cp-sat-optimizer

Specialized guidance for debugging and optimizing OR-Tools CP-SAT models in the EPL scheduling context.

## Instructions

- Use this skill when working with `src/baseline_solver.py` or any CP-SAT related code.
- Refer to `references/debugging.md` for infeasibility analysis.
- Ensure all hard constraints (H1-H12) are correctly modeled.
- Optimize for `W_ROUND_ORDER`, `W_WEEK_UNDERLOAD`, `W_WEEK_OVERLOAD`, `W_TRAVEL`, `W_TIER_MISMATCH`, and `W_CAF_PREFERRED`.

## Reference Files

- `references/debugging.md`: Common debugging steps for CP-SAT infeasibility.
