"""Tests for blocker detection.

The values here are not invented. They are the answers most often stored in the
`blockers` column on the production workspace, where 589 standups were flagged
as blocked and the ten commonest values were `Na`, `.`, `n`, `• None`, `na`,
`NA`, `0`, `2`, `1`, `0h`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from blockers import (  # noqa: E402
    find_blocker_answer,
    has_blockers,
    is_blocker_question,
    normalise,
    reports_a_blocker,
)

DEFAULT_Q = ["What did you complete yesterday?", "What are you working on today?", "Any blockers?"]
AVAILABILITY_Q = ["❇️ Previous day work", "➡️ Plan for today", "⏳ Availability in Hours"]


class TestRealProductionValues:
    """Every one of these was counted as a blocker before this module existed."""

    def test_the_ten_commonest_flagged_values_are_not_blockers(self):
        for value in ["Na", ".", "n", "• None", "na", "NA", "0", "2", "1", "0h"]:
            assert reports_a_blocker(value) is False, value

    def test_the_bullet_case(self):
        """The bot asks for bullets, then the old check failed to strip them."""
        assert reports_a_blocker("None") is False
        assert reports_a_blocker("• None") is False
        assert reports_a_blocker("- none.") is False

    def test_an_emoji_shortcode_does_not_hide_the_answer(self):
        assert reports_a_blocker("No Blocker:saluting_face:") is False

    def test_a_trailing_qualifier_does_not_change_the_answer(self):
        for value in ["nothing for now", "• nothing for now", "none as of now", "No blockers today"]:
            assert reports_a_blocker(value) is False, value

    def test_spanish_no_blocker_answers_are_not_blockers(self):
        for value in ["nada", "sin bloqueos", "sin bloqueo", "ninguno", "ninguna"]:
            assert reports_a_blocker(value) is False, value


class TestRealBlockersStillCount:
    def test_plain_english_blockers(self):
        for value in [
            "waiting on staging creds",
            "CI flake blocking release",
            "• Blocked on review from Sam",
            "need access to prod DB",
            "no access to the cluster",
            "nothing works, the cluster is down",
        ]:
            assert reports_a_blocker(value) is True, value

    def test_a_qualifier_inside_a_real_blocker_is_not_stripped_away(self):
        """ "blocked for now on review" must not reduce to "blocked"."""
        assert reports_a_blocker("blocked for now on review") is True

    def test_no_at_the_start_of_a_real_sentence(self):
        """ "No access to prod" contains "no" but is a blocker."""
        assert reports_a_blocker("No access to prod") is True


class TestQuestionDecidesWhetherToLook:
    def test_availability_answers_are_never_blockers(self):
        for value in ["4:30 Hrs", "8", "0h", "6 hours", "1.5 hrs"]:
            assert has_blockers(AVAILABILITY_Q, ["x", "y", value]) is False, value

    def test_the_same_answer_under_a_blocker_question_is_read_normally(self):
        assert has_blockers(DEFAULT_Q, ["x", "y", "waiting on creds"]) is True
        assert has_blockers(DEFAULT_Q, ["x", "y", "Na"]) is False

    def test_spanish_blocker_question_preserves_real_blockers(self):
        questions = ["Ayer", "Hoy", "¿Tienes algún bloqueo que te impida avanzar hoy?"]
        assert has_blockers(questions, ["x", "y", "Espero permisos de deploy"]) is True
        assert has_blockers(questions, ["x", "y", "sin bloqueos"]) is False

    def test_a_standup_with_no_blocker_question_never_reports_one(self):
        questions = ["Previous day work", "Plan for today", "Availability in Hours"]
        assert has_blockers(questions, ["a", "b", "anything at all here"]) is False

    def test_the_blocker_question_is_found_wherever_it_sits(self):
        questions = ["Any impediments?", "What did you do?", "What is next?"]
        assert find_blocker_answer(questions, ["stuck on auth", "b", "c"]) == "stuck on auth"
        assert has_blockers(questions, ["stuck on auth", "b", "c"]) is True

    def test_question_wording_variants(self):
        for q in [
            "Any blockers?",
            "Any blockers or impediments?",
            "Anything blocking you?",
            "Are you stuck?",
            "¿Tienes algún bloqueo que te impida avanzar hoy?",
        ]:
            assert is_blocker_question(q) is True, q
        for q in ["⏳ Availability in Hours", "What are you working on today?", "Mood?", ""]:
            assert is_blocker_question(q) is False, q


class TestEdges:
    def test_missing_and_empty_inputs(self):
        assert reports_a_blocker(None) is False
        assert reports_a_blocker("") is False
        assert reports_a_blocker("   ") is False
        assert has_blockers(None, None) is False
        assert has_blockers(DEFAULT_Q, []) is False

    def test_without_questions_it_falls_back_to_the_third_answer(self):
        """Legacy callers that cannot supply the questions still work."""
        assert find_blocker_answer(None, ["a", "b", "stuck"]) == "stuck"
        assert has_blockers(None, ["a", "b", "stuck"]) is True
        assert has_blockers(None, ["a", "b", "Na"]) is False

    def test_fewer_answers_than_questions(self):
        assert has_blockers(DEFAULT_Q, ["only one"]) is False

    def test_normalise_is_idempotent(self):
        for value in ["• None", "Na", "  nothing for now  ", "No Blocker:tada:"]:
            once = normalise(value)
            assert normalise(once) == once, value

    def test_a_multi_word_answer_of_only_no_words(self):
        assert reports_a_blocker("no, none") is False
        assert reports_a_blocker("none / nil") is False


class TestNotApplicable:
    """ "N/A" is the commonest short answer after "no", and it was read as a blocker.

    `normalise` leaves the slash alone, the phrase list did not carry the whole
    string, and the word split at the end broke it into {"n", "a"}. "a" is not
    a no-word, so the answer came back as a blocker. Production held 122 of
    these across every casing and bullet form.
    """

    def test_every_casing_and_bullet_form_seen_in_production(self):
        for value in ["N/A", "n/a", "N/a", "• N/A", "• n/a", "n/a.", "- N/A"]:
            assert reports_a_blocker(value) is False, value

    def test_the_other_separators_people_use(self):
        for value in ["n.a", "n\\a", "N.A."]:
            assert reports_a_blocker(value) is False, value

    def test_the_doubled_letter_typo(self):
        for value in ["nn", "Nn", "• nn"]:
            assert reports_a_blocker(value) is False, value

    def test_under_a_blocker_question(self):
        assert has_blockers(DEFAULT_Q, ["x", "y", "N/A"]) is False

    def test_a_slash_separated_pair_of_no_words_still_works(self):
        assert reports_a_blocker("none / nil") is False

    def test_a_real_blocker_containing_a_slash_is_untouched(self):
        assert reports_a_blocker("blocked on the CI/CD pipeline") is True
        assert reports_a_blocker("waiting on n/a approval from legal") is True


class TestPerTicketMultilineAnswers:
    """The Compass DSU single form answers the blocker question once per ticket:

    "TECH-43: Sin bloqueos\\nTECH-44: Sin bloqueos\\nTECH-46: Sin bloqueos".

    `normalise` flattens the newlines, so the whole string stopped matching the
    no-blocker phrases and every such standup was escalated to the manager
    (reported on the production workspace 2026-09-23 with exactly this format).
    Per-ticket lines must be judged per line: a blocker on any line is a
    blocker; negations on every line are none.
    """

    USER_FORMAT = "TECH-43: Sin bloqueos\nTECH-44: Sin bloqueos\nTECH-46: Sin bloqueos"
    SPANISH_Q = [
        "¿Qué lograste avanzar o completar ayer?",
        "¿Cuál es tu tarea principal para hoy?",
        "¿Tienes algún bloqueo que te impida avanzar hoy?",
    ]

    def test_the_exact_reported_format_is_not_a_blocker(self):
        assert reports_a_blocker(self.USER_FORMAT) is False
        assert has_blockers(self.SPANISH_Q, ["avance", "tarea", self.USER_FORMAT]) is False

    def test_ticket_prefixed_negations_single_line(self):
        for value in ["TECH-43: Sin bloqueos", "TECH-44: nada", "TECH-46: Ninguno", "TECH-17: Sin bloqueo"]:
            assert reports_a_blocker(value) is False, value

    def test_a_real_blocker_on_any_line_still_flags(self):
        answer = "TECH-43: Sin bloqueos\nTECH-44: Esperando acceso a staging"
        assert reports_a_blocker(answer) is True
        assert has_blockers(self.SPANISH_Q, ["avance", "tarea", answer]) is True

    def test_a_real_blocker_with_ticket_prefix_still_flags(self):
        for value in ["TECH-43: Esperando acceso al repositorio", "TECH-46: waiting on creds"]:
            assert reports_a_blocker(value) is True, value

    def test_a_bare_ticket_reference_with_no_text_is_not_a_blocker(self):
        assert reports_a_blocker("TECH-43:") is False


class TestSpec001SpanishNegations:
    """SPEC-001 (2026-09-24): remaining Spanish negation gaps.

    The owner's 4-ticket format of 2026-09-24 was already fixed by the
    per-ticket line judging; this class pins the variants that still
    mis-flagged on main: separator-less ticket keys and Spanish trailing
    time qualifiers.
    """

    OWNER_2026_09_24 = "TECH-17: Sin bloqueos\nTECH-39: Sin bloqueos\nTECH-40: Sin bloqueos\nTECH-34: Sin bloqueos"
    SPANISH_Q = [
        "¿Qué lograste avanzar o completar ayer?",
        "¿Cuál es tu tarea principal para hoy?",
        "¿Tienes algún bloqueo que te impida avanzar hoy?",
    ]

    def test_owner_2026_09_24_exact_format_is_not_a_blocker(self):
        assert reports_a_blocker(self.OWNER_2026_09_24) is False
        assert has_blockers(self.SPANISH_Q, ["avance", "tarea", self.OWNER_2026_09_24]) is False

    def test_owner_format_with_one_real_blocker_still_flags(self):
        mixed = "TECH-17: Sin bloqueos\nTECH-39: Sesión bloqueada, falta definición de requerimiento"
        assert reports_a_blocker(mixed) is True

    def test_ticket_key_without_separator_is_still_per_ticket(self):
        assert reports_a_blocker("TECH-39 sin bloqueos") is False
        assert reports_a_blocker("TECH-39 Sin bloqueos") is False
        assert reports_a_blocker("TECH-39 nada") is False

    def test_key_concatenation_never_matches(self):
        # "TECH-40abc" is not the key TECH-40; whatever follows stands on its own.
        assert reports_a_blocker("TECH-40abc nada") is True

    def test_spanish_trailing_qualifiers_are_neutral(self):
        for value in [
            "TECH-44: Nada por ahora",
            "TECH-34: Ninguno por hoy",
            "Sin bloqueos por ahora",
            "TECH-12: Sin bloqueos de momento",
            "TECH-12: Nada esta semana",
            "Ninguna todavía",
        ]:
            assert reports_a_blocker(value) is False, value

    def test_a_real_blocker_with_a_qualifier_still_flags(self):
        for value in [
            "bloqueado por el ambiente de pruebas",
            "bloqueado todavía",
            "TECH-39: Sesión bloqueada, falta definición de requerimiento",
            "TECH-44: Esperando acceso, por ahora nada avanzado",
        ]:
            assert reports_a_blocker(value) is True, value
