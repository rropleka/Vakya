import csv
import os
import tempfile
import unicodedata
import unittest

from vakya import DATA_DIR
from vakya.orthography import orthography
from vakya.phonemes import inventory, transcribe
from vakya.rules import Definitions, RuleError, compile_rule, load_rule_file

def definitions():
    d = Definitions()
    d.define_class("C", "[type=Consonant]")
    d.define_class("V", "[type=Vowel]")
    d.define_class("H", "{h₁, h₂, h₃}")
    d.define_feature(True, "dental", "[place=Alveolar]")
    d.define_feature(True, "sibilant", "[manner=Fricative]")
    return d

class ApplyTest(unittest.TestCase):
    def assertApplies(self, rule, word, expected):
        result = compile_rule(rule, definitions()).apply(inventory().tokenize(word))
        self.assertEqual(transcribe(result), expected, f"{rule} on {word}")

    def test_parallel_changes(self):
        self.assertApplies("p t k → f θ x", "pətk", "fəθx")
        self.assertApplies("{p t k} → {f θ x}", "kapt", "xafθ")

    def test_environments(self):
        self.assertApplies("p t k → f θ x / _C", "apta", "afta")
        self.assertApplies("p t k → f θ x / _C", "apa", "apa")
        self.assertApplies("s → h / #_", "sas", "has")
        self.assertApplies("e → i / _(C)i", "eti", "iti")
        self.assertApplies("e → i / _(C)i", "ei", "ii")
        self.assertApplies("æ → æɑ / _{rC, lC, h}", "ærm", "æɑrm")

    def test_negation_and_exceptions(self):
        self.assertApplies("s → h / × _{t, n}", "stas", "stah")
        self.assertApplies("p t k → f θ x // s_", "spat", "spaθ")

    def test_feature_changes(self):
        self.assertApplies("C[+dental] → C[+sibilant] / _C[+dental]", "atta", "asta")
        self.assertApplies("C[+dental] → C[+sibilant] / _C[+dental]", "adta", "azta")
        self.assertApplies("VH → V[+long] / _C, _#", "meh₂", "meː")

    def test_stress_rides_along(self):
        self.assertApplies("VH → V[+long] / _C, _#", "méh₂ter", "méːter")
        self.assertApplies("e → a / h₂_", "h₂ént", "h₂ánt")
        self.assertApplies("r̩ l̩ m̩ n̩ → ur ul um un", "ḿ̩tom", "úmtom")
        self.assertApplies("s → z / V[-stressed]_V", "ásasa", "ásaza")
        self.assertApplies("V → V[+stressed] / #(C)(C)(C)_", "pəter", "pə́ter")

    def test_insertion_deletion_doubling(self):
        self.assertApplies("∅ → e / #_s", "st", "est")
        self.assertApplies("h₂ → ∅", "ph₂ter", "pter")
        self.assertApplies("C → CC / V_j", "satja", "sattja")

    def test_simultaneous(self):
        # environments see the word as it was before the rule, so each s is judged on the original
        self.assertApplies("s → z / V_V", "asasa", "azaza")

    def test_compile_errors(self):
        for rule, message in [("p → f / _X", "class X is not defined"),
                              ("[+voice] → f", "not a \\+/- feature"),
                              ("[place=Dentl] → f", "has no value 'Dentl'"),
                              ("[+nasality] → f", "unknown feature 'nasality'"),
                              ("p → {f v}", "replacement can only contain"),
                              ("#p → f", "boundary"),
                              ("p → fC[+long]", "no matching sound")]:
            with self.assertRaisesRegex(RuleError, message, msg=rule):
                compile_rule(rule, definitions())

    def test_conditioned_sounds(self):
        self.assertApplies("e[-stressed] → i // _r", "βéreθe", "βériθi")
        self.assertApplies("V[-stressed]n → V[+nasal] / _#", "húnðɑn", "húnðɑ̃")
        self.assertApplies("V[+long] → V[+overlong] / _#", "seːmoː", "seːmô")

class AsciiInputTest(unittest.TestCase):
    def test_conversions(self):
        from vakya.phonemes import ascii_to_pie
        for typed, pie in [("se'k's", "séḱs"), ("ph2te:'r", "ph₂tḗr"), ("k'Mto'm", "ḱm̥tóm"), ("g'ho'stis", "ǵʰóstis"),
                           ("kwo'd", "kʷód"), ("e'k'wos", "éḱwos"), ("septM'", "septḿ̥"), ("sno'ygwhos", "snóygʷʰos"),
                           ("k'e':r", "ḱḗr"), ("k'e:'r", "ḱḗr"), ("k.wo", "kwo"),
                           ("dhugh2te:'r", "dʰugh₂tḗr")]:          # gh before a digit is g + laryngeal
            self.assertEqual(ascii_to_pie(typed), unicodedata.normalize("NFC", pie), typed)

    def test_unicode_passes_through(self):
        from vakya.phonemes import ascii_to_pie
        with open(os.path.join(DATA_DIR, "test_words.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.assertEqual(ascii_to_pie(row["pie"]), unicodedata.normalize("NFC", row["pie"]))

class PhonemeForTest(unittest.TestCase):
    def test_builds_symbols_from_features(self):
        inv = inventory()
        def changed(symbol, **features):
            return str(inv.phoneme_for({**inv.phonemes[symbol], **features}))
        self.assertEqual(changed("k", labialized=True), "kʷ")
        self.assertEqual(changed("t", manner="Fricative"), "s")
        self.assertEqual(changed("o", long=True, stressed=True), "óː")

class RuleFileTest(unittest.TestCase):
    def load(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.unlink, f.name)
        return load_rule_file(f.name)

    def test_loads_definitions_and_rules(self):
        rule_file = self.load("""# a comment
from: A
to: B

class C = [type=Consonant]
feature +dental = [place=Alveolar]

Spirantization: Stops become fricatives
before consonants.
    p t k → f θ x / _C
    C[+dental] → s / _#
""")
        self.assertEqual((rule_file.source, rule_file.target), ("A", "B"))
        self.assertEqual(rule_file.errors, [])
        self.assertEqual([entry.line for entry in rule_file.entries], [10, 11])
        self.assertEqual(rule_file.entries[0].name, "Spirantization")
        self.assertEqual(rule_file.entries[0].description, "Stops become fricatives before consonants.")

    def test_collects_errors_with_lines(self):
        rule_file = self.load("""from: A
to: B
    p → f
Broken: uses an undefined class
    p → f / _C
Fine: still loads after errors
    s → h
""")
        self.assertEqual([line for line, _ in rule_file.errors], [3, 5])
        self.assertIn("without a 'Name: description' heading", rule_file.errors[0][1])
        self.assertIn("class C is not defined", rule_file.errors[1][1])
        self.assertEqual([entry.text for entry in rule_file.entries], ["s → h"])

    def test_missing_header(self):
        rule_file = self.load("Fine: x\n    s → h\n")
        self.assertIn("missing 'from:' or 'to:'", rule_file.errors[-1][1])

class OrthographyTest(unittest.TestCase):
    def test_old_english(self):
        oe = orthography("Old English")
        for phonemes, spelling in [("fæder", "fæder"), ("broːθor", "brōþor"), ("jeok", "ġeoc"), ("ætːa", "ætta"),
                                   ("æːɑd", "ēad"), ("kʷæt", "cwæt"), ("ʃip", "sċip"), ("fǽder", "fæder")]:
            self.assertEqual(oe.spell(inventory().tokenize(phonemes)), spelling)

    def test_proto_germanic(self):
        pg = orthography("Proto-Germanic")
        for phonemes, spelling in [("hunðɑ̃", "hundą"), ("ɸɑðeːr", "fadēr"), ("seːmɔ̂", "sēmô"), ("xʷɑt", "hwat")]:
            self.assertEqual(pg.spell(inventory().tokenize(phonemes)), spelling)

    def test_reading(self):
        pg = orthography("Proto-Germanic")
        for written, phonemes in [("*fadēr", "ɸɑðeːr"), ("stainaz", "stɑinɑz"), ("kunją", "kunjɑ̃"), ("hwat", "xʷɑt")]:
            self.assertEqual(transcribe(pg.read(written)), unicodedata.normalize("NFC", phonemes))

    def test_spelling_contexts(self):
        me = orthography("Middle English")
        for phonemes, spelling in [("werk", "werk"), ("aːkər", "aker"), ("kat", "cat"), ("knɪ", None),
                                   ("ɔːn", "oon"), ("bloːmə", "blome"), ("doːm", "doom"), ("snɔːw", "snow")]:
            if spelling:
                self.assertEqual(me.spell(inventory().tokenize(phonemes)), spelling, phonemes)

    def test_bad_context_is_reported(self):
        from vakya.orthography import Orthography, OrthographyError
        with self.assertRaisesRegex(OrthographyError, "bad context"):
            Orthography("Test", [("k", "k", True, "_X")])

    def test_languages_without_a_table(self):
        self.assertIsNone(orthography("Modern English"))

if __name__ == "__main__":
    unittest.main()
