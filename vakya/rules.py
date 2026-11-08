"""
Rule files, and applying their sound changes to words as phoneme lists.

A rule file holds the changes for one step of the family tree:

    from: Proto-Indo-European
    to: Proto-Germanic

    class C = [type=Consonant]
    class H = {h₁, h₂, h₃}
    feature +dental = [place=Alveolar]

    Centumization: The palatovelars merge with the plain velars.
        kʲ gʲ gʲʱ → k g gʱ

Definitions must come before the rules that use them. Indented lines are rules, applied in file
order under the most recent "Name: description" heading. Lines starting with # are comments.
"""
import glob
import os
import re
from dataclasses import dataclass, field

from . import DATA_DIR
from .phonemes import Phoneme, PhonemeError, inventory
from .rule_parser import (Boundary, Choice, Class, Feature, Optional, Parser, Rule, RuleParseError, Segment, changes,
                          format_rule, parse_rule)

RULES_DIR = os.path.join(DATA_DIR, "rules")

# stress rides along with its vowel: a rule written for e also applies to é, and é stays stressed
SUPRASEGMENTAL = frozenset({"stressed"})

class RuleError(Exception):
    pass

def core(features):
    return {name: value for name, value in dict(features).items() if name not in SUPRASEGMENTAL and value is not False}

class Definitions:
    """A rule file's class letters and feature names, checked against the phoneme inventory."""

    def __init__(self):
        self.classes = {}       # letter -> element (Class, Choice or Segment)
        self.features = {}      # (name, True/False) -> tuple of inventory Features

        self.values = {}
        phoneme_inventory = inventory()
        for features in list(phoneme_inventory.phonemes.values()) + list(phoneme_inventory.diacritics.values()):
            for name, value in features.items():
                self.values.setdefault(name, set()).add(value)
        self.boolean = {name for name, values in self.values.items() if all(isinstance(v, bool) for v in values)}

    def define_class(self, letter, text):
        parser = Parser(text)
        element = parser.element()
        parser.skip_space()
        if not parser.at_end():
            parser.error("a class is a single [feature matrix], {set} or class letter")
        if isinstance(element, Choice) and any(len(option) != 1 for option in element.options):
            raise RuleError(f"class {letter}: each member must be a single sound")
        if isinstance(element, (Optional, Boundary)):
            raise RuleError(f"class {letter}: must be a feature matrix, set or class letter")
        self.validate(element)
        self.classes[letter] = element

    def define_feature(self, sign, name, text):
        parser = Parser(text)
        features = parser.matrix()
        parser.skip_space()
        if not parser.at_end():
            parser.error("expected only a [feature matrix]")
        for feature in features:
            self.check_inventory_feature(feature)
        self.features[(name, sign)] = features

    def check_inventory_feature(self, feature):
        if feature.name not in self.values:
            raise RuleError(f"unknown feature {feature.name!r}; define it with 'feature +{feature.name} = [...]' "
                            f"or use one of: {', '.join(sorted(self.values))}")
        if isinstance(feature.value, bool):
            if feature.name not in self.boolean:
                values = ", ".join(sorted(map(str, self.values[feature.name])))
                raise RuleError(f"{feature.name!r} is not a +/- feature; write [{feature.name}=value] ({values}) "
                                f"or define 'feature {'+' if feature.value else '-'}{feature.name} = [...]'")
        elif feature.value not in self.values[feature.name]:
            values = ", ".join(sorted(str(v) for v in self.values[feature.name] if not isinstance(v, bool)))
            raise RuleError(f"{feature.name!r} has no value {feature.value!r}; known values: {values}")

    def resolve(self, feature):
        """A feature as written in a rule, as inventory features."""
        if (feature.name, feature.value) in self.features:
            return self.features[(feature.name, feature.value)]
        self.check_inventory_feature(feature)
        return (feature,)

    def holds(self, feature, phoneme):
        for base in self.resolve(feature):
            if isinstance(base.value, bool):
                if bool(phoneme[base.name]) != base.value:
                    return False
            elif phoneme[base.name] != base.value:
                return False
        return True

    def assign(self, features, feature):
        for base in self.resolve(feature):
            if base.value is False:
                features.pop(base.name, None)   # absent and False are the same; keep phonemes canonical
            else:
                features[base.name] = base.value

    def validate(self, element):
        if isinstance(element, Segment):
            for feature in element.features:
                self.resolve(feature)
        elif isinstance(element, Class):
            if element.name is not None and element.name not in self.classes:
                raise RuleError(f"class {element.name} is not defined; add 'class {element.name} = [...]'")
            for feature in element.features:
                self.resolve(feature)
        elif isinstance(element, Choice):
            for option in element.options:
                for member in option:
                    self.validate(member)
        elif isinstance(element, Optional):
            for member in element.elements:
                self.validate(member)

    def matches(self, element, phoneme):
        """Whether a single-sound element (sound, class or set of sounds) matches a phoneme."""
        if isinstance(element, Segment):
            # e[-stressed] is e that is also unstressed; o[+overlong] is the overlong o
            expected = dict(element.phoneme.features)
            for feature in element.features:
                self.assign(expected, feature)
            return core(expected) == core(phoneme.features) and all(self.holds(feature, phoneme)
                                                                    for feature in element.features)
        if isinstance(element, Choice):
            return any(len(option) == 1 and self.matches(option[0], phoneme) for option in element.options)
        if isinstance(element, Class):
            if element.name is not None and not self.matches(self.classes[element.name], phoneme):
                return False
            return all(self.holds(feature, phoneme) for feature in element.features)
        return False

@dataclass(frozen=True)
class Change:
    target: tuple
    replacement: tuple

class CompiledRule:
    def __init__(self, rule: Rule, definitions: Definitions):
        self.rule = rule
        self.definitions = definitions
        self.changes = self.expand(rule)

        for environment in rule.environments + rule.exceptions:
            for element in environment.left + environment.right:
                definitions.validate(element)
        # for each change, which matched sound each replacement element is built from (None: a fresh sound)
        self.sources = [self.check_change(change) for change in self.changes]

    @staticmethod
    def expand(rule):
        # {p t k} → {f θ x} is the same three changes as p t k → f θ x
        result = []
        for before, after in changes(rule):
            if len(before) == 1 and isinstance(before[0], Choice) and len(after) == 1 and isinstance(after[0], Choice):
                targets, replacements = before[0].options, after[0].options
                if len(replacements) == 1:
                    replacements = replacements * len(targets)
                result.extend(Change(t, r) for t, r in zip(targets, replacements))
            else:
                result.append(Change(before, after))
        return result

    def check_change(self, change):
        for element in change.target:
            if isinstance(element, Boundary):
                raise RuleError("a boundary (#) belongs in the environment, not the target")
            self.definitions.validate(element)

        sources = []
        for k, element in enumerate(change.replacement):
            if isinstance(element, Segment):
                sources.append(k if k < len(change.target) else None)
                continue
            if not isinstance(element, Class):
                raise RuleError("a replacement can only contain sounds and feature changes like C[-voice]"
                                " (a set needs a matching set in the target)")
            # C[-voice] changes the sound matched at the same position; past the end of the target, a class
            # letter copies the target sound with the same letter (C → CC doubles a consonant)
            source = k
            if k >= len(change.target):
                source = next((j for j, t in enumerate(change.target)
                               if isinstance(t, Class) and element.name and t.name == element.name), None)
                if source is None:
                    raise RuleError(f"replacement {element.name or '[...]'} has no matching sound in the target")
            if any(isinstance(t, Optional) for t in change.target[:source + 1]):
                raise RuleError("a feature change can't follow an optional (...) part of the target")
            self.definitions.validate(element)
            sources.append(source)
        return sources

    def match(self, pattern, word, i):
        """Every end position where pattern matches word starting at i."""
        if not pattern:
            yield i
            return
        first, rest = pattern[0], pattern[1:]
        for j in self.match_element(first, word, i):
            yield from self.match(rest, word, j)

    def match_element(self, element, word, i):
        if isinstance(element, Boundary):
            if i == 0 or i == len(word):
                yield i
        elif isinstance(element, Optional):
            yield from self.match(element.elements, word, i)
            yield i
        elif isinstance(element, Choice):
            for option in element.options:
                yield from self.match(option, word, i)
        elif i < len(word) and self.definitions.matches(element, word[i]):
            yield i + 1

    def environment_matches(self, environment, word, start, end):
        left = any(e == start for j in range(start + 1) for e in self.match(environment.left, word, j))
        return left and any(True for _ in self.match(environment.right, word, end))

    def applies_at(self, word, start, end):
        positive = [env for env in self.rule.environments if not env.negated]
        negative = [env for env in self.rule.environments if env.negated] + list(self.rule.exceptions)
        if positive and not any(self.environment_matches(env, word, start, end) for env in positive):
            return False
        return not any(self.environment_matches(env, word, start, end) for env in negative)

    def produce(self, matched, replacement, sources):
        phoneme_inventory = inventory()
        result = []
        for element, index in zip(replacement, sources):
            source = matched[index] if index is not None and index < len(matched) else None
            if isinstance(element, Segment):
                features = dict(element.phoneme.features)
                if source is not None and (features.get("type") == "Vowel" or features.get("syllabic")):
                    for name in SUPRASEGMENTAL:
                        if source[name] and name not in features:
                            features[name] = source[name]
                for feature in element.features:
                    self.definitions.assign(features, feature)
                result.append(phoneme_inventory.phoneme_for(features) if features != dict(element.phoneme.features)
                              else element.phoneme)
            else:
                features = dict(source.features)
                for feature in element.features:
                    self.definitions.assign(features, feature)
                result.append(phoneme_inventory.phoneme_for(features))
        return result

    def apply(self, word: list[Phoneme]) -> list[Phoneme]:
        # simultaneous application: environments are checked against the word as it was before this rule
        result = []
        i = 0
        while i <= len(word):
            advanced = False
            for change, sources in zip(self.changes, self.sources):
                ends = sorted(set(self.match(change.target, word, i)), reverse=True)   # longest match first
                end = next((e for e in ends if (e > i or not change.target) and self.applies_at(word, i, e)), None)
                if end is None:
                    continue
                result.extend(self.produce(word[i:end], change.replacement, sources))
                if end > i:
                    i = end
                    advanced = True
                break
            if not advanced:
                if i < len(word):
                    result.append(word[i])
                i += 1
        return result

@dataclass
class Entry:
    name: str
    description: str
    line: int
    text: str
    rule: CompiledRule

@dataclass
class RuleFile:
    path: str
    source: str | None = None
    target: str | None = None
    definitions: Definitions = field(default_factory=Definitions)
    entries: list[Entry] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)     # (line, message)

def is_rule_file(text):
    return re.search(r"^(from|to):", text, re.MULTILINE) is not None

def load_rule_file(path) -> RuleFile:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    rule_file = RuleFile(path)
    heading = None              # (name, description) for the rules that follow
    in_heading = False          # unindented lines right after a heading continue its description
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            in_heading = False if not line else in_heading
            continue
        try:
            if raw[0].isspace():
                if heading is None:
                    raise RuleError("rule without a 'Name: description' heading")
                rule = parse_rule(line)
                rule_file.entries.append(Entry(heading[0], heading[1], number, line,
                                               CompiledRule(rule, rule_file.definitions)))
                in_heading = False
            elif match := re.fullmatch(r"(from|to):\s*(.+)", line):
                setattr(rule_file, "source" if match[1] == "from" else "target", match[2].strip())
            elif match := re.fullmatch(r"class\s+([A-Z])\s*=\s*(.+)", line):
                rule_file.definitions.define_class(match[1], match[2])
            elif match := re.fullmatch(r"feature\s+([+\-−])\s*([^\s=]+)\s*=\s*(.+)", line):
                rule_file.definitions.define_feature(match[1] == "+", match[2], match[3])
            elif in_heading:
                heading = (heading[0], f"{heading[1]} {line}".strip())
            elif ":" in line:
                name, _, description = line.partition(":")
                heading = (name.strip(), description.strip())
                in_heading = True
            else:
                raise RuleError("expected 'Name: description', an indented rule, or a class/feature definition")
        except (RuleError, RuleParseError, PhonemeError) as error:
            rule_file.errors.append((number, str(error)))

    if rule_file.source is None or rule_file.target is None:
        rule_file.errors.append((1, "missing 'from:' or 'to:' line"))
    return rule_file

def load_rule_files(directory=RULES_DIR):
    """Every rule file, keyed by (from, to) language names in lower case. Raises if any has errors."""
    result = {}
    problems = []
    for path in sorted(glob.glob(os.path.join(directory, "*.txt"))):
        rule_file = load_rule_file(path)
        name = os.path.relpath(path, DATA_DIR)
        problems.extend(f"{name}:{line}: {message.splitlines()[0]}" for line, message in rule_file.errors)
        if rule_file.source and rule_file.target:
            key = (rule_file.source.lower(), rule_file.target.lower())
            if key in result:
                problems.append(f"{name}: {rule_file.source} → {rule_file.target} is already defined in "
                                f"{os.path.relpath(result[key].path, DATA_DIR)}")
            result[key] = rule_file
    if problems:
        raise RuleError("rule files have errors (see 'vakya rules check'):\n  " + "\n  ".join(problems))
    return result

def compile_rule(text, definitions=None):
    """Parse and compile one rule, mostly for experiments and tests."""
    return CompiledRule(parse_rule(text), definitions or Definitions())

__all__ = ["CompiledRule", "Definitions", "Entry", "RuleError", "RuleFile", "compile_rule", "format_rule",
           "is_rule_file", "load_rule_file", "load_rule_files"]
