import sqlite3
import csv
import sys
import pandas as pd

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

    with open("data/languages.csv", 'r') as f:
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

    with open("data/sound_changes.csv", 'r') as f:
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

def rebuild():
    try:
        with sqlite3.connect('vakya.db') as connection:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")

            cursor.execute("DROP TABLE IF EXISTS SOUND_CHANGES") # have to drop this first or else FOREIGN KEY constraint will fail
            cursor.execute("DROP TABLE IF EXISTS LANGUAGES")

            build_tables(cursor)
            connection.commit()

            pd.set_option('display.max_rows', 500)
            pd.set_option('display.max_columns', 500)
            pd.set_option('display.width', 150)

            print("Languages:")
            print(pd.read_sql_query("SELECT * FROM LANGUAGES", connection, "Id"))
            print()
            print("Sound changes:")
            print(pd.read_sql_query("SELECT * FROM SOUND_CHANGES", connection, ["Parent_Id", "Child_Id", "Order_Index"]))
            print("----------------------------------------------------------------------")

    except sqlite3.Error as error:
        print("SQLite3 Error:", sys.exc_info())

if __name__ == "__main__":
    rebuild()