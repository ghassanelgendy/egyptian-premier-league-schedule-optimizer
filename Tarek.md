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

---

## 5. Comparison: Normalized Weighted Sum vs. Weighted Sum

The optimizer supports two primary formulation modes. Here is the mathematical comparison:

### 1. Classical Weighted Sum Method
The classical weighted sum minimizes the raw weighted sum of the objectives:
* Objective = sum( W_i * f_i(X) )
Where f_i(X) is the raw value of objective i (e.g., 55,000 kilometers of travel, 10 stadium overlaps).

* **Limitation (Dimensional Inhomogeneity):** It directly adds values of different units (kilometers, weeks, match counts). Because travel distance is numerically massive (in the tens of thousands), it completely dominates the objective function. The solver will ignore small-scale objectives like stadium turnaround overlaps or slot collisions, rendering their weights ineffective unless they are manually scaled up by millions.

### 2. Normalized Weighted Sum Method (Additive Utility)
The normalized weighted sum scales all objectives using normalization constants N_i to make them dimensionless:
* Objective = sum( w_i * [ f_i(X) / N_i ] )
Where w_i represents the normalized relative weights (sum of w_i = 1.0) and N_i represents the normalization constant (e.g. 50,000 for travel, 10 for overlaps).

* **Advantage:** By dividing each raw value f_i(X) by its normalizer N_i, all objectives are transformed into a dimensionless disutility score between 0.0 and 1.5. This ensures that a 10% increase in travel distance has the same mathematical impact as a 10% increase in stadium overlaps when weights are equal. The weights w_i represent true decision-maker priorities.

---

## 6. System Modifications & Recent Enhancements Log

The following changes have been successfully implemented:

### 1. Decimal AHP Weights
* High-level criteria weights are displayed as decimals in the range [0.0, 1.0] (instead of percentages) under the AHP comparisons matrix setup, ensuring mathematical transparency and verification of sum(w_i) = 1.0.

### 2. Real-Time AHP Consistency Advisor
* The system computes target consistent slider values:
  Target_Slider_ij = w_i / w_j
* If the Consistency Ratio (CR) is 0.10 or higher, the Consistency Advisor identifies the slider with the largest absolute deviation from its consistent target and displays a suggestion guiding the user on how to adjust it to achieve mathematical consistency.

### 3. Multi-Objective Performance Breakdown Table
* Added a breakdown table to the Insights Overview tab showing for each objective:
  - Metric Name
  - Raw Value f_i(X)
  - Normalizer N_i
  - Normalized Score d_i(X) = f_i(X) / N_i
  - Relative Weight w_i
  - Weighted Contribution = w_i * d_i(X)
* The sum of the weighted contributions matches the overall disutility score U(X) = sum( w_i * d_i(X) ).

### 4. Normalized Solver Status and JSON Reporting
* The solver status output file "06_baseline_solver_status.json" now logs both the final objective score and the individual objective breakdown in their normalized, dimensionless forms:
  - objective = Raw solver objective / 100,000
  - breakdown_i = Raw breakdown_i / N_i
* All Streamlit displays (Run & Progress, Insights, Monte Carlo) have been updated to dynamically render these decimal normalized values.

---

## 7. Step-by-Step Optimization Workflow & Methodology

The complete execution pipeline of the hybrid AHP-MODM scheduling framework flows step-by-step from user preferences to the final normalized results:

### Step 1: Decision-Maker Preferences (AHP Setup)
* **Action:** The user configures relative preferences between the 5 high-level criteria (Venue Rest, Travel, Chronology, Weekly Balance, Slot Quality) on the AHP UI panel.
* **Math:** The system maps the sliders (-8 to 8) to Saaty's 1-9 scale and constructs a 5x5 pairwise comparison matrix.
* **Consistency Check:** If the Consistency Ratio (CR) is 0.10 or higher, the Consistency Advisor recommends which slider to adjust. Once CR is below 0.10, the principal eigenvector is calculated using Power Iteration to yield 5 high-level weights that sum to exactly 1.0.

### Step 2: Sub-Objective Weight Mapping
* **Action:** The system maps the 5 criteria weights to 12 sub-metric weights (W_i) representing the individual soft constraints in the solver.
* **Math:** Weights are distributed proportionally based on empirical importance coefficients (e.g., Venue Rest weight is split into 85% stadium overlaps, 7% alternate venue relief, 5% other venue relief, and 3% home venue displacement).
* **Output:** All 12 mapped sub-metric weights sum to exactly 1.0.

### Step 3: CP-SAT Integerization and Normalization
* **Action:** Because Google OR-Tools CP-SAT only supports integer math, weights and normalizers are combined and scaled to build integer objective coefficients.
* **Math:** The solver calculates an integer coefficient for each objective:
  Solver_Weight_i = round( (W_i / sum(W_k)) * (100,000 / N_i) )
* **Objective Function:** The solver's internal objective function is formulated as:
  Minimize: sum( Solver_Weight_i * f_i(X) )
  Where f_i(X) represents the raw variables (like kilometers traveled, overlaps counted).

### Step 4: Constrained Search & Optimization
* **Action:** The CP-SAT solver is initiated.
* **Execution:** The solver searches the combinatorial space of matches, slots, and rounds, strictly enforcing hard constraints (FIFA calendar windows, team rest days, stadium overlaps) while minimizing the integerized disutility objective function.

### Step 5: Post-Solve Evaluation & Normalization
* **Action:** Once the solver completes and returns a schedule X, the post-solver evaluator parses the schedule.
* **Evaluation:** 
  1. Computes the raw metrics f_i(X) (e.g. total travel distance = 55,380 km, slot collisions = 45).
  2. Divides each raw metric by its normalizer denominator N_i to obtain the dimensionless normalized disutility score:
     d_i(X) = f_i(X) / N_i
  3. Divides the raw CP-SAT objective score (e.g., 98,304) by the 100,000 scaling factor to yield the normalized objective (e.g., 0.9830).
  4. Calculates the overall additive disutility score:
     U(X) = sum( w_i * d_i(X) )

### Step 6: Output Visualization and Reporting
* **Action:** The normalized objective score (0.9830) and the normalized breakdown dictionary are logged to "06_baseline_solver_status.json".
* **Dashboard Display:** The Streamlit dashboard displays the normalized metrics on the Run & Progress tab, and renders the detailed breakdown table under Insights -> Overview, verifying that the relative weights sum to 1.0 and showing the exact disutility contribution of each soft constraint.

---

## 8. AHP Method Details & Slider Interface Interpretation

To make the multi-objective weights selection intuitive for the user, the dashboard wraps Saaty's Analytic Hierarchy Process (AHP) in a 10-slider interface.

### 1. The Meaning of Each Slider (-8 to 8)
Each slider compares two high-level criteria (Criterion A vs. Criterion B) on a scale from -8 to 8, which represents Saaty's relative importance index:
* **Slider Value = 0 (Equal Importance):** Both criteria have equal importance. The comparison matrix entry is set to 1.0.
* **Slider Value is Positive (e.g. +2, Left is more important):** Criterion A is more important than Criterion B. The value is mapped to (Slider + 1) on Saaty's scale (e.g., +2 maps to 3, representing "Slightly More Important").
* **Slider Value is Negative (e.g. -2, Right is more important):** Criterion B is more important than Criterion A. The value is mapped to 1 / (|Slider| + 1) on Saaty's scale (e.g., -2 maps to 1/3, representing "Slightly Less Important").

The system uses these values to fill the pairwise matrix entry `a_ij` and sets `a_ji` to its reciprocal `1 / a_ij`.

### 2. Why 5 High-Level Criteria instead of 8 or 12 Objectives?
Comparing all 12 solver objectives (or even 8 objectives) directly is mathematically and cognitively impractical:
* **Cognitive Limit (Miller's Law):** Human decision-makers cannot consistently compare more than 7 (+/- 2) items at a time without making contradictory judgments (e.g. A > B, B > C, but C > A).
* **Combinatorial Explosion of Comparisons:** The number of comparisons required for N items is calculated as:
  Comparisons = N * (N - 1) / 2
  - **For 5 Criteria:** 10 comparisons (10 sliders). This is highly manageable and takes a user under 2 minutes.
  - **For 8 Criteria:** 28 comparisons (28 sliders). This leads to high user fatigue and results in highly inconsistent weights.
  - **For 12 Criteria:** 66 comparisons (66 sliders). This is practically unusable for human decision-makers.

### 3. Hierarchical Decomposition
To solve this, AHP groups the 12 sub-objectives into 5 high-level logical categories:
1. **Venue Rest & Integrity (VR):** Turns overlaps, relief stadiums, and home venue changes.
2. **Travel Efficiency (TE):** Away team travel kilometers.
3. **Round Chronology (RC):** Scheduling round order and calendar delay.
4. **Weekly Balance (WB):** Match counts per week.
5. **Broadcasting & Slot Quality (BQ):** Kickoff slots, match tiers, and scheduling spreads.

By comparing only these 5 categories (10 sliders), the user determines their high-level preferences. The system then automatically distributes these weights to the 12 sub-objectives proportionally based on their baseline ratios, combining mathematical precision with a simple, consistent user experience.

---

## 9. Solver Integerization (The 100,000 Scaling Factor) & Objective Proportionality

Google OR-Tools CP-SAT is a pure Integer Programming solver. To execute the Normalized Weighted Sum within this environment, the model must scale and integerize its weights and divisions.

### 1. Why the 100,000 Multiplier?
In a pure normalized model, the objective coefficient for a variable represents:
* Coefficient_i = Weight_i / Denominator_i
Because weights are decimals (e.g. 0.20) and denominators can be very large (e.g. 50,000 for travel), the raw mathematical terms become extremely small decimals:
* Travel Coefficient Term = 0.20 / 50,000 = 0.000004
If we directly rounded these small decimals to integers, they would collapse to 0. The solver would completely neglect travel distance, treating it as if it has no weight at all.

To prevent this collapse, the entire objective function is multiplied by a large scaling factor of **100,000**:
* Solver_Weight_i = round( (User_Weight_i / Total_User_Weights) * (100,000 / Denominator_i) )

Multiplying by 100,000 scales up the decimal coefficients so that even the smallest weight-to-denominator ratio remains represented by a non-zero integer coefficient.

### 2. Safeguarding Against Neglected Objectives
To guarantee that absolutely no objective is ever ignored or neglected by the solver, the code applies a mathematical lower bound clamp of **1** to all solver weights:
* Solver_Weight_i = max( 1, round( (User_Weight_i / Total_User_Weights) * (100,000 / Denominator_i) ) )

If an objective has a very small weight that would round down to 0, the `max(1, ...)` operator forces its coefficient to be at least 1. This ensures that every single active soft constraint retains a mathematical presence inside the solver search.

### 3. Proportionality & Nearness of Contributions
By dividing each objective's raw count by its normalization denominator (N_i), the solver evaluates them on a mathematically comparable scale. Here is how it behaves during search:
* **For Travel Distance (Raw = 55,000 km, N_travel = 50,000):**
  Solver contribution = (User_Weight * 55,000 / 50,000) * 100,000 = User_Weight * 110,000
* **For Same-Day Reuse Overlaps (Raw = 1 overlap, N_reuse = 10):**
  Solver contribution = (User_Weight * 1 / 10) * 100,000 = User_Weight * 10,000

Because the contributions (110,000 vs. 10,000) are within the same order of magnitude, the solver can make intelligent tradeoffs. It will gladly accept a minor increase of 100 km of travel (which adds 200 units to the objective) to resolve a single same-day reuse overlap (which subtracts 10,000 units from the objective), ensuring all constraints are optimized proportionally according to the user's priorities.
