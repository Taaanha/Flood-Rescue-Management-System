from frrms.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text(
        "SELECT setval(pg_get_serial_sequence('locations', 'location_id'), "
        "(SELECT MAX(location_id) FROM locations))"
    ))
    conn.commit()

print("Sequence fixed")