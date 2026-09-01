DROP TABLE IF EXISTS silver.procedures;
CREATE TABLE silver.procedures AS
SELECT
    procedure_code,
    name,
    avg_price::numeric AS avg_price,
    avg_cost::numeric AS avg_cost,
    avg_duration_min::numeric AS avg_duration_min
FROM bronze.procedures_reference;

ALTER TABLE silver.procedures ADD PRIMARY KEY (procedure_code);
