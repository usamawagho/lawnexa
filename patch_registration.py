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

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_patch()
