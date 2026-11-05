---
type: project
title: IRE Term Project
status: todo
due: 2026-11-20
priority: high
---

# IRE Term Project

**Final due:** 2026-11-20 · **Teams of up to 3** · **25% of grade**

A research/engineering problem in retrieval or recommendation with reasonable complexity.

> [!important] The bar
> **Depth and rigor of the study, not breadth.** May focus on a single thread — systems, ML, or
> evaluation. A narrow question answered well beats a broad one answered shallowly.

## Goal
Measure how fast a news recommender goes stale: how much a frozen model degrades as days pass, which of three
signals (word matching, meaning matching, click history) degrades first, and how often a rebuild pays off.
Primary data EB-NeRD; second dataset NPR; Adressa optional. Our **model** is the priority, not the dataset.
Plan: [[current-plan]] (what and when), [[stage-plan]] (how), [[cross-check]] (the two checked against each other).

> [!success] Team size resolved (2026-10-28)
> The team is **3 people, one pipeline**, within the cap of 3. The 2 + 2 option in
> [[project-ideas#The 2 plus 2 structure]] is not needed. Grading is individual either way.

## Submissions
- [ ] Ask instructor: 4-person team, or register 2+2? 📅 2026-08-24
- [ ] Declare project group (up to 3) 📅 2026-08-30
- [ ] Initial proposal + literature survey; identify the gap in prior work 📅 2026-08-31
- [ ] Problem finalized; working pipeline / experimental setup 📅 2026-09-30
- [ ] Completed investigation: ablations, evaluation, scaling discussion 📅 2026-11-20

## Sections
- [ ] Read domains + candidates; shortlist 2–3 📅 2026-08-24
- [ ] Pick the domain; download its data and confirm it loads 📅 2026-09-05
- [ ] Literature survey — cluster papers, find the gap 📅 2026-08-29
- [ ] Narrow the scope to something finishable 📅 2026-09-15
- [ ] Baseline + experimental harness 📅 2026-09-28
- [ ] Main experiments 📅 2026-10-25
- [ ] Ablations + scaling analysis 📅 2026-11-10
- [ ] Report 📅 2026-11-18

## Acceptable directions (from the course plan)

⭐ **[[shortlist|Our shortlist]]** — the four domains and problems we reduced to, in plain language, in our
own words. **Start here**; the file below is the full analysis behind it.

📋 **[[project-ideas|Three domains, their datasets, and candidate projects]]** — the search space is
closed to **e-commerce, multilingual, news** and the pairs between them. Everything else considered and
dropped. Organised **strongest datasets first**, because at this budget the data decides the project.

🌍 **[[project-ideas#Part 1 · The three domains, ranked by dataset strength|The three domains, ranked]]**

| Rank | Domain | The data | Entry cost |
|---|---|---|---|
| **1** | **E-commerce** | **ESCI: 2.6M human judgements**, 130k queries, 4-way graded, **Apache-2.0**, parquet · **Amazon-M2: millions of sessions, 6 locales** · XMarket: 52M reviews | **~15 hrs** |
| **2** | **Multilingual** | **MIRACL: 726k native-speaker judgements**, 78k queries, **18 languages**, ~5.9M passages/lang · **mMARCO: 13 langs, translated** | ~20 hrs |
| **3** | **News** | MIND 24.2M clicks · EB-NeRD 251M interactions · **Adressa 27.2M** · plista · NPR · IDEA | **~0 hrs** (in hand) |

**Dataset strength: e-commerce > multilingual > news. Total project cost: news > e-commerce >
multilingual.** Each domain has 3–4 *aspects* (different ways to see it), not one framing.

🇮🇳 **[[project-ideas#Indian languages — what's actually available|Indian languages]]** — **Hindi, Bengali
and Telugu have native-speaker judgements in MIRACL; Malayalam, Tamil and Kannada do not.** For those,
**IndicIRSuite** (11 languages incl. Malayalam/Tamil/Telugu, ⚠️ machine-translated) and **IndicRAGSuite**
(AI4Bharat, 13 languages, ⚠️ human-translated queries + LLM-generated training data) are the routes.
Telugu/Hindi/Bengali having *both* native and translated labels is what makes Candidate 3 sharp.

🔗 **[[project-ideas#Part 2 · The inter-domain pairs — where the best questions live|Inter-domain pairs]]**
— combinability tested on schema · labels · licence · shared metric. **The standout: Amazon-M2 is
natively e-commerce × multilingual**, so that pair needs no comparability argument. News×multilingual and
news×e-commerce are ⚠️ parallel-axes-only — never pool them.

⏱️ **[[project-ideas#Part 3 · Eight candidates|Eight candidates]]** — each opens with the broad idea in
plain terms, then the question, 2+2 split, and cost against ~165 research-hours.
**Recommendation: Candidate 2** (Amazon-M2 across 6 locales — strongest data, cleanest inter-domain
design, domain-shift task *given*). **Candidate 6** (news temporal decay) is the zero-new-data fallback;
**Candidate 8** (signal ablation) is the safety net that cannot fail.

🏆 **[[project-ideas#The challenge families in these domains|The challenge families]]** — **KDD Cup 2022 =
ESCI**, **KDD Cup 2023 = Amazon-M2**, RecSys 2024 = EB-NeRD = A-1, plus TREC, SemEval-2025 T7
(mono+crosslingual, on Codabench) and MTEB/BEIR. Both e-commerce datasets are ex-KDD-Cup, which is why
they ship splits, metrics, baselines *and* participant papers.

🧭 **[[project-ideas#Part 5 · Generating your own ideas|How to generate better ideas]]** — one spine, one
variation axis; the newly-useful axes are **label granularity**, **annotation provenance** (native vs.
translated) and **schema richness**; five prompts; and a filter that kills a bad idea in 10 minutes.

**The five sanctioned directions** (from the course plan) — your project must sit in one:

- Conversational search with query rewriting
- Long-term memory for search/recommendation agents
- Generative retrieval (DSI-lite) — ⚠️ **compute-blocked on free-tier GPU**
- RAG evaluation frameworks
- Standing-query web monitoring (change detection) — needs a corpus that changes, so **news**

## Optional bonus track (up to +10%, individual, due 2026-11-20)
- [ ] *(optional)* Marketplace simulation full build, **or** research survey 📅 2026-11-20

## Team
| Member | Roll number |
|---|---|
| Noel Alex Jacob | 2025201085 |
| Emil Joji | 2025201040 |
| Kspsvln Siddardha Kumar Kavuri (called "Sidhardha" in the notes) | 2025201061 |

One shared pipeline; who owns which stage is not decided yet (see [[stage-plan]]).

## Log
- 2026-10-26 — viability check of the temporal-decay proposal; EB-NeRD primary; datasets surveyed ([[datasets]]).
- 2026-10-27 — NPR downloaded and profiled; Adressa converted to parquet (3.11 GB, verified); EB-NeRD copied into `data/`.
- 2026-10-28 — team fixed at 3, one pipeline; click-history method fixed as co-click cosine; plans written in `docs/plan/`; **B1** (non-uniform EB-NeRD click corpus) open.

---
[[_syllabus|IRE course plan]] · [[Dashboard]]
