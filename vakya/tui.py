import glob
import os

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree

from . import DATA_DIR, database
from .engine import Engine
from .orthography import OrthographyError, orthography
from .phonemes import ASCII_PIE, PhonemeError, ascii_to_pie, describe_features, from_pie, transcribe
from .rule_parser import RuleParseError, describe_rule, parse_rule
from .rules import RULES_DIR, RuleError, load_rule_file


# all cell text goes through Text() so rule notation like C[+dental] isn't read as Rich markup
def plain(text, style=""):
    return Text(str(text), style=style)

class RulesScreen(Screen):
    """Type a rule to see how it parses, or pick one from the rule files to load it."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="rule, e.g. p t k → f θ x / _C", id="rule")
        yield Static(id="rule-error")
        yield DataTable(id="rule-detail", show_header=False, cursor_type="none")
        yield Static(plain("Rule files  (enter loads a rule above)", "bold"), classes="heading")
        yield DataTable(id="sources", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        self.sub_title = "Rules"
        detail = self.query_one("#rule-detail", DataTable)
        detail.add_columns("", "")
        detail.can_focus = False        # display only; Tab should go straight to the rule files

        sources = self.query_one("#sources", DataTable)
        sources.add_columns("File", "Line", "Name", "Rule", "Status")
        self.source_rules = []
        def add(path, line, name, text, error):
            status = plain("ok", "green") if error is None else plain(error.splitlines()[0], "red")
            sources.add_row(plain(os.path.relpath(path, DATA_DIR)), plain(line), plain(name), plain(text), status,
                            key=str(len(self.source_rules)))
            self.source_rules.append(text)

        for path in sorted(glob.glob(os.path.join(RULES_DIR, "*.txt"))):
            rule_file = load_rule_file(path)
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            results = [(entry.line, entry.name, entry.text, None) for entry in rule_file.entries]
            results += [(line, "", lines[line - 1].strip() if line <= len(lines) else "", message)
                        for line, message in rule_file.errors]
            for line, name, text, error in sorted(results):
                add(path, line, name, text, error)


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

class HelpScreen(Screen):
    """How to type PIE on an ordinary keyboard."""

    BINDINGS = [Binding("escape,f1,q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(plain("Typing PIE without diacritics", "bold"), classes="heading")
        yield DataTable(id="ascii", cursor_type="none")
        yield Static(plain("Examples:  se'k's → séḱs    ph2te:'r → ph₂tḗr    k'Mto'm → ḱm̥tóm    g'ho'stis → ǵʰóstis\n"
                           "Words typed with real diacritics work too. gh followed by 1-3 stays g + laryngeal (dhugh2te:'r)."),
                     classes="heading")
        yield Footer()

    def on_mount(self):
        self.sub_title = "Help"
        table = self.query_one("#ascii", DataTable)
        table.add_columns("Type", "Get", "")
        for typed, pie, description in ASCII_PIE:
            table.add_row(plain(typed, "bold"), plain(pie), plain(description, "dim"))

class VakyaApp(App):
    TITLE = "Vakya"
    CSS = """
    #word { margin: 0 1; }
    #phonemes { height: auto; padding: 0 2 1 2; }
    #status { height: auto; padding: 0 2 1 2; }
    #main { height: 1fr; }
    #tree { width: 2fr; border: round $primary; }
    #detail { width: 3fr; border: round $primary; }
    #detail-title { padding: 0 1; text-style: bold; }
    #rule { margin: 0 1; }
    #rule-error { height: auto; padding: 0 2; }
    #rule-detail { height: auto; max-height: 12; margin: 0 1 1 1; }
    .heading { padding: 0 1; }
    #sources { height: 1fr; margin: 0 1; }
    #ascii { height: auto; margin: 1 2; }
    """
    BINDINGS = [
        Binding("f", "toggle_features", "Features"),
        Binding("r", "rules", "Rules"),
        Binding("l", "reload", "Reload rules"),
        Binding("f1", "help", "Typing help"),
        Binding("escape", "focus_word", "Edit word"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, word="*séḱs"):
        super().__init__()
        self.word = word
        self.show_features = False
        self.selected = None
        self.stages = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(value=self.word, placeholder="PIE word: diacritics or ASCII, e.g. se'k's  (F1: how to type)", id="word")
        yield Static(id="phonemes")
        yield Static(id="status")
        with Horizontal(id="main"):
            yield Tree("", id="tree")
            with Vertical(id="detail"):
                yield Static(id="detail-title")
                yield DataTable(id="steps", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        self.connection = database.connect()
        self.load_engine()

        tree = self.query_one("#tree", Tree)
        tree.show_root = False
        self.nodes = {}
        for id, name, parent, type in self.engine.languages.values():   # parents come before children
            parent_node = self.nodes[parent] if parent is not None else tree.root
            self.nodes[id] = parent_node.add(name, data=id, expand=True)
        tree.root.expand()

        self.selected = next(iter(self.engine.languages))
        self.update_word(self.word)
        self.query_one("#word", Input).focus()

    def load_engine(self):
        # a broken rule file shouldn't stop the browser: show the error and derive without any rules
        status = self.query_one("#status", Static)
        orthography.cache_clear()
        try:
            self.engine = Engine(self.connection)
            status.update("")
            status.display = False
        except RuleError as error:
            self.engine = Engine(self.connection, rule_files={})
            status.update(plain(f"{error}\n(deriving without rules; fix the files and press l)", "red"))
            status.display = True

    def on_unmount(self):
        self.connection.close()

    @property
    def languages(self):
        return self.engine.languages

    @staticmethod
    def form(stage):
        try:
            return plain(stage.display, "green")
        except OrthographyError:
            return plain(f"/{stage.transcription}/", "yellow")

    def node_label(self, id):
        label = Text.assemble((self.languages[id][1], "bold"), "  ")
        if id in self.stages and self.languages[id][2] is None:
            pie = ascii_to_pie(self.word.strip())       # the root shows the word in PIE notation
            label.append(pie if pie.startswith("*") else "*" + pie, style="green")
        elif id in self.stages:
            stage = self.stages[id]
            label.append_text(self.form(stage))
            if stage.attested:
                forms = ", ".join(attested.form for attested in stage.attested)
                label.append(f"  ✓ {forms}" if stage.matches_attested else f"  ≠ {forms}",
                             style="green" if stage.matches_attested else "yellow")
        else:
            label.append("?", style="red")
        if self.languages[id][2] is not None:
            rule_file = self.engine.rule_file(id)
            count = len(rule_file.entries) if rule_file else 0
            label.append(f"  {count} rule{'s' if count != 1 else ''}", style="dim")
        return label

    def update_word(self, word):
        self.word = word
        phonemes = self.query_one("#phonemes", Static)
        self.stages = {}
        if not word.strip():
            phonemes.update(plain("type a PIE word", "dim"))
        else:
            try:
                parsed = from_pie(word)
                pie = ascii_to_pie(word.strip())
                pie = pie if pie.startswith("*") else "*" + pie
                phonemes.update(Text.assemble((pie, "bold green"), "   ", (f"/{transcribe(parsed)}/", "bold"), "   ",
                                              ("  ".join(map(str, parsed)), "")))
                self.stages = self.engine.derive_all(word)
            except PhonemeError as error:
                phonemes.update(plain(error, "red"))

        for id in self.languages:
            self.nodes[id].set_label(self.node_label(id))
        self.update_detail()

    def update_detail(self):
        title = self.query_one("#detail-title", Static)
        table = self.query_one("#steps", DataTable)
        table.clear(columns=True)

        if self.show_features:
            title.update(plain(f"Phonemes of {ascii_to_pie(self.word)}"))
            table.add_columns("Phoneme", "Features")
            try:
                for phoneme in from_pie(self.word):
                    table.add_row(plain(phoneme, "bold"), plain("  ".join(describe_features(phoneme))))
            except PhonemeError as error:
                table.add_row(plain("error", "red"), plain(error.args[0] if error.args else error))
            return

        id = self.selected
        title.update(Text.assemble("Derivation: ", (self.languages[id][1], "bold")))
        table.add_columns("Stage", "Rule", "Change", "Result")
        if id not in self.stages:
            return

        stage = self.stages[id]
        if self.languages[id][2] is None:
            pie = ascii_to_pie(self.word.strip())
            shown = plain(pie if pie.startswith("*") else "*" + pie, "green")
        else:
            shown = self.form(stage)
        attested = ""
        if stage.attested:
            attested = ("  attested ✓ " if stage.matches_attested else "  attested ≠ ") + \
                       ", ".join(a.form for a in stage.attested)
        title.update(Text.assemble("Derivation: ", (self.languages[id][1], "bold"), "  ", shown,
                                   (f"  /{stage.transcription}/", "dim"), (attested, "yellow")))
        # walk up to the root so the whole derivation shows, oldest change first
        lineage = []
        while id is not None:
            lineage.append(self.stages[id])
            id = self.languages[id][2]
        lineage.reverse()

        table.add_row(plain(lineage[0].language), plain("input", "dim"), plain(""), plain(lineage[0].transcription))
        for stage in lineage[1:]:
            if stage.formation:
                table.add_row(plain(stage.language), plain("formation", "yellow"), plain(stage.formation.form),
                              plain(stage.formation.note))
            if stage.problem:
                table.add_row(plain(stage.language), plain("formation not used", "red"), plain(""), plain(stage.problem))
            for step in stage.steps:
                table.add_row(plain(stage.language), plain(step.name), plain(step.rule),
                              plain(f"{transcribe(step.before)} → {transcribe(step.after)}"))
            if not stage.steps and not stage.formation:
                table.add_row(plain(stage.language), plain("(no changes)", "dim"), plain(""),
                              plain(stage.transcription))

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
        if action in ("toggle_features", "rules", "reload", "quit") and isinstance(self.focused, Input):
            return False
        return True

    def action_toggle_features(self):
        self.show_features = not self.show_features
        self.update_detail()

    def action_reload(self):
        self.load_engine()
        self.update_word(self.word)
        self.notify("Rules reloaded")

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_rules(self):
        self.push_screen(RulesScreen())

    def action_focus_word(self):
        self.query_one("#word", Input).focus()

def run(word="*séḱs"):
    VakyaApp(word).run()
