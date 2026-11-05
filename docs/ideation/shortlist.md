---
type: note
kind: reference
title: Term project — our shortlist
---

# Term project — our shortlist

These are the broad domains and the topics within them that we were able to reduce to, or thought of as interesting.

## Domains

- **News**
- **E-commerce**
- **Multi-Lingual**
- **Health** — back-up domain. A chatbot that takes ordinary everyday conversation, maps it to medical terms, and replies back in ordinary terms.

---

## News: how fast does it go stale? *(News)*

We train a news recommender on one week of clicks, then keep using it. It gets worse every day, because new articles keep arriving and people's interests move.

We measure exactly how fast it degrades. We find out which part rots first — the word matching, the meaning matching, or the click history. Then we work out how often we would have to rebuild it to keep it good enough.

The result is a trade-off curve: rebuild more often, spend more compute, get better results. That curve is the answer.

**Why it's good:** this is exactly what the course says IR is — paying a cost to get relevance. It needs no new data at all, and we can explain it to anyone in one sentence.

## E-commerce: does it work in another language? *(E-commerce × Multi-Lingual)*

Amazon has shopping data from six countries in six languages, all in one dataset with the same format.

We build one recommender and run it on all six. Then we ask whether it works equally well everywhere, or whether it only looked good because it was built and tested on English data.

Then we push harder: train it on the big languages, test it on the small ones, and see how badly it falls over.

**Why it's good:** every company expanding into a new country faces this exact problem. And because all six languages sit in one dataset with one format, nobody can argue our comparison is unfair.

## E-commerce: what is a "close enough" result worth? *(E-commerce)*

Search a shop for running shoes. Some results are exactly what you asked for. Some are substitutes — a different brand of running shoe. Some are complements — socks. Some are junk.

Amazon's data labels all four of those separately. But every scoring method squashes them into a single number, which means somebody quietly decided how much a substitute is worth — half of an exact match? A tenth? Nobody ever justifies that choice.

We take the same set of systems, score them several times with different values for a substitute, and check whether the "best" system changes depending on that choice.

**Why it's good:** it's a real argument that happens inside companies, and the published scores already hint something is wrong here. Even if the answer is "nothing changes," that's worth reporting — everyone assumes it without checking.

## Multilingual: does the trick still work in a smaller language? *(Multi-Lingual)*

Search techniques get invented in English, tested in English, and then written up as if they work everywhere. But English has more text on the internet than almost any other language, so the technique might be borrowing that abundance rather than being genuinely good.

There is a dataset — MIRACL — with the same search task in 18 languages, ranging from English and Chinese down to Swahili and Telugu, all judged by people who actually speak them.

So we run the same method on all 18 and plot how much it helps against how much data each language has. If the line slopes downward, the technique was partly living off English's abundance. If it stays flat, the technique is genuinely good.

We can then ask why it slopes. Two suspects: the language simply has less training data, or the language is built differently — Telugu, Tamil and Malayalam glue endings onto words, and Chinese, Japanese and Thai don't put spaces between words at all, which breaks the word-counting that older methods rely on.

**Why it's good:** almost nobody reports that slope, only the average. It runs on data we download once, needs no new labels, and "the slope is flat" is just as publishable as "the slope is steep". If anyone on the team reads Telugu, Hindi or Malayalam, we can also check the results by eye — which most teams working on these languages genuinely cannot do.

## Health: everyday words in, medical answers out, everyday words back *(Health — back-up)*

People describe symptoms the way they actually talk — "my chest feels tight", "I keep waking up thirsty". The documents that answer them are written in clinical language — "angina", "polyuria". The gap between those two vocabularies is the whole problem, and it runs in both directions: we have to translate the question *into* medical terms to find anything, and translate the answer *back* so it's readable.

So we build a chatbot with three stages. It takes an ordinary sentence, maps it to the medical terms that would actually appear in the literature, retrieves against those, and then replies in ordinary language again.

What makes this a retrieval project rather than a chatbot demo is that the middle stage is measurable. We can compare retrieving on the raw everyday phrasing against retrieving on the mapped medical terms, and report how much the mapping actually buys — per query, and grouped by how far apart the two vocabularies were to begin with.

**Why it's good:** the vocabulary gap is exactly where word-matching methods fail and meaning-based methods should win, so it is a clean test of something the course teaches directly. The data is free and needs no registration.

> [!warning] The one thing that could sink this
> We must not end up judging whether the medical advice is *correct* — we are not clinicians, and that claim is not ours to make. What we can judge is whether the answer **follows from the document we retrieved**, which is a reading-comprehension question anyone can check.
>
> We state that distinction explicitly, and we use the existing relevance judgements rather than writing our own. If we start inventing medical labels, the project stops being defensible.

---

## Why health is the back-up and not the main choice

It is the most appealing of the four to demo and the easiest to explain to someone outside the course. But it is a back-up for two reasons we should be honest about:

- **It is the only one of the four that needs us to build a system rather than measure one.** The other three re-score or re-run things that already exist; this one has a generation stage on both ends, and generation is where the time goes.
- **The evaluation is the weakest.** We would be measuring a retrieval improvement inside a pipeline whose output is text, and text is harder to score honestly than a ranking.

If the main choice runs into trouble, this is what we fall back to — but we should pick it deliberately, not drift into it because it demos well.

---
[[IRE-Term-Project|← tracking note]] · [[project-ideas|full analysis: domains, datasets, candidates]] · [[_syllabus|IRE course plan]] · [[Dashboard]]
