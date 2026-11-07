"""
The current regex engine: rules from sound_changes.csv are applied as regex substitutions on the
written form. To be replaced by parsed rules applied to phonemes.
"""
import re
import unicodedata
from dataclasses import dataclass

@dataclass(frozen=True)
class Step:
    language_id: int        # the language this change leads into
    language: str
    description: str
    in_regex: str
    out_regex: str
    before: str
    after: str

def get_changes(connection, id):
    return connection.execute("""WITH RECURSIVE LINEAGE AS (
                                    SELECT LANGUAGES.Id, LANGUAGES.Parent_Id, 0 AS Depth
                                    FROM LANGUAGES
                                    WHERE Id = ?

                                    UNION ALL

                                    SELECT LANGUAGES.Id, LANGUAGES.Parent_Id, Depth + 1
                                    FROM LANGUAGES
                                    JOIN LINEAGE ON LANGUAGES.Id = LINEAGE.Parent_Id
                                )

                                SELECT CHILD.Id, LANGUAGES.Name, In_Regex, Out_Regex, Description
                                FROM SOUND_CHANGES
                                JOIN LINEAGE CHILD ON SOUND_CHANGES.Child_Id = CHILD.Id
                                AND SOUND_CHANGES.Parent_Id = CHILD.Parent_Id
                                JOIN LANGUAGES ON LANGUAGES.Id = CHILD.Id

                                ORDER BY CHILD.Depth DESC, SOUND_CHANGES.Order_Index ASC
                                """, (id,)).fetchall()

def nfc(text):
    return unicodedata.normalize("NFC", text)

def derive(connection, word, language_id):
    """Apply every change from the root down to a language; returns (form, steps that changed something)."""
    # NFC on both sides so a decomposed ḱ in the input still matches a precomposed one in the rules
    form = nfc(word).strip("*")
    steps = []
    for child_id, language, in_regex, out_regex, description in get_changes(connection, language_id):
        result = re.sub(nfc(in_regex), nfc(out_regex or ""), form)
        if result != form:
            steps.append(Step(child_id, language, description, in_regex, out_regex or "", form, result))
        form = result
    return form, steps
