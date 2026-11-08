import glob
import os
import unittest
from unittest import mock

from vakya import DATA_DIR, database, lexicon
from vakya.engine import Engine
from vakya.rules import load_rule_file

GERMANIC = ["pie-to-proto-germanic", "proto-germanic-to-west-germanic", "west-germanic-to-old-english",
            "old-english-to-middle-english", "middle-english-to-modern-english"]

def germanic_engine(connection):
    # only the Germanic rule files, so these tests don't depend on other branches being complete
    files = {}
    for name in GERMANIC:
        rule_file = load_rule_file(os.path.join(DATA_DIR, "rules", name + ".txt"))
        files[(rule_file.source.lower(), rule_file.target.lower())] = rule_file
    return Engine(connection, rule_files=files)

def by_language(stages):
    return {stage.language: stage for stage in stages.values()}

class LexiconTest(unittest.TestCase):
    def test_ascii_and_unicode_words_match(self):
        self.assertEqual(lexicon.word_key("ph2te:'r"), lexicon.word_key("*ph₂tḗr"))

    def test_father_data(self):
        self.assertEqual(lexicon.formation("*ph₂tḗr", "Prakrit").form, "pitu")
        self.assertEqual([a.form for a in lexicon.attested_forms("ph2te:'r", "Modern English")], ["father"])
        self.assertEqual(lexicon.attested_forms("*ph₂tḗr", "West Germanic"), [])

class AttestedTest(unittest.TestCase):
    def test_predicted_next_to_attested(self):
        with database.connect() as connection:
            stages = by_language(germanic_engine(connection).derive_all("ph2te:'r"))
        connection.close()
        self.assertTrue(stages["Proto-Germanic"].matches_attested)        # *fadēr
        self.assertTrue(stages["Old English"].matches_attested)           # fæder
        self.assertTrue(stages["Middle English"].matches_attested)        # fader
        modern = stages["Modern English"]
        self.assertEqual(modern.transcription, "féɪdər")                  # the regular outcome
        self.assertFalse(modern.matches_attested)                         # attested father is irregular
        self.assertIsNone(stages["West Germanic"].matches_attested)       # nothing attested

class FormationTest(unittest.TestCase):
    def test_formation_replaces_the_parents_output(self):
        # pretend Middle English continued a different Old English form of the word
        fake = {(lexicon.word_key("*ph₂tḗr"), "middle english"): lexicon.Formation("mōdor", "test")}
        with mock.patch.object(lexicon, "formations", return_value=fake):
            with database.connect() as connection:
                stages = by_language(germanic_engine(connection).derive_all("ph2te:'r"))
            connection.close()
        self.assertEqual(stages["Old English"].display, "fæder")
        self.assertEqual(stages["Middle English"].formation.form, "mōdor")
        self.assertEqual(stages["Middle English"].display, "moder")

    def test_unreadable_formation_falls_back(self):
        # Modern English has no spelling table to read a formation's form with... but its parent does;
        # West Germanic's parent table can't read "q"
        fake = {(lexicon.word_key("*ph₂tḗr"), "west germanic"): lexicon.Formation("qqq", "test")}
        with mock.patch.object(lexicon, "formations", return_value=fake):
            with database.connect() as connection:
                stages = by_language(germanic_engine(connection).derive_all("ph2te:'r"))
            connection.close()
        west = stages["West Germanic"]
        self.assertIsNone(west.formation)
        self.assertIn("not used", west.problem)
        self.assertEqual(west.display, "*fadēr")                          # the regular development

if __name__ == "__main__":
    unittest.main()
