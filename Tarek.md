# Multi-Objective Optimization & Decision Theory Formulation

This document outlines the formal mathematical framework used in the Egyptian Premier League Schedule Optimizer, aligning the codebase with academic standards of Multi-Criteria Decision Making (MCDM).

---

## 1. Decision Theory Paradigms: MODM vs. MADM

In Operations Research, **Multi-Criteria Decision Making (MCDM)** is divided into two primary subfields:

1. **Multi-Objective Decision Making (MODM)**: Focuses on optimization problems over a continuous or combinatorially large feasible region defined by mathematical constraints. It features decision variables, constraints, and objective functions.
2. **Multi-Attribute Decision Making (MADM / MCDA)**: Focuses on ranking, sorting, or selecting from a finite, discrete set of pre-existing alternatives.

### The Hybrid AHP-MODM Framework
Our league schedule optimizer solves a **MODM** problem because it searches a combinatorial space of billions of possible fixture permutations to find an optimal schedule. 

However, assigning objective weights in a weighted-sum objective is traditionally subjective. To solve this, we employ a **Hybrid AHP-MODM framework**:
* **Phase 1 (MADM - AHP)**: We use Saaty's **Analytic Hierarchy Process (AHP)** to mathematically calculate objective weights from pairwise comparisons, ensuring mathematical consistency.
* **Phase 2 (MODM - Integer Programming)**: We feed the calculated weights into the **Additive Utility Function** objective of our CP-SAT integer programming solver to find the optimal schedule.

---

## 2. Multi-Objective Formulation (Additive Utility Theory)

The schedule optimization problem is mathematically defined as a Vector Optimization Problem (VOP):

$$\text{Minimize } [f_1(X), f_2(X), \dots, f_k(X)]$$
$$\text{subject to } X \in \mathbb{M}$$

Where:
* $X$ is the matrix of assignment decisions.
* $\mathbb{M}$ is the feasible domain defined by the hard constraints (stadium availability, team rest, streaks).
* $f_i(X)$ are the individual objective functions (travel, overlaps, scheduling deviations).

### Additive Utility Function (Weighted Sum)
Under Multi-Attribute Utility Theory (MAUT), if the objectives are additive, we transform the vector problem into a single scalar objective by maximizing a global utility function (or minimizing global disutility):

$$\text{Minimize } U(X) = \sum_{i=1}^{k} w_i \cdot d_i(f_i(X))$$

Where:
* $d_i(f_i(X)) = \frac{f_i(X)}{N_i}$ is the normalized **disutility function** mapping the raw objective to a dimensionless scale of $[0, 1]$.
* $N_i$ is the normalization denominator representing the worst-case reasonable value (nadir approximation) for objective $i$.
* $w_i$ is the weight of importance assigned to objective $i$, satisfying the conditions:
$$\sum_{i=1}^{k} w_i = 1, \quad w_i \ge 0$$

### Objective Normalization Denominators ($N_i$)
To maintain dimensional homogeneity (not adding kilometers to hours or occurrences), we normalize the raw metrics using the following physical scaling denominators ($N_i$):

| Objective ($f_i$) | Normalization Constant ($N_i$) | Physical Unit | Physical Basis for $N_i$ |
| :--- | :--- | :--- | :--- |
| **Stadium Maintenance Overlaps** | $N_{overlap} = 10$ | Occurrences | Max tolerable overlaps per season |
| **Alt Venue Relief** | $N_{alt} = 100$ | Occurrences | Expected alternative stadium usages |
| **Other Venue Relief** | $N_{other} = 50$ | Occurrences | Expected neutral stadium usages |
| **Round Order Deviation** | $N_{round} = 200$ | Weeks | Worst-case cumulative round delays |
| **Venue Displacement** | $N_{disp} = 5,000$ | Kilometers (km) | Upper bound on home displacement travel |
| **Weekly Underload** | $N_{under} = 50$ | Matches | Worst-case cumulative weekly match shortfalls |
| **Weekly Overload** | $N_{over} = 50$ | Matches | Worst-case cumulative weekly match excesses |
| **Away Travel Distance** | $N_{travel} = 50,000$ | Kilometers (km) | Upper bound on total away travel (306 matches) |
| **Tier Mismatch** | $N_{tier} = 300$ | Tier levels | Total mismatch index in an unaligned schedule |
| **Evening Kickoff Preference** | $N_{evening} = 200$ | Hours | Total early kickoff hour penalties |
| **Slot Spread Collisions** | $N_{spread} = 50$ | Occurrences | Max slot concurrency collisions |

### Detailed Derivations of Normalization Constants ($N_i$)

To mathematically justify the selected values of $N_i$, they are derived directly from the physical and structural parameters of the Egyptian Premier League (18 teams, 34 rounds, 306 matches per season):

1. **Away Travel Distance ($N_{travel} = 50,000$ km)**:
   * **Justification**: There are 306 matches in a season. Based on Egypt's geography, the average away travel distance is ~163 km (e.g. Cairo to Alexandria is ~200 km, local Cairo derbies are 0 km, trips to Suez/Ismailia are ~130 km, and trips to Aswan are ~900 km).
   * **Math**: $306 \text{ matches} \times 163.4 \text{ km/match} \approx 50,000 \text{ km}$. This forms the empirical upper limit of seasonal travel.

2. **Venue Displacement ($N_{disp} = 5,000$ km)**:
   * **Justification**: Cumulative distance traveled by home teams forced to play away from their primary stadiums.
   * **Math**: Assuming an average of 15 matches per season are displaced by an average of 333 km (e.g. playing in Alexandria instead of Cairo): $15 \text{ matches} \times 333 \text{ km} = 5,000 \text{ km}$.

3. **Round Order Deviation ($N_{round} = 200$ weeks)**:
   * **Justification**: Cumulative week deviations of matches from their ideal chronological round weeks.
   * **Math**: Assuming a highly postponed season where 100 matches are delayed by an average of 2 weeks due to international or CAF matches: $100 \text{ matches} \times 2 \text{ weeks} = 200 \text{ weeks}$.

4. **Evening Kickoff Hour Penalty ($N_{evening} = 200$ hours)**:
   * **Justification**: Penalizes kickoffs before 21:00 (e.g. 17:00 kickoffs receive a 4-hour penalty).
   * **Math**: Assuming 80 matches are scheduled early in hot months with an average penalty of 2.5 hours: $80 \text{ matches} \times 2.5 \text{ hours} = 200 \text{ hours}$.

5. **Weekly Underload ($N_{under} = 50$ matches) & Overload ($N_{over} = 50$ matches)**:
   * **Justification**: Match deviations below the soft weekly minimum (6) or above the soft weekly maximum (12).
   * **Math**: In a congested calendar, if 16 weeks experience average loads outside the soft range by ~3.1 matches: $16 \text{ weeks} \times 3.1 \text{ matches} \approx 50 \text{ matches}$.

6. **Alt Venue Relief ($N_{alt} = 100$ occurrences)**:
   * **Justification**: Playing at alternate home venues.
   * **Math**: If 6 teams play half of their home games (8.5 games) at alternate stadiums: $6 \text{ teams} \times 8.5 \text{ matches} \approx 50$ occurrences. Across the entire league, 100 is the typical worst-case upper bound.

7. **Other Venue Relief ($N_{other} = 50$ occurrences)**:
   * **Justification**: Highly undesirable usage of neutral venues. 50 occurrences is the absolute safety/security tolerance limit before the season's logistics are considered broken.

8. **Stadium Maintenance Overlaps ($N_{overlap} = 10$ occurrences)**:
   * **Justification**: Stadium hosting matches within the service gap (e.g., 3 days). A high-quality schedule must have 0 overlaps. 10 is established as the absolute worst-case limit of stadium tolerance.

9. **Tier Mismatch ($N_{tier} = 300$ levels)**:
   * **Justification**: Mismatches between match tiers and slot tiers.
   * **Math**: If 150 matches are scheduled in sub-optimal slots by an average of 2 tier levels: $150 \text{ matches} \times 2 \text{ levels} = 300 \text{ tier levels}$.

10. **Slot Spread Collisions ($N_{spread} = 50$ occurrences)**:
    * **Justification**: More than 1 match scheduled in the same kickoff slot on the same day.
    * **Math**: If 25 slots suffer from concurrency collisions, affecting 50 matches: $25 \text{ collisions} \times 2 = 50 \text{ occurrences}$.

11. **CAF Preferred Rest ($N_{caf\_pref} = 50$ occurrences)**:
    * **Justification**: Potential matches where CAF-participating teams can achieve an ideal 6-day rest window. This is limited by the total number of CAF domestic/international slot alignments.

---

## 3. Weight Determination: Analytic Hierarchy Process (AHP)

To mathematically derive the weight vector $w$, the Decision Maker (DM) performs pairwise comparisons on **5 high-level criteria** rather than comparing all 12 sub-metrics (which would require a tedious 66 comparisons).

### The 5 High-Level Criteria
1. **Venue Rest & Integrity (VR)**: Restricting back-to-back stadium use and minimizing home venue changes.
2. **Travel Efficiency (TE)**: Reducing total travel distance for away teams.
3. **Round Chronology (RC)**: Preserving chronological week orders and avoiding round-to-week spillovers.
4. **Weekly Balance (WB)**: Spreading matches evenly across calendar weeks.
5. **Broadcasting & Slot Quality (BQ)**: Optimizing evening kickoff slots, match quality tiers, and slot concurrency.

### Step 1: Pairwise Comparison Matrix ($A$)
The DM constructs a $5 \times 5$ matrix $A$, where $a_{ij}$ represents the relative importance of criterion $i$ over criterion $j$ on Saaty's 1–9 scale:

$$A = \begin{pmatrix}
1 & a_{12} & a_{13} & a_{14} & a_{15} \\
1/a_{12} & 1 & a_{23} & a_{24} & a_{25} \\
1/a_{13} & 1/a_{23} & 1 & a_{34} & a_{35} \\
1/a_{14} & 1/a_{24} & 1/a_{34} & 1 & a_{45} \\
1/a_{15} & 1/a_{25} & 1/a_{35} & 1/a_{45} & 1
\end{pmatrix}$$

### Step 2: Weight Vector Calculation (Principal Eigenvector)
The weights correspond to the normalized principal eigenvector of matrix $A$:

$$A w = \lambda_{max} w$$

We calculate this numerically using the **Power Iteration Method**:
1. Start with $w^{(0)} = [0.2, 0.2, 0.2, 0.2, 0.2]^T$.
2. Iteratively compute $v^{(t)} = A w^{(t-1)}$ and normalize: $w^{(t)} = \frac{v^{(t)}}{\|v^{(t)}\|_1}$.
3. Stop when $\|w^{(t)} - w^{(t-1)}\| < 10^{-6}$.
4. Estimate the maximum eigenvalue $\lambda_{max} = \frac{1}{n} \sum_{i=1}^{n} \frac{(A w)_i}{w_i}$.

### Step 3: Consistency Verification
To ensure the DM's judgments are mathematically consistent:
1. Compute the **Consistency Index (CI)**:
   $$CI = \frac{\lambda_{max} - 5}{4}$$
2. Compute the **Consistency Ratio (CR)**:
   $$CR = \frac{CI}{RI_5}$$
   Where Saaty's Random Index for $5 \times 5$ matrices is $RI_5 = 1.12$.
3. If $CR < 0.10$, the weights are mathematically consistent and accepted. If $CR \ge 0.10$, the DM's comparisons are inconsistent and must be revised.

### Step 4: Sub-metric Mapping
The calculated high-level weights ($w_{VR}, w_{TE}, w_{RC}, w_{WB}, w_{BQ}$) are distributed to the 12 sub-metric weights ($W_j$) proportionally based on their standard default ratios, ensuring $\sum_{j=1}^{12} W_j = 1.0$.

---

## 4. Empirical Evaluation: Decision Support & Metric Breakdown Dashboard

To bridge the gap between abstract mathematical formulas and decision-making utility, the system incorporates two real-time feedback loops:

### 1. Interactive AHP Consistency Advisor
Saaty's AHP allows for subjective inconsistency, but requires the Consistency Ratio ($CR$) to remain below $0.10$ to be mathematically valid. To guide the user toward a consistent comparisons matrix:
* **Ideal Consistent Target**: For any comparison $a_{ij}$ between criteria $i$ and $j$, the mathematically consistent target value is the ratio of their computed weights:
  $$a'_{ij} = \frac{w_i}{w_j}$$
* **Inconsistency Advisor**: The system calculates the error between the user's selected slider value $S_{ij}$ and the consistent target slider value $S'_{ij}$ (derived by mapping $a'_{ij}$ back to the $[-8, 8]$ scale) for all 10 pairwise comparisons. 
* **Correction Suggestion**: If $CR \ge 0.10$, the system highlights the comparison $(i, j)$ with the largest absolute error $|S_{ij} - S'_{ij}|$ and recommends moving it towards $S'_{ij}$, guaranteeing a rapid convergence to a valid, consistent matrix.

### 2. Multi-Objective Performance Breakdown
Once the CP-SAT solver generates a schedule $X$, the dashboard decomposes the global objective score into its constituent disutility functions. It computes and displays:
1. **Raw Metric Value $f_i(X)$**: The physical count (e.g., total kilometers, number of overlaps).
2. **Dimensionless Normalized Disutility $d_i(X) = f_i(X) / N_i$**: The scaled disutility for each objective.
3. **Normalized Weights $w'_i$**: The sub-metric weights normalized over the active solver objectives to ensure they sum to exactly 1.0:
   $$w'_i = \frac{w_i}{\sum_{k \in \text{active}} w_k}, \quad \sum w'_i = 1.0$$
4. **Weighted Contribution $C_i(X) = w'_i \cdot d_i(X)$**: The direct contribution of objective $i$ to the overall schedule disutility.

The total sum of these contributions matches the overall disutility score:
$$U(X) = \sum_{i=1}^{k} C_i(X)$$

This breakdown allows the Egyptian Football Association (EFA) to immediately identify which scheduling compromises (e.g., travel vs. kickoff slots) are driving the disutility score of the generated schedule.
