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
from skills.bulletin.worship_resolution import resolve_worship_profile
from tests.helpers import bulletin_input, make_church, verify_liturgy_source


class SavedWorshipTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
