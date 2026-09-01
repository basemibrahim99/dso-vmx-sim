-- Scheduling system identifies locations by store_code (e.g. "ON-01") --
-- resolve to the canonical location_id here. This join is also the target
-- of a quality check (no_unresolved_scheduling_locations): any store_code
-- that fails to match would silently drop appointments, so we assert
-- row-count parity rather than trust the join.
DROP TABLE IF EXISTS silver.appointments;
CREATE TABLE silver.appointments AS
SELECT
    s.appointment_id,
    loc.location_id,
    s.provider_id,
    NULLIF(s.patient_id, '') AS patient_id,
    s.scheduled_date::date AS scheduled_date,
    NULLIF(s.duration_min, '')::numeric AS duration_min,
    s.status
FROM bronze.scheduling_export s
JOIN silver.locations loc
    ON loc.store_code = s.location_code;

ALTER TABLE silver.appointments ADD PRIMARY KEY (appointment_id);
CREATE INDEX ON silver.appointments (patient_id);
CREATE INDEX ON silver.appointments (location_id, scheduled_date);
