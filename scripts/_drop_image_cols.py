from scrape_engine.db import connect, init_db

init_db()
with connect() as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'scraped_products'
              AND column_name LIKE '%%image%%'
            ORDER BY column_name
            """
        )
        cols = [r["column_name"] for r in cur.fetchall()]
print("image columns:", cols)
