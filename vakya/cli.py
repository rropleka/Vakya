import argparse
import os
import sqlite3
import sys
import unicodedata

from . import DATA_DIR, DB_PATH, database, engine
from .phonemes import PhonemeError, describe_features, from_pie, inventory, transcribe
from .rule_parser import RuleParseError, describe_rule, parse_rule, parse_source

ROOTS_FILE = os.path.join(DATA_DIR, "Proto-Indo-European", "roots.txt")

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
            rules, errors = parse_source(f.read())
        print(f"{path}: {len(rules)} parsed, {len(errors)} failed")

        if args.verbose:
            for entry, rule in rules:
                print(f"\n  line {entry.line}: {entry.name}")
                show_rule(rule, indent="    ")
            if errors:
                print()
        for entry, error in errors:
            message = str(error).replace("\n", "\n  ")
            print(f"  line {entry.line} ({entry.name}): {message}")
        failed = failed or bool(errors)
    return 1 if failed else 0

def cmd_tree(args):
    with database.connect() as connection:
        rows = database.languages(connection)
        counts = database.rule_counts(connection)
    connection.close()

    children = {}
    for row in rows:
        children.setdefault(row[2], []).append(row)

    lines = []
    def walk(row, prefix, last, root):
        id, name, parent, type = row
        branch = "" if root else ("└── " if last else "├── ")
        rules = "" if root else f"{counts.get(id, 0)} rule{'s' if counts.get(id, 0) != 1 else ''}"
        lines.append([prefix + branch + name, type, rules])
        kids = children.get(id, [])
        for i, child in enumerate(kids):
            walk(child, prefix + ("" if root else ("    " if last else "│   ")), i == len(kids) - 1, False)

    for root in children.get(None, []):
        walk(root, "", True, True)
    table(lines)
    return 0

def cmd_derive(args):
    with database.connect() as connection:
        if args.to:
            language = database.find_language(connection, args.to)
            if language is None:
                names = ", ".join(row[1] for row in database.languages(connection))
                raise CommandError(f"no language {args.to!r}; known languages: {names}")
            targets = [language]
        else:
            targets = [row for row in database.languages(connection) if row[2] is not None]

        for n, word in enumerate(args.words):
            if n:
                print()
            print(word)
            rows = []
            for id, name, parent, type in targets:
                form, steps = engine.derive(connection, word, id)
                if args.steps:
                    # with one target show the whole derivation; with the whole tree, each language's own changes
                    shown = steps if args.to else [step for step in steps if step.language_id == id]
                    table(rows)
                    rows = []
                    print(f"  {name}: {form}")
                    table([[f"{step.in_regex} → {step.out_regex}", step.description, f"{step.before} → {step.after}"]
                           for step in shown] or [["(no change)"]], indent="      ")
                else:
                    rows.append([name, form])
            table(rows, indent="  ")
    connection.close()
    return 0

def cmd_db_rebuild(args):
    database.rebuild()
    with sqlite3.connect(DB_PATH) as connection:
        count = len(database.languages(connection))
        count_changes = len(database.sound_changes(connection))
    connection.close()
    print(f"rebuilt {DB_PATH}: {count} languages, {count_changes} sound changes")
    return 0

def cmd_db_show(args):
    with database.connect() as connection:
        print("Languages:")
        table([[id, name, "" if parent is None else parent, type] for id, name, parent, type in database.languages(connection)],
              ["Id", "Name", "Parent", "Type"], indent="  ")
        print("\nSound changes:")
        table([[cell if cell is not None else "" for cell in row] for row in database.sound_changes(connection)],
              ["Parent", "Child", "Order", "In", "Out", "Description"], indent="  ")
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
                                description="Convert words in PIE notation (*ḱḗr) into phonemes. "
                                            "With no words, parses every root in roots.txt.")
    parse.add_argument("words", nargs="*", help="words in PIE notation, e.g. '*ḱḗr'")
    parse.add_argument("-f", "--features", action="store_true", help="list the features of every phoneme")
    parse.add_argument("--ipa", action="store_true", help="input is in the inventory's IPA rather than PIE notation")
    parse.set_defaults(func=cmd_parse)

    rules = commands.add_parser("rules", help="parse sound changes written in standard notation")
    rule_commands = rules.add_subparsers(dest="rules_command", required=True, metavar="command")
    rule_parse = rule_commands.add_parser("parse", help="show how a single rule is parsed")
    rule_parse.add_argument("rule", help="e.g. 'p t k → f θ x / _C'")
    rule_parse.set_defaults(func=cmd_rules_parse)
    rule_check = rule_commands.add_parser("check", help="parse every rule in source files and report failures")
    rule_check.add_argument("files", nargs="+")
    rule_check.add_argument("-v", "--verbose", action="store_true", help="also show each parsed rule")
    rule_check.set_defaults(func=cmd_rules_check)

    tree = commands.add_parser("tree", help="show the language family tree")
    tree.set_defaults(func=cmd_tree)

    derive = commands.add_parser("derive", help="derive a PIE word's reflexes",
                                 description="Apply the sound changes in sound_changes.csv to PIE words. "
                                             "Rules are still regexes applied to the written form.")
    derive.add_argument("words", nargs="+", help="words in PIE notation, e.g. '*séḱs'")
    derive.add_argument("-t", "--to", metavar="LANGUAGE", help="only this language (name or id); default: all")
    derive.add_argument("-s", "--steps", action="store_true", help="show each change that applied")
    derive.set_defaults(func=cmd_derive)

    tui = commands.add_parser("tui", help="interactive browser for derivations and rules")
    tui.add_argument("word", nargs="?", default="*séḱs", help="PIE word to start with")
    tui.set_defaults(func=cmd_tui)

    db = commands.add_parser("db", help="manage vakya.db")
    db_commands = db.add_subparsers(dest="db_command", required=True, metavar="command")
    db_commands.add_parser("rebuild", help="rebuild vakya.db from the CSVs").set_defaults(func=cmd_db_rebuild)
    db_commands.add_parser("show", help="print the database tables").set_defaults(func=cmd_db_show)

    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CommandError, PhonemeError, RuleParseError, sqlite3.Error, OSError) as error:
        print(f"vakya: error: {error}", file=sys.stderr)
        return 1
