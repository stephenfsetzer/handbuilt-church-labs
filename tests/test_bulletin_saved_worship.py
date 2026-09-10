from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from skills.bulletin.bulletin_production.interface import _normalize_liturgy, _validate_bulletin
from skills.bulletin.worship_resolution import resolve_worship_profile
from tests.helpers import bulletin_input, make_church, verify_liturgy_source


def _configured_profile(church: Path, **overrides) -> None:
    """Save a fully resolvable worship profile with no private sources needed.

    Every default in ``overrides`` still comes from the shipped Sunday
    library, so a test can exercise the real resolver without staging any
    church-owned liturgy text.
    """
    profile_path = church / "worship/profile.yaml"
    profile = yaml.safe_load(profile_path.read_text())
    profile["status"] = "confirmed"
    profile["tradition_pack"] = "episcopal-bcp-rite-ii"
    profile["defaults"].update(
        eucharistic_prayer="B", lords_prayer="traditional", prayers_of_the_people="III",
        blessing="omit", include_creed=True, include_confession=False,
        print_full_eucharistic_prayer=False, psalm_format="plain", psalm_response_start="second",
        doxology="omit", prayer_presentation="continuous", rubric_style="concise",
    )
    profile["defaults"].update(overrides)
    profile_path.write_text(yaml.safe_dump(profile))


class SavedWorshipTest(unittest.TestCase):
    def test_explicit_single_lesson_allows_missing_slot_and_both_disabled_rejects(self):
        request = bulletin_input()
        request["liturgy"].update(include_first_reading=True, include_second_reading=False)
        request["readings"].pop("second")
        _normalize_liturgy(request)
        _validate_bulletin(request)
        request["liturgy"].update(include_first_reading=False, include_second_reading=False)
        with self.assertRaisesRegex(Exception, "At least one non-Gospel"):
            _validate_bulletin(request)

    def test_numbered_reading_and_unshaped_psalm_stop_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            for slot in ('first', 'second', 'gospel'):
                request = bulletin_input()
                request['readings'][slot]['text'] = '1 The reader begins.\n\n2 The reader continues.'
                with patch('skills.bulletin.bulletin_production.interface._run') as render:
                    result = produce(church, request)
                    self.assertEqual(result['errors'][0]['code'], 'reading_presentation_unresolved')
                    render.assert_not_called()
            request = bulletin_input()
            request['readings']['psalm'].update(format='responsive_half_verse', text='1 No confirmed division.\n\n2 No confirmed division.')
            self.assertEqual(produce(church, request)['errors'][0]['code'], 'reading_presentation_unresolved')

    def test_saved_preferences_reach_pdf_and_weekly_override_stays_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config_path = church / 'church.yaml'
            config = yaml.safe_load(config_path.read_text())
            config['bulletin'] = {'doxology_music': {'title': 'Our Doxology', 'lyrics': [
                {'speaker': 'All', 'bold': True, 'lines': ['Synthetic sung doxology.']}]}}
            config['leadership'] = {'print_in_bulletin': True, 'clergy_and_staff': [
                {'name': 'Test Minister', 'role': 'Pastor'}], 'governing_body': {
                    'label': 'Parish Council', 'members': [{'name': 'Test Member', 'role': 'Member'}]}}
            config_path.write_text(yaml.safe_dump(config))
            profile_path = church / 'worship/profile.yaml'
            profile = yaml.safe_load(profile_path.read_text())
            profile['status'] = 'confirmed'
            profile['tradition_pack'] = 'episcopal-bcp-rite-ii'
            profile['defaults'].update(eucharistic_prayer='B', lords_prayer='traditional', prayers_of_the_people='III', blessing='omit', include_creed=True, include_confession=True, print_full_eucharistic_prayer=True, psalm_format='responsive_whole_verse', psalm_response_start='second', doxology='custom', prayer_presentation='continuous', rubric_style='concise')
            prayer = church / 'worship/liturgy/prayer.md'
            prayer.parent.mkdir(parents=True, exist_ok=True)
            prayer.write_text('# Synthetic Prayer\n\nCelebrant\tFirst synthetic prayer paragraph.\n\nCelebrant\tSecond synthetic prayer paragraph.\n\n*Then, facing the Holy Table, the Celebrant proceeds.*\n\n**People\tAmen.**\n')
            doxology = prayer.with_name('doxology.md')
            doxology.write_text('# Doxology\n\n**All\tOur custom synthetic doxology.**\n')
            verify_liturgy_source(church, prayer)
            verify_liturgy_source(church, doxology)
            profile['sources'].update(eucharistic_prayer=str(prayer.relative_to(church)), doxology=str(doxology.relative_to(church)))
            profile_path.write_text(yaml.safe_dump(profile))
            original_config, original_profile = config_path.read_bytes(), profile_path.read_bytes()
            resolved = resolve_worship_profile(church)
            self.assertEqual(resolved['status'], 'resolved', resolved)
            request = bulletin_input()
            request['liturgy'] = resolved['liturgy']
            request['readings']['first'].pop('text')
            request['readings']['first']['paragraphs'] = ['Forty days of synthetic testing.', 'A second verified paragraph.']
            request['readings']['psalm']['verses'] = [{'number': 1, 'text': 'The leader begins.'}, {'number': 2, 'text': 'The people answer.'}]
            result = produce(church, request)
            self.assertEqual(result['status'], 'ready_for_review', result)
            folder = Path(result['week_folder'])
            html = next(folder.glob('*.html')).read_text()
            self.assertIn('<strong>The people answer.</strong>', html)
            self.assertIn('<span class="vnum">2</span>', html)
            self.assertIn('class="service-person center"', html)
            self.assertNotIn('Then, facing the Holy Table', html)
            self.assertIn('The celebrant proceeds.', html)
            self.assertIn('Second synthetic prayer paragraph.', html)
            pdf_text = '\n'.join(p.extract_text() for p in PdfReader(next(folder.glob('*classic.pdf'))).pages)
            self.assertIn('Synthetic sung doxology.', pdf_text)
            self.assertIn('PARISH COUNCIL', pdf_text)
            self.assertIn('TestMember', ''.join(pdf_text.split()))
            self.assertNotIn('Our custom synthetic doxology.', pdf_text)
            next_week = copy.deepcopy(request)
            next_week['service']['date'] = '2026-09-27'
            next_week['service_music']['doxology'] = None
            result = produce(church, next_week)
            self.assertEqual(result['status'], 'ready_for_review', result)
            html = next(Path(result['week_folder']).glob('*.html')).read_text()
            self.assertIn('Our custom synthetic doxology.', html)
            self.assertNotIn('Synthetic sung doxology.', html)
            self.assertEqual(config_path.read_bytes(), original_config)
            self.assertEqual(profile_path.read_bytes(), original_profile)


    def test_produce_consumes_saved_worship_resolution_with_override_and_reversion(self):
        # No pre-resolution by the caller: produce() itself must call the
        # resolver and merge saved defaults before validation/rendering.
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church, closing_hymn_position="before_dismissal")

            week_one = bulletin_input()
            week_one["liturgy"] = {}
            result = produce(church, week_one)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = next(Path(result["week_folder"]).glob("*.html")).read_text()
            # Saved default: confession omitted, doxology omitted, closing
            # hymn before the spoken dismissal.
            self.assertNotIn("The Confession of Sin", html)
            self.assertLess(html.index("Test Closing"), html.index("The Dismissal"))

            week_two = bulletin_input()
            week_two["service"]["date"] = "2026-09-27"
            week_two["liturgy"] = {"include_confession": True}
            result_two = produce(church, week_two)
            self.assertEqual(result_two["status"], "ready_for_review", result_two)
            html_two = next(Path(result_two["week_folder"]).glob("*.html")).read_text()
            # An explicit weekly override wins over the saved default.
            self.assertIn("The Confession of Sin", html_two)

            week_three = bulletin_input()
            week_three["service"]["date"] = "2026-10-04"
            week_three["liturgy"] = {}
            result_three = produce(church, week_three)
            self.assertEqual(result_three["status"], "ready_for_review", result_three)
            html_three = next(Path(result_three["week_folder"]).glob("*.html")).read_text()
            # Week two's override does not stick; omitting it again reverts
            # to the saved default rather than carrying week two forward.
            self.assertNotIn("The Confession of Sin", html_three)

    def test_produce_blocks_on_unresolved_required_worship_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            # psalm_format is left blank (the scaffold default), so the
            # profile has a real, still-unresolved required choice.
            _configured_profile(church, psalm_format="")
            request = bulletin_input()
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "worship_resolution_needs_input")
            self.assertEqual(result["errors"][0]["field"], "liturgy.psalm_format")
            self.assertFalse(list((church / "bulletins").rglob("bulletin-production-receipt.json")))

    def test_produce_blocks_when_a_configured_variant_choice_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church)
            profile_path = church / "worship/profile.yaml"
            profile = yaml.safe_load(profile_path.read_text())
            profile["service_variants"] = {"principal": {
                "name": "Principal Sunday", "base_service_plan": "episcopal-rite-ii",
                "order_file": "worship/variants/principal.json",
                "confirmation_policy": "ask_each_week",
            }}
            profile_path.write_text(yaml.safe_dump(profile))
            request = bulletin_input()
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "worship_resolution_needs_input")
            self.assertEqual(result["errors"][0]["field"], "service.variant")

    def test_produce_blocks_rather_than_treats_a_missing_saved_profile_as_unconfigured(self):
        # church.yaml names worship/profile.yaml; deleting that saved file
        # is a broken connection, not a fresh unconfigured church. A silent
        # fallback here would make every saved worship preference vanish.
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church)
            (church / "worship/profile.yaml").unlink()
            request = bulletin_input()
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "worship_profile_missing")
            self.assertFalse(list((church / "bulletins").rglob("bulletin-production-receipt.json")))

    def test_produce_requires_an_explicit_time_among_several_saved_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config_path = church / "church.yaml"
            config = yaml.safe_load(config_path.read_text())
            config["church"]["regular_services"] = [
                {"day": "Sunday", "time": "9:00"},
                {"day": "Sunday", "time": "11:15"},
            ]
            config_path.write_text(yaml.safe_dump(config))
            request = bulletin_input()
            result = produce(church, request)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "service_time_choice_required")
            self.assertEqual(result["errors"][0]["field"], "service.time")

            request["service"]["time"] = "11:15 am"
            result_with_choice = produce(church, request)
            self.assertEqual(result_with_choice["status"], "ready_for_review", result_with_choice)
            html = next(Path(result_with_choice["week_folder"]).glob("*.html")).read_text()
            self.assertIn("11:15", html)

    def test_gospel_acclamation_defaults_to_lord_and_honors_a_saved_savior_choice(self):
        # No accidental change after default resolution: a church that has
        # never set gospel_acclamation still prints the standard BCP "Lord".
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church)
            request = bulletin_input()
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = next(Path(result["week_folder"]).glob("*.html")).read_text()
            self.assertIn("The Holy Gospel of our Lord Jesus Christ according to", html)
            self.assertNotIn("The Holy Gospel of our Savior Jesus Christ", html)

        # A church whose source verifiably reads "our Savior" instead.
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church, gospel_acclamation="savior")
            request = bulletin_input()
            request["service"]["date"] = "2026-09-27"
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = next(Path(result["week_folder"]).glob("*.html")).read_text()
            self.assertIn("The Holy Gospel of our Savior Jesus Christ according to", html)
            self.assertNotIn("The Holy Gospel of our Lord Jesus Christ according to", html)


if __name__ == '__main__':
    unittest.main()
