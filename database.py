# scripts/add_category_visibility.py
from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    conn = db.engine.connect()

    # Check existing columns
    cols = conn.execute(text("PRAGMA table_info(category);")).fetchall()
    col_names = {c[1] for c in cols}

    if "show_on_website" not in col_names:
        print("➕ Adding show_on_website")
        conn.execute(text("""
            ALTER TABLE category
            ADD COLUMN show_on_website BOOLEAN NOT NULL DEFAULT 1
        """))
    else:
        print("✔ show_on_website already exists")

    if "show_on_pos" not in col_names:
        print("➕ Adding show_on_pos")
        conn.execute(text("""
            ALTER TABLE category
            ADD COLUMN show_on_pos BOOLEAN NOT NULL DEFAULT 1
        """))
    else:
        print("✔ show_on_pos already exists")

    conn.commit()
    conn.close()

    print("✅ Category visibility columns are ready.")