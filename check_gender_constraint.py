from frrms.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='persons_gender_check'"
    )).fetchall()
    for r in rows:
        print(r)