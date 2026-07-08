from frrms.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    demo_assignments = [
        ("Sylhet", 2),
        ("Rajshahi", 1),
        ("Noakhali", 1),
    ]
    for district, count in demo_assignments:
        district_id_row = db.execute(
            text("SELECT id FROM districts WHERE name=:d"), {"d": district}
        ).first()
        if not district_id_row:
            print(f"Skipped {district}: not found in districts table")
            continue
        district_id = district_id_row[0]
        for i in range(count):
            db.execute(
                text(
                    """
                    INSERT INTO volunteer_requests(team_name, preferred_district, assigned_district_id, status, admin_note, created_at)
                    VALUES (:team, :pref, :district_id, 'assigned', :note, NOW())
                    """
                ),
                {
                    "team": f"demo_volunteer_{district}_{i+1}",
                    "pref": district,
                    "district_id": district_id,
                    "note": f"requester_name=Demo Volunteer {i+1}; requester_age=28",
                },
            )
        print(f"Assigned {count} demo volunteer(s) to {district}")
    db.commit()
finally:
    db.close()