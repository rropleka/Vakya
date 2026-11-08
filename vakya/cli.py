import argparse
import csv
import os
import sqlite3
import sys
import unicodedata

from . import DATA_DIR, DB_PATH, database
from .engine import Engine
from .orthography import OrthographyError
from .phonemes import ASCII_PIE, PhonemeError, ascii_to_pie, describe_features, from_pie, inventory, transcribe
from .rule_parser import RuleParseError, describe_rule, parse_rule
from .rules import RuleError, is_rule_file, load_rule_file

ROOTS_FILE = os.path.join(DATA_DIR, "Proto-Indo-European", "roots.txt")
TEST_WORDS = os.path.join(DATA_DIR, "test_words.csv")

ASCII_HELP = "PIE words can be typed in ASCII; put them in double quotes in the shell:\n" + "\n".join(
    f"  {typed:16} {pie:12} {description}" for typed, pie, description in ASCII_PIE) + \
    "\n  e.g. vakya derive \"se'k's\"   (= *séḱs)"

class CommandError(Exception):
    pass

def width(text):
    # combining marks take no column on screen, so len() overcounts ḿ̥ and friends
    return sum(1 for c in unicodedata.normalize("NFD", str(text)) if not unicodedata.combining(c))

def pad(text, size):
    return str(text) + " " * max(0, size - width(text))

def table(rows, headers=None, indent=""):
    rows = [[str(cell) for cell in row] for row in rows]
    if headers:
        rows.insert(0, list(headers))
    if not rows:
        return
    sizes = [max(width(row[i]) for row in rows if i < len(row)) for i in range(max(map(len, rows)))]
    for row in rows:
        print(indent + "  ".join(pad(cell, size) for cell, size in zip(row, sizes)).rstrip())

def cmd_parse(args):
    words = args.words
    if not words:
        with open(ROOTS_FILE, encoding="utf-8") as f:
            words = [line.strip() for line in f if line.strip()]

    failed = False
    rows = []
    for word in words:
        try:
            phonemes = inventory().tokenize(word) if args.ipa else from_pie(word)
        except PhonemeError as error:
            print(f"{word}: {error}", file=sys.stderr)
            failed = True
            continue

        if not args.ipa:
            word = ascii_to_pie(word)
        if args.features:
            print(f"{word}  /{transcribe(phonemes)}/")
            table([[phoneme, *describe_features(phoneme)] for phoneme in phonemes], indent="  ")
            print()
        else:
            rows.append([word, f"/{transcribe(phonemes)}/", " ".join(map(str, phonemes))])
    table(rows)
    return 1 if failed else 0

def show_rule(rule, indent=""):
    table(describe_rule(rule), indent=indent)

def cmd_rules_parse(args):
    show_rule(parse_rule(args.rule))
    return 0

def cmd_rules_check(args):
    failed = False
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            text = f.read()

        if not is_rule_file(text):
            raise CommandError(f"{path}: not a rule file (it needs 'from:' and 'to:' lines; see vakya/rules.py)")

        # also checks class and feature names against the file's definitions
        rule_file = load_rule_file(path)
        rules = len(rule_file.entries)
        errors = len(rule_file.errors)
        print(f"{path}: {rule_file.source} → {rule_file.target}, "
              f"{rules} rule{'s' if rules != 1 else ''}, {errors} error{'s' if errors != 1 else ''}")
        if args.verbose:
            for entry in rule_file.entries:
                print(f"\n  line {entry.line}: {entry.name}")
                show_rule(entry.rule.rule, indent="    ")
            if rule_file.errors:
                print()
        for line, message in rule_file.errors:
            message = message.replace("\n", "\n  ")
            print(f"  line {line}: {message}")
        failed = failed or bool(rule_file.errors)
    return 1 if failed else 0

def cmd_tree(args):
    with database.connect() as connection:
        engine = Engine(connection)
    connection.close()

    children = {}
    for row in engine.languages.values():
        children.setdefault(row[2], []).append(row)

    lines = []
    def walk(row, prefix, last, root):
        id, name, parent, type = row
        branch = "" if root else ("└── " if last else "├── ")
        rule_file = engine.rule_file(id)
        if root:
            rules = ""
        elif rule_file is None:
            rules = "no rule file"
        else:
            count = len(rule_file.entries)
            rules = f"{count} rule{'s' if count != 1 else ''}  {os.path.relpath(rule_file.path, DATA_DIR)}"
        lines.append([prefix + branch + name, type, rules])
        kids = children.get(id, [])
        for i, child in enumerate(kids):
            walk(child, prefix + ("" if root else ("    " if last else "│   ")), i == len(kids) - 1, False)

    for root in children.get(None, []):
        walk(root, "", True, True)
    table(lines)
    return 0

def form(stage):
    """A stage's form for display, and a note when it can't be spelled yet."""
    try:
        return stage.display, ""
    except OrthographyError as error:
        return f"/{stage.transcription}/", f"can't spell: {str(error).split(';')[0].removeprefix('no ')}"

def attested_column(stage):
    """The attested form(s) with ✓ when the prediction matches and ≠ when it doesn't."""
    if not stage.attested:
        return ""
    forms = ", ".join(attested.form for attested in stage.attested)
    return ("✓ " if stage.matches_attested else "≠ ") + forms

def notes(stage, note=""):
    result = [note] if note else []
    if stage.formation:
        result.append(f"continues {stage.formation.form} ({stage.formation.note})" if stage.formation.note
                      else f"continues {stage.formation.form}")
    if stage.problem:
        result.append(stage.problem)
    return "; ".join(result)

def show_steps(stage, indent):
    rows = [["(formation)", stage.formation.form, stage.formation.note]] if stage.formation else []
    rows += [[step.name, step.rule, f"{transcribe(step.before)} → {transcribe(step.after)}"] for step in stage.steps]
    table(rows or [["(no change)"]], indent=indent)

def cmd_derive(args):
    with database.connect() as connection:
        engine = Engine(connection, script=args.script)
        def language(key):
            row = database.find_language(connection, key)
            if row is None:
                names = ", ".join(row[1] for row in engine.languages.values())
                raise CommandError(f"no language {key!r}; known languages: {names}")
            return row

        target = language(args.to) if args.to else None
        source = language(args.source) if args.source else None
        if source and not target:
            raise CommandError("--from needs --to")

        for n, word in enumerate(args.words):
            if n:
                print()
            pie = ascii_to_pie(word) if not source or source[2] is None else word
            print(pie if pie.startswith("*") else "*" + pie)
            if target:
                stages = engine.derive(pie, target[0], source[0] if source else None)[1:]
            else:
                stages = [stage for stage in engine.derive_all(word).values()
                          if engine.languages[stage.language_id][2] is not None]

            rows = []
            for stage in stages:
                shown, note = form(stage)
                if args.steps:
                    table(rows, indent="  ")
                    rows = []
                    attested = attested_column(stage)
                    print(f"  {stage.language}: {shown}  /{stage.transcription}/"
                          + (f"  attested {attested}" if attested else "") + (f"  {notes(stage, note)}" if notes(stage, note) else ""))
                    show_steps(stage, indent="      ")
                else:
                    rows.append([stage.language, shown, f"/{stage.transcription}/", attested_column(stage), notes(stage, note)])
            if rows and any(row[3] for row in rows):
                table(rows, ["", "predicted", "", "attested", ""], indent="  ")
            else:
                table([[row[0], row[1], row[2], row[4]] for row in rows], indent="  ")
    connection.close()
    return 0

def cmd_check_words(args):
    """
    Each row gives the reconstructed or attested form (expected) and, when analogy or another irregular
    change made it differ from what the sound laws give, the regular outcome. Deriving the regular form
    counts as a known exception, not a failure.
    """
    with open(args.file, encoding="utf-8") as f:
        words = [row for row in csv.DictReader(f) if row["pie"].strip()]

    nfc = lambda text: unicodedata.normalize("NFC", text or "")
    with database.connect() as connection:
        engine = Engine(connection)
        rows = []
        counts = {"✓": 0, "≈": 0, "✗": 0}
        for row in words:
            language = database.find_language(connection, row["language"])
            if language is None:
                raise CommandError(f"{args.file}: no language {row['language']!r}")
            source = database.find_language(connection, row["from"]) if row.get("from") else None
            if row.get("from") and source is None:
                raise CommandError(f"{args.file}: no language {row['from']!r}")
            try:
                got, note = form(engine.derive(row["pie"], language[0], source[0] if source else None)[-1])
            except (PhonemeError, OrthographyError) as error:
                got, note = "", f"error: {error}"

            if nfc(got) == nfc(row["expected"]):
                mark = "✓"
            elif row.get("regular") and nfc(got) == nfc(row["regular"]):
                mark = "≈"
            else:
                mark = "✗"
            counts[mark] += 1
            if args.all or mark == "✗":
                rows.append([mark, row["pie"], (f"{row['from']} → " if row.get("from") else "") + row["language"],
                             row["expected"], got,
                             "; ".join(filter(None, [note, row.get("notes")]))])
    connection.close()

    table(rows, ["", "Input", "Language", "Expected", "Derived", "Notes"])
    if rows:
        print()
    print(f"{counts['✓']} correct, {counts['≈']} known exceptions (regular outcome derived), "
          f"{counts['✗']} wrong, of {len(words)} test words")
    return 0 if counts["✗"] == 0 else 1

def cmd_db_rebuild(args):
    database.rebuild()
    with sqlite3.connect(DB_PATH) as connection:
        count = len(database.languages(connection))
    connection.close()
    print(f"rebuilt {DB_PATH}: {count} languages")
    return 0

def cmd_db_show(args):
    with database.connect() as connection:
        print("Languages:")
        table([[id, name, "" if parent is None else parent, type] for id, name, parent, type in database.languages(connection)],
              ["Id", "Name", "Parent", "Type"], indent="  ")
    connection.close()
    return 0

def cmd_tui(args):
    try:
        from . import tui
    except ImportError as error:
        raise CommandError(f"the TUI needs Textual ({error}); install it with 'pip install textual'")
    tui.run(args.word)
    return 0

def build_parser():
    parser = argparse.ArgumentParser(prog="vakya",
                                     description="Derive the reflexes of Proto-Indo-European words through ordered sound changes.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    parse = commands.add_parser("parse", help="convert PIE words into phonemes",
                                description="Convert words in PIE notation (*ḱḗr, or ASCII k'e:'r) into phonemes. "
                                            "With no words, parses every root in roots.txt.",
                                epilog=ASCII_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parse.add_argument("words", nargs="*", help="words in PIE notation, e.g. '*ḱḗr'")
    parse.add_argument("-f", "--features", action="store_true", help="list the features of every phoneme")
    parse.add_argument("--ipa", action="store_true", help="input is in the inventory's IPA rather than PIE notation")
    parse.set_defaults(func=cmd_parse)

    rules = commands.add_parser("rules", help="parse sound changes written in standard notation")
    rule_commands = rules.add_subparsers(dest="rules_command", required=True, metavar="command")
    rule_parse = rule_commands.add_parser("parse", help="show how a single rule is parsed")
    rule_parse.add_argument("rule", help="e.g. 'p t k → f θ x / _C'")
    rule_parse.set_defaults(func=cmd_rules_parse)
    rule_check = rule_commands.add_parser("check", help="check rule files and report errors")
    rule_check.add_argument("files", nargs="+")
    rule_check.add_argument("-v", "--verbose", action="store_true", help="also show each parsed rule")
    rule_check.set_defaults(func=cmd_rules_check)

    tree = commands.add_parser("tree", help="show the language family tree")
    tree.set_defaults(func=cmd_tree)

    derive = commands.add_parser("derive", help="derive a PIE word's reflexes",
                                 description="Apply the rule files in data/rules down the family tree.",
                                 epilog=ASCII_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    derive.add_argument("words", nargs="+", help="words in PIE notation, e.g. '*séḱs'")
    derive.add_argument("-t", "--to", metavar="LANGUAGE", help="only this language (name or id); default: all")
    derive.add_argument("-f", "--from", dest="source", metavar="LANGUAGE",
                        help="the words are written in this ancestor (e.g. proto-germanic '*fadēr'); default: PIE")
    derive.add_argument("-s", "--steps", action="store_true", help="show each change that applied")
    derive.add_argument("--script", metavar="NAME",
                        help="use another script where a table exists (e.g. devanagari: data/orthography/hindi-devanagari.csv)")
    derive.set_defaults(func=cmd_derive)

    check_words = commands.add_parser("check-words", help="derive the test words and compare with the expected forms")
    check_words.add_argument("file", nargs="?", default=TEST_WORDS, help="CSV of pie,language,expected[,regular,from] (default: test_words.csv); "
                                  "'from' names the stage the input is written in (default PIE)")
    check_words.add_argument("-a", "--all", action="store_true", help="list passing words too")
    check_words.set_defaults(func=cmd_check_words)

    tui = commands.add_parser("tui", help="interactive browser for derivations and rules")
    tui.add_argument("word", nargs="?", default="*séḱs", help="PIE word to start with")
    tui.set_defaults(func=cmd_tui)

    db = commands.add_parser("db", help="manage vakya.db")
    db_commands = db.add_subparsers(dest="db_command", required=True, metavar="command")
    db_commands.add_parser("rebuild", help="rebuild vakya.db from languages.csv").set_defaults(func=cmd_db_rebuild)
    db_commands.add_parser("show", help="print the database tables").set_defaults(func=cmd_db_show)

    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CommandError, OrthographyError, PhonemeError, RuleError, RuleParseError, sqlite3.Error, OSError) as error:
        print(f"vakya: error: {error}", file=sys.stderr)
        return 1
