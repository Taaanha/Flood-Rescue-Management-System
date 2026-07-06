from frrms.database import engine
from sqlalchemy import text

TABLES = [
    "locations", "roles", "persons", "users", "rescue_personnel",
    "incidents", "alerts", "rescue_operations", "rescue_assignments",
    "victims", "shelters", "shelter_assignments", "resource_categories",
    "resources", "resource_inventory", "resource_allocations",
    "medical_aid", "incident_reports", "donors", "monetary_donations",
    "donation_allocations", "in_kind_donations", "volunteer_teams",
    "volunteer_team_members", "rescue_teams",
]

with engine.connect() as conn:
    for table in TABLES:
        try:
            pk_col = conn.execute(text(f"""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = '{table}'::regclass AND i.indisprimary
            """)).scalar()

            if not pk_col:
                print(f"Skipped {table}: no primary key found")
                continue

            seq = conn.execute(text(
                f"SELECT pg_get_serial_sequence('{table}', '{pk_col}')"
            )).scalar()

            if not seq:
                print(f"Skipped {table}: no sequence (not auto-increment)")
                continue

            conn.execute(text(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX({pk_col}) FROM {table}), 1))"
            ))
            print(f"Fixed {table} (pk={pk_col})")
        except Exception as e:
            print(f"Error on {table}: {e}")
    conn.commit()

print("Done.")