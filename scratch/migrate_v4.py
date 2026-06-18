import sqlite3
import os

DB_PATH = "data/sqlite/laptop_ai_box.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Creating empty or skipping...")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE cameras ADD COLUMN detect_eating BOOLEAN DEFAULT 1;")
        print("Successfully added detect_eating to cameras table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column detect_eating already exists.")
        else:
            print(f"Error: {e}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
