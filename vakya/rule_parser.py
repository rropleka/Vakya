"""
Parse sound changes written in standard notation into a structure the rule engine can apply.

    target → replacement / left _ right, left _ right // left _ right

Parsing is purely syntactic: phonemes are read with the inventory, but class letters (C, V, P)
and feature names ([+dental]) are kept as written and resolved later against a source's definitions.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .phonemes import Phoneme, inventory, normalize

ARROWS = ("->", "→", "⟶", ">")
NULLS = "∅Ø0"
NEGATIONS = "×!¬"
PLUS = "+"
MINUS = "-−–"
FEATURE_NAME = re.compile(r"[^\s,\]=+\-−–]+")

class RuleParseError(Exception):
    def __init__(self, message, text=None, position=None):
        self.message = message
        self.text = text
        self.position = position
        super().__init__(str(self))

    def __str__(self):
        if self.text is None:
            return self.message
        # combining marks take no column on screen
        column = sum(1 for c in self.text[:self.position] if not unicodedata.combining(c))
        return f"{self.message}\n    {self.text}\n    {' ' * column}^"

@dataclass(frozen=True)
class Feature:
    name: str
    value: object               # True for +name, False for -name, a string for name=value

@dataclass(frozen=True)
class Segment:
    phoneme: Phoneme

@dataclass(frozen=True)
class Class:
    name: str | None            # None for a bare feature matrix like [+voice]
    features: tuple[Feature, ...] = ()

@dataclass(frozen=True)
class Choice:
    options: tuple[tuple, ...]  # each option is a sequence of elements

@dataclass(frozen=True)
class Optional:
    elements: tuple

@dataclass(frozen=True)
class Boundary:
    kind: str                   # '#' word boundary

@dataclass(frozen=True)
class Environment:
    left: tuple
    right: tuple
    negated: bool = False       # × _C: applies everywhere except here

@dataclass(frozen=True)
class Rule:
    # target and replacement are parallel lists of sequences: p t k → f θ x is three changes at once;
    # an empty sequence is ∅
    target: tuple[tuple, ...]
    replacement: tuple[tuple, ...]
    environments: tuple[Environment, ...] = ()
    exceptions: tuple[Environment, ...] = ()
    text: str = field(default="", compare=False)

class Parser:
    def __init__(self, text):
        self.text = normalize(text).strip()
        self.pos = 0
        self.inventory = inventory()

    def error(self, message):
        raise RuleParseError(message, self.text, self.pos)

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def at_end(self):
        return self.pos >= len(self.text)

    def skip_space(self):
        while self.peek().isspace():
            self.pos += 1

    def arrow(self):
        return next((arrow for arrow in ARROWS if self.text.startswith(arrow, self.pos)), None)

    def expect(self, char):
        if self.peek() != char:
            self.error(f"expected {char!r}")
        self.pos += 1

    def parse(self) -> Rule:
        target = self.side()
        if not target:
            self.error("expected a target before the arrow")

        arrow = self.arrow()
        if arrow is None:
            self.error("expected '→'")
        self.pos += len(arrow)

        replacement = self.side()
        if not replacement:
            self.error("expected a replacement after the arrow (use ∅ for deletion)")

        environments = exceptions = ()
        if self.peek() == "/" and not self.text.startswith("//", self.pos):
            self.pos += 1
            environments = self.environments()
        if self.text.startswith("//", self.pos):
            self.pos += 2
            exceptions = self.environments()

        self.skip_space()
        if self.arrow():
            self.error("unexpected second arrow (two rules run together?)")
        if not self.at_end():
            self.error(f"unexpected {self.peek()!r}")

        if len(replacement) not in (1, len(target)):
            raise RuleParseError(f"{len(target)} targets but {len(replacement)} replacements", self.text, 0)
        for before, after in zip(target, replacement):
            if len(before) == len(after) == 1 and isinstance(before[0], Choice) and isinstance(after[0], Choice):
                if len(after[0].options) not in (1, len(before[0].options)):
                    raise RuleParseError(f"set of {len(before[0].options)} maps onto set of {len(after[0].options)}",
                                         self.text, 0)

        return Rule(target, replacement, environments, exceptions, unicodedata.normalize("NFC", self.text))

    def side(self):
        # whitespace separates parallel changes; sounds written together form a sequence
        alternatives = []
        self.skip_space()
        while not self.at_end() and self.peek() != "/" and not self.arrow():
            alternatives.append(self.sequence(stops=" \t/"))
            self.skip_space()
        return tuple(alternatives)

    def sequence(self, stops):
        if self.peek() in NULLS and self.peek():
            self.pos += 1
            if not self.at_end() and self.peek() not in stops and not self.arrow():
                self.error("∅ must stand alone")
            return ()

        elements = []
        while not self.at_end() and self.peek() not in stops and not self.arrow():
            elements.append(self.element())
        if not elements:
            self.error("expected a sound")
        return tuple(elements)

    def element(self):
        c = self.peek()

        if c == "{":
            self.pos += 1
            options = []
            while True:
                self.skip_space()
                if self.peek() == "}":
                    break
                if self.at_end():
                    self.error("unclosed '{'")
                options.append(self.sequence(stops=" \t,}"))
                self.skip_space()
                if self.peek() == ",":
                    self.pos += 1
            if not options:
                self.error("empty set")
            self.expect("}")
            return Choice(tuple(options))

        if c == "(":
            self.pos += 1
            elements = self.sequence(stops=")")
            self.expect(")")
            return Optional(elements)

        if c == "#":
            self.pos += 1
            return Boundary("#")

        if c == "[":
            return Class(None, self.matrix())

        if "A" <= c <= "Z":
            self.pos += 1
            return Class(c, self.matrix() if self.peek() == "[" else ())

        matched = self.inventory.match(self.text, self.pos)
        if matched is None:
            self.error(f"unknown symbol {c!r} (U+{ord(c):04X})")
        phoneme, self.pos = matched
        if self.peek() == "[":
            self.error("feature matrix after a phoneme; use a class letter or a bare [...]")
        return Segment(phoneme)

    def matrix(self):
        self.expect("[")
        features = []
        while True:
            while self.peek().isspace() or self.peek() == ",":
                self.pos += 1
            if self.peek() == "]":
                break
            if self.at_end():
                self.error("unclosed '['")

            sign = None
            if self.peek() == PLUS:
                sign = True
            elif self.peek() in MINUS:
                sign = False
            if sign is not None:
                self.pos += 1

            name = FEATURE_NAME.match(self.text, self.pos)
            if name is None:
                self.error("expected a feature name")
            self.pos = name.end()

            if self.peek() == "=":
                if sign is not None:
                    self.error("use either +/- or =value, not both")
                self.pos += 1
                value = FEATURE_NAME.match(self.text, self.pos)
                if value is None:
                    self.error("expected a feature value")
                self.pos = value.end()
                features.append(Feature(name.group(), value.group()))
            elif sign is None:
                self.error("feature needs +, - or =value")
            else:
                features.append(Feature(name.group(), sign))
        self.expect("]")
        if not features:
            self.error("empty feature matrix")
        return tuple(features)

    def environments(self):
        if self.peek().isspace():
            self.skip_space()
        if self.peek() == "{":
            self.error("braced environment lists are not supported; separate environments with commas")

        environments = []
        while True:
            self.skip_space()
            negated = self.peek() in NEGATIONS and self.peek() != ""
            if negated:
                self.pos += 1
            left = self.context(stops="_")
            self.expect("_")
            right = self.context(stops=",/")
            environments.append(Environment(left, right, negated))
            self.skip_space()
            if self.peek() != ",":
                return tuple(environments)
            self.pos += 1

    def context(self, stops):
        # spacing inside an environment is insignificant: V _ V is V_V
        elements = []
        while True:
            self.skip_space()
            if self.at_end() or self.peek() in stops or self.arrow():
                return tuple(elements)
            if self.peek() == "_":
                self.error("only one '_' per environment")
            elements.append(self.element())

def parse_rule(text) -> Rule:
    return Parser(text).parse()

@dataclass(frozen=True)
class Entry:
    name: str
    description: str
    rule_text: str
    line: int

def read_labeled(text):
    """
    Read sources laid out as

        Name: prose description.

            Phonological rule: p t k → f θ x / _C
    """
    entries = []
    name = description = None
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rule = re.match(r"Phonological rule:\s*(.*)", line)
        if rule:
            if name is None:
                raise RuleParseError(f"line {number}: rule without a name")
            entries.append(Entry(name, description, rule.group(1), number))
            name = description = None
        elif name is not None:
            description += " " + line
        else:
            name, _, description = line.partition(":")
            name, description = name.strip(), description.strip()
    return entries

def parse_source(text, reader=read_labeled):
    """Parse every rule in a source; returns ([(entry, rule)], [(entry, error)]) so one bad line doesn't stop the rest."""
    rules, errors = [], []
    for entry in reader(text):
        try:
            rules.append((entry, parse_rule(entry.rule_text)))
        except RuleParseError as error:
            errors.append((entry, error))
    return rules, errors

def format_element(element):
    if isinstance(element, Segment):
        return str(element.phoneme)
    if isinstance(element, Class):
        features = " ".join(format_feature(feature) for feature in element.features)
        return (element.name or "") + (f"[{features}]" if features else "")
    if isinstance(element, Choice):
        return "{" + ", ".join(format_sequence(option) for option in element.options) + "}"
    if isinstance(element, Optional):
        return f"({format_sequence(element.elements)})"
    if isinstance(element, Boundary):
        return element.kind
    raise TypeError(f"not a rule element: {element!r}")

def format_feature(feature):
    if feature.value is True:
        return f"+{feature.name}"
    if feature.value is False:
        return f"-{feature.name}"
    return f"{feature.name}={feature.value}"

def format_sequence(sequence):
    return "".join(map(format_element, sequence)) or "∅"

def format_environment(environment):
    left = "".join(map(format_element, environment.left))
    right = "".join(map(format_element, environment.right))
    return ("× " if environment.negated else "") + f"{left}_{right}"

def format_rule(rule):
    """Canonical notation for a parsed rule: parse_rule(format_rule(rule)) == rule."""
    text = " ".join(map(format_sequence, rule.target)) + " → " + " ".join(map(format_sequence, rule.replacement))
    if rule.environments:
        text += " / " + ", ".join(map(format_environment, rule.environments))
    if rule.exceptions:
        text += " // " + ", ".join(map(format_environment, rule.exceptions))
    return text

def changes(rule):
    """The individual target → replacement pairs: p t k → f θ x gives (p, f), (t, θ), (k, x)."""
    replacements = rule.replacement * len(rule.target) if len(rule.replacement) == 1 else rule.replacement
    return list(zip(rule.target, replacements))

def class_names(rule):
    """Class letters a rule uses, which a source has to define before the rule can be applied."""
    names = set()
    def visit(sequence):
        for element in sequence:
            if isinstance(element, Class) and element.name:
                names.add(element.name)
            elif isinstance(element, Choice):
                for option in element.options:
                    visit(option)
            elif isinstance(element, Optional):
                visit(element.elements)
    for sequence in rule.target + rule.replacement:
        visit(sequence)
    for environment in rule.environments + rule.exceptions:
        visit(environment.left)
        visit(environment.right)
    return sorted(names)

def describe_rule(rule):
    """(label, text) rows explaining how a rule was read: each change, where it applies, which classes it needs."""
    rows = [("rule", format_rule(rule))]
    for before, after in changes(rule):
        rows.append(("change", f"{format_sequence(before)} → {format_sequence(after)}"))
    for environment in rule.environments:
        where = format_environment(Environment(environment.left, environment.right))
        rows.append(("except in" if environment.negated else "only in", where))
    for environment in rule.exceptions:
        rows.append(("except in", format_environment(environment)))
    if class_names(rule):
        rows.append(("classes", ", ".join(class_names(rule)) + "  (must be defined to apply)"))
    return rows
