---
type: note
kind: reference
title: Term project — current plan (high level)
---

# Current plan — the high-level view

The **master** description of what the project does, in what order, by when, and what is decided. The detailed,
per-stage version is [[stage-plan]]; [[cross-check]] shows that the two agree, item by item, and lists every
disagreement found when they were compared. If the two ever differ, this file wins on **what and when**, and
[[stage-plan]] wins on **how** (parallelism, memory, gates).

> [!important] Status — planning only; B1 decided on 2026-10-29 (option D)
> No experiment has been run, so no result is claimed. B1 is decided: **option D**, the click-forward evaluation, and the
> hourly fast axis (T6h) is core (D22). Cell counts and the hourly scope remain estimates until T4 measures fit times.

## 1. The question

A news recommender is built from past clicks and articles, but news is replaced within hours. We measure how
much a **frozen** model degrades as days pass, which of three signals degrades first, and how often a rebuild
pays off. Signals: word matching (BM25), meaning matching (frozen multilingual MiniLM), click history (co-click
cosine); references: recency, popularity, and feed position (NPR only).

| ID | Question | Answered by stage | Evidence it produces |
|---|---|---|---|
| RQ0 | How fast do articles age; how much of the click stream is on articles newer than the fit date? | T3 | age curve and unseen-click share, with intervals |
| RQ1 | How fast does quality fall with time since the fit, in **hours** (fast axis) and days (slow axis)? | T6, T6h, T7 | decay against days since fit, per scorer and regime, paired intervals |
| RQ2 | Which signal falls first, and why? | T7 (with T4's scorers) | the same curves side by side, regime A versus B, four diagnostics |
| RQ3 | What rebuild interval balances quality and cost? | T8 | quality-against-cost curve for 1, 2, 3, 5, 7, 14 days |

## 2. The design in six decisions

| # | Decision | Status | Where it is carried out |
|---|---|---|---|
| 1 | One **decay matrix**: the metric for every (fit date r, day d > r) on the same sampled clicks (option D); all RQs are read from it | proposed (D5) | T6 |
| 2 | **Decay** = gap to a model rebuilt the previous day, M(d−1, d) − M(r, d) | proposed (D7) | T6, T7 |
| 3 | **Two regimes**: A fully frozen, B live profiles | proposed (D6); under option D, B = the profile gains the clicks made before each sampled click | T6 |
| 4 | **7-day sliding fit window** | proposed (D8); one corpus under option D | T1, T4, T6 |
| 5 | Metrics under option D: MRR and recall@10 primary, AUC and nDCG@5 secondary, paired bootstrap CIs, n always shown | proposed (D10) | T4, T7 |
| 6 | **Determinism contract** for parallel runs; memory budget 16 GB for the worker pool | proposed (D19) | every stage; tested in T5 |

Also fixed in the stage plan and recorded in the log once chosen: sample N = 20,000 impressions per day, reader
profile cap M = 50 clicks, unscorable candidates tie at the bottom in a seeded shuffle (D11).

## 3. Datasets (measured; detail in [[dataset-stats]])

| | Role | Why |
|---|---|---|
| **EB-NeRD large** | primary | impression lists, full text, publish times, long histories; **15 labelled days only** |
| **NPR (Globo)** | second, replication | 118 days, impression lists, publish times; no body text, 82 % one-time users |
| **Adressa** | optional | 90 days of clicks, publish times; **no impression lists** |

All three are parquet and inside this project's `data/`. The 17 GB Adressa tarball remains; **you will delete it
later** (I will not).

## 4. B1 — the design issue found on 2026-10-28 (decided 2026-10-29: option D)

> [!warning] B1: the EB-NeRD click corpus is not uniform across dates
> *Measured* on the local files (clicks per day, `data/stats/` and the history files):
>
> | Dates | What exists | Clicks a day |
> |---|---|---|
> | 27 Apr – 3 May | history of the **train** users only | about 4.6–6.7 M |
> | 4 – 17 May | history of train **and** validation users | about 9–13 M |
> | 18 – 25 May | validation history plus the impression clicks | about 6.7–8.5 M |
> | 26 May – 1 Jun | impression clicks only (history ends 25 May) | about 1.6–2.0 M |
>
> History clicks are **reads of any kind** (about 11 per user per day) and the impression clicks are clicks
> inside logged slates (about 4 per user per day). On the two days where both exist (18 and 25 May) only
> 0.4–0.7 % of (user, article) pairs appear in both, so they are different events, not duplicates.
> A 7-day window ending on 30 May holds roughly a fifth of the clicks of one ending on 17 May, and of a
> different kind. That would make "stale" and "less or different training data" indistinguishable, which is
> the confound the sliding window was meant to remove.

**What it affects:** the fit-date family (3–30 May, 28 dates), the cell count (301), the regime-B profile
definition, the daily-rebuilt control for late dates, and the hourly axis.

| Option | What it is | Gives | Costs |
|---|---|---|---|
| **A (recommended to try first)** | Fit only on the **history** (all-reads) corpus of the **validation cohort** (4–25 May), fit dates 10–24 May; evaluate on the **train cohort's** impressions, 18–25 May | one event type and one user population in every window; control available for every day; staleness up to 15 days; about 92 cells | shorter evaluation span (8 days); regime B can add only impression clicks after 18 May, so "live profile" is partial there |
| **B** | Fit only on **impression clicks**, 3-day windows from 18 May, fit dates 20–30 May | one event type throughout; the whole labelled span | thin corpus (a window is about 5 M clicks); history used only for profiles |
| **C** | Keep the mixed corpus and downsample every window to the same click count | removes the volume effect | does **not** remove the change of event type; only usable as a sensitivity run |
| **D (new, 2026-10-28; recommended)** | **Click-forward evaluation.** Fit and score on the **same click corpus**: the validation users' history (4–25 May, one event type, one cohort). For each sampled click (user, article, time *t*) on day *d*, rank the clicked article among the **pool** of articles published at or before *t* and within the last 48 hours (defined from publish time only). Fit dates 10–23 May, evaluation days 11–24 May | one uniform corpus end to end; no slates needed, so the **same harness runs on EB-NeRD, NPR and Adressa**; about 105 cells; staleness up to 14 days; uses the click logs as the main event | the pool window is a design choice (sensitivity run at 24, 48, 72 h); clicks on older articles (2.3 % in the measured week) are excluded and reported; recency and popularity become strong baselines; no conditioning on what the site showed |

**Decided 2026-10-29: D as primary, A as cross-check, B as robustness.** (Recommendation as put to the team: **D as primary**, with **A as a cross-check** (the train
users' impression slates, 18–25 May, scored by the same models; if the slate protocol and the click-forward
protocol tell the same story, the pool-based protocol is validated) and **B as a robustness run**. Either way, every figure that depends on the fit-date family is marked
*provisional* until this is settled; now settled.)

## 5. The stages and the schedule

| Stage | What | Planned | Depends on |
|---|---|---|---|
| T0 | decisions, folders, scaffold | 2026-10-28 | your answers |
| T1a–d | stores for EB-NeRD, NPR, Adressa, and the embeddings | 2026-10-29 → 30 | T0 |
| T2 | fixed sample (20,000 clicks a day) and profile slices | 2026-10-31 | T1a |
| T3 | model-free stage (RQ0) | 2026-10-31 → 11-02 | T1a |
| T4 | scorers and smoke test (sets worker counts) | 2026-10-31 → 11-03 | T1, T2 |
| T5 | leakage and determinism tests | 2026-11-03 → 04 | T4 |
| T6 | decay matrix, EB-NeRD (about 105 cells, estimate) | 2026-11-05 → 07 | T5 |
| T7 | RQ1 and RQ2 | 2026-11-08 → 11 | T6 |
| T8 | RQ3 | 2026-11-12 → 13 | T6 |
| T9 | second dataset | 2026-11-09 → 12 | T1b, T5 |
| T6h | **hourly fast axis** (core, gated on the measured fit time) | 2026-11-08 → 11 | T5, T6 |
| T10 | report and ai-log | 2026-11-15 → 20 | T7, T8, T9 |
| T11 | cleanup and freeze | 2026-11-18 → 19 | T10 |

Experiments stop on **2026-11-15**. The deadline is **2026-11-20**.

**Cut order** (first to go first): the extras of T6h (48 h tail, finer fit spacing) → Adressa → T9 (NPR) → the earliest fit date → the A-versus-B comparison →
per-signal fit seconds → the semantic scorer's second encoder. T0–T8 on one dataset is a complete project. The
daily-rebuilt control is never cut.

## 6. What the analysis reports

No hypotheses are fixed in advance and nothing is committed before a run; that practice was my addition, not a project
requirement ([[log]] D23, withdrawn 2026-10-29). The analysis reports, with intervals and *n*:

| Item | Where |
|---|---|
| decay against staleness, per scorer and regime, in hours and in days | T7, T6h |
| the click-history and meaning-matching curves side by side, regime A against B, and where word matching falls | T7 |
| the knee of the quality-against-cost curve for rebuild schedules | T8 |
| **recency check** (a harness check, not a finding): the recency scorer's gap must be exactly 0, otherwise there is a bug | T5 and every cell of T6 |

Staleness is at most 14 days under option D.

## 7. Decisions

| ID | Decision | State (2026-10-28) |
|---|---|---|
| D15 | Team | **decided: 3 people (Noel, Sidhardha, Emil), one pipeline** |
| — | Click-history method | **decided: co-click cosine first**, factorisation only as an extension |
| — | Priority | **our model, not the dataset**; datasets are carriers of the question |
| D13 | Git repo for `code/` | **deferred**; no deadline attached |
| D14 | Tell the instructor the primary dataset changed | open, low stakes |
| — | Second dataset | NPR by default; not yet challenged |
| **B1** | Fit-corpus and evaluation design | **decided 2026-10-29: D** (fit and score on clicks), with A as cross-check and B as robustness (D21) |
| D22 | Hourly fast axis is core (T6h), fit hours spread over the day | **decided 2026-10-29** |

**Clicks can fit the model and score it.** The model is fitted from click logs, and "how important the current
period is" can be read from them alone (RQ0). Scoring does not strictly need impression slates either: ranking
each later click among the articles that were live at that moment is a valid protocol, and it is the only one
Adressa allows. What impressions add is the set of candidates the site actually showed, which conditions on
exposure; that is why option A keeps them as a cross-check. *(Corrected 2026-10-28: an earlier version of this
paragraph said impressions are needed for the headline metric. That overstated it; [[datasets]] already described
the click-only protocol.)*


## 8. The hourly question (raised 2026-10-28)

For a fast-moving site the unit of staleness is hours, not days. *Measured* on EB-NeRD (validation users' history,
fit at 07:00 on 10–22 May, 75.9 M clicks with a publish time):

| Hours since the fit | Clicks on articles published after the fit |
|---|---|
| 1 | 19.5 % |
| 2 | 59.7 % |
| 3 | 77.2 % |
| 6 | 90.8 % |
| 12 | 95.4 % |
| 24 | 96.2 % |
| 48 | 97.4 % |

First day 87.0 %, second day 97.3 %. So **almost the whole transition happens in the first six hours**, and a daily
grid would see only the saturated end. Consequences: (1) the **fast axis moves from an optional extra (old T9b) to
a core stage, T6h**; (2) the daily grid stays as the slow axis and will probably look flat after day 1,
which is itself a finding; (3) RQ3 is likely to turn on hourly rebuilds or incremental updates, so the cost
side needs the incremental co-click update measured. Caveats: one fit hour (07:00) only, one cohort, and the
curve will differ with the hour of day; an hour about 01:00 has ten times fewer clicks than its neighbours and is
unexplained.

**Run on all three datasets (2026-10-28, [[log]] P30, P31).** Same measure, fit at 07:00 local time, 95 % intervals over fit days:

| Dataset (fit days) | 1 h | 6 h | 24 h | Hours to 50 % | Hours to 90 % |
|---|---|---|---|---|---|
| EB-NeRD (13) | 19.5 % [14.6, 23.9] | 90.8 % [88.5, 92.5] | 96.2 % [95.8, 96.5] | 2 | 6 |
| Adressa (80) | 6.4 % [4.8, 8.3] | 48.5 % [45.4, 51.5] | 87.8 % [86.8, 88.7] | 7 | 40 |
| NPR (85) | 1.0 % [0.7, 1.5] | 15.5 % [11.3, 20.1] | 85.6 % [80.6, 89.7] | 13 | 34 |

The time scale differs by roughly ten times between publishers, so **T6h is needed on EB-NeRD but a daily grid is already
informative on NPR**. The tails do not follow the median click age, so no single-scale rule is claimed. The event types
differ between the datasets, which is a confound.

**Fit hour matters (log P32).** On EB-NeRD the hours to 50 % are 2 for a fit between 06:00 and 18:00 but 6 for a fit at midnight or 21:00;
Adressa goes from 4 h (18:00) to 13 h (00:00); NPR stays at 12–16 h whatever the hour. So **T6h must sample fit hours across the
day, not one hour**, and every hourly curve is reported per fit hour with its interval. The EB-NeRD timestamps were read as UTC;
their real time zone is not established and is checked in T1a.

---
[[IRE-Term-Project|← tracking note]] · [[stage-plan]] · [[cross-check]] · [[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/tasks-explained|tasks-explained]] · [[Subjects/IRE/Projects/IRE-Term-Project/docs/planning/architecture|architecture]] · [[Subjects/IRE/Projects/IRE-Term-Project/log|log]]
