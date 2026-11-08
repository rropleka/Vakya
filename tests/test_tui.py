import unittest

try:
    from textual.widgets import DataTable, Input, Static, Tree

    from vakya.tui import HelpScreen, RulesScreen, VakyaApp
except ImportError:
    VakyaApp = None

def cells(table):
    return [[str(cell) for cell in table.get_row_at(i)] for i in range(table.row_count)]

@unittest.skipIf(VakyaApp is None, "Textual is not installed")
class TuiTest(unittest.IsolatedAsyncioTestCase):
    async def test_derivation_follows_typing_and_selection(self):
        app = VakyaApp("*séḱs")
        async with app.run_test(size=(120, 40)) as pilot:
            tree = app.query_one("#tree", Tree)
            self.assertIn("sehs", str(app.nodes[2].label))
            self.assertIn("/sékʲs/", str(app.query_one("#phonemes", Static).render()))

            await pilot.press("enter", "down")          # into the tree, onto Proto-Germanic
            self.assertEqual(app.selected, 2)
            rows = cells(app.query_one("#steps", DataTable))
            self.assertEqual(rows[1][1], "Centumization")
            self.assertEqual(rows[1][3], "sékʲs → séks")

            await pilot.press("f")                      # features view
            rows = cells(app.query_one("#steps", DataTable))
            self.assertEqual([row[0] for row in rows], ["s", "é", "kʲ", "s"])
            self.assertIn("palatized", rows[2][1])

    async def test_letter_shortcuts_type_into_the_word_box(self):
        app = VakyaApp("")
        async with app.run_test() as pilot:
            await pilot.press("q", "f", "r")
            self.assertEqual(app.query_one("#word", Input).value, "qfr")
            self.assertTrue(app.is_running)
            self.assertIn("unknown symbol 'q'", str(app.query_one("#phonemes", Static).render()))

    async def test_ascii_input_and_help(self):
        app = VakyaApp("")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press(*"se'k's")
            self.assertIn("*séḱs", str(app.query_one("#phonemes", Static).render()))
            self.assertIn("sehs", str(app.nodes[2].label))
            await pilot.press("enter", "f1")
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("escape")
            self.assertNotIsInstance(app.screen, HelpScreen)

    async def test_rules_screen(self):
        app = VakyaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("enter", "r")
            self.assertIsInstance(app.screen, RulesScreen)

            await pilot.press(*"p t k -> f θ x / _C")   # the test harness cannot type →
            detail = cells(app.screen.query_one("#rule-detail", DataTable))
            self.assertIn(["change", "t → θ"], detail)

            await pilot.press(*" -> h")                 # now two rules run together
            self.assertIn("second arrow", str(app.screen.query_one("#rule-error", Static).render()))

            sources = app.screen.query_one("#sources", DataTable)
            rows = cells(sources)
            centumization = next(i for i, row in enumerate(rows) if row[2] == "Centumization")
            await pilot.press("tab", *["down"] * centumization, "enter")   # load a rule from the rule files
            self.assertEqual(app.screen.query_one("#rule", Input).value, "kʲ gʲ gʲʱ → k g gʱ")
            self.assertIn(["change", "kʲ → k"], cells(app.screen.query_one("#rule-detail", DataTable)))

            await pilot.press("escape")
            self.assertNotIsInstance(app.screen, RulesScreen)

if __name__ == "__main__":
    unittest.main()
