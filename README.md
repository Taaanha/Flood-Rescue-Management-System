# FRRMS Command

Flood Rescue and Resource Management System (FRRMS) web console built with FastAPI, PostgreSQL, SQLAlchemy, Jinja2 templates, Bootstrap&nbsp;5, Chart.js, and Leaflet.js.

## Features

- Session-based authentication with role-aware UI (admin, district_manager, team_leader)
- Dashboard with KPIs, Leaflet map centered on Bangladesh, and Chart.js district chart
- Victim registry view
- Rescue units status board
- Inventory health and low-stock alerts
- Admin team assignment panel (district/place assignment for volunteer requests)
- Team volunteer registration flow (submit preferred district/place and wait for assignment)
- Shelter management (add and list shelters)
- Resource distribution workflow (allocate inventory to districts/places)
- Donation management (monetary and in-kind)

## Getting started

1. **Install dependencies**

   ```bash
   cd "e:\frrms fastapi"
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment**

   - Local development (default): set `APP_ENV=local` and use `POSTGRES_*` values.
   - Cloud/deployed: set `APP_ENV=production` and set `DATABASE_URL` (Neon).

3. **Run the app**

   ```bash
   # One-time: copy .env.example to .env and set your password
   # Then run:
   env\Scripts\python -m uvicorn frrms.main:app --reload --env-file .env
   ```

4. **Open in browser**

   - Navigate to `http://127.0.0.1:8000`
   - Use one of the demo credentials on the login screen, e.g.:
     - `admin` / `admin123`
     - `district` / `district123`
     - `team` / `team123`

## Production notes

- Set a strong `SessionMiddleware` secret key via environment or by editing `frrms/main.py`.
- DB selection is controlled by `APP_ENV`:
  - `APP_ENV=local` -> uses `POSTGRES_*` (your local pgAdmin/PostgreSQL)
  - `APP_ENV=production` or `APP_ENV=cloud` -> uses `DATABASE_URL` (Neon)
- `POSTGRES_*` variables:
  `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_SSLMODE`
- On startup, the app now verifies DB connectivity and auto-creates tables from `frrms/models.py` if they do not already exist.
- Replace the dummy in-memory users in `frrms/routers/auth.py` with real user persistence and password hashing.
- On first run, baseline districts/resources/inventory are seeded for easier testing.

