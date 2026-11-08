import contextlib
import io
import os
import tempfile
import unittest

from vakya import DATA_DIR
from vakya.cli import main

def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()

class CliTest(unittest.TestCase):
    def test_parse(self):
        code, out, _ = run("parse", "*ḱḗr")
        self.assertEqual(code, 0)
        self.assertIn("/kʲéːr/", out)

    def test_parse_features(self):
        code, out, _ = run("parse", "-f", "*ḱḗr")
        self.assertIn("palatized", out)

    def test_parse_roots_file(self):
        code, out, _ = run("parse")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 12)

    def test_parse_error(self):
        code, _, err = run("parse", "--ipa", "q")
        self.assertEqual(code, 1)
        self.assertIn("unknown symbol 'q'", err)

    def test_rules_parse(self):
        code, out, _ = run("rules", "parse", "p t k → f θ x / _C")
        self.assertEqual(code, 0)
        self.assertIn("t → θ", out)
        self.assertIn("classes", out)

    def test_rules_parse_error(self):
        code, _, err = run("rules", "parse", "p → f → v")
        self.assertEqual(code, 1)
        self.assertIn("second arrow", err)

    def test_rules_check_rejects_other_files(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Spirantization: stops became fricatives\n    p t k → f θ x\n")
        self.addCleanup(os.unlink, f.name)
        code, _, err = run("rules", "check", f.name)
        self.assertEqual(code, 1)
        self.assertIn("not a rule file", err)

    def test_tree(self):
        code, out, _ = run("tree")
        self.assertEqual(code, 0)
        self.assertIn("├── Proto-Germanic", out)
        self.assertIn("└── Proto-Indo-Iranian", out)
        self.assertIn("pie-to-proto-germanic.txt", out)

    def test_father_demo(self):
        code, out, _ = run("derive", "ph2te:'r")
        self.assertEqual(code, 0)
        lines = {line.split()[0] + (" " + line.split()[1] if line.split()[1] == "English" else ""): line
                 for line in out.splitlines()[2:] if line.strip()}
        self.assertIn("✓ fæder", lines["Old English"])
        self.assertIn("✓ fader", lines["Middle English"])
        self.assertIn("≠ father", lines["Modern English"])        # the regular outcome is /féɪdər/
        self.assertIn("✓ pitā", lines["Sanskrit"])
        self.assertIn("continues pitu", lines["Prakrit"])
        self.assertIn("✓ piu", lines["Hindi"])

    def test_devanagari_is_opt_in(self):
        code, out, _ = run("derive", "ph2te:'r", "--to", "hindi")
        self.assertIn("Hindi               piu", out)
        code, out, _ = run("derive", "ph2te:'r", "--to", "hindi", "--script", "devanagari")
        self.assertIn("पिउ", out)
        self.assertIn("✓ piu", out)                               # compared in romanization

    def test_derive(self):
        code, out, _ = run("derive", "*séḱs", "--to", "proto-germanic", "--steps")
        self.assertEqual(code, 0)
        self.assertIn("Proto-Germanic: *sehs", out)
        self.assertIn("Centumization", out)
        self.assertIn("sékʲs → séks", out)
        self.assertIn("Grimm's law", out)

    def test_derive_spells_old_english(self):
        code, out, _ = run("derive", "ph2te:'r", "--to", "Old English")
        self.assertEqual(code, 0)
        self.assertIn("Proto-Germanic  *fadēr", out)
        self.assertIn("Old English     fæder", out)

    def test_derive_from_proto_germanic(self):
        code, out, _ = run("derive", "--from", "proto-germanic", "--to", "old english", "*stainaz")
        self.assertEqual(code, 0)
        self.assertIn("stān", out)

    def test_derive_to_middle_english(self):
        code, out, _ = run("derive", "ph2te:'r", "--to", "middle english")
        self.assertIn("Middle English  fader", out)

    def test_check_words(self):
        code, out, _ = run("check-words")
        self.assertIn("known exceptions", out)

    def test_rules_check_rule_files(self):
        code, out, _ = run("rules", "check", os.path.join(DATA_DIR, "rules", "pie-to-proto-germanic.txt"))
        self.assertEqual(code, 0)
        self.assertIn("Proto-Indo-European → Proto-Germanic", out)

    def test_derive_unknown_language(self):
        code, _, err = run("derive", "*séḱs", "--to", "Klingon")
        self.assertEqual(code, 1)
        self.assertIn("no language 'Klingon'", err)

if __name__ == "__main__":
    unittest.main()
