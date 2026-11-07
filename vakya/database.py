import csv
import os
import sqlite3

from . import DATA_DIR, DB_PATH

LANGUAGES_CSV = os.path.join(DATA_DIR, "languages.csv")
SOUND_CHANGES_CSV = os.path.join(DATA_DIR, "sound_changes.csv")
SOURCES = (LANGUAGES_CSV, SOUND_CHANGES_CSV)

def build_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS LANGUAGES(
            Id          INT     NOT NULL    PRIMARY KEY,
            Name        TEXT    NOT NULL,
            Parent_Id   INT     REFERENCES LANGUAGES(Id),
            Type        TEXT    CHECK (Type IN ('proto', 'attested', 'intermediate', 'dialect'))
        )
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS SOUND_CHANGES(
            Order_Index     INT     NOT NULL,
            Parent_Id       INT     NOT NULL,
            Child_Id        INT     NOT NULL,
            In_Regex        TEXT    NOT NULL,
            Out_Regex       TEXT,
            Description     TEXT,

            UNIQUE(Parent_Id, Child_Id, Order_Index),
            FOREIGN KEY(Parent_Id)  REFERENCES LANGUAGES(Id),
            FOREIGN KEY(Child_Id)   REFERENCES LANGUAGES(Id)
        );
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

    with open(SOUND_CHANGES_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute(
                "INSERT INTO SOUND_CHANGES (Order_Index, Parent_Id, Child_Id, In_Regex, Out_Regex, Description) VALUES (?,?,?,?,?,?)",
                (
                    int(row['order_index']),
                    int(row['parent_id']),
                    int(row['child_id']),
                    row['in_regex'],
                    row['out_regex'],
                    row['description']
                )
            )

def rebuild(path=DB_PATH):
    with sqlite3.connect(path) as connection:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        cursor.execute("DROP TABLE IF EXISTS SOUND_CHANGES") # have to drop this first or else FOREIGN KEY constraint will fail
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

def rule_counts(connection):
    """Number of sound changes leading into each language, by child id."""
    return dict(connection.execute("SELECT Child_Id, COUNT(*) FROM SOUND_CHANGES GROUP BY Child_Id").fetchall())

def sound_changes(connection):
    return connection.execute("""SELECT Parent_Id, Child_Id, Order_Index, In_Regex, Out_Regex, Description
                                 FROM SOUND_CHANGES ORDER BY Parent_Id, Child_Id, Order_Index""").fetchall()
