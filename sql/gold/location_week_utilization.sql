-- Location x week grain, feeding the chair-utilization/OEE model (SDD 6.1).
DROP TABLE IF EXISTS gold.location_week_utilization;
CREATE TABLE gold.location_week_utilization AS
WITH avg_duration AS (
    -- No-show appointments never had a completed procedure, so the raw
    -- data doesn't capture their intended length. Approximated with that
    -- location's average completed-visit duration -- a documented
    -- assumption, not an observed fact.
    SELECT location_id, AVG(duration_min) AS avg_completed_duration
    FROM silver.appointments
    WHERE status = 'completed'
    GROUP BY location_id
),
appt_minutes AS (
    SELECT
        a.location_id,
        date_trunc('week', a.scheduled_date)::date AS week_start,
        a.status,
        COALESCE(a.duration_min, ad.avg_completed_duration) AS minutes
    FROM silver.appointments a
    JOIN avg_duration ad ON ad.location_id = a.location_id
),
-- assumed operating capacity: 8 hours/day, 5 days/week per chair.
-- Documented assumption -- raw data has no explicit operating-hours source.
capacity AS (
    SELECT location_id, chairs, chairs * 8 * 60 * 5 AS available_minutes
    FROM silver.locations
)
SELECT
    am.location_id,
    am.week_start,
    c.chairs,
    c.available_minutes,
    COUNT(*) AS total_appointments,
    SUM(CASE WHEN am.status = 'no_show' THEN 1 ELSE 0 END) AS no_show_count,
    ROUND(SUM(CASE WHEN am.status = 'no_show' THEN 1 ELSE 0 END)::numeric / COUNT(*), 3) AS no_show_rate,
    SUM(am.minutes) AS scheduled_minutes,
    SUM(CASE WHEN am.status = 'completed' THEN am.minutes ELSE 0 END) AS completed_minutes,
    ROUND(
        SUM(CASE WHEN am.status = 'completed' THEN am.minutes ELSE 0 END)::numeric
        / NULLIF(c.available_minutes, 0),
        3
    ) AS utilization_pct
FROM appt_minutes am
JOIN capacity c ON c.location_id = am.location_id
GROUP BY am.location_id, am.week_start, c.chairs, c.available_minutes;

CREATE INDEX ON gold.location_week_utilization (location_id, week_start);
