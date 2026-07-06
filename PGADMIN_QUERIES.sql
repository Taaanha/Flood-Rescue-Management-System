-- FRRMS: pgAdmin-ready SQL query sheet
-- Run these manually in pgAdmin for viva demonstration.

/* =========================
   DASHBOARD
   ========================= */

-- KPI: total rescued victims
SELECT COUNT(*) AS total_rescued
FROM victims
WHERE LOWER(COALESCE(status::text, '')) = 'rescued';

-- Chart: victims placed in shelters (top 10)
SELECT
  COALESCE(
    NULLIF(TRIM(s_exact.shelter_name), ''),
    NULLIF(TRIM(s_district.shelter_name), ''),
    'Unknown Shelter'
  ) AS shelter_name,
  COUNT(*) AS sheltered_count
FROM victims v
JOIN persons p ON p.person_id = v.person_id
LEFT JOIN locations lv ON lv.location_id = p.location_id
LEFT JOIN shelters s_exact ON s_exact.location_id = p.location_id
LEFT JOIN LATERAL (
  SELECT s2.shelter_name
  FROM shelters s2
  JOIN locations l2 ON l2.location_id = s2.location_id
  WHERE lv.district IS NOT NULL
    AND LOWER(l2.district) = LOWER(lv.district)
  ORDER BY s2.shelter_id ASC
  LIMIT 1
) AS s_district ON TRUE
WHERE LOWER(COALESCE(v.status::text, '')) = 'in_shelter'
GROUP BY 1
ORDER BY sheltered_count DESC, shelter_name ASC
LIMIT 10;

-- KPI: active teams
SELECT COUNT(*) AS active_teams
FROM rescue_teams;

-- KPI: shelters
SELECT COUNT(*) AS total_shelters
FROM shelters;

-- KPI: pending team approvals
SELECT COUNT(*) AS team_pending_approval
FROM volunteer_teams
WHERE status = 'pending';

-- Inventory rows for health computation
SELECT *
FROM resource_inventory;

-- Active map alerts with location
SELECT a.*, l.area_name, l.district, l.latitude, l.longitude
FROM alerts a
JOIN locations l ON l.location_id = a.location_id
WHERE l.latitude IS NOT NULL
  AND l.longitude IS NOT NULL
  AND a.status = 'issued'
ORDER BY a.issued_at DESC NULLS LAST
LIMIT 100;

-- Find existing location before creating alert marker
SELECT *
FROM locations
WHERE area_name = :area_name
  AND district = :district_name
LIMIT 1;

-- Clear alert marker
UPDATE alerts
SET status = 'resolved'
WHERE alert_id = :alert_id;

/* =========================
   VICTIMS MODULE
   ========================= */

-- Victims page: incident list
SELECT incident_id, title
FROM incidents
ORDER BY created_at DESC NULLS LAST, incident_id DESC
LIMIT 200;

-- Victims page: victim table data
SELECT
  v.victim_id AS id,
  p.full_name,
  COALESCE(l.district, '-') AS district,
  CASE WHEN v.status IN ('deceased', 'hospitalized') THEN 'critical' ELSE 'stable' END AS health_status,
  COALESCE(ro.operation_name, '-') AS rescue_team,
  '-' AS current_facility,
  v.status
FROM victims v
JOIN persons p ON p.person_id = v.person_id
LEFT JOIN rescue_operations ro ON ro.operation_id = v.rescued_by_operation_id
LEFT JOIN locations l ON l.location_id = p.location_id
ORDER BY v.victim_id DESC
LIMIT 300;

-- Register victim: find incident by title
SELECT incident_id
FROM incidents
WHERE LOWER(title) = LOWER(:title)
ORDER BY incident_id DESC
LIMIT 1;

-- Register victim: ensure district location
SELECT location_id
FROM locations
WHERE LOWER(district) = LOWER(:district)
ORDER BY location_id DESC
LIMIT 1;

INSERT INTO locations(area_name, district, created_at)
VALUES ('Unknown', :district, NOW())
RETURNING location_id;

-- Register victim: create incident if needed
INSERT INTO incidents(title, location_id, severity, status, created_at)
VALUES (:title, :location_id, 'moderate', 'active', NOW())
RETURNING incident_id;

-- Register victim: create person + victim
INSERT INTO persons(full_name, created_at)
VALUES (:full_name, NOW())
RETURNING person_id;

INSERT INTO victims(person_id, incident_id, status, special_needs, rescued_at)
VALUES (:person_id, :incident_id, :status, :special_needs, NOW());

-- Register victim: optional explicit district mapping
INSERT INTO locations(area_name, district, created_at)
VALUES ('Unknown', :district, NOW())
RETURNING location_id;

UPDATE persons
SET location_id = :location_id
WHERE person_id = :person_id;

-- Leave shelter / update victim status
UPDATE victims
SET status = :status
WHERE victim_id = :victim_id;

/* =========================
   OPERATIONS + COMMAND CONSOLE
   ========================= */

-- Operations page: list operations
SELECT
  ro.operation_id,
  ro.operation_name,
  ro.status,
  ro.priority,
  ro.scheduled_start,
  i.title AS incident_title,
  l.area_name,
  l.district
FROM rescue_operations ro
JOIN incidents i ON i.incident_id = ro.incident_id
LEFT JOIN locations l ON l.location_id = ro.target_location_id
ORDER BY ro.created_at DESC NULLS LAST, ro.operation_id DESC
LIMIT 100;

-- Dropdowns / support lists
SELECT incident_id, title
FROM incidents
ORDER BY created_at DESC NULLS LAST, incident_id DESC;

SELECT location_id, area_name, district
FROM locations
ORDER BY location_id DESC
LIMIT 200;

SELECT rp.personnel_id, p.full_name
FROM rescue_personnel rp
JOIN persons p ON p.person_id = rp.person_id
ORDER BY rp.personnel_id DESC
LIMIT 200;

-- Create operation
INSERT INTO rescue_operations(
  incident_id, operation_name, description, target_location_id,
  status, priority, scheduled_start, created_at
)
VALUES (
  :incident_id, :operation_name, :description, :target_location_id,
  'planned', :priority, :scheduled_start, NOW()
);

-- Create incident
INSERT INTO incidents(title, description, location_id, severity, status, created_at)
VALUES (:title, :description, :location_id, :severity, 'active', NOW());

-- Close operation
UPDATE rescue_operations
SET status = 'completed', completed_at = NOW()
WHERE operation_id = :operation_id;

-- Assign personnel
INSERT INTO rescue_assignments(operation_id, personnel_id, assignment_role, assigned_at, notes)
VALUES (:operation_id, :personnel_id, :assignment_role, NOW(), :notes)
ON CONFLICT DO NOTHING;

-- Field console lists
SELECT incident_id, title
FROM incidents
ORDER BY incident_id DESC
LIMIT 100;

SELECT operation_id, operation_name
FROM rescue_operations
WHERE status IN ('planned', 'in_progress')
ORDER BY operation_id DESC
LIMIT 100;

SELECT resource_id, resource_name, unit
FROM resources
ORDER BY resource_id DESC
LIMIT 200;

SELECT v.victim_id, p.full_name, v.status
FROM victims v
JOIN persons p ON p.person_id = v.person_id
ORDER BY v.victim_id DESC
LIMIT 100;

-- Add rescued victim
INSERT INTO persons(full_name, phone, created_at)
VALUES (:full_name, :phone, NOW())
RETURNING person_id;

INSERT INTO victims(person_id, incident_id, status, special_needs, rescued_by_operation_id, rescued_at)
VALUES (:person_id, :incident_id, 'rescued', :special_needs, :operation_id, NOW());

-- Field status update
UPDATE victims
SET status = :status
WHERE victim_id = :victim_id;

-- Resource request flow
SELECT resource_id
FROM resources
WHERE LOWER(resource_name) = LOWER(:name)
LIMIT 1;

SELECT category_id
FROM resource_categories
WHERE LOWER(category_name) = LOWER('General')
LIMIT 1;

INSERT INTO resource_categories(category_name, description)
VALUES ('General', 'General resources')
RETURNING category_id;

INSERT INTO resources(resource_name, category_id, unit, description, is_consumable, created_at)
VALUES (:resource_name, :category_id, :unit, :description, TRUE, NOW())
RETURNING resource_id;

INSERT INTO resource_allocations(resource_id, operation_id, quantity, unit, status, notes, created_at)
VALUES (:resource_id, :operation_id, :quantity, :unit, 'requested', :notes, NOW());

-- Field report submit
INSERT INTO incident_reports(
  incident_id, operation_id, report_type, title, content,
  casualties, rescued_count, submitted_by, submitted_at
)
VALUES (
  :incident_id, :operation_id, 'situation_update', :title, :content,
  :casualties, :rescued_count, :submitted_by, NOW()
);

-- Coordinator console
SELECT
  ra.allocation_id, r.resource_name, ra.quantity, ra.unit,
  ra.status, ra.notes, ro.operation_name
FROM resource_allocations ra
JOIN resources r ON r.resource_id = ra.resource_id
LEFT JOIN rescue_operations ro ON ro.operation_id = ra.operation_id
WHERE ra.status = 'requested'
ORDER BY ra.created_at DESC NULLS LAST, ra.allocation_id DESC;

SELECT
  ir.report_id, ir.title, ir.report_type, ir.submitted_at,
  p.full_name AS submitted_by_name, ir.content
FROM incident_reports ir
LEFT JOIN users u ON u.user_id = ir.submitted_by
LEFT JOIN persons p ON p.person_id = u.person_id
ORDER BY ir.submitted_at DESC NULLS LAST, ir.report_id DESC
LIMIT 200;

-- Approve/reject resource request
UPDATE resource_allocations
SET status = 'approved',
    approved_by = :approved_by,
    notes = COALESCE(notes, '') || CASE WHEN :note = '' THEN '' ELSE E'\n[COORDINATOR APPROVED] ' || :note END
WHERE allocation_id = :allocation_id;

UPDATE resource_allocations
SET status = 'returned',
    approved_by = :approved_by,
    notes = COALESCE(notes, '') || CASE WHEN :note = '' THEN E'\n[COORDINATOR REJECTED]' ELSE E'\n[COORDINATOR REJECTED] ' || :note END
WHERE allocation_id = :allocation_id;

-- Comment on report
UPDATE incident_reports
SET content = COALESCE(content, '') || E'\n\n[Coordinator Note ' || :stamp || ' by ' || :username || '] ' || :comment
WHERE report_id = :report_id;

/* =========================
   RESCUE UNITS
   ========================= */

-- Ensure table exists / compatibility columns
SELECT to_regclass('public.rescue_teams') IS NOT NULL;

CREATE TABLE IF NOT EXISTS rescue_teams (
  team_id SERIAL PRIMARY KEY,
  team_name VARCHAR(150) NOT NULL UNIQUE,
  status VARCHAR(30) DEFAULT 'standby',
  assets_count INTEGER DEFAULT 0,
  contact_number VARCHAR(30),
  working_district VARCHAR(100),
  working_place VARCHAR(150)
);

ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS status VARCHAR(30);
ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS assets_count INTEGER DEFAULT 0;
ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS contact_number VARCHAR(30);
ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_district VARCHAR(100);
ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_place VARCHAR(150);

-- Rescue units page (schema variant 1)
SELECT
  rt.team_id AS id,
  rt.team_name AS name,
  COALESCE(rt.status, 'standby') AS status,
  COALESCE(rt.assets_count, 0) AS assets_count,
  COALESCE(rt.contact_number, '-') AS contact,
  COALESCE(rt.working_place || ', ' || rt.working_district, rt.working_place, rt.working_district, '-') AS assigned_place
FROM rescue_teams rt
ORDER BY rt.team_id DESC;

-- Rescue units page (fallback schema variant 2)
SELECT
  rt.id AS id,
  rt.name AS name,
  COALESCE(rt.status, 'standby') AS status,
  COALESCE(rt.assets_count, 0) AS assets_count,
  COALESCE(rt.contact_number, '-') AS contact,
  COALESCE(rt.working_place || ', ' || rt.working_district, rt.working_place, rt.working_district, '-') AS assigned_place
FROM rescue_teams rt
ORDER BY rt.id DESC;

-- Rescue units page (fallback from volunteer teams)
SELECT
  vt.team_id AS id,
  vt.team_name AS name,
  'standby' AS status,
  COALESCE((SELECT COUNT(*) FROM volunteer_team_members vtm WHERE vtm.team_id = vt.team_id), 0) AS assets_count,
  '-' AS contact,
  COALESCE(l.area_name || ', ' || l.district, '-') AS assigned_place
FROM volunteer_teams vt
LEFT JOIN locations l ON l.location_id = vt.base_location_id
ORDER BY vt.team_id DESC;

-- Create/update rescue units
INSERT INTO rescue_teams(team_name, status, assets_count, contact_number, working_district, working_place)
VALUES (:team_name, :status, :assets_count, :contact_number, :working_district, :working_place);

UPDATE rescue_teams
SET status = :status,
    assets_count = :assets_count,
    contact_number = COALESCE(contact_number, :contact_number),
    working_district = COALESCE(:working_district, working_district),
    working_place = COALESCE(:working_place, working_place)
WHERE team_id = :id;

UPDATE rescue_teams
SET status = :status
WHERE team_id = :id;

UPDATE rescue_teams
SET status = :status
WHERE id = :id;

/* =========================
   OPERATIONS.PY (ORM EQUIVALENT SQL)
   ========================= */

-- Volunteer registration page
SELECT *
FROM volunteer_requests
WHERE team_name = :username
ORDER BY created_at DESC;

SELECT *
FROM districts
ORDER BY name ASC;

-- Admin assignments
SELECT *
FROM volunteer_requests
ORDER BY created_at DESC;

SELECT *
FROM districts
ORDER BY name ASC;

-- District create check
SELECT *
FROM districts
WHERE name = :name
LIMIT 1;

-- Assignment lookups
SELECT * FROM volunteer_requests WHERE id = :request_id;
SELECT * FROM districts WHERE id = :district_id;

-- Shelters page
SELECT s.*, l.area_name, l.district, l.division
FROM shelters s
LEFT JOIN locations l ON l.location_id = s.location_id
ORDER BY s.shelter_id DESC;

-- Resource distribution page lists
SELECT * FROM resource_inventory ORDER BY inventory_id DESC;
SELECT * FROM resource_distributions ORDER BY distributed_at DESC LIMIT 30;
SELECT * FROM districts ORDER BY name ASC;
SELECT * FROM resource_categories ORDER BY category_name ASC;
SELECT * FROM resources ORDER BY resource_name ASC;

-- Resource create/update checks
SELECT * FROM resources WHERE resource_name = :name LIMIT 1;
SELECT * FROM resource_categories WHERE category_name = :category_name LIMIT 1;

-- Inventory upsert lookup style
SELECT *
FROM resource_inventory
WHERE resource_id = :resource_id
  AND location_id = :location_id
LIMIT 1;

-- Donations page
SELECT * FROM monetary_donations ORDER BY received_at DESC LIMIT 30;
SELECT * FROM in_kind_donations ORDER BY received_at DESC LIMIT 30;
SELECT * FROM resources ORDER BY resource_name ASC;

-- Donor lookup
SELECT * FROM donors WHERE donor_name = :donor_name LIMIT 1;

-- Team onboarding lists
SELECT * FROM volunteer_teams ORDER BY created_at DESC LIMIT 20;
SELECT * FROM volunteer_teams ORDER BY created_at DESC;
SELECT * FROM volunteer_teams ORDER BY team_name ASC;

-- Team approval lists
SELECT * FROM volunteer_team_applications WHERE team_id = :team_id;
SELECT * FROM volunteer_team_members WHERE team_id = :team_id;

-- Person/profile lookup by email
SELECT * FROM persons WHERE email = :email LIMIT 1;
SELECT * FROM rescue_personnel WHERE person_id = :person_id LIMIT 1;

/* =========================
   QUICK DEBUG QUERIES (useful in viva)
   ========================= */

SELECT COUNT(*) FROM victims;
SELECT status::text, COUNT(*) FROM victims GROUP BY status::text ORDER BY 2 DESC;
SELECT * FROM persons ORDER BY person_id DESC LIMIT 20;
SELECT * FROM locations ORDER BY location_id DESC LIMIT 20;
SELECT * FROM rescue_operations ORDER BY operation_id DESC LIMIT 20;
SELECT * FROM resource_allocations ORDER BY allocation_id DESC LIMIT 20;
SELECT * FROM incident_reports ORDER BY report_id DESC LIMIT 20;
