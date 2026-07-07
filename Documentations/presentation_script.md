# Egyptian Premier League Schedule Optimizer: Presentation Script
## Phase 2 Graduation Project Presentation Guide

This document contains a comprehensive, slide-by-slide script and structural plan for the Phase 2 Graduation Project presentation. It is designed to run between 30 and 45 minutes. Mentions of individual presenters and team hand-off transitions have been omitted to allow flexible speaker assignments during the defense.

---

## 🎬 Slide-by-Slide Script & Visual Layout

### Slide 1: Title Slide (EPL Schedule Optimizer)
* **Visual Layout:**
  - Background: Custom Nile-League brand elements, gradient green and white Egyptian football theme.
  - Text: **Optimizing the Egyptian Premier League Schedule: A Mathematical Optimization Approach using Google OR-Tools CP-SAT**
  - Subtitle: Graduation Project - Phase 2 Defense
  - Team Names & IDs: Rawan Ehab (20220133), Mohamed Osama (20220477), Ibrahim Medhat (20221003), Ghassan Tarek (20220239), Abdelrahman Ashraf (20220189)
  - Under Supervision of: Dr. Sally Kassem, Eng. Rawaa Hesham (Cairo University, Faculty of Computers and Artificial Intelligence)
* **Speaking Script:**
  "Good morning, respected committee members and professors. Welcome to our graduation project defense for the 'Egyptian Premier League Schedule Optimizer'. Today, we present the culmination of our engineering and research efforts: a fully operational optimization engine running on Boolean Satisfiability (SAT) constraint solvers. We will show you how we solved one of the most complex, politically sensitive, and logistically congested scheduling problems in world football. Egyptian football is a source of national pride, but behind the scenes lies a scheduling nightmare. Our task was to replace arbitrary manual drafts with a rigid, mathematically proven, and automated system."

---

### Slide 2: Project Overview & Motivation
* **Visual Layout:**
  - Left panel: A high-level stakeholder diagram mapping:
    - **Governing Body (EFA/EPL)** (demands season start/end matching international calendars)
    - **Security Authorities** (stipulate venue bans and high-risk matches)
    - **Broadcasters (ONTime Sports)** (demand Tier-1 weekend slots for maximum viewers)
    - **Clubs (Al Ahly, Zamalek, Pyramids, etc.)** (demand fair rest windows and minimized travel fatigue)
  - Right panel: A bulleted list outlining the transition from Phase 1 to Phase 2.
* **Speaking Script:**
  "Scheduling a professional football league is not just about drawing dates out of a hat. In Egypt, it involves balancing highly conflicting demands from four major stakeholders. The league organizers want to finish by June. Broadcasters want Al Ahly and Zamalek to play on Friday evenings. Security forces want high-risk derbies played in neutral venues under specific conditions. And the clubs themselves are screaming for fair rest periods, especially those traveling across the continent.
  
  In Phase 1, we focused on database design, scraping historical data, and formulating the basic system architecture. In Phase 2, we present a complete, fully functional scheduling engine that translates raw operational rules into mathematical equations, runs them through an industrial-grade solver, audits continental conflicts, and presents a polished, interactive dashboard for league coordinators."

---

### Slide 3: A el problem aslun (The Core Problem)
* **Visual Layout:**
  - A timeline diagram showing:
    - **Summer 2019:** Emergency hosting of AFCON 2019 (disrupting Egypt's regular calendar).
    - **2020:** COVID-19 pandemic delays (compressing subsequent seasons).
    - **2020-2024:** The "Domino Effect" (seasons starting as late as December and running into August).
  - Graph showing historical seasons and the "wasted calendar days" (Ghost Gaps) where no matches were scheduled, despite no FIFA or CAF conflicts.
* **Speaking Script:**
  "Let us address the root of the issue: *'A el problem aslun?'* (What is the core problem?). The root of the scheduling crisis in the Egyptian Premier League dates back to 2019. When Egypt stepped in to host the Africa Cup of Nations at the last minute, the domestic calendar was completely derailed. Just as the league tried to recover, the COVID-19 pandemic hit. This created a severe 'Domino Effect'. Because one season ended late, the next season started late, pushing kickoff dates as far back as November or December.
  
  This compression forced the Egyptian Football Association into a perpetual cycle of emergency scheduling, arbitrary postponements, and massive disparities in matches played. In fact, if you looked at the league table in May 2021, Al Ahly had played five matches fewer than Al Masry simply because of uncoordinated CAF postponements. This destroyed the competitive integrity of our national league."

---

### Slide 4: The Domino Effect & Congestion
* **Visual Layout:**
  - Bar chart of historical seasons comparing the maximum rest gap between matches.
  - Explanatory box describing **"Ghost Gaps"**: days wasted in the calendar due to manual planning inefficiency where neither FIFA international dates nor CAF continental tournaments were playing.
* **Speaking Script:**
  "When matches are delayed, they pile up. We analyzed the historical data of the past five seasons and found a shocking inefficiency we call the 'Ghost Gap'. These are periods where the calendar is completely empty—no league matches are played—yet there are no international FIFA dates or continental CAF matches taking place. In the 2023/24 season, the longest Ghost Gap reached an astonishing 75 days! This means teams were left idle for over two months, only to be subjected to intense fixture congestion later, playing every 72 hours. This uneven rest directly affects player health, team performance, and spectator integrity. Our mathematical model was designed specifically to eradicate these Ghost Gaps."

---

### Slide 5: Specific Egyptian Bottlenecks
* **Visual Layout:**
  - An icon-based map highlighting Egyptian bottlenecks:
    - 🏟️ **Cairo International Stadium Sharing:** Shared by AHL, ZAM, and ZED.
    - 🏟️ **Borg Al-Arab Stadium Sharing:** Shared by SMO and PHA.
    - ✈️ **Continental Travel Buffers:** AHL, ZAM, and PYR travel to deep Africa for CAF Champions League matches, requiring a bidirectional 4-day rest buffer.
    - 👮 **Security Matrix:** Banned cities for specific high-risk fixtures (e.g., AHL playing in Ismailia or Alexandria due to security mandates).
* **Speaking Script:**
  "Why couldn't the EFA just copy the schedule of the English Premier League or the German Bundesliga? The answer lies in the unique operational bottlenecks of Egyptian football.
  
  First, stadium sharing: Al Ahly, Zamalek, and Zed FC all share Cairo International Stadium. Smouha and Pharco share Borg Al-Arab. You cannot have two home matches at the same venue on the same day, or even within a 48-hour maintenance window.
  
  Second, security: Security agencies enforce strict rules. High-risk matches must be played at designated neutral stadiums, and certain teams are banned from hosting specific opponents in their home cities.
  
  Third, and most chaotic, is the CAF conflict. Unlike Europe, where UEFA Champions League dates are locked years in advance, African continental match dates are fluid. A team might play in South Africa on a Saturday, fly back to Cairo, and be expected to play a local match on Tuesday. Manual schedulers couldn't handle this multi-dimensional puzzle, leading to arbitrary postponements. Our solver is designed to handle all of these bottlenecks simultaneously."

---

### Slide 6: F el objective bta3na (Our Objective)
* **Visual Layout:**
  - Main Heading: **What are we actually optimizing?**
  - Left column: **Hard Constraints** (Non-negotiable safety rules)
  - Right column: **Soft Objectives** (Quality & fairness goals)
  - Bottom graphic: A scale balancing **Fairness (Equal Rest Gaps)** on one side and **Efficiency (Travel & TV Slots)** on the other.
* **Speaking Script:**
  "Now we define the core mandate: *'F el objective bta3na enna n3ml kaza'* (Our objective is to do the following): We are not just building a static timetable. We are building a dynamic optimization system that generates a complete Double Round Robin calendar where every team plays every other team home and away.
  
  Our goal is to fit all 34 rounds, meaning all 306 matches, strictly within the standard global football calendar—starting in August and concluding in May. And we must do this while respecting every single security rule, stadium share, and FIFA international break as hard constraints, while simultaneously optimizing for fairness and commercial value as soft objectives."

---

### Slide 7: Optimization Objectives & Metrics
* **Visual Layout:**
  - A table outlining the optimization criteria:
    - **Objective 1: Rest Equity** (Minimizing the standard deviation of rest days between opponents in a single match).
    - **Objective 2: Home/Away Streak Minimization** (Capping consecutive home or away streaks at 2 matches to prevent psychological fatigue).
    - **Objective 3: Travel Distance Reduction** (Minimizing the total kilometers traveled by the away teams, optimized via a stadium-to-stadium distance matrix).
    - **Objective 4: Broadcast Optimization** (Matching Tier-1 matches with prime-time weekend slots to maximize advertising revenue).
* **Speaking Script:**
  "Let's break down the soft objectives.
  
  First, Rest Equity: If Al Ahly plays Zamalek, and Al Ahly has had 6 days of rest while Zamalek has had only 3, that match is fundamentally unfair. Our model penalizes rest disparities, ensuring that opponents have as close to equal recovery times as possible.
  
  Second, Home/Away Streaks: Playing three away matches in a row is exhausting. We enforce a strict cap of 2 consecutive home or away games.
  
  Third, Travel Fatigue: Egypt is geographically spread out. Teams traveling from Aswan to Alexandria face massive journeys. Our model uses a real-world distance matrix to minimize total travel distance.
  
  Finally, Broadcast Value: The league is a commercial product. We classified matches and kickoff slots into tiers. A Tier-1 clash—like the Cairo Derby—must be placed in a Tier-1 prime-time slot, which we define as Friday or Saturday evening after 7 PM."

---

### Slide 8: gbto el data mnen (Data & Parameters)
* **Visual Layout:**
  - A diagram showing the automated data collection pipeline:
    - Web Scrapers (Python + BeautifulSoup) ➡️ Raw CSV Files ➡️ Preprocessing & Validation ➡️ Unified Excel Data Model.
  - Logos of **Yallakora** and **Transfermarkt** as the primary data sources.
* **Speaking Script:**
  "Let us address the data source: *'Gbto el data mnen?'* (Where did you get the data from?). Any optimization model is only as good as the data feeding it.
  
  To ensure real-time accuracy, we built custom Python web scrapers to gather team metadata, stadium locations, and historical calendars from Egypt's leading sports portal, 'Yallakora', and squad market values from 'Transfermarkt'.
  
  We extracted stadium capacities, floodlight availability, and geographic locations to build a realistic representation of Egyptian football infrastructure. This scraping bypassed manual data entry errors and gave us a direct pipeline to the active league state."

---

### Slide 9: Relational Schema & Preprocessing
* **Visual Layout:**
  - Entity-Relationship Diagram (ERD) mapping the input schema:
    - `Team_Details` (PK: `Team_ID`) ➡️ Linked to `Stadiums` (PK: `Stadium_ID`) via `Home_Stadium_ID`.
    - `Stadiums` ➡️ Linked to `Dist_Matrix` (Origin, Destination, Distance_KM).
    - `Team_Details` ➡️ Linked to `Sec_Matrix` (Home_Team_ID, Away_Team_ID, Banned/Forced Venues).
    - `Calendar` (PK: `Day_ID`) ➡️ Linked to `FIFA_DAYS` and `unique_CAF_dates`.
* **Speaking Script:**
  "Once the data was scraped, we preprocessed it into a highly connected schema. We standardized inconsistent team names across websites using a normalized translation map—for example, mapping 'Ahly SC' and 'Al Ahly SC' to the unique ID 'AHL'.
  
  As you can see on the screen, our data model is divided into two sub-schemas. The **Infrastructure Model** links teams to their primary and alternate stadiums, which in turn maps to a distance matrix of Egypt's highways. It also links to the Security Matrix, which lists forbidden matchups and forced neutral stadiums.
  
  The **Temporal Model** centers around a master calendar. It maps every possible kickoff slot, flagging FIFA international windows and CAF Champions League dates, allowing us to build a comprehensive timeline before the optimization runs."

---

### Slide 10: System Parameters & Rest Caps
* **Visual Layout:**
  - A summary card layout displaying the core system configuration constants defined in [src/constants.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/constants.py):
    - `NUM_TEAMS = 18`, `NUM_ROUNDS = 34`, `MATCHES_PER_ROUND = 9`.
    - `MIN_REST_DAYS_LOCAL = 3` (minimum 4 days apart).
    - `MIN_REST_DAYS_CAF = 3` (minimum 4 days apart).
    - `MAX_MATCHES_PER_DAY = 3`.
    - `MAX_MATCHES_PER_SLOT = 2`.
    - `SOFT_WEEK_LOAD = 6 to 12 matches`.
* **Speaking Script:**
  "From this schema, we extract our core scheduling parameters.
  
  Our league configuration is standard: 18 teams, 34 rounds, 9 matches per round, totaling 306 fixtures.
  
  To protect player welfare, we set `MIN_REST_DAYS_LOCAL = 3`. This guarantees that if a team plays on a Monday, their next match cannot be earlier than Friday, ensuring at least 3 full rest days.
  
  We also bound the calendar load: a maximum of 3 matches can be played on a single date, and no more than 2 matches can kick off at the exact same time. This spreads matches out across the week, allowing TV viewers to watch multiple games and preventing stadium logistics from buckling.
  
  Finally, our soft weekly load target is 6 to 12 matches, ensuring the season moves at a steady pace without long periods of inactivity or sudden, congested double-round weeks."

---

### Slide 11: el mathematical model (The Math)
* **Visual Layout:**
  - Main Decision Variable:
    $$x_{m,s} \in \{0,1\} \quad \forall m \in M, s \in \text{feasible\_domain}(m)$$
  - Hard Constraints:
    - **H3 (Team Date Uniqueness):**
      $$\sum_{\substack{m \in M \\ t \in \text{team}(m)}} \sum_{\substack{s \in \text{feasible\_domain}(m) \\ \text{date}(s) = d}} x_{m,s} \leq 1 \quad \forall t \in T, \forall d \in D$$
    - **H5 (Daily Match Cap):**
      $$\sum_{m \in M} \sum_{\substack{s \in \text{feasible\_domain}(m) \\ \text{date}(s) = d}} x_{m,s} \leq \text{MAX\_DAY} \quad \forall d \in D$$
* **Speaking Script:**
  "Now, let's look at *'el mathematical model'* (the mathematical model). We formulated the league scheduling as an Integer Linear Programming problem.
  
  Our primary decision variable is a binary variable, $x_{m,s}$, which equals 1 if match $m$ is assigned to calendar slot $s$, and 0 otherwise. To reduce the search space, $x_{m,s}$ is only defined for slots that fall within the match's feasible domain.
  
  We enforce several hard constraints.
  
  Look at Constraint **H3 (Team Date Uniqueness)**: This equation guarantees that for any team $t$ and any calendar date $d$, the sum of all match assignments involving team $t$ on that date is at most 1. In other words, a team cannot play two matches on the same day.
  
  Constraint **H5 (Daily Match Cap)**: This limits the total matches played across all teams on a single date $d$ to `MAX_DAY` (which is 3), preventing excessive scheduling load on security and broadcasters."

---

### Slide 12: Advanced Constraints & Rest Windows
* **Visual Layout:**
  - Equations for:
    - **H7 (Team Rest - Sliding 4-Day Window):**
      $$\sum_{\substack{m \in M \\ t \in \text{team}(m)}} \sum_{\substack{s \in \text{feasible\_domain}(m) \\ \text{date}(s) \in [d, d + \text{REST\_LOCAL} - 1]}} x_{m,s} \leq 1 \quad \forall t \in T, \forall d \in D$$
    - **H12 (Bidirectional CAF Buffer):**
      $$\sum_{\substack{s \in \text{feasible\_domain}(m) \\ |\text{date}(s) - d| < \text{CAF\_BUFFER}}} x_{m,s} = 0 \quad \forall m \in M, t \in \text{team}(m) \cap C, d \in \text{caf\_dates}(t)$$
* **Speaking Script:**
  "Let's move to the rest-day constraints, which are critical for player welfare.
  
  Constraint **H7 (Sliding 4-Day Team Rest Window)**: Instead of checking static weeks, we use a sliding window. For every team $t$ and every starting date $d$, the sum of matches played in the 4-day window $[d, d+3]$ must not exceed 1. This mathematically guarantees a minimum of 3 full rest days between any two league matches.
  
  Now, look at Constraint **H12 (Bidirectional CAF Buffer)**: This was a major addition in Phase 2. For teams competing in Africa—denoted by the set $C$—if they have a continental match on date $d$, the sum of their domestic match assignments in the window $[d - 4, d + 4]$ must equal 0. This enforces a strict 4-day travel and rest buffer both *before* and *after* their CAF commitments, resolving the main source of historical fixture congestion."

---

### Slide 13: Objective Function & Penalties
* **Visual Layout:**
  - Objective Function:
    $$\text{Minimize } \mathcal{Z} = \mathcal{Z}_1 + \mathcal{Z}_2 + \mathcal{Z}_3 + \mathcal{Z}_4 + \mathcal{Z}_5$$
  - Breakdown of terms:
    - $\mathcal{Z}_1$ (Round Placement Deviation): $W_{\text{ROUND}} \sum | \text{week}(s) - \text{nominal\_week}(r) |$
    - $\mathcal{Z}_2, \mathcal{Z}_3$ (Weekly Under/Overload): $W_{\text{LOAD}} \sum (\text{under\_load}_w + \text{over\_load}_w)$
    - $\mathcal{Z}_4$ (Travel Distance): $W_{\text{TRAVEL}} \sum \text{travel\_km}(m) \cdot x_{m,s}$
    - $\mathcal{Z}_5$ (Tier Mismatch): $W_{\text{TIER}} \sum | \text{match\_tier}(m) - \text{slot\_tier}(s) |$
* **Speaking Script:**
  "Our objective function, $\mathcal{Z}$, is a weighted sum of five soft penalties that we want to minimize.
  
  The first term, $\mathcal{Z}_1$, penalizes round placement deviation. It calculates the difference between the actual calendar week of a match and its nominal round week, keeping the rounds running in chronological order.
  
  The second and third terms, $\mathcal{Z}_2$ and $\mathcal{Z}_3$, handle weekly load deviations, penalizing weeks with fewer than 6 matches or more than 12 matches.
  
  The fourth term, $\mathcal{Z}_4$, is travel distance. It multiplies the distance the away team must travel by the assignment variable, minimizing the total travel distance across the entire league.
  
  The fifth term, $\mathcal{Z}_5$, is the tier mismatch. It calculates the absolute difference between the match tier and the kickoff slot tier. Since a low difference minimizes the penalty, this forces high-tier derbies into high-tier, weekend prime-time slots."

---

### Slide 14: Round 34 Simultaneous Kickoff & Venue Bottleneck
* **Visual Layout:**
  - Explanation of the **Simultaneous Kickoff Constraint (H14)**:
    - All 9 matches of Round 34 must share the exact same kickoff date and slot:
      $$\text{slot\_idx}(m) = S_{\text{final}} \quad \forall m \in M : \text{round}(m) = 34$$
  - A table of stadium sharing conflicts for Round 34:
    - **Cairo International Stadium:** AHL, ZAM, and ZED all host home matches.
    - **Borg Al-Arab Stadium:** SMO and PHA both host home matches.
  - Visual diagram showing how the solver resolves this bottleneck by dynamically shifting teams to alternate or relief stadiums (Alt_Stadium_ID) and applying displacement penalties.
* **Speaking Script:**
  "Finally, let's discuss the final round, Round 34. To ensure sporting fairness, all 9 matches must kickoff at the exact same second. This is constraint **H14**.
  
  However, this creates a massive venue bottleneck. If Al Ahly, Zamalek, and ZED FC are all scheduled to play home matches in the final round, they cannot all play at Cairo International Stadium simultaneously. Similarly, Smouha and Pharco cannot both play at Borg Al-Arab.
  
  To resolve this, we introduced venue flexibility variables, $y_{m,s,v}$, allowing the solver to dynamically move teams to their pre-registered alternate stadiums—like shifting Zamalek to Petro Sport, or Pharco to Haras El Hodoud stadium—while applying a large penalty in the objective function to discourage displacement unless mathematically necessary to achieve feasibility."

---

### Slide 15: el implementation (Methodologies & Algorithms)
* **Visual Layout:**
  - Flowchart of the Two-Stage Generation:
    1. **Stage 1 (Circle Method):** Shuffles teams ➡️ Generates Double Round-Robin pairings (153 fixtures) ➡️ Mirrors pairings for second leg (306 fixtures).
    2. **Stage 2 (CP-SAT Orientation Solver):** Assigns home/away orientations to satisfy streak caps.
    3. **Output:** A complete, balanced fixture framework.
* **Speaking Script:**
  "Let's look at *'el implementation'* (how we built it). Solving a 306-match assignment problem with hundreds of constraints directly is computationally expensive. To make the model solvable in real-time, we designed a two-stage generation pipeline in [src/fixture_generator.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/fixture_generator.py).
  
  In Stage 1, we use the classic **Circle Method** of tournament pairing. We shuffle the team IDs using a random seed, fix the first team, and rotate the rest to generate a mathematically perfect 17-round pairing. We then mirror these rounds for the second leg, swapping home and away sides.
  
  In Stage 2, we pass these pairings into a dedicated **CP-SAT Orientation Solver**. This solver's sole job is to assign home/away orientations to each pairing. It ensures that no team has a sequence of three consecutive home or away matches, and that home/away games are balanced across the season. By solving this subproblem first, we pass a fixed, streak-compliant fixture framework to the main scheduler, reducing the combinatorial complexity of the main solve by orders of magnitude."

---

### Slide 16: Domain Pruning & Fallbacks
* **Visual Layout:**
  - A diagram showing the **Three-Attempt Domain Retry Loop** implemented in [src/baseline_retry.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/baseline_retry.py):
    - **Attempt 1: Compact Policy** (strict 5-day round windows; most organized).
    - ❌ *If Infeasible:* **Attempt 2: Relaxed Policy** (spillover windows up to 28 days).
    - ❌ *If Infeasible:* **Attempt 3: Full Policy** (full spillover tails up to 56 days).
  - Code snippet showing the domain building loop from [src/slot_domain.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/slot_domain.py):
    ```python
    for match in matches:
        domain = build_feasible_slots(match, data, policy)
        if violates_caf_buffer(domain):
            prune_slots(domain)
    ```
* **Speaking Script:**
  "Once the fixtures are oriented, we build the feasible slot domains for each match. First, we pre-filter the calendar, pruning out any slots that violate the bidirectional CAF buffers for continental teams.
  
  However, this heavy pruning can sometimes lead to an infeasible model where some matches have zero valid slots. To prevent solver failure, we implemented a **Three-Attempt Domain Retry Loop**.
  
  We start with the **Compact Policy**, which restricts matches to strict 5-day round windows. If the CP-SAT solver finds this infeasible, the system automatically catches the exception, widens the round windows to a **Relaxed Policy** of 28 days, and retries. If still infeasible, it falls back to the **Full Policy** of 56 days. This tiered approach guarantees that we always find a feasible schedule, even under extreme calendar congestion."

---

### Slide 17: Dedicated Round 34 Rescue Model
* **Visual Layout:**
  - Flowchart of the **Rescue Model** logic in [src/baseline_solver.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/baseline_solver.py):
    - Solve Rounds 1-33 Subproblem ➡️ Extract occupied schedule state ➡️ Build miniature Round 34 model ➡️ Iterate candidate slots in Round 34 window ➡️ Assign venues and alternate stadiums ➡️ Merge schedules.
* **Speaking Script:**
  "Even with domain fallbacks, the simultaneous kickoff constraint of Round 34 remains a major mathematical bottleneck. If the solver fails to find a solution under the strict, unified model, our pipeline triggers a dedicated **Round 34 Rescue Model**.
  
  The Rescue Model works by dividing and conquering. First, it isolates and solves the subproblem for Rounds 1 through 33. This regular schedule is solved quickly and locked. We then extract the occupied state—dates used, stadiums booked, and team rest histories.
  
  Next, we build a miniature CP-SAT model specifically for the 9 matches of Round 34. The model iterates through the candidate slots in the final round window. For each slot, it attempts to schedule all 9 matches simultaneously, dynamically assigning alternate stadiums and resolving venue conflicts. Once a valid slot is found, it merges the two schedules, rescuing the pipeline from infeasibility."

---

### Slide 18: Post-Solve Validation Engine
* **Visual Layout:**
  - Validation table showing the rules checked by [src/validation.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/validation.py):
    - 🔍 **Completeness:** 306 matches scheduled.
    - 🔍 **FIFA Blackouts:** 100% compliant (no matches on FIFA dates).
    - 🔍 **Daily Load:** max 3 matches per day.
    - 🔍 **Venue Conflicts:** no double-bookings.
    - 🔍 **CAF Buffers:** >= 4 rest days.
    - 🔍 **Team Rest Gaps:** >= 3 rest days.
    - 🔍 **Streaks:** max 2 consecutive home/away.
* **Speaking Script:**
  "The final step of our pipeline is the **Post-Solve Validation Engine**, implemented in [src/validation.py](file:///g:/Learn/College/Graduation%20Project/Egyptian-Premier-League-Schedule-Optimizer/src/validation.py).
  
  We do not simply trust the solver's output. The validation engine is a completely independent script that audits the final schedule against every single hard and soft rule.
  
  It checks that exactly 306 matches are scheduled, that no match lands on a FIFA date, that stadium bookings do not overlap, and that player rest gaps are respected. If any violation is found, it is flagged as an ERROR and written to a diagnostic report. This ensures that the schedule we deliver is 100% verified and ready for deployment."

---

### Slide 19: el results (Overall Effectiveness & Feasibility Metrics)
* **Visual Layout:**
  - Major Heading: **EPL Optimizer Phase 2 Execution Summary**
  - KPI Blocks displaying:
    - **Feasibility Status:** `FEASIBLE` (Solved in 600.5 seconds).
    - **Total Matches Scheduled:** 306 / 306 (100% completeness).
    - **Domain Policy Fallback Used:** `Attempt 2: epl_relaxed` (Extended spillover).
    - **Hard Constraint Violations:** 0 Errors.
    - **Soft Constraint Warnings:** 3 Cairo Stadium Service Gap Warnings (Soft maintenance guidelines).
* **Speaking Script:**
  "Let's look at *'el results'* (the results). We executed our complete scheduling pipeline using a random seed of 88. The solver successfully found a feasible schedule under the `epl_relaxed` domain policy in 600.5 seconds, mapping all 306 matches.
  
  Most importantly, when we pass this schedule to our validation engine, it reports exactly zero hard constraint errors. 100% of FIFA breaks are protected, and player rest windows are fully respected. The only flags in the entire report are three soft warnings regarding Cairo International Stadium hosting matches within 48 hours of each other, which are minor maintenance gaps rather than operational errors. This proves the system is extremely effective at finding valid calendars under dense constraints."

---

### Slide 20: Ghost Gap & Calendar Efficiency Analysis
* **Visual Layout:**
  - **Bar Chart (Historical vs. Optimized Max Adjusted Gap):**
    - Season 18_19: 54 Wasted Days
    - Season 20_21: 43 Wasted Days
    - Season 21_22: 46 Wasted Days
    - Season 22_23: 31 Wasted Days
    - Season 23_24: 75 Wasted Days
    - **Our Optimized Model (Seed 88): 5 Wasted Days**
  - Callout Box: **Wasted days** represent calendar gaps where no matches were played despite no FIFA or CAF commitments.
* **Speaking Script:**
  "Let's dive into the detailed efficiency analysis. In previous seasons, the league suffered from massive 'Ghost Gaps'—wasted days where the calendar sat completely empty for no valid reason. In the 2023/24 season, this gap peaked at a staggering 75 days.
  
  Our model, by contrast, dynamically schedules matches during continental weeks, restricting calendar blackouts only to official FIFA windows. We successfully reduced the maximum adjusted gap to just 5 days. This is a 93% improvement in calendar utilization, allowing us to complete the entire 34-round season strictly within the August-May window and eliminating summer spillover."

---

### Slide 21: Travel Distance Optimization & Balancing
* **Visual Layout:**
  - **Bar Chart (Total League Travel KM Comparison):**
    - Historical 2020/21: 75,530 KM
    - Historical 2022/23: 70,705 KM
    - **Our Optimized Model: 55,005 KM** (27% travel reduction from the peak)
  - Team-by-team travel distribution table, showing balanced travel kilometers between Cairo-based clubs and regional clubs (e.g., El Gouna, Aswan, Al Masry).
* **Speaking Script:**
  "Travel fatigue has a direct, negative impact on player performance and recovery. We evaluated our model's travel cost against historical baselines.
  
  In the 2020/21 season, manual scheduling forced teams to travel a combined 75,530 kilometers, often due to uncoordinated venue routing. By introducing a real-world highway distance matrix into the objective function, our CP-SAT solver minimized total travel to just 55,005 kilometers. This represents a 27% reduction in travel fatigue, saving clubs hundreds of hours of transit and significant financial costs, while maintaining a balanced travel distribution across Cairo and regional teams."

---

### Slide 22: Home/Away Streaks & Rest Gaps Distribution
* **Visual Layout:**
  - **Bar Chart (Max Home/Away Consecutive Streak):**
    - Historical Seasons: 4 to 6 consecutive matches (due to emergency postponements)
    - **Our Optimized Model: 2 consecutive matches** (Strict H13 limit)
  - **Rest Days Frequency Distribution Histogram:**
    - 3 Rest Days (4 days apart): 72% of fixtures
    - 4-5 Rest Days (5-6 days apart): 20% of fixtures
    - 6+ Rest Days (FIFA/CAF windows): 8% of fixtures
* **Speaking Script:**
  "In historical schedules, postponements forced teams to play a long string of consecutive home or away matches to 'catch up'—sometimes playing 5 away games in a row. Our model enforces a hard consecutive home/away streak limit of 2, which was 100% satisfied across all 18 teams.
  
  Furthermore, looking at the recovery distribution, over 70% of matches are scheduled with exactly 3 rest days, which is the optimal professional standard for football leagues. The remaining matches receive even longer recovery periods during FIFA or CAF gaps. No team is subjected to playing a match with fewer than 3 full rest days, safeguarding player health."

---

### Slide 23: Broadcast Alignment & Tier Allocation Effectiveness
* **Visual Layout:**
  - **Match-Tier vs. Slot-Tier Matrix Chart:**
    - **Tier-1 Matches (Derbies):** 100% assigned to Tier-1 Slots (Friday/Saturday Prime-Time)
    - **Tier-2 Matches:** 88% assigned to Tier-2 Slots
    - **Tier-3 Matches:** 94% assigned to Tier-3 Slots
  - Callout metrics showing the correlation between high-value slots and commercial match tiers.
* **Speaking Script:**
  "A major objective for the Egyptian Premier League is commercial value. Broadcasters demand that high-profile matches air during prime-time weekend slots to maximize viewership.
  
  Our solver achieved a perfect 100% matching rate for Tier-1 derby matches, ensuring games like Al Ahly vs. Zamalek or Pyramids are scheduled exclusively on Friday or Saturday evenings after 7:00 PM. Tier-2 and Tier-3 matches are distributed across weekdays and afternoons, keeping a steady stream of broadcasted content throughout the week without diluting the value of prime-time slots."

---

### Slide 24: Streamlit Dashboard Demo (Explore & Travel)
* **Visual Layout:**
  - Screenshots of the **Streamlit Web Application**:
    - Left side: The **Model Configuration Panel** (sliders for tuning weights and rest limits).
    - Right side: **Travel Statistics Bar Chart** showing travel kilometers per team, and the **Head-to-Head Chooser** showing team logos.
* **Speaking Script:**
  "To make our optimization engine accessible to league coordinators, we built an interactive web dashboard using Streamlit.
  
  The dashboard features a dark theme with purple accent styling. In the sidebar, users can tune model constants in real-time. If the EFA wants to test a 4-day minimum rest rule instead of 3, they can simply adjust the slider and re-run the pipeline.
  
  The dashboard also provides rich analytics, including interactive bar charts of total travel kilometers per team, allowing coordinators to quickly verify that travel load is distributed fairly among clubs."

---

### Slide 25: Interactive Calendar View
* **Visual Layout:**
  - Screenshot of the Streamlit **Interactive Calendar Tab**:
    - A responsive grid layout of a calendar month.
    - Match cards showing team logos and kick-off times inside cell grids.
    - Badges for **FIFA Windows** and **CAF Dates**.
    - Hover cards explaining *why* empty days are empty (e.g., 'Blocked: FIFA International Date').
* **Speaking Script:**
  "One of our proudest frontend achievements is the **Interactive Calendar View**.
  
  Instead of viewing schedule outputs in flat, hard-to-read spreadsheets, coordinators can browse the season month-by-month.
  
  As you can see, matches are displayed with club logos and kickoff times directly in the calendar grid. Empty days are not just blank; hovering over them reveals the exact reason they are empty—whether it is a blocked FIFA international window, a CAF travel buffer, or a stadium maintenance day. This transparency builds trust with club representatives and league stakeholders."

---

### Slide 26: Phase 2 Summary & Conclusion
* **Visual Layout:**
  - A summary list of achievements:
    - **Mathematical Framework:** Formulated a complete Integer Linear Programming model.
    - **Feasibility Guarantee:** Implemented a three-attempt domain fallback and a dedicated Round 34 Rescue Model.
    - **Eradication of Inefficiencies:** Reduced wasted calendar days (Ghost Gaps) from 75 days to 5 days.
    - **Stakeholder Alignment:** Balanced security, broadcasting, and player rest requirements.
* **Speaking Script:**
  "To conclude, our Phase 2 implementation has successfully demonstrated that operations research and constraint programming can solve the deep-rooted scheduling issues of the Egyptian Premier League.
  
  We have moved from a theoretical database schema to a fully operational, automated scheduling pipeline. By translating rules into equations and using OR-Tools CP-SAT, we proved that a 34-round season can be completed within 10 months, while ensuring 100% compliance with player rest rules, security matrices, and stadium-sharing limits."

---

### Slide 27: Future Work & System Expansion
* **Visual Layout:**
  - Three pillars of future work:
    1. **Multi-Objective Pareto Optimization:** Allowing coordinators to generate and choose from a frontier of trade-off schedules (e.g., Travel-optimized vs. Rest-optimized).
    2. **Ramadan & Weather Modeling:** Dynamic adjustments for fasting hours during Ramadan and Alexandria's winter rain blockouts.
    3. **REST API & EFA Integration:** Packaging the engine as a cloud API to integrate directly with EFA league management systems.
* **Speaking Script:**
  "Looking forward, we have identified three key areas to expand this project.
  
  First, we want to implement **Multi-Objective Pareto Optimization**. Instead of outputting a single schedule, the system would generate a Pareto frontier of alternative schedules, allowing coordinators to compare and choose between a schedule that minimizes travel vs. one that maximizes broadcast revenue.
  
  Second, we want to incorporate local constraints like Ramadan fasting times and winter weather disruptions in Alexandria, dynamically shifting kickoff slots based on seasonal variables.
  
  Third, we plan to package the scheduling engine as a REST API. This would allow the Egyptian Football Association to integrate our optimizer directly into their existing player registration and league management software, digitizing Egyptian football administration from end to end."

---

### Slide 28: Final Slide (Thank You)
* **Visual Layout:**
  - Slide text: **Thank You! Questions?**
  - Faculty Logo: Cairo University, Faculty of Computers and Artificial Intelligence.
  - Contact Information: Team Emails & GitHub Repository Link.
* **Speaking Script:**
  "We would like to express our deepest gratitude to our supervisor, Dr. Sally Kassem, and our teaching assistant, Eng. Rawaa Hesham, for their guidance throughout this project.
  
  Thank you, respected committee members, for your time. We are now open to any questions you may have."

---

## 💡 Presentation Delivery Tips for the Team

1. **Maintain the Professional Narrative:**
   - Always connect the math to the football reality. Don't just say *'Constraint H7 restricts sliding windows'*. Say *'Constraint H7 guarantees that players get at least 3 full rest days between matches, directly reducing hamstring injuries and fatigue'*.
   - Use the Egyptian Arabic phrases naturally. They highlight the team's familiarity with local league challenges and keep the committee engaged.

2. **Handle the Math with Confidence:**
   - Walk through the LaTeX formulas slowly. Explain that CP-SAT is chosen because of its incredible efficiency in pruning infeasible search spaces compared to traditional branch-and-bound ILP.

3. **Live Demo Preparation:**
   - Have the Streamlit app running locally and pre-loaded. If the committee asks, show them the **Calendar View** and show how changing the travel weight $W_{\text{TRAVEL}}$ in the sidebar shifts teams' matches in real-time.
