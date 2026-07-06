-- ============================================================
--  FLOOD RESCUE & RESOURCE MANAGEMENT SYSTEM
--  Normalized Schema (3NF) — PostgreSQL
--  Includes: RBAC, Locations, Incidents, Rescue Ops,
--            Resources, Shelters, Medical Aid, Alerts
-- ============================================================

-- ============================================================
-- 0. EXTENSIONS
-- ============================================================
-- Uncomment if you want geographic distance queries
-- CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- 1. LOCATIONS
--    Central lookup for all geographic references.
--    Eliminates repeated lat/lng across tables (3NF).
-- ============================================================
CREATE TABLE locations (
    location_id     SERIAL PRIMARY KEY,
    area_name       VARCHAR(150)   NOT NULL,
    district        VARCHAR(100)   NOT NULL,
    division        VARCHAR(100),
    latitude        DECIMAL(9,6),
    longitude       DECIMAL(9,6),
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. ROLES  (RBAC)
--    Defines system roles: admin, coordinator, field_personnel
-- ============================================================
CREATE TABLE roles (
    role_id         SERIAL PRIMARY KEY,
    role_name       VARCHAR(50)    NOT NULL UNIQUE,
    description     TEXT
);

INSERT INTO roles (role_name, description) VALUES
    ('admin',           'Full system access — manages users, resources, and reports'),
    ('coordinator',     'Manages operations, assigns personnel, tracks resources'),
    ('field_personnel', 'Field-level access — updates rescue status, logs aid');

-- ============================================================
-- 3. PERSONS
--    Single source for all human identities in the system.
--    Subtyped into rescue_personnel and victims below.
-- ============================================================
CREATE TABLE persons (
    person_id       SERIAL PRIMARY KEY,
    full_name       VARCHAR(150)   NOT NULL,
    phone           VARCHAR(20),
    email           VARCHAR(150)   UNIQUE,
    national_id     VARCHAR(30)    UNIQUE,
    date_of_birth   DATE,
    gender          VARCHAR(10)    CHECK (gender IN ('Male', 'Female', 'Other')),
    address         TEXT,
    location_id     INT            REFERENCES locations(location_id),
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 4. USERS  (system accounts — RBAC)
--    Separate from persons to allow non-person system users
--    and to cleanly isolate authentication concerns.
-- ============================================================
CREATE TABLE users (
    user_id         SERIAL PRIMARY KEY,
    person_id       INT            NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    username        VARCHAR(80)    NOT NULL UNIQUE,
    password_hash   VARCHAR(255)   NOT NULL,
    role_id         INT            NOT NULL REFERENCES roles(role_id),
    is_active       BOOLEAN        DEFAULT TRUE,
    last_login      TIMESTAMP,
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 5. RESCUE PERSONNEL
--    Subtype of persons — those who perform rescue operations.
-- ============================================================
CREATE TYPE personnel_status AS ENUM ('available', 'on_mission', 'off_duty', 'injured');

CREATE TABLE rescue_personnel (
    personnel_id    SERIAL PRIMARY KEY,
    person_id       INT            NOT NULL UNIQUE REFERENCES persons(person_id) ON DELETE CASCADE,
    designation     VARCHAR(100),                 -- e.g., 'Diver', 'Medic', 'Boat Operator'
    specialization  VARCHAR(100),
    status          personnel_status DEFAULT 'available',
    joined_date     DATE,
    base_location_id INT           REFERENCES locations(location_id)
);

-- ============================================================
-- 6. INCIDENTS
--    A flood event or crisis zone.
-- ============================================================
CREATE TYPE incident_status AS ENUM ('active', 'under_control', 'resolved', 'monitoring');
CREATE TYPE severity_level  AS ENUM ('low', 'moderate', 'high', 'critical');

CREATE TABLE incidents (
    incident_id     SERIAL PRIMARY KEY,
    title           VARCHAR(200)   NOT NULL,
    description     TEXT,
    location_id     INT            NOT NULL REFERENCES locations(location_id),
    severity        severity_level DEFAULT 'moderate',
    status          incident_status DEFAULT 'active',
    water_level_m   DECIMAL(5,2),              -- water level in metres
    affected_area_km2 DECIMAL(8,2),
    reported_by     INT            REFERENCES users(user_id),
    started_at      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP,
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 7. ALERTS
--    Warnings and notifications tied to incidents or locations.
-- ============================================================
CREATE TYPE alert_type   AS ENUM ('flood_warning', 'evacuation_order', 'resource_shortage', 'all_clear', 'general');
CREATE TYPE alert_status AS ENUM ('issued', 'acknowledged', 'resolved', 'expired');

CREATE TABLE alerts (
    alert_id        SERIAL PRIMARY KEY,
    incident_id     INT            REFERENCES incidents(incident_id),
    location_id     INT            REFERENCES locations(location_id),
    alert_type      alert_type     NOT NULL,
    message         TEXT           NOT NULL,
    severity        severity_level DEFAULT 'moderate',
    status          alert_status   DEFAULT 'issued',
    issued_by       INT            REFERENCES users(user_id),
    issued_at       TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP
);

-- ============================================================
-- 8. RESCUE OPERATIONS
--    A specific mission within an incident.
-- ============================================================
CREATE TYPE operation_status AS ENUM ('planned', 'in_progress', 'completed', 'aborted');

CREATE TABLE rescue_operations (
    operation_id    SERIAL PRIMARY KEY,
    incident_id     INT            NOT NULL REFERENCES incidents(incident_id),
    operation_name  VARCHAR(200)   NOT NULL,
    description     TEXT,
    target_location_id INT         REFERENCES locations(location_id),
    status          operation_status DEFAULT 'planned',
    priority        INT            CHECK (priority BETWEEN 1 AND 5),  -- 1=highest
    led_by          INT            REFERENCES rescue_personnel(personnel_id),
    scheduled_start TIMESTAMP,
    actual_start    TIMESTAMP,
    completed_at    TIMESTAMP,
    created_by      INT            REFERENCES users(user_id),
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 9. RESCUE ASSIGNMENTS
--    Junction: which personnel are on which operation.
--    Resolves M:M between rescue_personnel and rescue_operations.
-- ============================================================
CREATE TYPE assignment_role AS ENUM ('team_lead', 'diver', 'medic', 'boat_operator', 'logistics', 'general');

CREATE TABLE rescue_assignments (
    assignment_id   SERIAL PRIMARY KEY,
    operation_id    INT            NOT NULL REFERENCES rescue_operations(operation_id) ON DELETE CASCADE,
    personnel_id    INT            NOT NULL REFERENCES rescue_personnel(personnel_id),
    assignment_role assignment_role DEFAULT 'general',
    assigned_at     TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    released_at     TIMESTAMP,
    notes           TEXT,
    UNIQUE (operation_id, personnel_id)
);

-- ============================================================
-- 10. VICTIMS
--     Subtype of persons — people needing or who received aid.
-- ============================================================
CREATE TYPE victim_status AS ENUM ('missing', 'rescued', 'in_shelter', 'hospitalized', 'deceased', 'reunited');

CREATE TABLE victims (
    victim_id       SERIAL PRIMARY KEY,
    person_id       INT            NOT NULL UNIQUE REFERENCES persons(person_id) ON DELETE CASCADE,
    incident_id     INT            REFERENCES incidents(incident_id),
    status          victim_status  DEFAULT 'missing',
    found_at_location_id INT       REFERENCES locations(location_id),
    number_of_dependents INT       DEFAULT 0,
    special_needs   TEXT,          -- medical conditions, disability, etc.
    rescued_by_operation_id INT    REFERENCES rescue_operations(operation_id),
    rescued_at      TIMESTAMP
);

-- ============================================================
-- 11. SHELTERS
--     Relief camps and evacuation centres.
-- ============================================================
CREATE TYPE shelter_status AS ENUM ('open', 'full', 'closed', 'preparing');

CREATE TABLE shelters (
    shelter_id      SERIAL PRIMARY KEY,
    shelter_name    VARCHAR(200)   NOT NULL,
    location_id     INT            NOT NULL REFERENCES locations(location_id),
    capacity        INT            NOT NULL CHECK (capacity > 0),
    current_occupancy INT          DEFAULT 0 CHECK (current_occupancy >= 0),
    status          shelter_status DEFAULT 'open',
    has_medical_unit BOOLEAN       DEFAULT FALSE,
    manager_id      INT            REFERENCES rescue_personnel(personnel_id),
    opened_at       TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    closed_at       TIMESTAMP,
    CONSTRAINT occupancy_check CHECK (current_occupancy <= capacity)
);

-- ============================================================
-- 12. SHELTER ASSIGNMENTS
--     Which victim is in which shelter and when.
-- ============================================================
CREATE TABLE shelter_assignments (
    shelter_assignment_id SERIAL  PRIMARY KEY,
    victim_id       INT            NOT NULL REFERENCES victims(victim_id) ON DELETE CASCADE,
    shelter_id      INT            NOT NULL REFERENCES shelters(shelter_id),
    checked_in_at   TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    checked_out_at  TIMESTAMP,
    is_current      BOOLEAN        DEFAULT TRUE,
    notes           TEXT
);

-- ============================================================
-- 13. RESOURCE CATEGORIES
--     Normalized category lookup (avoids repeating strings).
-- ============================================================
CREATE TABLE resource_categories (
    category_id     SERIAL PRIMARY KEY,
    category_name   VARCHAR(100)   NOT NULL UNIQUE,  -- 'Boat', 'Medicine', 'Food', 'Clothing'
    description     TEXT
);

INSERT INTO resource_categories (category_name, description) VALUES
    ('Watercraft',      'Boats, dinghies, rafts used in rescue'),
    ('Vehicle',         'Land vehicles — trucks, ambulances'),
    ('Food Supply',     'Packaged food, rations, water'),
    ('Medicine',        'Drugs, first aid, medical equipment'),
    ('Shelter Supply',  'Tents, blankets, bedding'),
    ('Communication',   'Radios, phones, satellite equipment'),
    ('Safety Gear',     'Life jackets, helmets, ropes');

-- ============================================================
-- 14. RESOURCES
--     Individual resource items tracked in the system.
-- ============================================================
CREATE TYPE resource_condition AS ENUM ('new', 'good', 'fair', 'poor', 'under_repair');

CREATE TABLE resources (
    resource_id     SERIAL PRIMARY KEY,
    resource_name   VARCHAR(150)   NOT NULL,
    category_id     INT            NOT NULL REFERENCES resource_categories(category_id),
    unit            VARCHAR(30)    NOT NULL,  -- 'unit', 'kg', 'litres', 'box'
    description     TEXT,
    condition       resource_condition DEFAULT 'good',
    is_consumable   BOOLEAN        DEFAULT FALSE,
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 15. RESOURCE INVENTORY
--     Stock levels per location/warehouse.
--     Separating inventory from resource definition = 3NF.
-- ============================================================
CREATE TABLE resource_inventory (
    inventory_id    SERIAL PRIMARY KEY,
    resource_id     INT            NOT NULL REFERENCES resources(resource_id),
    location_id     INT            NOT NULL REFERENCES locations(location_id),
    quantity        DECIMAL(10,2)  NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    minimum_threshold DECIMAL(10,2) DEFAULT 0,   -- triggers shortage alert
    last_updated    TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (resource_id, location_id)
);

-- ============================================================
-- 16. RESOURCE ALLOCATIONS
--     Tracks dispatching of resources to operations.
--     Junction: resource_inventory → rescue_operations.
-- ============================================================
CREATE TYPE allocation_status AS ENUM ('requested', 'approved', 'dispatched', 'delivered', 'returned', 'consumed');

CREATE TABLE resource_allocations (
    allocation_id   SERIAL PRIMARY KEY,
    resource_id     INT            NOT NULL REFERENCES resources(resource_id),
    operation_id    INT            REFERENCES rescue_operations(operation_id),
    shelter_id      INT            REFERENCES shelters(shelter_id),  -- OR to a shelter
    quantity        DECIMAL(10,2)  NOT NULL CHECK (quantity > 0),
    unit            VARCHAR(30),
    status          allocation_status DEFAULT 'requested',
    requested_by    INT            REFERENCES users(user_id),
    approved_by     INT            REFERENCES users(user_id),
    dispatched_at   TIMESTAMP,
    returned_at     TIMESTAMP,
    notes           TEXT,
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT allocation_target CHECK (
        (operation_id IS NOT NULL AND shelter_id IS NULL) OR
        (operation_id IS NULL AND shelter_id IS NOT NULL)
    )
);

-- ============================================================
-- 17. MEDICAL AID
--     Medical treatments given to victims.
-- ============================================================
CREATE TABLE medical_aid (
    aid_id          SERIAL PRIMARY KEY,
    victim_id       INT            NOT NULL REFERENCES victims(victim_id) ON DELETE CASCADE,
    operation_id    INT            REFERENCES rescue_operations(operation_id),
    shelter_id      INT            REFERENCES shelters(shelter_id),
    treated_by      INT            REFERENCES rescue_personnel(personnel_id),
    treatment_type  VARCHAR(150)   NOT NULL,     -- 'First Aid', 'Surgery', 'Vaccination'
    diagnosis       TEXT,
    treatment_notes TEXT,
    medication      TEXT,
    is_critical     BOOLEAN        DEFAULT FALSE,
    treated_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    follow_up_date  DATE
);

-- ============================================================
-- 18. INCIDENT REPORTS
--     Situation updates and post-event reports.
-- ============================================================
CREATE TYPE report_type AS ENUM ('situation_update', 'operation_summary', 'resource_report', 'casualty_report', 'final_report');

CREATE TABLE incident_reports (
    report_id       SERIAL PRIMARY KEY,
    incident_id     INT            NOT NULL REFERENCES incidents(incident_id),
    operation_id    INT            REFERENCES rescue_operations(operation_id),
    report_type     report_type    NOT NULL,
    title           VARCHAR(200)   NOT NULL,
    content         TEXT           NOT NULL,
    casualties      INT            DEFAULT 0,
    rescued_count   INT            DEFAULT 0,
    submitted_by    INT            NOT NULL REFERENCES users(user_id),
    submitted_at    TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);
-- ============================================================
-- 19. DONORS
--     Individuals or organizations contributing funds/resources.
-- ============================================================

CREATE TYPE donor_type AS ENUM ('individual', 'organization', 'ngo', 'corporate');

CREATE TABLE donors (
    donor_id        SERIAL PRIMARY KEY,
    donor_name      VARCHAR(200) NOT NULL,
    donor_type      donor_type   DEFAULT 'individual',
    phone           VARCHAR(20),
    email           VARCHAR(150),
    address         TEXT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
-- ============================================================
-- 20. MONETARY DONATIONS
--     Financial contributions collected centrally.
-- ============================================================

CREATE TYPE donation_status AS ENUM ('received', 'allocated', 'partially_allocated', 'closed');

CREATE TABLE monetary_donations (
    donation_id     SERIAL PRIMARY KEY,
    donor_id        INT NOT NULL REFERENCES donors(donor_id) ON DELETE CASCADE,
    amount          DECIMAL(12,2) NOT NULL CHECK (amount > 0),
    currency        VARCHAR(10) DEFAULT 'BDT',
    payment_method  VARCHAR(50),  -- 'bank_transfer', 'mobile_banking', 'cash'
    transaction_reference VARCHAR(150),
    received_by     INT REFERENCES users(user_id), -- should be admin
    status          donation_status DEFAULT 'received',
    received_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT
);
-- ============================================================
-- 21. DONATION FUND ALLOCATIONS
--     Tracks where donated money is spent.
-- ============================================================

CREATE TABLE donation_allocations (
    allocation_id   SERIAL PRIMARY KEY,
    donation_id     INT NOT NULL REFERENCES monetary_donations(donation_id) ON DELETE CASCADE,
    incident_id     INT REFERENCES incidents(incident_id),
    operation_id    INT REFERENCES rescue_operations(operation_id),
    shelter_id      INT REFERENCES shelters(shelter_id),
    amount_allocated DECIMAL(12,2) NOT NULL CHECK (amount_allocated > 0),
    allocated_by    INT REFERENCES users(user_id),  -- admin
    allocated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    purpose         TEXT,
    CONSTRAINT allocation_target_check CHECK (
        (incident_id IS NOT NULL)::int +
        (operation_id IS NOT NULL)::int +
        (shelter_id IS NOT NULL)::int = 1
    )
);
-- ============================================================
-- 22. IN-KIND DONATIONS (Resource-based)
-- ============================================================

CREATE TABLE in_kind_donations (
    in_kind_id      SERIAL PRIMARY KEY,
    donor_id        INT NOT NULL REFERENCES donors(donor_id) ON DELETE CASCADE,
    resource_id     INT NOT NULL REFERENCES resources(resource_id),
    quantity        DECIMAL(10,2) NOT NULL CHECK (quantity > 0),
    unit            VARCHAR(30),
    received_by     INT REFERENCES users(user_id), -- admin
    received_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT
);

-- ============================================================
-- 23. VOLUNTEER TEAMS
--     Permanent registered volunteer units.
--     Teams must be reviewed and approved before activation.
-- ============================================================

CREATE TYPE team_status AS ENUM ('pending', 'approved', 'rejected', 'inactive');

CREATE TABLE volunteer_teams (
    team_id            SERIAL PRIMARY KEY,
    team_name          VARCHAR(150)   NOT NULL,
    leader_id          INT            REFERENCES rescue_personnel(personnel_id),
    base_location_id   INT            REFERENCES locations(location_id),
    status             team_status    DEFAULT 'pending',
    reviewed_by        INT            REFERENCES users(user_id),   -- admin/coordinator
    reviewed_at        TIMESTAMP,
    created_at         TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (team_name)
);

-- ============================================================
-- 24. VOLUNTEER TEAM MEMBERS
--     Junction table linking rescue personnel to teams.
--     Resolves M:M relationship between personnel and teams.
-- ============================================================

CREATE TABLE volunteer_team_members (
    team_id        INT NOT NULL REFERENCES volunteer_teams(team_id) ON DELETE CASCADE,
    personnel_id   INT NOT NULL REFERENCES rescue_personnel(personnel_id) ON DELETE CASCADE,
    joined_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, personnel_id)
);


-- ============================================================
-- CENTRAL FUND OVERVIEW
-- ============================================================

CREATE VIEW v_central_fund_status AS
SELECT
    SUM(md.amount) AS total_collected,
    COALESCE(SUM(da.amount_allocated), 0) AS total_allocated,
    SUM(md.amount) - COALESCE(SUM(da.amount_allocated), 0) AS remaining_balance
FROM monetary_donations md
LEFT JOIN donation_allocations da
    ON md.donation_id = da.donation_id;


-- ============================================================
-- INDEXES  (Performance on common query patterns)
-- ============================================================
CREATE INDEX idx_incidents_location     ON incidents(location_id);
CREATE INDEX idx_incidents_status       ON incidents(status);
CREATE INDEX idx_operations_incident    ON rescue_operations(incident_id);
CREATE INDEX idx_operations_status      ON rescue_operations(status);
CREATE INDEX idx_assignments_operation  ON rescue_assignments(operation_id);
CREATE INDEX idx_assignments_personnel  ON rescue_assignments(personnel_id);
CREATE INDEX idx_victims_incident       ON victims(incident_id);
CREATE INDEX idx_victims_status         ON victims(status);
CREATE INDEX idx_shelter_assignments_victim  ON shelter_assignments(victim_id);
CREATE INDEX idx_shelter_assignments_shelter ON shelter_assignments(shelter_id);
CREATE INDEX idx_inventory_resource     ON resource_inventory(resource_id);
CREATE INDEX idx_inventory_location     ON resource_inventory(location_id);
CREATE INDEX idx_allocations_operation  ON resource_allocations(operation_id);
CREATE INDEX idx_medical_aid_victim     ON medical_aid(victim_id);
CREATE INDEX idx_alerts_incident        ON alerts(incident_id);
CREATE INDEX idx_users_role             ON users(role_id);
-- Index for fast donor donation lookup
CREATE INDEX idx_donations_donor
ON monetary_donations(donor_id);

-- Index for donation status filtering
CREATE INDEX idx_donations_status
ON monetary_donations(status);

-- Allocation lookups
CREATE INDEX idx_allocations_donation
ON donation_allocations(donation_id);

CREATE INDEX idx_allocations_incident
ON donation_allocations(incident_id);

CREATE INDEX idx_allocations_shelter
ON donation_allocations(shelter_id);

-- In-kind donation tracking
CREATE INDEX idx_in_kind_donor
ON in_kind_donations(donor_id);

CREATE INDEX idx_in_kind_resource
ON in_kind_donations(resource_id);

-- ============================================================
-- INDEXES (Performance Optimization for Team Queries)
-- ============================================================

CREATE INDEX idx_team_members_team
ON volunteer_team_members(team_id);

CREATE INDEX idx_team_members_personnel
ON volunteer_team_members(personnel_id);

CREATE INDEX idx_team_status
ON volunteer_teams(status);
-- ============================================================
-- SAMPLE VIEWS  (Useful for reports and dashboards)
-- ============================================================

-- Active incidents with location detail
CREATE VIEW v_active_incidents AS
SELECT
    i.incident_id,
    i.title,
    i.severity,
    i.status,
    i.water_level_m,
    i.started_at,
    l.area_name,
    l.district,
    l.latitude,
    l.longitude
FROM incidents i
JOIN locations l ON i.location_id = l.location_id
WHERE i.status = 'active';

-- Shelter occupancy overview
CREATE VIEW v_shelter_occupancy AS
SELECT
    s.shelter_id,
    s.shelter_name,
    l.area_name,
    l.district,
    s.capacity,
    s.current_occupancy,
    s.capacity - s.current_occupancy AS available_spaces,
    ROUND(s.current_occupancy::NUMERIC / s.capacity * 100, 1) AS occupancy_pct,
    s.status
FROM shelters s
JOIN locations l ON s.location_id = l.location_id;

-- Resource inventory with shortage flag
CREATE VIEW v_inventory_status AS
SELECT
    r.resource_id,
    r.resource_name,
    rc.category_name,
    l.area_name,
    ri.quantity,
    ri.minimum_threshold,
    CASE WHEN ri.quantity <= ri.minimum_threshold THEN TRUE ELSE FALSE END AS is_low_stock
FROM resource_inventory ri
JOIN resources r         ON ri.resource_id = r.resource_id
JOIN resource_categories rc ON r.category_id = rc.category_id
JOIN locations l         ON ri.location_id  = l.location_id;

-- Personnel availability
CREATE VIEW v_personnel_availability AS
SELECT
    rp.personnel_id,
    p.full_name,
    rp.designation,
    rp.specialization,
    rp.status,
    l.area_name AS base_location
FROM rescue_personnel rp
JOIN persons p           ON rp.person_id      = p.person_id
LEFT JOIN locations l    ON rp.base_location_id = l.location_id;

-- Victim tracking summary
CREATE VIEW v_victim_tracking AS
SELECT
    v.victim_id,
    p.full_name,
    p.phone,
    v.status         AS victim_status,
    i.title          AS incident_name,
    fl.area_name     AS found_at,
    s.shelter_name,
    v.special_needs,
    v.rescued_at
FROM victims v
JOIN persons p              ON v.person_id              = p.person_id
LEFT JOIN incidents i       ON v.incident_id            = i.incident_id
LEFT JOIN locations fl      ON v.found_at_location_id   = fl.location_id
LEFT JOIN shelter_assignments sa ON v.victim_id = sa.victim_id AND sa.is_current = TRUE
LEFT JOIN shelters s        ON sa.shelter_id             = s.shelter_id;

-- ============================================================
-- END OF SCHEMA
-- ============================================================
