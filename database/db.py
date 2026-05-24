import sqlite3
import os
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)

def get_connection():
    """Create a database connection to the SQLite database specified by DB_PATH."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        if conn:
            conn.close()
        raise

def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                website TEXT,
                phone TEXT,
                address TEXT,
                rating REAL,
                linkedin TEXT,
                twitter TEXT,
                instagram TEXT,
                facebook TEXT,
                business_type TEXT,
                pain_points TEXT,
                opportunities TEXT,
                generated_email TEXT,
                email_subject TEXT,
                contacted BOOLEAN DEFAULT 0,
                error_log TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email)
            )
        ''')
        conn.commit()
        logger.info("Database initialized successfully.")
        migrate_db(conn)    # Always run migrations after init
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        conn.close()

def migrate_db(conn=None):
    """
    Safely add any missing columns to an existing leads table.
    This allows schema evolution without wiping existing data.
    """
    _close_after = False
    if conn is None:
        conn = get_connection()
        _close_after = True

    # Define columns that should exist: (column_name, column_definition)
    NEW_COLUMNS = [
        ("facebook",      "TEXT"),
        ("phone",         "TEXT"),
        ("email_subject", "TEXT"),
    ]
    try:
        cursor = conn.cursor()
        # Get existing column names
        cursor.execute("PRAGMA table_info(leads)")
        existing = {row[1] for row in cursor.fetchall()}

        for col_name, col_def in NEW_COLUMNS:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")
                logger.info(f"DB migration: added column '{col_name}'")

        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Migration error: {e}")
    finally:
        if _close_after:
            conn.close()

def insert_lead(lead_data):
    """Insert a new lead into the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Ensure email is present to avoid integrity errors if it's supposed to be unique and non-null in logic
        # though UNIQUE(email) allows multiple NULLs in SQLite. We will filter out duplicates later or here.
        cursor.execute('''
            INSERT INTO leads (name, email, website, phone, address, rating, linkedin, twitter, instagram, facebook)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            lead_data.get('name'),
            lead_data.get('email'),
            lead_data.get('website'),
            lead_data.get('phone'),
            lead_data.get('address'),
            lead_data.get('rating'),
            lead_data.get('linkedin'),
            lead_data.get('twitter'),
            lead_data.get('instagram'),
            lead_data.get('facebook'),
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        logger.warning(f"Duplicate email found for lead: {lead_data.get('email')} - Skipping insertion.")
        return None
    except sqlite3.Error as e:
        logger.error(f"Database error during insert: {e}")
        return None
    finally:
        conn.close()

def get_all_leads(uncontacted_only=False):
    """Retrieve leads from the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if uncontacted_only:
            cursor.execute("SELECT * FROM leads WHERE contacted = 0")
        else:
            cursor.execute("SELECT * FROM leads")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Database error during fetch: {e}")
        return []
    finally:
        conn.close()

def update_lead(lead_id, data):
    """Update specific fields of a lead."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        set_clause = ", ".join([f"{key} = ?" for key in data.keys()])
        values = list(data.values())
        values.append(lead_id)
        
        cursor.execute(f"UPDATE leads SET {set_clause} WHERE id = ?", tuple(values))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error during update: {e}")
    finally:
        conn.close()

def delete_lead(lead_id):
    """Delete a lead from the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error during delete: {e}")
    finally:
        conn.close()

def delete_all_leads():
    """Delete ALL leads from the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads")
        conn.commit()
        logger.info("All leads deleted.")
    except sqlite3.Error as e:
        logger.error(f"Database error during delete all: {e}")
    finally:
        conn.close()
