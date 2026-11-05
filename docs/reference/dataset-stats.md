---
type: note
kind: reference
title: Term project — complete statistics for the three datasets
---

# Complete statistics — EB-NeRD, NPR, Adressa

Everything here was **measured** on 2026-10-27 from the local parquet files (scripts in the session scratchpad,
not kept in the project). Per-day CSVs are in `data/stats/`. Companion to [[datasets]]; decisions in
[[Subjects/IRE/Projects/IRE-Term-Project/log|log]].

> [!important] Definitions used throughout
> - **Day:** EB-NeRD, the calendar date of the impression; NPR, the calendar date after shifting the UTC
>   timestamp by 3 hours (Brasília); Adressa, the Norwegian local day of its file.
> - **Click:** EB-NeRD, an entry in `article_ids_clicked`; NPR, the one clicked item of an impression;
>   Adressa, an event that carries an article (`id` present). Adressa events without an article (front pages and
>   similar) are **not** clicks and are listed separately as *events*.
> - **Per-day summaries** read *min / median / mean / max*.
> - **Article age at click:** click time minus the article's publish time, in hours.

## 1. Side by side

| | EB-NeRD large | NPR (Globo) | Adressa |
|---|---|---|---|
| Format on disk | parquet (A1 work folder) | parquet (`data/npr/raw/`) | parquet (`data/adressa/parquet/`, converted) |
| Language | Danish | Portuguese | Norwegian |
| Days with data | 15 (14 full, 1 Jun partial) | 116 of 118 | 90 of 90 |
| Records | 24,630,275 impressions | 1,402,576 impressions | 113,579,695 events |
| Clicks | 24,783,679 | 1,402,576 | 35,244,078 (article events, 31.0 % of events) |
| Distinct users | 974,791 | 1,162,802 | 4,805,071 (3,614,911 with an article click) |
| Distinct articles | 125,541 in the file | 148,099 in the file | 81,018 clicked |
| Impression lists | yes | yes | **none** |
| Article text | title, subtitle, body | title and topics only | title, keywords, author, category, weighted profile; no body |
| Publish time | yes (100 % of clicked) | yes (100 % of clicked) | yes (93.3 % of article events) |

## 2. Per-day volume *(min / median / mean / max)*

| | EB-NeRD (14 full days) | NPR (112 days with 3,000+ impressions) | Adressa (90 days) |
|---|---|---|---|
| Impressions or events | 1,421,920 / 1,722,884 / 1,727,324 / 1,995,799 | 3,014 / 10,488 / 12,497 / 43,585 | 913,575 / 1,261,410 / 1,261,997 / 1,657,608 |
| Clicks | 1,430,649 / 1,733,244 / 1,738,111 / 2,010,881 | same as impressions | 221,357 / 394,007 / 391,601 / 601,357 |
| Users | 379,819 / 418,718 / 417,139 / 449,267 | 2,946 / 9,962 / 11,882 / 39,638 | 183,658 / 246,594 / 244,590 / 377,125 |
| Users with an article click | n/a | n/a | 110,026 / 162,572 / 164,262 / 304,750 |
| Distinct articles clicked | n/a | n/a | 4,642 / 7,456 / 7,288 / 8,488 |

EB-NeRD 2023-06-01 is partial (450,121 clicks, 167,820 users). NPR has no data on 2023-01-20 and 2023-04-27, and
4 days under 3,000 impressions that are left out of the NPR column: 2023-02-12 (75), 2023-03-04 (1,543), 2023-04-05 (811), 2023-04-12 (441).

## 3. Users and click depth

| | EB-NeRD | NPR | Adressa |
|---|---|---|---|
| Impressions per user (median / mean / 90th pct) | 13 / 25.3 / 66 | 1 / 1.21 / 2 | n/a |
| Users with a single impression | 8.2 % | 82.2 % | n/a |
| Article clicks per clicking user (median / mean / 90th / 99th) | n/a | n/a | 2 / 9.7 / 14 / 178 |
| Clicking users with exactly one click | n/a | n/a | 49.0 % |
| Users active on one day only | n/a | n/a | 65.4 % |
| Users active on 7 or more days | n/a | n/a | 560,226 (11.7 %) |
| Users with 5 or more article clicks | n/a | n/a | 805,816 |
| Stored history per user (median / mean / 90th) | 86 / 151 / 386 clicks | 6 / 11.7 / 34 items | n/a (the event stream is the history) |
| Users with empty history | 0.0 % | 0.0 % | n/a |

## 4. Slates (impression lists)

| | EB-NeRD | NPR | Adressa |
|---|---|---|---|
| Candidates per impression (mean / median / 90th / max) | 11.5 / 9 / 22 / 100 | 10.0 / 10 / 10 / 40 | none |
| Impressions with exactly one click | 99.5 % | 100 % | n/a |
| With more than one click | 0.5 % | 0 % | n/a |
| With no click | 0.0 % | 0 % | n/a |

## 5. Article age at click *(hours since publication)*

| | EB-NeRD | NPR | Adressa |
|---|---|---|---|
| Clicks with a publish time | 24,630,275 | 1,402,576 | 32,899,130 |
| Median | 3.0 h | 13.8 h | 5.6 h |
| 85th percentile | 10.6 h | 26.5 h | 26.9 h |
| 95th percentile | 40.1 h | 63.3 h | 438.3 h |
| Within 24 hours | 93.3 % | 81.5 % | 81.6 % |
| Older than 30 days | 2.0 % | 0.4 % | 4.6 % |
| Clicks before the publish time | 0.0 % | 0.0 % | 1.3 % |

More than 80 % of clicks land within a day of publication in all three. EB-NeRD is the fastest (median
3.0 h); Adressa has the longest tail (the 95th percentile is
18 days, and 4.6 % of clicks are on articles older than 30 days).
The Adressa clicks-before-publication share (1.3 %) is probably a publish-time clock or
timezone artefact; not investigated. Ages are measured against UTC timestamps; NPR `publishDate` has no
time zone in the file, and aligning it with the UTC click times gives no negative ages.

## 6. Articles

| | EB-NeRD | NPR | Adressa |
|---|---|---|---|
| Articles | 125,541 in the file, 64,213 published 2020 or later | 148,099 (2014–2023; about 17–22 k a month in Jan–Apr 2023) | 81,018 clicked |
| Published per day (median) | 162 (18–31 May) | 750 | see `data/stats/adressa_publish_per_day.csv` |
| Title length (median words) | 6 | 14 | not measured |
| Body length (median characters) | 1799 | 2308 (count only, no text) | no body |
| Categories or topics | 29 categories | 102 topics | 136 `category1` values |
| Premium share | 10.0 % | n/a | n/a |

## 7. Dataset-specific

**EB-NeRD.** Subscribers 6.6 % of impressions; SSO users 10.4 %; median read time 21 s. Devices (codes as in the dataset): 2: 15,355,302, 1: 8,523,577, 3: 750,583, 0: 813. History covers 974,791 users.

**NPR.** Logged users 412,822 impressions, non-logged 989,754. Algorithm mix: top-state 1,224,048 (87.3 %), als 92,700 (6.6 %), recents 76,700 (5.5 %), top 9,128 (0.7 %). Clicked feed position: position 1 41.4 %, position 2 28.1 %, position 3 11.6 %.

**Adressa.** Devices: Mobile 47.5 %, Desktop 33.8 %, Tablet 18.7 %. Operating systems: iPhone OS 38.8 %, Windows 29.3 %, Android 27.0 %, Macintosh 4.2 %. Referrer class: direct 50.0 %, internal 34.0 %, search 9.3 %, other 3.6 %, social 3.1 %. Country: no 95.9 %, es 1.0 %, se 0.9 %. `activeTime` present on 51.4 % of events (median 25 s, mean 45 s).

## 8. Adressa, every day *(Norwegian local days)*

| Date | Events | Article clicks | Users | Users with an article click | Distinct articles clicked |
|---|---|---|---|---|---|
| 2017-01-01 | 1,513,739 | 435,885 | 248,892 | 164,365 | 4,642 |
| 2017-01-02 | 1,613,128 | 502,292 | 310,255 | 195,512 | 6,168 |
| 2017-01-03 | 1,648,346 | 492,448 | 297,376 | 203,408 | 5,725 |
| 2017-01-04 | 1,496,417 | 601,357 | 295,788 | 238,226 | 6,597 |
| 2017-01-05 | 1,327,429 | 463,358 | 257,171 | 187,092 | 7,044 |
| 2017-01-06 | 1,356,987 | 290,523 | 238,124 | 131,740 | 6,091 |
| 2017-01-07 | 1,087,223 | 316,128 | 199,643 | 129,846 | 5,963 |
| 2017-01-08 | 1,206,322 | 365,654 | 223,291 | 143,721 | 6,009 |
| 2017-01-09 | 1,296,258 | 364,810 | 240,758 | 150,464 | 7,294 |
| 2017-01-10 | 1,221,035 | 361,737 | 246,974 | 164,668 | 6,699 |
| 2017-01-11 | 1,224,147 | 329,900 | 245,966 | 152,320 | 6,700 |
| 2017-01-12 | 1,396,707 | 402,910 | 257,636 | 174,194 | 6,658 |
| 2017-01-13 | 1,237,995 | 367,991 | 235,199 | 158,927 | 6,376 |
| 2017-01-14 | 1,028,315 | 316,786 | 199,654 | 137,195 | 5,806 |
| 2017-01-15 | 1,095,184 | 353,533 | 207,076 | 141,613 | 6,386 |
| 2017-01-16 | 1,385,196 | 465,651 | 249,011 | 172,703 | 7,260 |
| 2017-01-17 | 1,330,218 | 456,632 | 273,943 | 179,122 | 7,679 |
| 2017-01-18 | 1,554,776 | 598,365 | 377,125 | 304,750 | 7,461 |
| 2017-01-19 | 1,308,269 | 445,768 | 265,603 | 188,221 | 7,496 |
| 2017-01-20 | 1,233,003 | 440,500 | 251,517 | 184,857 | 6,990 |
| 2017-01-21 | 998,882 | 323,061 | 194,364 | 130,333 | 6,147 |
| 2017-01-22 | 1,193,499 | 420,624 | 210,343 | 150,147 | 6,885 |
| 2017-01-23 | 1,319,823 | 453,739 | 255,105 | 181,168 | 7,866 |
| 2017-01-24 | 1,350,226 | 425,129 | 313,274 | 219,483 | 7,613 |
| 2017-01-25 | 1,400,735 | 319,894 | 263,342 | 149,007 | 7,404 |
| 2017-01-26 | 1,360,001 | 390,103 | 256,049 | 164,823 | 7,602 |
| 2017-01-27 | 1,340,865 | 438,087 | 241,773 | 169,754 | 7,256 |
| 2017-01-28 | 1,213,501 | 399,396 | 221,829 | 156,531 | 6,542 |
| 2017-01-29 | 1,179,764 | 459,476 | 242,427 | 184,348 | 7,038 |
| 2017-01-30 | 1,325,344 | 439,124 | 260,483 | 181,459 | 8,060 |
| 2017-01-31 | 1,225,622 | 276,220 | 241,828 | 135,437 | 7,676 |
| 2017-02-01 | 1,309,447 | 268,667 | 239,959 | 130,238 | 7,451 |
| 2017-02-02 | 1,237,784 | 331,377 | 234,559 | 142,397 | 7,507 |
| 2017-02-03 | 1,198,645 | 390,186 | 222,612 | 155,287 | 7,310 |
| 2017-02-04 | 960,878 | 296,243 | 201,079 | 131,620 | 6,569 |
| 2017-02-05 | 1,216,714 | 409,087 | 220,549 | 154,367 | 7,292 |
| 2017-02-06 | 1,261,152 | 365,532 | 292,782 | 192,678 | 7,794 |
| 2017-02-07 | 1,326,637 | 440,160 | 292,848 | 210,769 | 7,791 |
| 2017-02-08 | 1,340,304 | 374,245 | 246,978 | 163,669 | 7,473 |
| 2017-02-09 | 1,451,664 | 472,758 | 256,819 | 182,541 | 7,615 |
| 2017-02-10 | 1,171,730 | 411,431 | 220,695 | 159,220 | 7,302 |
| 2017-02-11 | 1,081,598 | 378,599 | 208,913 | 152,252 | 6,305 |
| 2017-02-12 | 1,058,280 | 313,662 | 207,183 | 133,328 | 6,879 |
| 2017-02-13 | 1,373,508 | 502,209 | 264,441 | 195,466 | 7,958 |
| 2017-02-14 | 1,336,681 | 341,901 | 260,200 | 146,189 | 7,475 |
| 2017-02-15 | 1,269,491 | 332,387 | 266,152 | 165,398 | 7,542 |
| 2017-02-16 | 1,283,761 | 401,061 | 249,679 | 169,696 | 7,503 |
| 2017-02-17 | 1,204,150 | 357,862 | 236,533 | 151,809 | 7,206 |
| 2017-02-18 | 950,713 | 221,357 | 201,596 | 110,026 | 6,391 |
| 2017-02-19 | 1,071,515 | 347,429 | 219,185 | 149,823 | 7,158 |
| 2017-02-20 | 1,289,415 | 352,408 | 248,107 | 155,174 | 7,824 |
| 2017-02-21 | 1,282,644 | 350,917 | 259,383 | 161,476 | 7,598 |
| 2017-02-22 | 1,251,893 | 397,828 | 259,878 | 181,872 | 7,632 |
| 2017-02-23 | 1,179,985 | 404,447 | 259,125 | 180,835 | 7,247 |
| 2017-02-24 | 1,239,071 | 477,140 | 247,849 | 190,005 | 6,954 |
| 2017-02-25 | 1,093,834 | 343,899 | 203,357 | 142,003 | 6,303 |
| 2017-02-26 | 1,312,271 | 410,262 | 223,627 | 150,806 | 6,871 |
| 2017-02-27 | 1,261,669 | 345,250 | 231,739 | 141,587 | 7,849 |
| 2017-02-28 | 1,258,236 | 439,760 | 258,949 | 182,839 | 8,110 |
| 2017-03-01 | 1,356,881 | 442,206 | 264,712 | 182,482 | 7,746 |
| 2017-03-02 | 1,231,504 | 349,041 | 240,463 | 153,610 | 7,576 |
| 2017-03-03 | 1,252,460 | 429,054 | 244,044 | 165,171 | 7,253 |
| 2017-03-04 | 1,105,324 | 314,256 | 214,326 | 133,457 | 6,392 |
| 2017-03-05 | 1,271,461 | 532,385 | 256,424 | 201,565 | 7,257 |
| 2017-03-06 | 1,354,321 | 385,955 | 263,143 | 171,708 | 8,378 |
| 2017-03-07 | 1,657,608 | 523,965 | 278,261 | 193,784 | 8,186 |
| 2017-03-08 | 1,427,383 | 420,210 | 268,144 | 178,093 | 7,720 |
| 2017-03-09 | 1,332,963 | 356,732 | 254,404 | 154,860 | 8,044 |
| 2017-03-10 | 1,150,646 | 309,930 | 219,906 | 134,347 | 7,596 |
| 2017-03-11 | 913,575 | 276,061 | 183,658 | 117,630 | 6,578 |
| 2017-03-12 | 1,051,516 | 346,083 | 215,612 | 145,882 | 7,533 |
| 2017-03-13 | 1,330,838 | 406,345 | 249,181 | 171,339 | 8,267 |
| 2017-03-14 | 1,391,247 | 414,916 | 258,719 | 175,048 | 8,295 |
| 2017-03-15 | 1,529,909 | 442,233 | 287,279 | 190,642 | 8,048 |
| 2017-03-16 | 1,270,612 | 443,792 | 250,181 | 178,843 | 8,229 |
| 2017-03-17 | 1,340,317 | 424,289 | 241,050 | 164,317 | 7,685 |
| 2017-03-18 | 1,035,710 | 331,914 | 191,426 | 127,734 | 6,672 |
| 2017-03-19 | 1,078,712 | 382,265 | 205,386 | 147,029 | 7,405 |
| 2017-03-20 | 1,255,098 | 415,566 | 257,045 | 174,591 | 8,488 |
| 2017-03-21 | 1,300,119 | 480,288 | 268,274 | 195,157 | 8,325 |
| 2017-03-22 | 1,285,084 | 437,240 | 247,273 | 174,013 | 8,280 |
| 2017-03-23 | 1,306,720 | 279,466 | 244,720 | 136,201 | 7,897 |
| 2017-03-24 | 1,227,699 | 339,362 | 246,647 | 146,486 | 7,741 |
| 2017-03-25 | 1,005,218 | 339,728 | 198,649 | 138,954 | 6,962 |
| 2017-03-26 | 1,170,799 | 435,107 | 224,866 | 165,534 | 7,083 |
| 2017-03-27 | 1,252,727 | 340,570 | 236,741 | 145,374 | 8,284 |
| 2017-03-28 | 1,243,203 | 402,591 | 237,672 | 160,455 | 8,265 |
| 2017-03-29 | 1,230,608 | 402,243 | 240,996 | 165,619 | 8,036 |
| 2017-03-30 | 1,365,708 | 293,220 | 246,540 | 140,006 | 7,980 |
| 2017-03-31 | 1,111,099 | 351,920 | 220,776 | 144,839 | 7,692 |
| **Total / distinct** | 113,579,695 | 35,244,078 | 4,805,071 distinct | 3,614,911 distinct | 81,018 distinct |

The daily user columns count users per day, so they do not add up to the distinct total.

## 9. EB-NeRD, every day

| Date | Impressions | Clicks | Users | Mean slate size |
|---|---|---|---|---|
| 2023-05-18 | 1,421,920 | 1,430,649 | 379,819 | 11.2 |
| 2023-05-19 | 1,897,879 | 1,909,541 | 430,051 | 11.3 |
| 2023-05-20 | 1,548,080 | 1,556,394 | 386,084 | 11.2 |
| 2023-05-21 | 1,643,980 | 1,652,051 | 396,723 | 11.2 |
| 2023-05-22 | 1,808,738 | 1,819,896 | 441,885 | 10.9 |
| 2023-05-23 | 1,674,124 | 1,684,700 | 420,908 | 10.9 |
| 2023-05-24 | 1,665,494 | 1,674,984 | 416,528 | 10.7 |
| 2023-05-25 | 1,639,851 | 1,651,579 | 443,249 | 11.3 |
| 2023-05-26 | 1,810,037 | 1,822,703 | 444,742 | 11.4 |
| 2023-05-27 | 1,558,351 | 1,567,684 | 384,221 | 11.6 |
| 2023-05-28 | 1,771,644 | 1,781,789 | 400,061 | 12.5 |
| 2023-05-29 | 1,851,104 | 1,861,553 | 410,957 | 12.4 |
| 2023-05-30 | 1,995,799 | 2,010,881 | 449,267 | 12.2 |
| 2023-05-31 | 1,895,537 | 1,909,154 | 435,457 | 11.9 |
| 2023-06-01 (partial) | 447,737 | 450,121 | 167,820 | 12.1 |

NPR's 116 days are in `data/stats/npr_daily.csv` (date, impressions, users, mean slate size) and summarised in section 2.

## 10. What these numbers say about the plan

- **Volume is not a constraint on EB-NeRD or Adressa.** A 20,000-impression daily sample is a small fraction of a day. On NPR a day holds about 10,000 impressions, so days are pooled.
- **Click history is rich on EB-NeRD** (median 86 history clicks) **and sparse on NPR** (median 6; 82.2 % of users appear once). Adressa is between them: half of clicking users have one click, but 805,816 users have five or more.
- **Adressa has no slates**, so its candidate pool must be built from publish time. About 7,288 distinct articles are clicked per day, which bounds that pool.
- **Staleness pressure:** in all three, over 80 % of clicks come within 24 hours of publication, so a model built a day ago has lost most of the articles being clicked now. Median age at click is 14 h on NPR and 3 h on EB-NeRD.
