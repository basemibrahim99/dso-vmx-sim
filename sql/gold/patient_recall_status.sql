-- Patient grain, feeding the churn/recall-risk model (SDD 6.2). Target is
-- defined operationally from observed behavior in the model step, NOT
-- from data/ground_truth/ -- this table only carries the raw ingredients
-- (days overdue, visit history), never the hidden ground-truth churn_risk.
DROP TABLE IF EXISTS gold.patient_recall_status;
CREATE TABLE gold.patient_recall_status AS
SELECT
    p.patient_id,
    p.location_id,
    p.insurance_type,
    p.signup_date,
    p.last_visit_date,
    p.recall_due_date,
    -- fixed "as of" date matching the generator's TODAY -- this is a static
    -- synthetic snapshot, not a live daily pipeline, so CURRENT_DATE would
    -- silently drift from the data's actual reference point.
    (DATE '2026-08-26' - p.recall_due_date) AS days_overdue,
    COALESCE(v.visit_count, 0) AS visit_count
FROM silver.patients p
LEFT JOIN (
    SELECT patient_id, COUNT(*) AS visit_count
    FROM silver.appointments
    WHERE status = 'completed'
    GROUP BY patient_id
) v ON v.patient_id = p.patient_id;

CREATE INDEX ON gold.patient_recall_status (location_id);
