"""A skill is copied into the run directory, so a skill that quotes a rubric is a crib.

FrontierScience-Research's sixty questions are a **fixed test set**. There is no train
split, no held-out half and no second draw of the population: every number this repository
has ever published about that benchmark is a measurement over those sixty rubrics. And
``install_run_skills`` copies a skill's whole body into ``<run root>/.claude/skills/``,
which is the operator's working directory — so the model answering task *n* can read every
word of it.

Five skills were written in one pass against a scored sixty-task trial, from artifacts that
contain the rubrics, the per-item judgements and both arms' answers. That is the exact
material an answer key is made of, and the failure it invites is not dishonesty: it is a
sentence like "the criterion here wants the conventional mechanism, which is X", written
because X is what made the loss legible. A skill carrying that sentence would raise the
next trial's score and the rise would mean nothing, because the arms would differ by a
crib rather than by craft. There is no way to detect that after the fact from a score.

So the rule is written into the skills — an evidence section cites task ids, rubric item
numbers and weights, both arms' scores, the sentence in a judgement that describes the
*shape* of a loss, and counts from the run artifacts, and never the correct answer — and
this file is the half of it a machine can hold.

**Three scans, each with a control that proves it would catch a leak.** They are not the
same scan at three thresholds; they catch three different ways an answer gets copied:

* **Phrase.** Any seven consecutive words shared with a rubric. This is the scan for prose
  lifted or lightly paraphrased out of a criterion.
* **Quantity.** Any numeric literal from a rubric carrying three or more significant
  digits. This is the scan for a value: a computed energy, a ratio, a threshold.
* **Identifier.** Any token from a rubric that mixes letters and digits. This is the scan
  for a named entity — a compound, a gene, a state label — which is the shape a biology or
  chemistry answer key takes and which the other two scans do not see.

**What is deliberately *not* scanned, and why, because it was tried.** The obvious gate is
"every alphanumeric token of twelve characters or more from a rubric". Run against the 163
markdown files the pack held before the five skills landed, that scan flagged **85 distinct
tokens across 365 file-token pairs**, every one of them ordinary English: `distribution` in
32 files, `configuration` in 26, `substitution` in 20, `architecture` in 18, and behind
them `approximation`, `experimental`, `concentration`, `justification`. Narrowing it to
tokens that appear in a rubric and in no *problem* statement — answer-only vocabulary,
which sounds like exactly the right cut — still leaves 37 of them. A gate at that threshold
is an exemption list longer than the check, and an exemption list of ordinary words is a
gate that has been switched off. :class:`TheScanThisGateDoesNotUseTests` pins that
measurement so the next person to reach for it can see the result without re-deriving it.

**Gated on the dataset, like ``test_fs_dataset``.** The split is not committed and CI
installs nothing, so on a clean runner this file is absent rather than red. That is a real
weakness — the machine that has the dataset is the machine that writes the skills — and it
is the same trade ``test_every_skill_can_be_loaded`` makes with its corpus.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.frontierscience import FS_RUBRIC_HEAD_PATTERN, load_dataset, resolve_dataset_path

REPO = Path(__file__).resolve().parent.parent
SKILL_PACK = REPO / "src" / "skills"

#: Words in a shared run before it counts as a quotation.
#:
#: Measured, not chosen for roundness. Over the 168 markdown files the pack shipped before
#: the FrontierScience five, the number of runs shared with a rubric was 100 at four words,
#: 9 at five, **1 at six** and **0 at seven**. The survivors are ordinary English — "at
#: least one of the", "at the end of the", "because it is the only", and at six words
#: "at least one of the following" in a writing skill's reference file. Seven is where
#: English stops colliding with a rubric by accident, so it is the shortest span at which
#: a hit is evidence rather than noise. Six with one name exempted would be the same gate
#: with an exemption for an ordinary phrase, which is a gate switched off.
#:
#: That measurement is asserted, not only written here:
#: :meth:`TheScanWouldCatchALeakTests.test_seven_is_the_measured_boundary_and_not_a_free_parameter`
#: reproduces the 6-and-7 counts on the pack as it stands and holds that this constant is
#: the *shortest* clean length. Without it the floor was pinned and the ceiling was free —
#: 6 and 4 went red, 8 and 20 and 40 stayed green, and 40 is the scan switched off.
PHRASE_WORDS = 7

#: A run of exactly seven words taken verbatim out of the split, hard-coded.
#:
#: The phrase control below used to build its leak with ``phrases()`` at ``PHRASE_WORDS``,
#: so the leak was always exactly as long as the scan: true at 7, true at 40, true at any
#: threshold anyone set. A control that cannot fail is a green line. This is the anchor
#: that fixes it, and it has to be a literal for the same reason.
#:
#: It is the rubric grammar's own item head rather than a criterion, because an anchor
#: only has to be *in the split at seven words* — putting an actual criterion in this file
#: to prove the gate works would be the thing the gate exists to prevent, one directory
#: over. ``phrases()`` drops the digits and the punctuation, so what this contributes is
#: ``points item assign points as follows pts``, which is in three of the sixty rubrics.
A_SEVEN_WORD_RUN_FROM_THE_SPLIT = "Points: 1.5, Item: Assign points as follows: - (0.375pts)"

#: Significant digits before a number is specific enough to be an answer.
#:
#: Two would admit every ordinary fraction: a skill has to be able to say a criterion was
#: scored 0.5 of 1.0. Three is the point at which a literal stops being a proportion and
#: starts being a measurement — 45.36, 208.8, 1638, 0.2478 — and 47 of the split's
#: literals survive it, including every value the trial's own analysis flagged as
#: answer-bearing. Over the 168 markdown files the pack shipped before the FrontierScience
#: five, this scan collided exactly once, on a year.
SIGNIFICANT_DIGITS = 3

#: Four-digit literals in this range are read as years rather than as quantities. The one
#: collision the quantity scan had against the shipped pack was ``2023`` in a skill's prose
#: against ``2023`` in a rubric, and neither is a measurement of anything. Bounded rather
#: than open-ended so that a four-digit *value* — an energy, a count, a wavenumber — is not
#: waved through by a rule about dates.
#:
#: Both halves are asserted, because an exemption with no test is a hole with a comment on
#: it: ``test_a_four_digit_value_is_not_waved_through_as_a_year`` names the two four-digit
#: graded quantities the split actually contains and holds that this range does not reach
#: them, and ``test_the_year_exemption_is_still_earning_its_place`` holds that ``2023`` is
#: still a live collision, so the exemption can be deleted the day it stops being one.
YEAR_RANGE = range(1900, 2100)

#: Rubric tokens the identifier scan drops before it starts. Both are markup rather than
#: science: ``2nd``/``3rd``/``4th`` order a list, and ``1pt``/``25pts`` are the weight
#: annotations the rubric grammar itself is built out of. Leaving them in would make the
#: scan fire on any skill that writes "the 2nd of the two rows", which is prose, not a leak.
_IDENTIFIER_NOISE = re.compile(r"^\d+(?:st|nd|rd|th|pt|pts)$", re.IGNORECASE)

#: The rubric's own weight annotations, which are scoring metadata and not science. Two
#: forms, because the grammar has two: an item head (``Points: 1.5, Item: ...``) and a
#: weighted sub-bullet (``- **(0.25pts)**``, and in one row ``(**0.125pts)``). Subtracted
#: from the quantity corpus, because a skill quoting a criterion's weight — "item 3 carries
#: 3.0 of the task's 10" — is citing the grading scale, which is the thing the evidence
#: sections are *supposed* to cite. Matched narrowly on purpose: an earlier draft accepted
#: any parenthesised number followed by a comma and swallowed ``(45.36 , \text{g})``,
#: which is a graded value and the single literal this scan most needs to keep.
_SUB_BULLET_WEIGHT = re.compile(r"\(\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*pts?\b", re.IGNORECASE)

_WORD = re.compile(r"[a-z]+")
#: A numeric literal. The trailing lookahead forbids a word character but *allows* a dot,
#: so a value that ends a sentence — "the pipeline scored 45.36." — is still seen; an
#: earlier version forbade both and silently missed every number written at a full stop,
#: which is where a leaked value is most likely to sit.
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_IDENTIFIER = re.compile(
    r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{3,}\b"
)


def dataset_present() -> bool:
    """Whether the pinned split is on this machine, in the order the code looks for it."""
    return resolve_dataset_path(None).is_file()


def phrases(text: str, length: int = PHRASE_WORDS) -> set[str]:
    """Every run of *length* consecutive alphabetic words, casefolded.

    Punctuation, markup and digits are dropped rather than treated as word boundaries, so
    a quotation that was reflowed, re-emphasised or had its LaTeX stripped still matches
    the criterion it came from.
    """
    words = _WORD.findall(text.casefold())
    return {" ".join(words[index : index + length]) for index in range(len(words) - length + 1)}


def significant_digits(literal: str) -> int:
    """How many digits of a numeric literal carry information.

    Leading and trailing zeros carry none: ``100`` is one significant digit and ``0.50``
    is one, while ``108`` is three because the zero is interior.
    """
    return len(literal.replace(".", "").strip("0")) or 1


def is_a_year(literal: str) -> bool:
    return literal.isdigit() and len(literal) == 4 and int(literal) in YEAR_RANGE


def quantities(text: str) -> set[str]:
    """Numeric literals specific enough that writing one down would be quoting a value."""
    return {
        literal
        for literal in _NUMBER.findall(text)
        if significant_digits(literal) >= SIGNIFICANT_DIGITS and not is_a_year(literal)
    }


def rubric_weights(text: str) -> set[str]:
    """The point values this rubric assigns, which are not things it is asking for."""
    found = set(_SUB_BULLET_WEIGHT.findall(text))
    for line in text.splitlines():
        head = FS_RUBRIC_HEAD_PATTERN.match(line)
        if head:
            found.add(head.group(1))
    return found


def graded_quantities(rubrics_: list[str]) -> set[str]:
    """Every quantity the split states, minus the weights it grades them out of."""
    corpus: set[str] = set()
    weights: set[str] = set()
    for rubric in rubrics_:
        corpus |= quantities(rubric)
        weights |= rubric_weights(rubric)
    return corpus - weights


def identifiers(text: str) -> set[str]:
    """Tokens mixing letters and digits, casefolded, minus the rubric's own markup."""
    return {
        token.casefold()
        for token in _IDENTIFIER.findall(text)
        if not _IDENTIFIER_NOISE.match(token)
    }


def skill_bodies() -> dict[str, str]:
    """Every file a skill ships, not only its ``SKILL.md``.

    A skill directory may carry reference material, and ``install_run_skills`` copies the
    whole tree. A crib in ``reference.md`` reaches the model exactly as well as one in the
    skill body, so the scan has to cover what is installed rather than what is indexed.
    """
    return {
        str(path.relative_to(SKILL_PACK)): path.read_text(encoding="utf-8")
        for path in sorted(SKILL_PACK.rglob("*.md"))
    }


def rubrics() -> list[str]:
    return [row.rubric for row in load_dataset()]


@unittest.skipUnless(dataset_present(), "the pinned FrontierScience split is not on this machine")
class NoSkillQuotesARubricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rubrics = rubrics()
        self.bodies = skill_bodies()
        self.assertTrue(self.bodies, "the skill pack did not parse")

    def test_no_skill_shares_seven_consecutive_words_with_a_rubric(self) -> None:
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= phrases(rubric)
        offenders: list[str] = []
        for name, body in self.bodies.items():
            for phrase in sorted(phrases(body) & corpus):
                offenders.append(f"{name} quotes a rubric: {phrase!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_skill_writes_a_quantity_a_rubric_grades(self) -> None:
        corpus = graded_quantities(self.rubrics)
        self.assertTrue(corpus, "no rubric quantity was extracted; the scan is empty")
        offenders: list[str] = []
        for name, body in self.bodies.items():
            for literal in sorted(quantities(body) & corpus):
                offenders.append(f"{name} states a graded quantity: {literal}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_skill_names_an_identifier_a_rubric_names(self) -> None:
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= identifiers(rubric)
        self.assertTrue(corpus, "no rubric identifier was extracted; the scan is empty")
        offenders: list[str] = []
        for name, body in self.bodies.items():
            for token in sorted(identifiers(body) & corpus):
                offenders.append(f"{name} names a graded identifier: {token}")
        self.assertEqual(offenders, [], "\n".join(offenders))


@unittest.skipUnless(dataset_present(), "the pinned FrontierScience split is not on this machine")
class TheScanWouldCatchALeakTests(unittest.TestCase):
    """Three controls. A scan with no control is a green line, not a gate.

    Each one builds a synthetic skill body out of the real split — one rubric sentence,
    one rubric quantity, one rubric identifier — and asserts the corresponding scan finds
    it. None of these bodies is written to disk: they are strings, and the skill pack is
    read-only here.
    """

    def setUp(self) -> None:
        self.rubrics = rubrics()

    def test_a_body_carrying_a_rubric_sentence_is_caught(self) -> None:
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= phrases(rubric)
        leaked = sorted(phrases(self.rubrics[0]))[0]
        body = (
            "# A skill that explains too much\n\nWhen the sheet asks this, the reader is "
            f"looking for the following: {leaked}. Write it in the section that owes it.\n"
        )
        self.assertTrue(
            phrases(body) & corpus,
            "the phrase scan did not catch a rubric sentence pasted into a skill body",
        )

    def _phrase_collisions(self, length: int) -> set[tuple[str, str]]:
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= phrases(rubric, length)
        return {
            (name, phrase)
            for name, body in skill_bodies().items()
            for phrase in phrases(body, length) & corpus
        }

    def test_a_hard_coded_rubric_run_is_caught_at_whatever_threshold_is_in_force(self) -> None:
        """The anchor the synthesised control above does not provide.

        The test above pastes a leak built at ``PHRASE_WORDS`` and is therefore true at
        every value of it. This one pastes seven fixed words, so the scan has to still be
        looking at spans of seven for it to pass.
        """
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= phrases(rubric)
        self.assertEqual(
            len(_WORD.findall(A_SEVEN_WORD_RUN_FROM_THE_SPLIT.casefold())),
            7,
            "the anchor stopped being seven words long",
        )
        body = (
            "# A skill that explains too much\n\nThe grader's own head line for this item "
            f"reads {A_SEVEN_WORD_RUN_FROM_THE_SPLIT} and the criterion under it is the "
            "one this section is about.\n"
        )
        self.assertTrue(
            phrases(body) & corpus,
            f"at PHRASE_WORDS={PHRASE_WORDS} the phrase scan no longer sees seven words "
            "taken verbatim out of the split, which means it has been raised past the "
            "length it was measured at and is not scanning for quotations any more",
        )

    def test_seven_is_the_measured_boundary_and_not_a_free_parameter(self) -> None:
        """The constant's docstring, as assertions. Both directions, because only one of
        them was held: 6 and 4 went red on their own, and 8, 20 and 40 did not.

        A span length is clean when nothing in the pack collides with a rubric at that
        length, and the right constant is the *shortest* clean one. Anything longer is
        also clean and scans for less; at 40 it scans for nothing at all.
        """
        self.assertEqual(
            self._phrase_collisions(PHRASE_WORDS),
            set(),
            "the pack collides with a rubric at the length the gate runs at",
        )
        self.assertTrue(
            self._phrase_collisions(PHRASE_WORDS - 1),
            f"PHRASE_WORDS={PHRASE_WORDS} is longer than it needs to be: the pack is "
            f"already clean at {PHRASE_WORDS - 1} words, so every span between them is "
            "being scanned for and nothing is being found. Lower it to the shortest "
            "clean length or the scan is switched off by degrees.",
        )
        self.assertEqual(self._phrase_collisions(7), set())
        six = self._phrase_collisions(6)
        self.assertEqual(
            sorted(six),
            [("paper-writing/reference.md", "at least one of the following")],
            "the six-word measurement in PHRASE_WORDS' comment no longer holds; re-derive "
            f"it and rewrite the comment. Collisions: {sorted(six)}",
        )

    def test_a_body_carrying_a_rubric_quantity_is_caught(self) -> None:
        corpus = graded_quantities(self.rubrics)
        leaked = sorted(corpus)[0]
        body = f"# A skill that states a value\n\nThe number the grader wants is {leaked}.\n"
        self.assertIn(leaked, quantities(body) & corpus)

    def test_an_item_weight_is_not_mistaken_for_a_leaked_value(self) -> None:
        """The other side of the same scan, and the reason it needed a second pass.

        An evidence section is supposed to say what a criterion was worth. A gate that
        refused "item 3 carries 3.0 of the task's 10", or the 1.25 one biology item
        carries, would be forcing the skills to drop the citation that makes them
        checkable — so the weights come out of the corpus, and this holds that they did.
        """
        corpus = graded_quantities(self.rubrics)
        weights = set()
        for rubric in self.rubrics:
            weights |= rubric_weights(rubric)
        self.assertIn("1.25", weights, "the weight grammar stopped matching")
        self.assertEqual(corpus & weights, set())
        self.assertIn(
            "45.36",
            corpus,
            "a graded value written inside brackets was swallowed as if it were a weight",
        )

    def test_a_four_digit_value_is_not_waved_through_as_a_year(self) -> None:
        """The cost side of the year exemption, which had no test at all.

        ``YEAR_RANGE`` is the one place in this file where a rubric literal is allowed
        through unexamined, and the way an exemption like that dies is by widening: open
        it to every four-digit number and the ten tests here stay green while two graded
        quantities the split really states walk straight past the scan. So they are named.
        """
        corpus = graded_quantities(self.rubrics)
        for literal in ("1638", "2559"):
            self.assertFalse(
                is_a_year(literal),
                f"{literal} is a value the split grades, and YEAR_RANGE now reaches it: "
                "the date exemption has been widened into an exemption for quantities",
            )
            self.assertIn(
                literal,
                corpus,
                f"{literal} has left the graded-quantity corpus; if the split changed, "
                "find the four-digit values it states now and pin those instead",
            )

    def test_the_year_exemption_is_still_earning_its_place(self) -> None:
        """The other half of the rule this repository keeps for exemptions: every one of
        them owes a test that fails when it stops being needed.

        Without ``YEAR_RANGE`` the quantity scan fires on ``2023`` in a shipped skill's
        prose against ``2023`` in a rubric, and neither is a measurement of anything. The
        day that stops being true this test goes red and the exemption comes out.
        """

        def ignoring_the_year_rule(text: str) -> set[str]:
            return {
                literal
                for literal in _NUMBER.findall(text)
                if significant_digits(literal) >= SIGNIFICANT_DIGITS
            }

        rubric_numbers: set[str] = set()
        weights: set[str] = set()
        for rubric in self.rubrics:
            rubric_numbers |= ignoring_the_year_rule(rubric)
            weights |= rubric_weights(rubric)
        rubric_numbers -= weights

        waved_through = {
            (name, literal)
            for name, body in skill_bodies().items()
            for literal in ignoring_the_year_rule(body) & rubric_numbers
        }
        self.assertTrue(
            waved_through,
            "nothing in the pack collides with a four-digit rubric literal any more, so "
            "YEAR_RANGE is an exemption with no cases: delete it and this test",
        )
        self.assertTrue(
            all(is_a_year(literal) for _, literal in waved_through),
            "the year exemption is hiding a literal that is not year-shaped: "
            f"{sorted(waved_through)}",
        )
        self.assertIn(
            "2023",
            {literal for _, literal in waved_through},
            "the one collision the exemption was written for is gone; re-derive it",
        )

    def test_a_body_carrying_a_rubric_identifier_is_caught(self) -> None:
        corpus: set[str] = set()
        for rubric in self.rubrics:
            corpus |= identifiers(rubric)
        leaked = sorted(corpus)[0]
        body = f"# A skill that names the thing\n\nThe entity being asked for is {leaked}.\n"
        self.assertIn(leaked, identifiers(body) & corpus)

    def test_an_ordinary_skill_body_is_not_caught_by_any_of_the_three(self) -> None:
        """The other half of a control: the scans have to pass something innocent.

        Written the way the five FrontierScience skills are written — about the shape of a
        loss, with rubric item numbers and per-item scores and no content — because that
        is the style the gate has to leave room for.
        """
        corpus_phrase: set[str] = set()
        corpus_identifier: set[str] = set()
        for rubric in self.rubrics:
            corpus_phrase |= phrases(rubric)
            corpus_identifier |= identifiers(rubric)
        corpus_quantity = graded_quantities(self.rubrics)
        body = (
            "# Answer the part where it is asked\n\nItem 3 carries 1.25 of the task's 10 "
            "and the control took it while the pipeline scored 0.0; the loss set and the "
            "uncovered set were the same four items. Give each printed part its own "
            "heading and state the instance the part asks for, with its unit, before any "
            "sweep over it.\n"
        )
        self.assertEqual(phrases(body) & corpus_phrase, set())
        self.assertEqual(quantities(body) & corpus_quantity, set())
        self.assertEqual(identifiers(body) & corpus_identifier, set())


@unittest.skipUnless(dataset_present(), "the pinned FrontierScience split is not on this machine")
class TheScanThisGateDoesNotUseTests(unittest.TestCase):
    """Why there is no "long token" scan, kept as a measurement rather than a claim.

    The design this file was built from asked for one: every alphanumeric token of twelve
    characters or more taken from a rubric, asserted absent from every skill. It is the
    first thing anyone reaches for, so the reason it is not here has to be re-derivable
    rather than remembered — and it is a number, so it is asserted.

    If this test ever fails downward, the token scan has become affordable and should be
    added. That is the outcome this file wants.
    """

    #: What the token scan collided with on the pack as it stood before the
    #: FrontierScience five landed: 85 distinct ordinary English words, 87 with them.
    #: Asserted as a floor well under the measurement, because the pack grows and the
    #: exact figure moves with it; the claim being pinned is "dozens", not "eighty-five".
    ORDINARY_WORD_COLLISIONS = 40

    def test_the_twelve_character_token_scan_is_still_unusable(self) -> None:
        token = re.compile(r"[A-Za-z0-9]{12,}")
        corpus = {t.casefold() for rubric in rubrics() for t in token.findall(rubric)}
        collided = {
            t
            for body in skill_bodies().values()
            for t in {x.casefold() for x in token.findall(body)}
            if t in corpus
        }
        self.assertGreater(
            len(collided),
            self.ORDINARY_WORD_COLLISIONS,
            "the twelve-character token scan now collides with few enough ordinary words "
            "to be worth adding as a fourth gate; add it and delete this test. Collisions: "
            f"{sorted(collided)}",
        )

    def test_narrowing_it_to_answer_only_vocabulary_does_not_rescue_it(self) -> None:
        """The obvious repair, measured: keep only tokens that appear in a rubric and in
        no problem statement, which is the vocabulary a model is not already holding. It
        removes about half the collisions and leaves dozens."""
        token = re.compile(r"[A-Za-z0-9]{12,}")
        rows = load_dataset()
        in_problems = {t.casefold() for row in rows for t in token.findall(row.problem)}
        answer_only = {
            t.casefold() for row in rows for t in token.findall(row.rubric)
        } - in_problems
        collided = {
            t
            for body in skill_bodies().values()
            for t in {x.casefold() for x in token.findall(body)}
            if t in answer_only
        }
        self.assertGreater(
            len(collided),
            20,
            "the answer-only token scan is now clean enough to use; add it and delete "
            f"this test. Collisions: {sorted(collided)}",
        )


if __name__ == "__main__":
    unittest.main()
