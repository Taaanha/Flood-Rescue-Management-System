# FRRMS Viva Query Sheet

This file summarizes database queries used by the app, organized by module and function/route.

## 1) Dashboard chart query (rescued victims by district)

Source: `frrms/routers/dashboard.py` (`GET /dashboard`)

```sql
SELECT
  COALESCE(NULLIF(TRIM(l.district), ''), 'Unknown') AS district,
  COUNT(*) AS rescued_count
FROM victims v
JOIN persons p ON p.person_id = v.person_id
LEFT JOIN locations l ON l.location_id = p.location_id
WHERE LOWER(COALESCE(v.status::text, '')) = 'rescued'
GROUP BY 1
ORDER BY rescued_count DESC, district ASC
LIMIT 10;
```

Related KPI query:

```sql
SELECT COUNT(*)
FROM victims
WHERE LOWER(COALESCE(status::text, '')) = 'rescued';
```

---

## 2) auth.py

- `login_form` (`GET /login`): no DB query.
- `login` (`POST /login`): no DB query.
- `logout` (`GET /logout`): no DB query.
- `me` (`GET /me`): no DB query.

---

## 3) dashboard.py

### `dashboard` (`GET /dashboard`)
- ORM: `query(ResourceInventory)`
- SQL: count rescued victims.
- SQL: rescued victims grouped by district.
- ORM: `query(Alert).join(Location)...` for active map alerts.

### `create_alert_marker` (`POST /dashboard/alerts`)
- ORM: `query(Location).filter(area_name, district).first()`
- ORM insert/update: `Location`, insert `Alert`.

### `clear_alert_marker` (`POST /dashboard/alerts/{alert_id}/clear`)
- ORM: `db.get(Alert, alert_id)` and update status.

---

## 4) inventory.py

### `inventory_page` (`GET /inventory`)
- ORM: `query(ResourceInventory)` with joined `resource` and `location`.
- ORM: `query(Resource)`.
- ORM: `query(ResourceCategory)`.

---

## 5) victims.py

### `_ensure_location_for_incident` (helper)
```sql
SELECT location_id
FROM locations
WHERE LOWER(district)=LOWER(:district)
ORDER BY location_id DESC
LIMIT 1;
```

```sql
INSERT INTO locations(area_name, district, created_at)
VALUES ('Unknown', :district, NOW())
RETURNING location_id;
```

### `victims_page` (`GET /victims`)
```sql
SELECT incident_id, title
FROM incidents
ORDER BY created_at DESC NULLS LAST, incident_id DESC
LIMIT 200;
```

```sql
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
```

### `register_victim` (`POST /victims/register`)
- SQL: find existing incident by title.
- SQL: optionally create incident.
- SQL: create person.
- SQL: create victim row.
- SQL: optionally create location and update person location.

### `leave_shelter` (`POST /victims/{victim_id}/leave-shelter`)
```sql
UPDATE victims
SET status = :status
WHERE victim_id = :victim_id;
```

---

## 6) command.py

### Helpers

#### `_ensure_system_user_id`
- `SELECT user_id FROM users WHERE username=:u`
- `SELECT role_id FROM roles WHERE role_name=:r`
- optional: `INSERT INTO roles(...) RETURNING role_id`
- `INSERT INTO persons(...) RETURNING person_id`
- `INSERT INTO users(...) RETURNING user_id`

#### `_ensure_default_location_id`
- `SELECT location_id FROM locations ORDER BY location_id ASC LIMIT 1`
- optional: `INSERT INTO locations(...) RETURNING location_id`

#### `_resolve_incident_id`
- `SELECT incident_id FROM incidents WHERE LOWER(title)=LOWER(:title) ...`
- optional: `INSERT INTO incidents(...) RETURNING incident_id`

#### `_resolve_operation_id`
- `SELECT operation_id FROM rescue_operations WHERE incident_id=:incident_id AND LOWER(operation_name)=LOWER(:name) ...`
- optional: `INSERT INTO rescue_operations(...) RETURNING operation_id`

### Operations routes

#### `operations_page` (`GET /operations`)
- SQL list operations joined with incidents and locations.
- SQL list incidents.
- SQL list locations.
- SQL list rescue personnel joined with persons.

#### `create_operation` (`POST /operations/create`)
- SQL insert into `rescue_operations`.

#### `create_incident` (`POST /incidents/create`)
- SQL insert into `incidents`.

#### `close_operation` (`POST /operations/{operation_id}/close`)
- SQL update `rescue_operations` status to completed.

#### `assign_personnel` (`POST /operations/{operation_id}/assign`)
- SQL insert into `rescue_assignments` with `ON CONFLICT DO NOTHING`.

### Field console routes

#### `field_console_page` (`GET /field-console`)
- SQL list incidents.
- SQL list active operations.
- SQL list resources.
- SQL list victims joined with persons.

#### `add_rescued_victim` (`POST /field/victims/rescued`)
- SQL insert person.
- SQL insert victim with status `'rescued'`.

#### `update_victim_status` (`POST /field/victims/{victim_id}/status`)
- SQL update victim status.

#### `create_resource_request` (`POST /field/resource-requests`)
- SQL find/create resource category/resource.
- SQL insert into `resource_allocations` with status `requested`.

#### `create_field_report` (`POST /field/reports`)
- SQL insert into `incident_reports`.

### Coordinator console routes

#### `coordinator_console_page` (`GET /coordinator-console`)
- SQL list pending resource allocations joined with resource + operation.
- SQL list incident reports joined with users + persons.

#### `review_resource_request` (`POST /resource-requests/{allocation_id}/review`)
- SQL update allocation as `approved` or `returned`.

#### `comment_on_report` (`POST /incident-reports/{report_id}/comment`)
- SQL update `incident_reports.content` append coordinator note.

---

## 7) rescue_units.py

### `_ensure_rescue_units_table` (helper)
- `SELECT to_regclass('public.rescue_teams') IS NOT NULL`
- optional `CREATE TABLE IF NOT EXISTS rescue_teams (...)`
- multiple `ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS ...`

### `rescue_units_page` (`GET /rescue-units`)
- SQL read from `rescue_teams` using `team_id/team_name` schema.
- SQL fallback read using `id/name` schema.
- SQL fallback derived view from `volunteer_teams` and `volunteer_team_members`.

### `create_rescue_unit` (`POST /rescue-units/create`)
- SQL insert/update `rescue_teams` (supports both schema variants).

### `update_rescue_unit_status` (`POST /rescue-units/{unit_id}/status`)
- SQL update status by `team_id` or by `id` fallback.

---

## 8) operations.py

### Helper queries

#### `_sync_rescue_unit_from_team`
- SQL schema sync: `ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS ...`
- SQL find existing rescue team by `team_name` or `name`.
- SQL update existing rescue team.
- SQL insert rescue team.

#### `_ensure_location`
- ORM: query location by area + district; insert if not found.

### Volunteer registration + assignments

#### `volunteer_registration_page` (`GET /volunteer-registration`)
- ORM: `query(VolunteerRequest)` filtered by username.
- ORM: `query(District)`.

#### `submit_volunteer_registration` (`POST /volunteer-registration`)
- ORM insert `VolunteerRequest`.

#### `admin_assignments_page` (`GET /admin/assignments`)
- ORM: `query(VolunteerRequest)` + joined district.
- ORM: `query(District)`.

#### `create_district` (`POST /districts`)
- ORM: find district by name; insert if absent.

#### `assign_volunteer_request` (`POST /admin/assignments/{request_id}/assign`)
- ORM: `db.get(VolunteerRequest)`
- ORM: `db.get(District)`
- ORM update assignment fields.

#### `approve_single_volunteer_request` / `reject_single_volunteer_request`
- ORM: `db.get(VolunteerRequest)` and update status.
- plus helper sync SQL in approve path.

### Shelters + resources

#### `shelters_page` (`GET /shelters`)
- ORM: `query(Shelter)` joined location.

#### `create_shelter` (`POST /shelters`)
- ORM: ensure/create location; insert shelter.

#### `resource_distribution_page` (`GET /resource-distribution`)
- ORM queries: `ResourceInventory`, `ResourceDistribution`, `District`, `ResourceCategory`, `Resource`.

#### `create_resource` (`POST /resources`)
- ORM: find duplicate resource.
- ORM: find/create category.
- ORM: insert resource.

#### `update_resource` (`POST /resources/{resource_id}/update`)
- ORM: `db.get(Resource)`
- ORM: duplicate-name check.
- ORM: find/create category.
- ORM: update resource.

#### `add_or_update_inventory` (`POST /resource-inventory`)
- ORM: `db.get(Resource)`.
- ORM: find inventory row by resource + location.
- ORM insert/update inventory row.

#### `distribute_resource` (`POST /resource-distribution`)
- ORM: `db.get(ResourceInventory)`.
- ORM create `ResourceDistribution` and decrement inventory.

### Donations

#### `donations_page` (`GET /donations`)
- ORM queries: `MonetaryDonation`, `InKindDonation`, `Resource`.

#### `add_monetary_donation` (`POST /donations/monetary`)
- ORM: find/create donor.
- ORM: insert monetary donation.

#### `add_in_kind_donation` (`POST /donations/in-kind`)
- ORM: find/create donor.
- ORM: get resource OR create resource via category.
- ORM: insert in-kind donation.

### Team onboarding + approvals

#### `team_onboarding_page` (`GET /team-onboarding`)
- ORM query `VolunteerTeam` joined with applications.
- ORM list queries for created/all teams.

#### `create_volunteer_team` (`POST /team-onboarding/create-team`)
- ORM duplicate check on team name.
- ORM create team + leader application.

#### `add_team_member_application` (`POST /team-onboarding/{team_id}/members`)
- ORM: `db.get(VolunteerTeam)`.
- ORM insert member application.

#### `join_team_by_code` (`POST /team-onboarding/join`)
- ORM: `db.get(VolunteerTeam)`.
- ORM insert member application.

#### `team_approvals_page` (`GET /admin/team-approvals`)
- ORM queries `VolunteerTeam` and `VolunteerRequest`.

#### `_get_or_create_personnel_from_application`
- ORM: find/create `Person`.
- ORM: find/create/update `RescuePersonnel`.

#### `approve_team` (`POST /admin/team-approvals/{team_id}/approve`)
- ORM: `db.get(VolunteerTeam)`.
- ORM: query pending applications.
- ORM: query/add `VolunteerTeamMember`.
- helper sync SQL for rescue units.

#### `reject_team` (`POST /admin/team-approvals/{team_id}/reject`)
- ORM: `db.get(VolunteerTeam)` + query applications and reject pending.

#### `add_single_volunteer_to_team` (`POST /admin/team-approvals/add-single-volunteer`)
- ORM: `db.get(VolunteerTeam)`.
- ORM: insert application/personnel/member.
- ORM: count team members.
- helper sync SQL for rescue units.

---

## 9) Quick Viva-ready one-liners

- Dashboard chart uses `victims + persons + locations` and groups by district.
- Dashboard KPI uses the same rescued-status filter as chart.
- Victim statuses are enum-based (`victim_status`), so filtering uses `status::text`.
- `command.py` is mostly raw SQL workflows for operations/field/coordinator consoles.
- `operations.py` is mostly ORM workflows for volunteer/resource/donation/team modules.
- `rescue_units.py` includes schema-compatibility fallbacks for old/new `rescue_teams` column naming.
