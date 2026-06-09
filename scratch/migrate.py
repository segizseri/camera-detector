import sqlite3
import os

db_path = "data/sqlite/laptop_ai_box.db"

if os.path.exists(db_path):
    print(f"Migrating database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Add bus_id to cameras
    try:
        cursor.execute("ALTER TABLE cameras ADD COLUMN bus_id TEXT REFERENCES buses(id)")
        print("Added bus_id to cameras")
    except sqlite3.OperationalError:
        print("bus_id already exists or error")

    # Add AI feature flags to cameras
    columns = [
        ("detect_fights", "BOOLEAN DEFAULT 1"),
        ("detect_bullying", "BOOLEAN DEFAULT 1"),
        ("detect_theft", "BOOLEAN DEFAULT 1"),
        ("detect_passengers", "BOOLEAN DEFAULT 1")
    ]
    
    for col_name, col_def in columns:
        try:
            cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_def}")
            print(f"Added {col_name} to cameras")
        except sqlite3.OperationalError:
            print(f"{col_name} already exists or error")
            
    conn.commit()
    conn.close()
    print("Migration complete.")
else:
    print("Database file not found, nothing to migrate.")
