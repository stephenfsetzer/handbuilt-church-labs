from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from pypdf import PdfReader

from skills.bulletin.sunday_library import SundayLibraryError, catalog, lookup, verify_shipped_liturgy
from skills.bulletin.bulletin_production import produce
from skills.bulletin.bulletin_production.interface import _liturgy_identifier, _validate_reading_presentation, _validate_liturgy_sources, StageFailure
from skills.bulletin.renderer.render_bulletin import configured_liturgy_file, liturgy_section, render_blocks
from skills.bulletin.worship_resolution import resolve_profile_data
from tests.helpers import REPO_ROOT, bulletin_input, make_church


class SundayLibraryTest(unittest.TestCase):
    def test_every_advertised_standard_choice_resolves_offline(self):
        pack = yaml.safe_load((REPO_ROOT / 'skills/bulletin/traditions/episcopal-bcp-rite-ii.yaml').read_text())
        for prayer in ('A', 'B', 'C', 'D'):
            for form in ('I', 'II', 'III', 'IV', 'V', 'VI'):
                for lord in ('traditional', 'contemporary'):
                    defaults = dict(eucharistic_prayer=prayer, prayers_of_the_people=form, lords_prayer=lord, blessing='omit')
                    result = resolve_profile_data({'status': 'confirmed', 'defaults': defaults}, pack)
                    self.assertEqual(result['status'], 'resolved', result)
                    for key, choice in defaults.items():
                        if key == 'blessing':
                            continue
                        unit = pack['shipped_sources'][key][choice]
                        self.assertEqual(_liturgy_identifier(key, choice, defaults), unit)
                        self.assertEqual(configured_liturgy_file({'liturgy': defaults}, key), unit)
                        verify_shipped_liturgy(unit)

    def test_selected_psalm_preserves_numbering_and_response_pattern(self):
        self.assertEqual(len(catalog('psalms')), 150)
        psalm = lookup('psalms', '23', verses='1-3,5-6')
        self.assertEqual([v['number'] for v in psalm['verses']], [1,2,3,5,6])
        self.assertIn('shepherd', psalm['verses'][0]['first'])
        self.assertTrue(psalm['verses'][0]['second'])
        self.assertIn('#page=', psalm['source']['location'])
        whole = lookup('psalms', '23', verses='1-2', psalm_format='responsive_whole_verse')
        self.assertIn('text', whole['verses'][0])
        for invalid in ('0', '7', '3-1', '1,1', '1-2,2-3', '6,1'):
            with self.subTest(verses=invalid), self.assertRaises(SundayLibraryError):
                lookup('psalms', '23', verses=invalid)

    def test_bundled_source_tampering_cannot_pass_as_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / 'skills/bulletin/resources/bcp1979'
            resource.mkdir(parents=True)
            (resource / 'manifest.json').write_text(json.dumps({'liturgy': {'test': {'sha256': 'mismatch'}}}))
            source = root / 'skills/bulletin/renderer/liturgy/test.md'
            source.parent.mkdir(parents=True)
            source.write_text('Changed text.')
            with self.assertRaises(SundayLibraryError):
                verify_shipped_liturgy('test', plugin_root=root)

    def test_full_prayer_aliases_and_preface_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            for letter in 'ABCD':
                request = bulletin_input()
                request['liturgy'].update(eucharistic_prayer=letter, print_full_eucharistic_prayer=True)
                self.assertEqual(_liturgy_identifier('eucharistic_prayer', letter, request['liturgy']), f'eucharistic-prayer-{letter.lower()}-full')
                request['proper_preface'] = ''
                if letter in 'AB':
                    with self.assertRaises(StageFailure):
                        _validate_liturgy_sources(request, church)
                else:
                    _validate_liturgy_sources(request, church)

    def test_psalm_without_printed_division_keeps_its_words(self):
        for mode in ('responsive_half_verse', 'responsive_whole_verse', 'unison', 'plain'):
            reading = lookup('psalms', '24', verses='10', psalm_format=mode)
            _validate_reading_presentation(reading, 'psalm')
            self.assertNotIn('*', reading['text'])
            self.assertIn('King of glory', reading['text'])

    def test_form_vi_responses_and_explicit_confession_omission(self):
        html = liturgy_section('prayers-of-the-people-vi', {})
        self.assertGreaterEqual(html.count('dialogue response'), 9)
        omitted = liturgy_section('prayers-of-the-people-vi', {'omit_form_vi_confession': True})
        self.assertNotIn('Have mercy upon us, most merciful Father', omitted)
        self.assertIn('Who put their trust in you', omitted)
        self.assertIn('concluding Collect', omitted)

    def test_prayer_ending_stays_with_amen_without_repeated_label(self):
        html = render_blocks([
            ('prose', [(0, 'Through Christ, and with Christ, and in Christ.')]),
            ('dialogue', {'speaker': 'People', 'bold': True, 'lines': [(None, 'AMEN.')]}),
        ], {})
        self.assertIn('class="dialogue-group"', html)
        self.assertNotIn('Celebrant', html)
        self.assertIn('AMEN.', html)

    def test_form_vi_production_has_one_confession(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            request = bulletin_input()
            request['liturgy'].update(prayers_of_the_people='VI')
            result = produce(church, request)
            self.assertEqual(result['status'], 'ready_for_review', result)
            pdf = next(Path(result['week_folder']).glob('*classic.pdf'))
            text = ''.join(''.join(p.extract_text().split()) for p in PdfReader(pdf).pages)
            self.assertEqual(text.count('Havemercyuponus,mostmercifulFather'), 1)
            self.assertNotIn('LetusconfessoursinsagainstGodandourneighbor', text)
            self.assertEqual(text.count('AlmightyGodhavemercyonyou'), 1)

    def test_standard_prayer_b_produces_without_private_prayer_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            request = bulletin_input()
            request['liturgy'].update(eucharistic_prayer='B', lords_prayer='contemporary', prayers_of_the_people='IV', print_full_eucharistic_prayer=True)
            with patch('urllib.request.urlopen', side_effect=AssertionError('Network is not needed for bundled liturgy')):
                result = produce(church, request)
            self.assertEqual(result['status'], 'ready_for_review', result)
            pdf = next(Path(result['week_folder']).glob('*classic.pdf'))
            text = '\n'.join(p.extract_text() for p in PdfReader(pdf).pages)
            self.assertIn('givethankstoyou', ''.join(text.split()))
            self.assertIn('the goodness and love', text)
            self.assertIn('Our Father in heaven', text)
            self.assertFalse(any((church / 'worship/liturgy').glob('*.md')))


if __name__ == '__main__':
    unittest.main()
