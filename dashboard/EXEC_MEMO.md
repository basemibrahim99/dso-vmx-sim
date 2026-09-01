# Portfolio Value Review — Dental Group (10 locations)

*Prepared for: Deal team / Operating partner review*
*Data: synthetic, `SIM`-prefixed throughout*

## Bottom line

Two independent signals — chair capacity and patient retention — point at
the same four locations. Fixing operational execution there is worth an
estimated **$9.3M/year in recoverable capacity**, and proactive outreach
to at-risk patients portfolio-wide protects roughly **$4.2M/year** in
revenue that's currently exposed.

## Finding 1: Capacity is under-utilized at 4 of 10 locations

Portfolio average chair utilization is 74.5%. Four locations sit below
that:

| Location | Utilization | Gap to benchmark | Idle capacity, annualized |
|---|---|---|---|
| Winnipeg, MB | 68% | -6.5pts | ~$994K/yr |
| Hamilton, ON | 71% | -3.5pts | ~$901K/yr |
| Calgary, AB | 71% | -3.5pts | ~$1.56M/yr |
| Kelowna, BC | 72% | -3pts | ~$1.75M/yr |

Combined, closing this gap represents **~$178,993/week (~$9.3M/year)** in
recoverable revenue capacity across the portfolio — the highest-leverage,
lowest-risk lever available, since it doesn't require new patient
acquisition, only better scheduling utilization of chairs already staffed
and paid for.

**Recommendation**: prioritize a scheduling/operations review at these
four sites first — the same underlying issue (elevated no-show rates)
shows up at all four, suggesting a fixable process gap rather than four
unrelated problems.

## Finding 2: 6,342 patients are at high risk of churning

A predictive model flags 6,342 patients (of ~90K active) as high
churn-risk, representing **~$4.2M in at-risk annual revenue**. Risk is not
evenly distributed — the same four underutilized locations also carry the
largest concentration of at-risk patients and revenue, reinforcing that
these sites need attention on both the supply side (capacity) and the
demand side (retention).

**Recommendation**: stand up proactive recall outreach for the high-risk
segment, starting at the four flagged locations. Even a modest reduction
in realized churn among this group returns disproportionately, since
they're concentrated rather than spread thin across the portfolio.

## What this is built on

Two models, each validated against data the model never saw during
training or scoring:
- **Chair utilization**: recovered location performance ranking with a
  0.94 rank correlation against the true (held-out) location-quality signal.
- **Churn risk**: a prospective model (trained on a historical window,
  scored on current data — not fit to already-known outcomes) that
  correctly ranks patient risk meaningfully above chance, bounded by a
  real statistical ceiling — a meaningful share of individual churn risk
  is driven by factors no operational data can observe.

Full methodology, validation detail, and the underlying pipeline: see
[`SDD.md`](../SDD.md).
