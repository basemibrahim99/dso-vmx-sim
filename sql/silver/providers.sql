DROP TABLE IF EXISTS silver.providers;
CREATE TABLE silver.providers AS
SELECT
    provider_id,
    location_id,
    role,
    name,
    hire_date::date AS hire_date,
    hourly_cost::numeric AS hourly_cost
FROM bronze.providers_reference;

ALTER TABLE silver.providers ADD PRIMARY KEY (provider_id);
