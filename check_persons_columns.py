from frrms.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='persons'"
    )).fetchall()
    for r in rows:
        print(r)