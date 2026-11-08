"""
Word-level data: which PIE formation each branch continues, and the attested reflexes.

data/formations.csv — word,language,form,note
    Where a branch continues a different formation of the word than its parent's regular outcome (a
    different case or stem, or a change of stem class), `language` is computed from `form` instead of
    from its parent's output. `form` is written in the parent language's spelling (PIE notation when the
    parent is the root).

data/attested.csv — word,language,form,source
    Real reflexes, in the language's spelling table's conventions, shown next to the regular prediction.

`word` is the PIE word in PIE notation (*ph₂tḗr); input typed in ASCII matches too.
"""
import csv
import os
import unicodedata
from dataclasses import dataclass
from functools import cache

from . import DATA_DIR
from .phonemes import ascii_to_pie

FORMATIONS_CSV = os.path.join(DATA_DIR, "formations.csv")
ATTESTED_CSV = os.path.join(DATA_DIR, "attested.csv")

def word_key(word):
    return unicodedata.normalize("NFC", ascii_to_pie(word.strip())).strip("*")

@dataclass(frozen=True)
class Formation:
    form: str
    note: str

@dataclass(frozen=True)
class Attested:
    form: str
    source: str

def read_rows(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if (row.get("word") or "").strip()]

@cache
def formations():
    return {(word_key(row["word"]), row["language"].strip().lower()): Formation(row["form"].strip(), row.get("note") or "")
            for row in read_rows(FORMATIONS_CSV)}

@cache
def attested():
    result = {}
    for row in read_rows(ATTESTED_CSV):
        result.setdefault((word_key(row["word"]), row["language"].strip().lower()), []).append(
            Attested(unicodedata.normalize("NFC", row["form"].strip().lstrip("*")), row.get("source") or ""))
    return result

def formation(word, language):
    return formations().get((word_key(word), language.lower()))

def attested_forms(word, language):
    return attested().get((word_key(word), language.lower()), [])

def reload():
    formations.cache_clear()
    attested.cache_clear()
