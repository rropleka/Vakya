import contextlib
import io
import os
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

    def test_rules_check(self):
        code, out, _ = run("rules", "check", os.path.join(DATA_DIR, "sources", "proto-iranian-sample.txt"))
        self.assertEqual(code, 1)
        self.assertIn("4 parsed, 1 failed", out)
        self.assertIn("line 15 (Debuccalization)", out)

    def test_tree(self):
        code, out, _ = run("tree")
        self.assertEqual(code, 0)
        self.assertIn("└── Proto-Germanic", out)

    def test_derive(self):
        code, out, _ = run("derive", "*séḱs", "--to", "proto-germanic", "--steps")
        self.assertEqual(code, 0)
        self.assertIn("Proto-Germanic: séks", out)
        self.assertIn("séḱs → séks", out)

    def test_derive_unknown_language(self):
        code, _, err = run("derive", "*séḱs", "--to", "Klingon")
        self.assertEqual(code, 1)
        self.assertIn("no language 'Klingon'", err)

if __name__ == "__main__":
    unittest.main()
