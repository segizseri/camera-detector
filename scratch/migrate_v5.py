import sqlite3
import os

DB_PATH = "data/sqlite/laptop_ai_box.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Create Visitors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                id VARCHAR PRIMARY KEY,
                first_seen DATETIME,
                last_seen DATETIME,
                visit_count INTEGER DEFAULT 1,
                face_embedding BLOB,
                face_snapshot VARCHAR,
                is_flagged BOOLEAN DEFAULT 0
            )
        """)
        
        # Add visitor_id to events
        cursor.execute("ALTER TABLE events ADD COLUMN visitor_id VARCHAR REFERENCES visitors(id);")
        print("Successfully created visitors table and added visitor_id to events.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Migration already applied (visitor_id exists).")
        else:
            print(f"Error during migration: {e}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
