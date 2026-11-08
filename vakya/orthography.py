"""
Spelling phonemes in a language's native orthography.

data/orthography/<language-name>.csv maps phonemes to spellings:

    phonemes,spelling
    θ,þ
    æɑ,ea
    aː,ā

The phonemes column is read with the inventory and may hold a sequence (a diphthong spelled as one
unit); the longest match wins. Stress is ignored, and a long consonant with no row of its own is
spelled doubled (tː → tt).

The table also works backwards, to read a word written in the language (*fadēr) as phonemes. When
several phonemes share a spelling, an optional third column `read` set to "no" marks the rows that
reading should skip, leaving the one a written letter stands for.

An optional fourth column `context` limits a row to an environment, written as in sound changes
(_{E, ə} before a front vowel or ə, _C# before a final consonant, // s_ except after s). For a given
phoneme the first row whose context matches is used, so put the general row (no context) last:

    k,k,no,_{E, ə}
    k,k,no,_#
    k,c,,

The classes C (consonant), V (vowel), E (front vowel) and B (back vowel) are available. Contexts are
ignored when reading.
"""
import csv
import os
import re
import unicodedata
from functools import cache

from . import DATA_DIR
from .phonemes import Phoneme, inventory

ORTHOGRAPHY_DIR = os.path.join(DATA_DIR, "orthography")

class OrthographyError(Exception):
    pass

def key(phoneme):
    return frozenset((name, value) for name, value in phoneme.features if name != "stressed")

def slug(language):
    return re.sub(r"[^a-z0-9]+", "-", language.lower()).strip("-")

def context_definitions():
    from .rules import Definitions
    definitions = Definitions()
    definitions.define_class("C", "[type=Consonant]")
    definitions.define_class("V", "[type=Vowel]")
    definitions.define_class("E", "{[type=Vowel backness=Front], [type=Vowel backness=Near-front]}")
    definitions.define_class("B", "[type=Vowel backness=Back]")
    return definitions

def compile_context(text, definitions):
    """A spelling context (_C#, // s_) as a compiled rule whose environments can be tested."""
    from .rules import compile_rule
    text = text.strip()
    return compile_rule("p → p " + (text if text.startswith("//") else "/ " + text), definitions)

class Orthography:
    def __init__(self, language, rows):
        self.language = language
        self.spellings = {}     # phoneme keys -> [(spelling, context or None)] in file order
        self.readings = {}      # spelling (NFD) -> phonemes
        definitions = None
        for phonemes, spelling, readable, context in rows:
            tokens = inventory().tokenize(phonemes)
            if context:
                definitions = definitions or context_definitions()
                try:
                    context = compile_context(context, definitions)
                except Exception as error:
                    raise OrthographyError(f"{os.path.relpath(path_for(language), DATA_DIR)}: "
                                           f"bad context {context!r} for {phonemes}: {error}") from None
            self.spellings.setdefault(tuple(map(key, tokens)), []).append((spelling, context or None))
            if readable:
                self.readings.setdefault(unicodedata.normalize("NFD", spelling), tokens)
        self.max_length = max(map(len, self.spellings), default=1)
        self.max_spelling = max(map(len, self.readings), default=1)

    def read(self, text) -> list[Phoneme]:
        """A written word as phonemes, unstressed; longest spelling first."""
        text = unicodedata.normalize("NFD", text.strip().strip("*"))
        result = []
        i = 0
        while i < len(text):
            for length in range(min(self.max_spelling, len(text) - i), 0, -1):
                tokens = self.readings.get(text[i:i + length])
                # don't split a letter from its diacritics: "a" must not match the start of "ą"
                if tokens is not None and not (i + length < len(text) and unicodedata.combining(text[i + length])):
                    result.extend(tokens)
                    i += length
                    break
            else:
                raise OrthographyError(f"can't read {text[i]!r} in {unicodedata.normalize('NFC', text)!r} "
                                       f"as {self.language}")
        return result

    def choose(self, phonemes, start, end):
        """The spelling of phonemes[start:end] in its context, or None."""
        for spelling, context in self.spellings.get(tuple(map(key, phonemes[start:end])), ()):
            if context is None or context.applies_at(phonemes, start, end):
                return spelling
        return None

    def spell(self, phonemes) -> str:
        phonemes = list(phonemes)
        result = []
        i = 0
        while i < len(phonemes):
            for length in range(min(self.max_length, len(phonemes) - i), 0, -1):
                spelling = self.choose(phonemes, i, i + length)
                if spelling is not None:
                    result.append(spelling)
                    i += length
                    break
            else:
                result.append(self.spell_one(phonemes[i]))
                i += 1
        return "".join(result)

    def spell_one(self, phoneme):
        if phoneme["long"] and phoneme["type"] == "Consonant":
            short = key(phoneme) - {("long", True)}
            unconditioned = [spelling for spelling, context in self.spellings.get((short,), ()) if context is None]
            if unconditioned:
                return unconditioned[0] * 2
        raise OrthographyError(f"no {self.language} spelling for /{phoneme}/; add it to "
                               f"{os.path.relpath(path_for(self.language), DATA_DIR)}")

def path_for(language, script=None):
    return os.path.join(ORTHOGRAPHY_DIR, slug(language) + (f"-{slug(script)}" if script else "") + ".csv")

@cache
def orthography(language, script=None):
    """The language's orthography (or its table for another script, e.g. hindi-devanagari.csv), or None."""
    path = path_for(language, script)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        rows = [(row["phonemes"], row["spelling"], (row.get("read") or "").strip().lower() != "no",
                 (row.get("context") or "").strip())
                for row in csv.DictReader(f) if row["phonemes"]]
    return Orthography(language, rows)
