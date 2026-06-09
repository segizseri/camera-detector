import sqlite3
import os

db_path = "data/sqlite/laptop_ai_box.db"

def migrate():
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check existing columns
    cursor.execute("PRAGMA table_info(cameras)")
    cols = [c[1] for c in cursor.fetchall()]
    
    new_cols = [
        ("bus_id", "TEXT"),
        ("counting_config", "TEXT"),
        ("detect_fights", "BOOLEAN DEFAULT 1"),
        ("detect_bullying", "BOOLEAN DEFAULT 1"),
        ("detect_theft", "BOOLEAN DEFAULT 1"),
        ("detect_passengers", "BOOLEAN DEFAULT 1")
    ]
    
    for col_name, col_type in new_cols:
        if col_name not in cols:
            print(f"Adding column {col_name}...")
            try:
                cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Failed to add {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists.")
            
    conn.commit()
    conn.close()
    print("Migration finished successfully.")

if __name__ == "__main__":
    migrate()
