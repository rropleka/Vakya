import os
import unittest

from vakya import DATA_DIR
from vakya.phonemes import inventory
from vakya.rule_parser import (Boundary, Choice, Class, Environment, Feature, Optional, RuleParseError, Segment,
                               format_rule, parse_rule)

def seg(text):
    [phoneme] = inventory().tokenize(text)
    return Segment(phoneme)

class ParseRuleTest(unittest.TestCase):
    def test_parallel_lists(self):
        rule = parse_rule("pʰ tʰ kʰ → f θ x")
        self.assertEqual(rule.target, ((seg("pʰ"),), (seg("tʰ"),), (seg("kʰ"),)))
        self.assertEqual(rule.replacement, ((seg("f"),), (seg("θ"),), (seg("x"),)))
        self.assertEqual(rule.environments, ())

    def test_class_environment(self):
        rule = parse_rule("p t k → f θ x / _C")
        self.assertEqual(rule.environments, (Environment((), (Class("C"),)),))

    def test_class_with_features(self):
        rule = parse_rule("C[+aspiration] → C[-aspiration]")
        self.assertEqual(rule.target, ((Class("C", (Feature("aspiration", True),)),),))
        self.assertEqual(rule.replacement, ((Class("C", (Feature("aspiration", False),)),),))

    def test_negated_environment_with_set(self):
        rule = parse_rule("s → h / × _{P, n}")
        self.assertEqual(rule.environments, (Environment((), (Choice(((Class("P"),), (seg("n"),))),), negated=True),))

    def test_feature_change_in_environment(self):
        rule = parse_rule("C[+dental] → C[+sibilant] / _C[+dental]")
        self.assertEqual(rule.environments[0].right, (Class("C", (Feature("dental", True),)),))

    def test_two_rules_run_together(self):
        with self.assertRaisesRegex(RuleParseError, "second arrow"):
            parse_rule("C[+aspiration] → C[-aspiration]s → h / × _{P, n}")

    def test_sequence_vs_parallel(self):
        self.assertEqual(parse_rule("tt → st").target, ((seg("t"), seg("t")),))
        self.assertEqual(len(parse_rule("t t → s s").target), 2)

    def test_multi_character_phonemes(self):
        self.assertEqual(parse_rule("kʷ → p").target, ((seg("kʷ"),),))
        self.assertEqual(parse_rule("h₂ → ∅ / V_V").target, ((seg("h₂"),),))

    def test_deletion_and_insertion(self):
        self.assertEqual(parse_rule("h₂ → ∅ / V_V").replacement, ((),))
        rule = parse_rule("∅ → e / #_s")
        self.assertEqual(rule.target, ((),))
        self.assertEqual(rule.environments, (Environment((Boundary("#"),), (seg("s"),)),))

    def test_set_at_start_of_environment(self):
        rule = parse_rule("s → ʂ / {r, i}_")
        self.assertIsInstance(rule.environments[0].left[0], Choice)

    def test_spaces_around_underscore(self):
        self.assertEqual(parse_rule("s → z / V _ V , # _ t"), parse_rule("s → z / V_V, #_t"))

    def test_arrow_and_null_spellings(self):
        for text in ("h₂ > Ø / V_V", "h₂ -> 0 / V_V", "h₂→∅/V_V"):
            self.assertEqual(parse_rule(text), parse_rule("h₂ → ∅ / V_V"), text)

    def test_braced_sets(self):
        rule = parse_rule("{p t k} → {f θ x}")
        self.assertEqual(rule.target, ((Choice(((seg("p"),), (seg("t"),), (seg("k"),))),),))

    def test_optional_multiple_environments_and_exceptions(self):
        rule = parse_rule("e → i / _(C)#, _j // s_")
        self.assertEqual(rule.environments, (Environment((), (Optional((Class("C"),)), Boundary("#"))),
                                             Environment((), (seg("j"),))))
        self.assertEqual(rule.exceptions, (Environment((seg("s"),), ()),))

    def test_features_after_a_set_apply_to_each_member(self):
        rule = parse_rule("{æ, i}[-stressed] → e")
        [[choice]] = rule.target
        self.assertEqual([option[0].features for option in choice.options],
                         [(Feature("stressed", False),), (Feature("stressed", False),)])
        with self.assertRaisesRegex(RuleParseError, "every member must be one sound"):
            parse_rule("{æt, i}[-stressed] → e")

    def test_feature_values(self):
        self.assertEqual(parse_rule("[backness=Near-front] → e").target[0][0].features,
                         (Feature("backness", "Near-front"),))
        rule = parse_rule("[manner=Stop +voice] → [manner=Fricative]")
        self.assertEqual(rule.target, ((Class(None, (Feature("manner", "Stop"), Feature("voice", True))),),))

    def test_errors(self):
        for text, message in [
            ("p t k → f θ", "3 targets but 2 replacements"),
            ("{p t k} → {f θ}", "set of 3 maps onto set of 2"),
            ("p → q", "unknown symbol 'q'"),
            ("p → f / _C_", "only one '_'"),
            ("p f", "expected '→'"),
            ("p → f / C[+voice", "unclosed '\\['"),
            ("p → f / C[voice]", "needs \\+, - or =value"),
            ("aː → æː / ! _N or if nasalized", "space inside an environment"),
            ("i o → e a / V _ V C", "space inside an environment"),
        ]:
            with self.assertRaisesRegex(RuleParseError, message, msg=text):
                parse_rule(text)

class FormatRuleTest(unittest.TestCase):
    def test_round_trip(self):
        for text in ["pʰ tʰ kʰ → f θ x", "p t k → f θ x / _C", "C[+aspiration] → C[-aspiration]",
                     "s → h / × _{P, n}", "h₂ → ∅ / V_V", "∅ → e / #_s", "e → i / _(C)#, _j // s_",
                     "[manner=Stop +voice] → [manner=Fricative]"]:
            self.assertEqual(format_rule(parse_rule(text)), text)
            self.assertEqual(parse_rule(format_rule(parse_rule(text))), parse_rule(text))

    def test_normalizes_spelling(self):
        self.assertEqual(format_rule(parse_rule("h₂>Ø/ V _ V")), "h₂ → ∅ / V_V")

if __name__ == "__main__":
    unittest.main()
