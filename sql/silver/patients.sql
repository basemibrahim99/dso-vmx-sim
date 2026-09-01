-- Patient records already use the canonical numeric location_id directly --
-- the cleanest of the three sources, no join needed, just typing.
DROP TABLE IF EXISTS silver.patients;
CREATE TABLE silver.patients AS
SELECT
    patient_id,
    location_id,
    insurance_type,
    NULLIF(last_visit_date, '')::date AS last_visit_date,
    NULLIF(recall_due_date, '')::date AS recall_due_date,
    signup_date::date AS signup_date
FROM bronze.patient_records;

ALTER TABLE silver.patients ADD PRIMARY KEY (patient_id);
