# Silver Layer ERD

How the six `silver.*` tables (see [sql/silver/](../sql/silver/)) relate,
once the three bronze source systems' different location-key schemes
(`store_code`, `display_name`, numeric `location_id`) have already been
resolved to one canonical `location_id`.

```mermaid
%%{init: {'flowchart': {'curve': 'basis'}}}%%
flowchart TB
    subgraph REF[" Reference data — rarely changes "]
        direction LR
        LOC["🏢 <b>LOCATIONS</b>
        <u>location_id</u> PK
        store_code · display_name
        chairs · region"]
        PROV["🦷 <b>PROVIDERS</b>
        <u>provider_id</u> PK
        location_id FK
        role · hourly_cost"]
        PROC["🧾 <b>PROCEDURES</b>
        <u>procedure_code</u> PK
        avg_price · avg_cost · duration"]
    end

    subgraph ACT[" Activity data — grows every run "]
        direction LR
        PAT["🧑 <b>PATIENTS</b>
        <u>patient_id</u> PK
        location_id FK
        insurance_type · recall_due_date"]
        APPT["📅 <b>APPOINTMENTS</b>
        <u>appointment_id</u> PK
        location_id · provider_id · patient_id FK
        status: completed | no_show"]
        CLM["💵 <b>CLAIMS</b>
        <u>claim_id</u> PK
        location_id · patient_id FK · procedure_code FK
        billed_amount · paid_amount"]
    end

    LOC -->|"1 → many"| PROV
    LOC -->|"1 → many"| PAT
    LOC -->|"1 → many"| APPT
    LOC -->|"1 → many"| CLM
    PROV -->|"performs"| APPT
    PAT -->|"books"| APPT
    PAT -.->|"billed for (~98%, see note)"| CLM
    PROC -->|"billed as"| CLM

    classDef hub fill:#fef3c7,stroke:#b45309,stroke-width:2.5px,color:#1c1917,font-weight:bold
    classDef dim fill:#dbeafe,stroke:#1d4ed8,stroke-width:1.5px,color:#1c1917
    classDef fact fill:#dcfce7,stroke:#15803d,stroke-width:1.5px,color:#1c1917
    class LOC hub
    class PROV,PROC dim
    class PAT,APPT,CLM fact
```

🟠 **Locations** is the hub every other table resolves against — the
canonical `location_id` that replaced three source-system-specific keys.
🔵 **Blue** = reference/dimension data. 🟢 **Green** = activity/fact data
that grows with every pipeline run. The dashed edge (`PATIENTS ⇢ CLAIMS`)
marks the one non-total relationship: `claims.patient_id` is null for ~2%
of rows (an unresolved self-pay/walk-in in the source billing system) — see
[sql/silver/claims.sql](../sql/silver/claims.sql) for why those rows are
deliberately excluded from de-duplication rather than silently merged.

<details>
<summary><b>Full column reference</b> (every column, not just keys)</summary>

```mermaid
erDiagram
    LOCATIONS ||--o{ PROVIDERS : "staffed by"
    LOCATIONS ||--o{ PATIENTS : "home location of"
    LOCATIONS ||--o{ APPOINTMENTS : "hosts"
    LOCATIONS ||--o{ CLAIMS : "billed at"
    PROVIDERS ||--o{ APPOINTMENTS : "performs"
    PATIENTS ||--o{ APPOINTMENTS : "books"
    PATIENTS |o--o{ CLAIMS : "billed for (nullable ~2%)"
    PROCEDURES ||--o{ CLAIMS : "billed as"

    LOCATIONS {
        string location_id PK
        string store_code "scheduling system's key"
        string display_name "billing system's key"
        string city
        string province
        string region
        int chairs
        date opened_date
    }
    PROVIDERS {
        string provider_id PK
        string location_id FK
        string role "dentist | hygienist"
        string name
        date hire_date
        numeric hourly_cost
    }
    PROCEDURES {
        string procedure_code PK
        string name
        numeric avg_price
        numeric avg_cost
        numeric avg_duration_min
    }
    PATIENTS {
        string patient_id PK
        string location_id FK
        string insurance_type
        date last_visit_date "nullable"
        date recall_due_date "nullable"
        date signup_date
    }
    APPOINTMENTS {
        string appointment_id PK
        string location_id FK
        string provider_id FK
        string patient_id FK
        date scheduled_date
        numeric duration_min "null for no_show"
        string status "completed | no_show"
    }
    CLAIMS {
        string claim_id PK
        string location_id FK
        string patient_id FK "nullable ~2%, see silver/claims.sql"
        string procedure_code FK
        date claim_date
        numeric billed_amount
        numeric paid_amount
        string insurance_status "paid | denied | self_pay"
    }
```

</details>

## Notes

- **`LOCATIONS`** is the canonical dimension every other table resolves
  against — `PROVIDERS`/`PATIENTS` already carry the numeric `location_id`
  directly from their bronze source, while `APPOINTMENTS` and `CLAIMS` are
  joined in via `store_code` and `display_name` respectively (see
  [sql/silver/appointments.sql](../sql/silver/appointments.sql) and
  [sql/silver/claims.sql](../sql/silver/claims.sql)).
- No FK constraints are enforced in Postgres here (each silver table is a
  `DROP`/`CREATE TABLE AS` rebuild every run, not an incrementally-loaded
  table) — this diagram documents the logical relationships the SQL joins
  rely on, not physical constraints.
