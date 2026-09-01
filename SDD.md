# SDD — DSO VMX Simulator (MVP)

## 1. Purpose

A synthetic multi-location dental group (DSO), built to demonstrate the
actual workflow of a PE Value Maximization analyst: unify messy
multi-system data from a portfolio company, then surface insight that maps
to EBITDA impact, downside risk, or a roll-up/expansion decision — not just
a model score.

Every deliverable in this MVP should answer: *what decision does this
change, and what's the dollar or risk impact of that decision?*

## 2. Goals

- Unify fragmented, multi-system operational data from a newly-acquired or
  portfolio dental group (scheduling, billing, patient records) into one
  coherent, queryable source of truth — the prerequisite for any real
  analysis in a roll-up.
- Surface dollar-quantified, decision-relevant insight — capacity/utilization
  gaps, patient retention risk — that a VMX team could act on to support a
  deal thesis, a post-acquisition value-creation plan, or an exit-readiness
  assessment.
- Produce outputs (dashboard, models, memo) usable directly by a
  non-technical stakeholder — a portfolio-company operator or PE partner —
  without needing a data team to translate them first.

## 3. Non-goals (explicitly out of scope, for this project overall)

- No real PHI or real client data, ever — synthetic only (`SIM-` prefixed
  IDs throughout, already enforced in the generator).
- Not a production system — no auth, no multi-tenancy, no real-time
  streaming.
- Not trying to build all 8 JD-example model types at once (see §7).

## 4. MVP scope

**In scope:**
- Pipeline: bronze → silver → gold, resolving the three location-key
  schemes into one, parsing the two date formats, deduping billing,
  flagging missing `patient_id`.
- Two models: Chair Utilization/OEE, Patient Churn/Recall Risk.
- One Tableau Public dashboard.
- One-page exec summary memo (written for a non-technical reader).

**Out of scope for MVP** (queued for Phase 4, §8):
- Market expansion scoring, staff benchmarking, pricing optimization,
  claims automation, demand forecasting.
- Any Azure/Fabric cloud deployment.

## 5. Architecture (local-first)

| Layer | Choice | Why |
|---|---|---|
| Storage | Postgres (via `docker-compose`) | Matches Redshift-family SQL you already use at Boosted — same mental model, zero new syntax to learn, more representative of a real warehouse than a file-based DB |
| Orchestration | Airflow (via `docker-compose`) | You already know this tool from Boosted; reuse, don't relearn |
| Modeling | Python (pandas / scikit-learn) | Standard, matches JD's named stack |
| BI | Tableau Public | Free, runs on Mac, publishes to a shareable link with no extra hosting step |
| Docs | This SDD + README + 1-page exec memo | The memo is a deliverable, not an afterthought — it's the artifact non-technical stakeholders actually read |

Docker + Docker Compose already confirmed available on this machine.

**Data flow:**
```
raw CSVs (bronze, already generated)
  -> Airflow DAG: clean + entity-resolve
  -> Postgres silver tables (typed, deduped, one location_id)
  -> Airflow DAG: aggregate
  -> Postgres gold tables (business-ready facts)
  -> Python models (read gold, write predictions + $ impact back)
  -> Tableau Public (reads gold + predictions)
```

## 6. Model specs

### 6.1 Chair Utilization / OEE
- **Grain:** location × week
- **Inputs:** scheduled vs. completed chair-minutes, no-show rate, chair count
- **Output:** `utilization_pct`, `idle_cost_per_week` (idle hours × blended
  provider hourly cost), `tier` (red/yellow/green vs. portfolio benchmark)
- **Business framing:** *"Location X is running at Y% utilization; closing
  the gap to the portfolio benchmark is worth ~$Z/month in recoverable
  capacity."*
- **Validation:** rank-correlate recovered location ranking against
  `data/ground_truth/location_health.csv` — **for validation only**, never
  as a model input (see §9).

### 6.2 Patient Churn / Recall Risk
- **Grain:** patient
- **Inputs:** tenure, days since last visit, visit count, no-show count,
  insurance type, home-location utilization tier. Recall interval /
  recall due date deliberately **excluded** as a feature — see design note
  below.
- **Target:** defined operationally — "no completed visit within 1.5× their
  own recall interval" — never from the ground-truth file (see §9).
  **Built prospectively**: features are computed as of a historical cutoff
  (12 months before "today"), and the label is built from what actually
  happened after that cutoff, so the model can't see an outcome that's
  already fully visible in its own inputs. An earlier version computed
  both features and label as of "today" — the model scored 0.995 AUC
  against its own label but only 0.147 Spearman against ground truth,
  because it was mostly re-deriving an already-obvious gap rather than
  predicting anything. Rebuilt as above; see [models/churn_risk.py](../models/churn_risk.py)
  docstring for the full account.
- **Output:** `churn_risk_score`, `tier`, `revenue_at_risk` (avg. annual
  patient revenue × churn probability)
- **Business framing:** *"142 patients are flagged high-risk this month,
  representing ~$X in at-risk annual revenue — recommend proactive recall
  outreach."*
- **Validation:** AUC / rank-correlation against
  `data/ground_truth/patient_churn_risk.csv`. Result: Spearman 0.398, AUC
  0.681 — just under the 0.70 target in §7. A diagnostic in
  `churn_risk.py` (`diagnose_ceiling`) shows only ~28% of true churn_risk
  variance is even explainable by location, the rest being unobservable
  per-patient noise baked into the generator — so 0.681 should be read
  against that realistic ceiling, not against 1.0. Still open: whether to
  push further feature engineering or accept this with the ceiling
  documented.

## 7. Success criteria

**Technical**
- Full pipeline runs end-to-end from a single Airflow DAG trigger,
  idempotently (safe to rerun).
- Documented data-quality checks pass (no null `location_id` post-resolution,
  no duplicate-content claims, all dates parsed to one type).
- Churn model AUC ≥ 0.70 against ground truth.
- Utilization ranking Spearman correlation ≥ 0.6 against ground truth.

**Portfolio**
- Every model output ends in a dollar-impact or risk-flag sentence, not a
  bare score.
- Dashboard is a working Tableau Public link.
- Exec memo is readable by someone with zero data background in under 2
  minutes.

## 8. Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Data generator (messy sources + causal signal + ground truth) | **Done** |
| 1 | Pipeline: entity resolution, cleaning, bronze/silver/gold in Postgres, Airflow DAG, quality checks | **Done** |
| 2 | Two models (utilization, churn) with $ framing, validated against ground truth | **Done** (churn AUC vs. ground truth: 0.681, just under the 0.70 target — see §6.2 note) |
| 3 | Tableau Public dashboard + exec memo | Data exports + build spec done ([dashboard/](../dashboard/)); Tableau build itself is manual (not automatable) |
| 4 | Expansion: market-expansion scoring (real StatCan data), staff benchmarking, pricing optimization, claims automation, demand forecasting | Post-MVP |
| 5 | Optional Azure/Fabric deployment + public GitHub polish | Post-MVP |

## 9. Key design constraint — no ground-truth leakage

`data/ground_truth/` exists **only** to validate whether a model recovered
the real pattern after the fact. It must never be joined into a model's
training features or the pipeline's gold tables — doing so would make the
"prediction" a lookup, and the validation step meaningless. Treat it the
same way you'd treat a client's actual outcome data in a real diligence
engagement: useful for grading yourself, not for cheating the analysis.

## 10. Open risk

Tableau Public publishes workbooks **publicly** by design — there's no
private-workbook option on the free tier. This is fine here since all data
is synthetic, but it's the reason the generator enforces `SIM-` prefixes
and clearly synthetic names everywhere — worth double-checking before any
publish that nothing looks like it could be mistaken for real data.
