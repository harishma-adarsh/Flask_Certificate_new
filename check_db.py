import sqlite3
import pandas as pd
import os

# Set database path
DB_PATH = "certificates.db"

def check_database():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found in current directory.")
        return

    try:
        # Connect to the database
        conn = sqlite3.connect(DB_PATH)
        
        # Read the certificates table into a pandas DataFrame
        df = pd.read_sql_query("SELECT * FROM certificates", conn)
        
        if df.empty:
            print("The database is currently empty.")
        else:
            print("\n--- DATABASE CONTENTS ---")
            # Using to_string() ensures the whole table is printed
            print(df.to_string(index=False))
            print(f"\nTotal Records: {len(df)}")
            
        conn.close()
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    check_database()
