"""
Derive a PIE word's reflexes by applying each step's rule file down the family tree.
"""
import unicodedata
from dataclasses import dataclass, field

from . import database, lexicon
from .orthography import OrthographyError, orthography
from .phonemes import Phoneme, from_pie, inventory, transcribe
from .rules import RuleError, load_rule_files

def stress_first_vowel(phonemes):
    # words read from a Germanic spelling carry no accent marks, but Germanic stress is on the first syllable
    result = list(phonemes)
    for i, phoneme in enumerate(result):
        if phoneme["type"] == "Vowel" or phoneme["syllabic"]:
            result[i] = inventory().phoneme_for({**dict(phoneme.features), "stressed": True})
            break
    return result

@dataclass(frozen=True)
class Step:
    name: str               # the rule's heading
    rule: str               # the rule as written
    line: int
    before: tuple[Phoneme, ...]
    after: tuple[Phoneme, ...]

@dataclass
class Stage:
    language_id: int
    language: str
    type: str
    phonemes: tuple[Phoneme, ...]
    steps: list[Step] = field(default_factory=list)     # the changes from the parent to this language
    rule_count: int = 0
    formation: lexicon.Formation | None = None         # set when this stage starts from another formation
    attested: list = field(default_factory=list)        # lexicon.Attested reflexes of the word, if any
    script: str | None = None                           # e.g. "devanagari": an alternative spelling table
    problem: str | None = None                          # why a listed formation couldn't be used

    @property
    def transcription(self):
        return transcribe(self.phonemes)

    @property
    def spelling(self):
        """Native spelling if the language has an orthography table, else None."""
        table = (self.script and orthography(self.language, self.script)) or orthography(self.language)
        return table.spell(self.phonemes) if table else None

    @property
    def display(self):
        spelling = self.spelling
        star = "*" if self.type in ("proto", "intermediate") else ""     # reconstructed, not attested
        return star + (spelling if spelling is not None else self.transcription)

    @property
    def matches_attested(self):
        """True or False when attested forms are known, None otherwise."""
        if not self.attested:
            return None
        # attested forms are recorded in the language's default (romanized) spelling, whatever script is shown
        table = orthography(self.language)
        try:
            predicted = unicodedata.normalize("NFC", table.spell(self.phonemes) if table else self.transcription)
        except OrthographyError:
            return False
        return any(predicted == attested.form for attested in self.attested)

class Engine:
    def __init__(self, connection, rule_files=None, script=None):
        self.connection = connection
        self.script = script
        self.languages = {row[0]: row for row in database.languages(connection)}
        self.rule_files = load_rule_files() if rule_files is None else rule_files

        names = {row[1].lower(): row for row in self.languages.values()}
        for (source, target), rule_file in self.rule_files.items():
            if source not in names or target not in names:
                missing = rule_file.source if source not in names else rule_file.target
                raise RuleError(f"{rule_file.path}: no language named {missing!r} in languages.csv")
            if names[target][2] != names[source][0]:
                raise RuleError(f"{rule_file.path}: {rule_file.target} is not a child of {rule_file.source}")

    def rule_file(self, language_id):
        id, name, parent, type = self.languages[language_id]
        if parent is None:
            return None
        return self.rule_files.get((self.languages[parent][1].lower(), name.lower()))

    def step(self, phonemes, language_id):
        """One step down the tree: the parent's form → this language's form."""
        id, name, parent, type = self.languages[language_id]
        rule_file = self.rule_file(language_id)
        stage = Stage(id, name, type, tuple(phonemes), rule_count=len(rule_file.entries) if rule_file else 0)
        for entry in rule_file.entries if rule_file else ():
            result = tuple(entry.rule.apply(list(stage.phonemes)))
            if result != stage.phonemes:
                stage.steps.append(Step(entry.name, entry.text, entry.line, stage.phonemes, result))
                stage.phonemes = result
        return stage

    def read(self, word, language_id):
        """A word written in a language: PIE notation for the root, the language's spelling otherwise."""
        id, name, parent, type = self.languages[language_id]
        if parent is None:
            return from_pie(word)
        table = orthography(name)
        if table is None:
            raise OrthographyError(f"{name} has no spelling table, so words can't be read from it")
        return stress_first_vowel(table.read(word))

    def child(self, word, parent_stage, language_id):
        """A language's stage from its parent's: the parent's output, or a formation listed for the word."""
        name = self.languages[language_id][1]
        formation = lexicon.formation(word, name)
        phonemes, problem = parent_stage.phonemes, None
        if formation is not None:
            try:
                phonemes = tuple(self.read(formation.form, parent_stage.language_id))
            except OrthographyError as error:
                # fall back to the regular development rather than lose the whole tree
                formation, problem = None, f"formation {lexicon.formation(word, name).form!r} not used: {error}"
        stage = self.step(phonemes, language_id)
        stage.formation = formation
        stage.problem = problem
        stage.attested = lexicon.attested_forms(word, name)
        stage.script = self.script
        return stage

    def root(self, word, language_id):
        id, name, parent, type = self.languages[language_id]
        stage = Stage(id, name, type, tuple(self.read(word, id)), script=self.script)
        stage.attested = lexicon.attested_forms(word, name) if parent is None else []
        return stage

    def derive(self, word, language_id, source_id=None) -> list[Stage]:
        """Stages from the root (or from source_id, an ancestor the word is written in) down to one language."""
        lineage = database.lineage(self.connection, language_id)
        if source_id is not None:
            ids = [row[0] for row in lineage]
            if source_id not in ids:
                raise RuleError(f"{self.languages[source_id][1]} is not an ancestor of {self.languages[language_id][1]}")
            lineage = lineage[ids.index(source_id):]

        stages = [self.root(word, lineage[0][0])]
        for id, name, parent, type in lineage[1:]:
            # formations and attested forms are keyed by the PIE word, so they apply only to PIE input
            if source_id is None:
                stages.append(self.child(word, stages[-1], id))
            else:
                stages.append(self.step(stages[-1].phonemes, id))
                stages[-1].script = self.script
        return stages

    def derive_all(self, word) -> dict[int, Stage]:
        """Every language's stage, each computed once from its parent's."""
        stages = {}
        for id, name, parent, type in self.languages.values():     # parents come before children
            stages[id] = self.root(word, id) if parent is None else self.child(word, stages[parent], id)
        return stages
