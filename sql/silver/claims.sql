-- Billing system identifies locations by display_name (not store_code or
-- location_id -- a third scheme), sometimes upper-cased (~3% of rows), and
-- writes dates as MM/DD/YYYY instead of scheduling's ISO format.
DROP TABLE IF EXISTS silver.claims;
CREATE TABLE silver.claims AS
WITH typed AS (
    SELECT
        b.claim_id,
        UPPER(TRIM(b.location_name)) AS location_name_normalized,
        NULLIF(b.patient_id, '') AS patient_id,
        b.procedure_code,
        TO_DATE(b.claim_date, 'MM/DD/YYYY') AS claim_date,
        b.billed_amount::numeric AS billed_amount,
        b.paid_amount::numeric AS paid_amount,
        b.insurance_status
    FROM bronze.billing_export b
),
resolved AS (
    SELECT t.*, loc.location_id
    FROM typed t
    JOIN silver.locations loc
        ON UPPER(TRIM(loc.display_name)) = t.location_name_normalized
),
deduped AS (
    -- ~1.5% of claims are accidental double-entries (same charge billed
    -- twice). De-duplicate on content, keeping the lowest claim_id.
    -- Restricted to patient_id IS NOT NULL: DISTINCT ON treats NULLs as
    -- equal for grouping purposes in Postgres, so applying this to the
    -- ~2% of claims with a missing patient_id would risk collapsing
    -- genuinely distinct claims that happen to share procedure/date/amount.
    -- Those pass through unmodified below and are instead surfaced by the
    -- missing_patient_id quality check, not silently merged.
    SELECT DISTINCT ON (patient_id, procedure_code, claim_date, billed_amount, location_id)
        claim_id, location_id, patient_id, procedure_code, claim_date,
        billed_amount, paid_amount, insurance_status
    FROM resolved
    WHERE patient_id IS NOT NULL
    ORDER BY patient_id, procedure_code, claim_date, billed_amount, location_id, claim_id
)
SELECT * FROM deduped
UNION ALL
SELECT claim_id, location_id, patient_id, procedure_code, claim_date,
       billed_amount, paid_amount, insurance_status
FROM resolved
WHERE patient_id IS NULL;

ALTER TABLE silver.claims ADD PRIMARY KEY (claim_id);
CREATE INDEX ON silver.claims (patient_id);
CREATE INDEX ON silver.claims (location_id);
