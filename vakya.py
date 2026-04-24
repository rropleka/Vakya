import sqlite3
import re
import sys, os
import build_tree

cursor = None

def get_changes(id):
    cursor.execute("""WITH RECURSIVE LINEAGE AS (
                        SELECT LANGUAGES.Id, LANGUAGES.Parent_Id, 0 AS Depth
                        FROM LANGUAGES
                        WHERE Id = ?

                        UNION ALL

                        SELECT LANGUAGES.Id, LANGUAGES.Parent_Id, Depth + 1
                        FROM LANGUAGES
                        JOIN LINEAGE ON LANGUAGES.Id = LINEAGE.Parent_Id
                    )

                    SELECT In_Regex, Out_Regex
                    FROM SOUND_CHANGES
                    JOIN LINEAGE CHILD ON SOUND_CHANGES.Child_Id = CHILD.Id 
                    AND SOUND_CHANGES.Parent_Id = CHILD.Parent_Id

                    ORDER BY CHILD.Depth DESC, SOUND_CHANGES.Order_Index ASC
                    """, (id,))
    return cursor.fetchall()

def apply_changes(lexeme, rules):
    if rules == []:
        return lexeme

    rule = rules.pop()
    lexeme = apply_changes(lexeme, rules)

    return re.sub(rule[0], rule[1], lexeme)

try:
    if not os.path.isfile("vakya.db"):
        print("Rebuilding")
        build_tree.rebuild()

    with sqlite3.connect("vakya.db") as connection:
        cursor = connection.cursor()
        print(apply_changes("séḱs", get_changes(2)))

except sqlite3.Error as error:
    print("SQLite3 Error:", sys.exc_info())