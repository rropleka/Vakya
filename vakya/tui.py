import glob
import os

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree

from . import DATA_DIR, database, engine
from .phonemes import PhonemeError, describe_features, from_pie, transcribe
from .rule_parser import RuleParseError, describe_rule, parse_rule, parse_source

SOURCES_DIR = os.path.join(DATA_DIR, "sources")

# all cell text goes through Text() so rule notation like C[+dental] isn't read as Rich markup
def plain(text, style=""):
    return Text(str(text), style=style)

class RulesScreen(Screen):
    """Type a rule to see how it parses, or pick one from the sources to load it."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="rule, e.g. p t k → f θ x / _C", id="rule")
        yield Static(id="rule-error")
        yield DataTable(id="rule-detail", show_header=False, cursor_type="none")
        yield Static(plain("Sources  (enter loads a rule above)", "bold"), classes="heading")
        yield DataTable(id="sources", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        self.sub_title = "Rules"
        detail = self.query_one("#rule-detail", DataTable)
        detail.add_columns("", "")
        detail.can_focus = False        # display only; Tab should go straight to the sources

        sources = self.query_one("#sources", DataTable)
        sources.add_columns("File", "Line", "Name", "Rule", "Status")
        self.source_rules = []
        for path in sorted(glob.glob(os.path.join(SOURCES_DIR, "*.txt"))):
            with open(path, encoding="utf-8") as f:
                rules, errors = parse_source(f.read())
            results = [(entry, None) for entry, _ in rules] + list(errors)
            for entry, error in sorted(results, key=lambda result: result[0].line):
                status = plain("ok", "green") if error is None else plain(error.message, "red")
                sources.add_row(plain(os.path.basename(path)), plain(entry.line), plain(entry.name),
                                plain(entry.rule_text), status, key=str(len(self.source_rules)))
                self.source_rules.append(entry.rule_text)

        self.query_one("#rule", Input).focus()

    def on_input_changed(self, event: Input.Changed):
        detail = self.query_one("#rule-detail", DataTable)
        error = self.query_one("#rule-error", Static)
        detail.clear()
        error.update("")
        if not event.value.strip():
            return
        try:
            rule = parse_rule(event.value)
        except RuleParseError as parse_error:
            error.update(plain(parse_error, "red"))
            return
        for label, text in describe_rule(rule):
            detail.add_row(plain(label, "bold"), plain(text))

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "sources":
            rule = self.query_one("#rule", Input)
            rule.value = self.source_rules[int(event.row_key.value)]
            rule.focus()

class VakyaApp(App):
    TITLE = "Vakya"
    CSS = """
    #word { margin: 0 1; }
    #phonemes { height: auto; padding: 0 2 1 2; }
    #main { height: 1fr; }
    #tree { width: 2fr; border: round $primary; }
    #detail { width: 3fr; border: round $primary; }
    #detail-title { padding: 0 1; text-style: bold; }
    #rule { margin: 0 1; }
    #rule-error { height: auto; padding: 0 2; }
    #rule-detail { height: auto; max-height: 12; margin: 0 1 1 1; }
    .heading { padding: 0 1; }
    #sources { height: 1fr; margin: 0 1; }
    """
    BINDINGS = [
        Binding("f", "toggle_features", "Features"),
        Binding("r", "rules", "Rules"),
        Binding("escape", "focus_word", "Edit word"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, word="*séḱs"):
        super().__init__()
        self.word = word
        self.show_features = False
        self.selected = None
        self.results = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(value=self.word, placeholder="PIE word, e.g. *séḱs  (enter: browse descendants)", id="word")
        yield Static(id="phonemes")
        with Horizontal(id="main"):
            yield Tree("", id="tree")
            with Vertical(id="detail"):
                yield Static(id="detail-title")
                yield DataTable(id="steps", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        self.connection = database.connect()
        self.languages = {row[0]: row for row in database.languages(self.connection)}
        self.rule_counts = database.rule_counts(self.connection)

        tree = self.query_one("#tree", Tree)
        tree.show_root = False
        self.nodes = {}
        for id, name, parent, type in self.languages.values():   # parents come before children
            parent_node = self.nodes[parent] if parent is not None else tree.root
            self.nodes[id] = parent_node.add(name, data=id, expand=True)
        tree.root.expand()

        self.selected = next(iter(self.languages))
        self.update_word(self.word)
        self.query_one("#word", Input).focus()

    def on_unmount(self):
        self.connection.close()

    def node_label(self, id, form):
        name = self.languages[id][1]
        label = Text.assemble((name, "bold"), "  ", (form, "green"))
        if self.languages[id][2] is not None:
            count = self.rule_counts.get(id, 0)
            label.append(f"  {count} rule{'s' if count != 1 else ''}", style="dim")
        return label

    def update_word(self, word):
        self.word = word
        phonemes = self.query_one("#phonemes", Static)
        if not word.strip():
            phonemes.update(plain("type a PIE word", "dim"))
        else:
            try:
                parsed = from_pie(word)
                phonemes.update(Text.assemble((f"/{transcribe(parsed)}/", "bold"), "   ",
                                              ("  ".join(map(str, parsed)), "")))
            except PhonemeError as error:
                phonemes.update(plain(error, "red"))

        for id in self.languages:
            self.results[id] = engine.derive(self.connection, word, id)
            self.nodes[id].set_label(self.node_label(id, self.results[id][0]))
        self.update_detail()

    def update_detail(self):
        title = self.query_one("#detail-title", Static)
        table = self.query_one("#steps", DataTable)
        table.clear(columns=True)

        if self.show_features:
            title.update(plain(f"Phonemes of {self.word}"))
            table.add_columns("Phoneme", "Features")
            try:
                for phoneme in from_pie(self.word):
                    table.add_row(plain(phoneme, "bold"), plain("  ".join(describe_features(phoneme))))
            except PhonemeError as error:
                table.add_row(plain("error", "red"), plain(error.args[0] if error.args else error))
            return

        id = self.selected
        form, steps = self.results.get(id, (self.word, []))
        title.update(Text.assemble("Derivation: ", (self.languages[id][1], "bold"), "  ", (form, "green")))
        table.add_columns("Stage", "Change", "Result", "Description")
        if self.languages[id][2] is None:
            table.add_row(plain("input"), plain(""), plain(form), plain("the word as typed"))
        elif not steps:
            table.add_row(plain("(no changes)", "dim"), plain(""), plain(form), plain(""))
        for step in steps:
            table.add_row(plain(step.language), plain(f"{step.in_regex} → {step.out_regex}"),
                          plain(f"{step.before} → {step.after}"), plain(step.description))

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "word":
            self.update_word(event.value)

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "word":
            self.query_one("#tree", Tree).focus()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted):
        if event.node.data is not None:
            self.selected = event.node.data
            if not self.show_features:
                self.update_detail()

    def check_action(self, action, parameters):
        # single-letter shortcuts would swallow typing, so they only apply outside the text box
        if action in ("toggle_features", "rules", "quit") and isinstance(self.focused, Input):
            return False
        return True

    def action_toggle_features(self):
        self.show_features = not self.show_features
        self.update_detail()

    def action_rules(self):
        self.push_screen(RulesScreen())

    def action_focus_word(self):
        self.query_one("#word", Input).focus()

def run(word="*séḱs"):
    VakyaApp(word).run()
