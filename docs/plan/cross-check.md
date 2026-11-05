---
type: note
kind: reference
title: Term project — cross-check of the two plans
---

# Cross-check — does the stage plan deliver the current plan?

[[current-plan]] says **what and when**; [[stage-plan]] says **how**. This note compares them in both directions
and lists every disagreement found on 2026-10-28, with what was done. Checked against the older planning
documents too ([[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/tasks-explained|tasks-explained]],
[[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/architecture|architecture]],
[[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/summary|summary]]).

**Keep this honest:** when either plan changes, re-run the two directions below and add a dated row to the
findings table. A check that was not repeated is not a check.

## 1. Forward: every high-level item has a stage that produces it

| High-level item (current plan) | Stage that produces it | Output it must leave | Status |
|---|---|---|---|
| RQ0 article age and unseen-click share | T3 | `results/rq0/` | covered |
| RQ1 decay curves | T6 → T7 | matrix shards, `results/rq1_rq2/` | covered (option D, 2026-10-29) |
| RQ2 which signal first, and why | T4 scorers → T7 | curves per scorer and regime, four diagnostics | covered (option D, 2026-10-29) |
| RQ3 rebuild interval and cost | T8 | `results/rq3/` | covered |
| Decision 1 (one decay matrix) | T6 | `results/decay_matrix/` | covered |
| Decision 2 (decay = gap to the daily-rebuilt control) | T6 (cell d−1, d), T7 | the control is present for every day | covered; the control exists for every evaluation day under D (fit dates 10–23 May) |
| Decision 3 (two regimes) | T4 (`ReaderContext`), T6 | both regimes in every cell | covered; regime B = profile gains clicks made before each sampled click |
| Decision 4 (7-day sliding window) | T1, T4 `FitWindow`, T6 | one window per fit date | covered (option D, 2026-10-29) |
| Decision 5 (metrics, paired CIs, n shown) | T4 metrics, T7 bootstrap | `metric = x [lo, hi], n` | covered |
| Decision 6 (determinism and memory) | T5 tests, every stage's "Parallel" and "Memory" rows | hashes equal across worker counts | covered |
| Curves per scorer and regime compared (was H1–H3, H5) | T7 | tables and plots with intervals | covered |
| Recency check: gap exactly 0 | T5, every T6 cell | zero, or the run fails | covered |
| The knee of the cost curve | T8 | reported, not asserted | covered |
| Datasets: EB-NeRD, NPR, Adressa | T1a, T1b, T1c | stores with checksummed manifests | covered |
| Second dataset | T9 | `results/npr/` | covered |
| Hourly fast axis (core, D22) | T6h | decay against hours since the fit | covered; **scope depends on the T4 fit time** |
| Report and ai-log | T10 | report, curated `ai-log.md` | covered |
| Experiments stop 2026-11-15, deadline 2026-11-20 | schedule in both plans | — | dates agree after fix F2 |
| Cut order | both plans | — | agree after fix F3 |
| Open decisions | current plan section 7, stage plan section 7 | — | agree after fix F7 |

## 2. Backward: every stage serves a high-level item

| Stage | Serves | Needed because |
|---|---|---|
| T0 | all (decisions, folders, scaffold) | a clean start |
| T1a–c | all RQs | every scorer reads these stores |
| T1d | RQ2 (meaning matching) | the second signal needs embeddings |
| T2 | decision 1 (same impressions in every cell) | pairing |
| T3 | RQ0 | the cheapest, model-free result |
| T4 | RQ1, RQ2; sets worker counts | the three signals behind one interface |
| T5 | recency check and decision 6 | a leak or a parallel difference would look like decay |
| T6 | RQ1–RQ3 | the matrix |
| T7 | RQ1, RQ2 | the main finding |
| T8 | RQ3 | the practical recommendation |
| T9 | generality of RQ1–RQ3 | one publisher is not a finding |
| T6h | RQ1 on the fast axis | the median EB-NeRD click is on an article 1.4 h old |
| T10 | deliverable | graded |
| T11 | reproducibility and tidiness | frozen, hashed results; nothing stray |

No stage is orphaned and no high-level item lacks a stage.

## 3. Findings: where the two plans, or the older documents, disagreed

| # | Finding | Severity | Fix | State |
|---|---|---|---|---|
| **B1** | The EB-NeRD click corpus changes in volume and kind across dates (see [[current-plan]] section 4), so the 28-date fit family, the 301 cells and regime B are not sound as written | **blocking** | marked provisional in both plans; options A, B, C laid out; stage T1a gets a gate | **decided 2026-10-29: option D**; stage plan rewritten (T2, T4, T6) |
| F1 | The stage plan assumed history and impression clicks overlap and need a 60-second de-duplication tolerance | medium | measured: on the two boundary days only 0.4–0.7 % of (user, article) pairs are in both and 0.1 % of matched pairs are within 60 s, so de-duplicate on exact (user, article, time) only and report the overlap | fixed in [[stage-plan]] T1a |
| F2 | Dates disagreed: the architecture gantt started T0 on 2026-10-26 and ran T6 from 11-03; the stage plan started 10-28 and ran T6 from 11-05; `summary.md` listed no dates | medium | the schedule in [[current-plan]] is the master; the architecture gantt now points to it | fixed |
| F3 | Three cut orders: `tasks-explained` (T9b, T9, 3 May fit date, A-versus-B, …), `summary.md` (hourly, Adressa, NPR, regime B, …), stage plan (T9b, T9, 3 May) | medium | one master order in [[current-plan]] section 5; the other two now match it | fixed |
| F4 | The NPR column is `algo` (values `top-state`, `als`, `recents`, `top`), but architecture and tasks-explained call it `list_type` | low | renamed to `algo` in the schema and adapter tables | fixed |
| F5 | The stage plan's check "day totals match dataset-stats" would fail on EB-NeRD, because the stage plan uses the dataset's 07:00 day and `dataset-stats` uses the calendar date | medium | the gate now compares **totals** (24,630,275 impressions; 24,783,679 clicks) and a re-derivation of the calendar-date table, not 07:00 days | fixed in [[stage-plan]] T1a |
| F6 | Architecture says click history is "damped for very heavy readers"; the stage plan caps profiles at the last 50 clicks; the two are different mechanisms | low | both stated: damping in the similarity, the cap on the profile; the cap is a parameter recorded in the log | noted in [[current-plan]] section 2 |
| F7 | The stage plan listed the tarball deletion as a question; you decided to delete it yourself later | low | recorded as your action; no deletion by me | fixed |
| F8 | `proposal` section 0.4 proposes "for example 50 k" impressions a day; the design uses 20,000 (A1's default after finding F34) | low | the proposal is an archive of an earlier idea; 20,000 is the master | noted, proposal left as written |
| F9 | The proposal's section 6.2 names three cutoffs (3, 10, 17 May); architecture and stage plan use a continuous family of fit dates | low | superseded by B1's outcome | fixed by B1 (option D: fit dates 10–23 May) |
| F10 | `architecture` Part E said "28 fit dates, 301 cells, about 72 M values" | medium | marked provisional under B1; recomputed once B1 is decided (option A gives about 92 cells) | fixed by B1 (option D: fit dates 10–23 May) |
| F11 | The stage plan counted 147 M exploded history clicks | low | the correct figure is about 238 M (1,579,672 rows at a mean of 151) before removing users in both histories | fixed earlier |
| F12 | After the team's answers on 2026-10-28, the decisions section of both plans, the log (D9, D13–D15) and the tracking note had to agree | low | all four updated together: team of 3 and one pipeline, co-click cosine, git deferred with a deadline, instructor notice open, B1 still open | fixed |
| F13 | The current plan said impressions were needed to score; [[datasets]] already described a click-only protocol, so the plans contradicted the dataset note | medium | corrected in [[current-plan]]; option D added; the stage plan marks which stages change under D (T2 sample unit, T4 and T6 candidate source, metric set) | fixed; D itself awaits confirmation |
| F14 | Hourly analysis was an optional last-minute extension (T9b) in all documents, but the measured click ages (median 1.4 h; 91 % of clicks on post-fit articles by 6 h) put the effect inside the first hours | medium | promoted to T6h (proposed core, gated by the T4 fit time) in the current plan, stage plan, tasks-explained, summary, architecture and log; cut order and gantt updated everywhere | fixed; D22 awaits confirmation |
| F15 | After D21, the stage plan still used impressions and slates in T1a (07:00 day), T4 (per-slate), T6 (impression metrics, 72 M values) and T7 | high | rewritten to clicks and the 48 h pool; the slate parts are marked as the option-A cross-check | fixed |
| F16 | Stage plan counted 301 cells, 28 fit units and a 3 May fit date; option D gives 14 fit dates, 105 cells | high | fixed in the stage plan (T6, cost control, gantt text, cut order), the architecture's Part E and the disk budget (about 25 M per-click ranks, not 72 M) | fixed |
| F17 | The T6 metric set (AUC, MRR, nDCG@5) differed from the current plan (MRR, recall@10 primary) | medium | T6, T7, T4, architecture and summary now say per-click rank, MRR and recall@10 primary, AUC and nDCG@5 secondary | fixed |
| F18 | **T6h's sample was undefined**: 20,000 clicks a day is about 830 an hour, too few for 1–3 hour offsets | high | T6h draws its own sample per (day, hour) bucket, default 5,000 (*estimate*, set in T4); fit times 00–21 h in steps of 3 on a 5-day block | fixed; the 5,000 is a default to be tested |
| F19 | T6h's consistency check ("24 h agrees with day 1") compared unlike things | medium | now: for the 00:00 fit, offsets 1–24 agree within the intervals with the daily cell (*r*, *r* + 1) | fixed |
| F20 | T1a used the dataset's 07:00 day for the click corpus, and the EB-NeRD time zone is unestablished (log P32) | medium | day = calendar date of the stored timestamps, one config value; the time-zone check is made in T1a and T5 | fixed |
| F21 | T3 covered EB-NeRD only, though the model-free curves already exist for all three datasets (log P30, P32) | medium | T3 covers all three and must reproduce P30; T1a reproduces P28 | fixed |
| F22 | T5 had no test for a pool that includes articles published after the click, the new leak that option D introduces | high | boundary mutation and a pool check added | fixed |
| F23 | T9 still described slates and a slate generator for Adressa; under D, Adressa uses the same harness | medium | rewritten; NPR uses all about 10,000 clicks a day, mostly empty regime-B profiles, larger pool window, daily grid only | fixed |
| F24 | The stage plan's "done when all pass and are committed", T0's git repo and the git row referred to practices removed in D23 | low | reworded | fixed |
| F25 | `architecture`, `tasks-explained` and `summary` still describe slates | medium | banner on the first two pointing to the stage plan; their numbers, task tables and summary diagram updated; the slate diagrams in `architecture` stay as the cross-check description | partly fixed: the architecture's Parts A to D are not rewritten |
| F26 | Dependencies in the stage diagram missed T3 on NPR and Adressa | low | edges added | fixed |
| F27 | The plans measured quality but had no account of inputs, process, fresh-versus-decayed or serving | high | section 2.4 of the stage plan: input metrics with fail thresholds, a process ledger, an **exact stratum decomposition of the decay** (S0 seen, S1 missed, S2 new today), serving proxies, robustness metrics; T1, T4, T6, T7, T8 write them | fixed; thresholds are defaults |
| F28 | No cleanup stage and no tested end-to-end check that the pipeline can measure a known effect | high | T11 (cleanup and freeze, with an approval list for deletions) and, in T5, a **planted-decay** test and a strata-identity test | fixed |
| F29 | The one-off scripts behind log P28, P30 and P32 live only in the session scratchpad | medium | T11 copies them into `code/`; until then they are not reproducible from the project | partly fixed 2026-10-29: `code/modelfree.py` reproduces P30 from the stores; the original P28 script is still only in the scratchpad |
| F30 | Only per-unit cost was recorded (seconds, peak memory); nothing for resources **inside** a unit (phases, memory over time, CPU, I/O, swap, disk) or **between** stages (handoff, plan-versus-actual, cumulative disk) | high | section 2.5 of the stage plan and `code/monitor.py` (not yet written): phase timers, 1 Hz trace, guards that abort without a partial result, handshake with hashes, stage reports, tests in T0 and T5 | fixed in the plan; the module is built in T0 |
| F31 | The machine has a 30 GB swap partition (2.2 GB in use), so a rule of "no swap" cannot hold | low | the guard is swap **growth** during the run; available memory was 18 GB at the check (earlier 21 GB), so the 16 GB pool cap is re-checked at T4 | noted |

## 4. Gates added to the stage plan by this check

| Stage | Gate | Why |
|---|---|---|
| T1a | **Click-source report**: clicks per day by source (history, impression), users per day by source, and the overlap, written to the manifest | makes B1 visible in the data, not only in this note |
| T1a | The fit-corpus choice (A, B or C) is read from one config value, so changing it does not change code | B1 is undecided |
| T2 | the evaluation cohort and days are an explicit config, not derived | under A the evaluation cohort is the train users |
| T5 | a **volume-equality test**: the windows of a fit-date family differ in click count by less than a stated factor, or the run fails | a design that reintroduces B1 must be caught automatically |

## 5. How to re-run this check

1. For every row of [[current-plan]] sections 1, 2, 6 and 7, find the stage in [[stage-plan]] that produces it.
2. For every stage, find the high-level item it serves.
3. Compare every number, date and name that appears in both. Any difference goes in section 3, with a fix.
4. Compare both against [[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/architecture|architecture]],
   [[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/tasks-explained|tasks-explained]] and
   [[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/summary|summary]].

---
[[IRE-Term-Project|← tracking note]] · [[current-plan]] · [[stage-plan]] · [[Subjects/IRE/Projects/IRE-Term-Project/log|log]]
