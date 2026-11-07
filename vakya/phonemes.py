import csv
import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache

from . import DATA_DIR

PHONEME_DIR = os.path.join(DATA_DIR, "phoneme")

def normalize(text):
    # NFD splits precomposed letters (é → e + ◌́) so every diacritic is its own character;
    # IPA ɡ and ASCII g look identical but are different code points, so pick one
    return unicodedata.normalize("NFD", text).replace("ɡ", "g")

def parse_value(value):
    return {"True": True, "False": False}.get(value, value)

@dataclass(frozen=True)
class Phoneme:
    # identity is the feature set: kʷ from the table and k + ʷ from diacritics are the same phoneme
    symbol: str = field(compare=False)
    features: frozenset

    def __getitem__(self, feature):
        return dict(self.features).get(feature)

    def __str__(self):
        return unicodedata.normalize("NFC", self.symbol)

    def __repr__(self):
        return f"/{self}/"

class PhonemeError(Exception):
    pass

class Inventory:
    def __init__(self, phonemes, diacritics):
        self.phonemes = phonemes        # symbol -> {feature: value}
        self.diacritics = diacritics    # symbol -> {feature: value}
        self.max_length = max(len(symbol) for symbol in phonemes)

    @classmethod
    def load(cls, directory=PHONEME_DIR):
        bases = {}
        with open(os.path.join(directory, "ipa.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bases[normalize(row["ipa"])] = normalize(row["base"] or "")

        deltas = {}
        with open(os.path.join(directory, "features.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                symbol = normalize(row["ipa"])
                if symbol not in bases:
                    raise PhonemeError(f"features.csv: {symbol!r} is not listed in ipa.csv")
                deltas.setdefault(symbol, {})[row["feature"]] = parse_value(row["value"])

        diacritics = {}
        with open(os.path.join(directory, "diacritics.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                diacritics.setdefault(normalize(row["symbol"]), {})[row["feature"]] = parse_value(row["value"])

        resolved = {}
        def resolve(symbol, chain=()):
            if symbol in resolved:
                return resolved[symbol]
            if symbol in chain:
                raise PhonemeError(f"ipa.csv: base cycle {' → '.join(chain + (symbol,))}")
            if symbol not in bases:
                raise PhonemeError(f"ipa.csv: base {symbol!r} of {chain[-1]!r} is not defined")

            features = dict(resolve(bases[symbol], chain + (symbol,))) if bases[symbol] else {}
            features.update(deltas.get(symbol, {}))
            resolved[symbol] = features
            return features

        for symbol in bases:
            resolve(symbol)

        return cls(resolved, diacritics)

    def match(self, text, i):
        """Read one phoneme (plus any diacritics) from normalized text at i; returns (phoneme, end) or None."""
        # longest match first, so kʷ wins over k and h₁ over h
        for length in range(min(self.max_length, len(text) - i), 0, -1):
            symbol = text[i:i + length]
            if symbol in self.phonemes:
                break
        else:
            return None

        features = dict(self.phonemes[symbol])
        i += length
        while i < len(text) and text[i] in self.diacritics:
            symbol += text[i]
            features.update(self.diacritics[text[i]])
            i += 1

        return Phoneme(symbol, frozenset(features.items())), i

    def tokenize(self, text) -> list[Phoneme]:
        text = normalize(text)
        result = []
        i = 0
        while i < len(text):
            matched = self.match(text, i)
            if matched is None:
                raise PhonemeError(f"unknown symbol {text[i]!r} (U+{ord(text[i]):04X}) at position {i} in {text!r}")
            phoneme, i = matched
            result.append(phoneme)
        return result

@cache
def inventory():
    return Inventory.load()

def from_pie(text):
    """Convert conventional PIE notation (*ḱḗr, *septḿ̥, *gʷʰen-) to the IPA-based inventory."""
    text = normalize(text).strip("*-")
    text = re.sub("([kg])́", r"\1ʲ", text)         # acute on a velar marks a palatal: ḱ ǵ
    text = text.replace("̥", "̩")             # ring below marks a syllabic resonant: r̥ m̥
    text = re.sub("̄([̀-ͯ]*)", r"\1ː", text)  # macron marks length: ē → eː (keep accent on the vowel)
    text = text.replace("i̯", "j").replace("u̯", "w")  # i̯ u̯
    text = text.replace("y", "j")                       # PIE y is the glide [j]
    text = text.replace("ʰ", "ʱ")                       # PIE "aspirates" are breathy voiced
    return inventory().tokenize(text)

FEATURE_ORDER = ("type", "manner", "height", "place", "backness", "voice")

def describe_features(phoneme):
    features = dict(phoneme.features)
    ordered = [key for key in FEATURE_ORDER if key in features] + sorted(key for key in features if key not in FEATURE_ORDER)
    # boolean features read better as their name ("palatized") than as "True"
    return [key if features[key] is True else str(features[key]) for key in ordered if features[key] is not False]

def transcribe(phonemes):
    return "".join(str(phoneme) for phoneme in phonemes)
