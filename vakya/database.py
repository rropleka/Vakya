import csv
import os
import sqlite3

from . import DATA_DIR, DB_PATH

LANGUAGES_CSV = os.path.join(DATA_DIR, "languages.csv")
SOURCES = (LANGUAGES_CSV,)

def build_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS LANGUAGES(
            Id          INT     NOT NULL    PRIMARY KEY,
            Name        TEXT    NOT NULL,
            Parent_Id   INT     REFERENCES LANGUAGES(Id),
            Type        TEXT    CHECK (Type IN ('proto', 'attested', 'intermediate', 'dialect'))
        )
        """)

    with open(LANGUAGES_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parent = int(row['parent_id']) if row['parent_id'] != '' else None
            cursor.execute(
                "INSERT INTO LANGUAGES (Id, Name, Parent_Id, Type) VALUES (?,?,?,?)",
                (
                    int(row['id']),
                    row['name'],
                    parent,
                    row['type']
                )
            )

def rebuild(path=DB_PATH):
    with sqlite3.connect(path) as connection:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        cursor.execute("DROP TABLE IF EXISTS SOUND_CHANGES") # left over from databases built before rule files
        cursor.execute("DROP TABLE IF EXISTS LANGUAGES")

        build_tables(cursor)
        connection.commit()
    connection.close()

def is_stale(path=DB_PATH):
    if not os.path.isfile(path):
        return True
    built = os.path.getmtime(path)
    return any(os.path.getmtime(source) > built for source in SOURCES)

def connect(path=DB_PATH):
    """Open the database, rebuilding it first if it is missing or older than the CSVs."""
    if is_stale(path):
        rebuild(path)
    return sqlite3.connect(path)

def languages(connection):
    """All languages as (id, name, parent_id, type), parents before children."""
    return connection.execute("""WITH RECURSIVE TREE AS (
                                    SELECT Id, Name, Parent_Id, Type, Name AS Path
                                    FROM LANGUAGES
                                    WHERE Parent_Id IS NULL

                                    UNION ALL

                                    SELECT LANGUAGES.Id, LANGUAGES.Name, LANGUAGES.Parent_Id, LANGUAGES.Type,
                                           TREE.Path || '/' || LANGUAGES.Name
                                    FROM LANGUAGES
                                    JOIN TREE ON LANGUAGES.Parent_Id = TREE.Id
                                )

                                SELECT Id, Name, Parent_Id, Type FROM TREE ORDER BY Path
                                """).fetchall()

def find_language(connection, key):
    """Look a language up by id or by name (case-insensitive)."""
    if str(key).isdigit():
        row = connection.execute("SELECT Id, Name, Parent_Id, Type FROM LANGUAGES WHERE Id = ?", (int(key),)).fetchone()
    else:
        row = connection.execute("SELECT Id, Name, Parent_Id, Type FROM LANGUAGES WHERE Name = ? COLLATE NOCASE",
                                 (key,)).fetchone()
    return row

def lineage(connection, id):
    """The languages from the root down to this one, as (id, name, parent_id, type)."""
    rows = connection.execute("""WITH RECURSIVE LINEAGE AS (
                                    SELECT Id, Name, Parent_Id, Type, 0 AS Depth
                                    FROM LANGUAGES
                                    WHERE Id = ?

                                    UNION ALL

                                    SELECT LANGUAGES.Id, LANGUAGES.Name, LANGUAGES.Parent_Id, LANGUAGES.Type, Depth + 1
                                    FROM LANGUAGES
                                    JOIN LINEAGE ON LANGUAGES.Id = LINEAGE.Parent_Id
                                )

                                SELECT Id, Name, Parent_Id, Type FROM LINEAGE ORDER BY Depth DESC
                                """, (id,)).fetchall()
    return rows
