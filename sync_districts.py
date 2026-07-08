from frrms.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("SELECT DISTINCT district FROM locations")).fetchall()
    created = 0
    for (district,) in rows:
        exists = db.execute(text("SELECT 1 FROM districts WHERE name=:d"), {"d": district}).first()
        if exists:
            continue
        db.execute(text("INSERT INTO districts(name) VALUES (:d)"), {"d": district})
        created += 1
    db.commit()
    print(f"Created {created} new district rows.")
finally:
    db.close()