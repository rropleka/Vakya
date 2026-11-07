import unittest

try:
    from textual.widgets import DataTable, Input, Static, Tree

    from vakya.tui import RulesScreen, VakyaApp
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
            self.assertIn("séks", str(app.nodes[2].label))
            self.assertIn("/sékʲs/", str(app.query_one("#phonemes", Static).render()))

            await pilot.press("enter", "down")          # into the tree, onto Proto-Germanic
            self.assertEqual(app.selected, 2)
            rows = cells(app.query_one("#steps", DataTable))
            self.assertEqual(rows[0][1], "ḱ → k")
            self.assertEqual(rows[0][2], "séḱs → séks")

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

    async def test_rules_screen(self):
        app = VakyaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("enter", "r")
            self.assertIsInstance(app.screen, RulesScreen)

            await pilot.press(*"p t k -> f θ x / _C")   # the test harness cannot type →
            detail = cells(app.screen.query_one("#rule-detail", DataTable))
            self.assertIn(["change", "t → θ"], detail)

            sources = app.screen.query_one("#sources", DataTable)
            statuses = [row[4] for row in cells(sources)]
            self.assertEqual(statuses.count("ok"), 4)
            self.assertIn("second arrow", statuses[3])

            await pilot.press("tab", "down", "down", "down", "enter")   # load the broken Debuccalization rule
            self.assertIn("second arrow", str(app.screen.query_one("#rule-error", Static).render()))

            await pilot.press("escape")
            self.assertNotIsInstance(app.screen, RulesScreen)

if __name__ == "__main__":
    unittest.main()
