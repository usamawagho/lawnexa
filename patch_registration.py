import sqlite3

def run_patch():
    conn = sqlite3.connect("lawnexa.db")
    cursor = conn.cursor()
    cols = [
        ("phone", "TEXT"),
        ("address", "TEXT"),
        ("specializations", "TEXT"),
        ("bar_council_no", "TEXT"),
        ("chamber_address", "TEXT"),
        ("city", "TEXT"),
        ("experience_years", "INTEGER"),
        ("consultation_fee", "INTEGER"),
        ("profile_image", "TEXT")
    ]
    for col_name, col_type in cols:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            print(f"Added {col_name} column")
        except Exception as e:
            print(f"Column {col_name} may already exist.")

    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            doc_type VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            form_data TEXT NOT NULL,
            generated_html TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        print("Created user_documents table")
    except Exception as e:
        print("user_documents table error/already exists:", e)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_patch()
