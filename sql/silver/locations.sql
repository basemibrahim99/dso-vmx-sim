-- Canonical location dimension. Bronze loaded everything as TEXT (raw
-- landing zone, no coercion) -- this is the first place types get enforced.
DROP TABLE IF EXISTS silver.locations;
CREATE TABLE silver.locations AS
SELECT
    location_id,
    store_code,
    display_name,
    city,
    province,
    region,
    chairs::int AS chairs,
    opened_date::date AS opened_date
FROM bronze.locations_reference;

ALTER TABLE silver.locations ADD PRIMARY KEY (location_id);
