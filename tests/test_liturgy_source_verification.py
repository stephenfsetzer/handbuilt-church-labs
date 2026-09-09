from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.bulletin.liturgy_sources import LiturgySourceError, inspect_source, record_source
from skills.bulletin.bulletin_production import produce
from skills.bulletin.worship_resolution import _private_source_status
from tests.helpers import bulletin_input, make_church, verify_liturgy_source


class LiturgySourceVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = make_church(Path(self.temp.name))
        self.text = self.church / 'worship/liturgy/local.md'
        self.text.parent.mkdir(parents=True, exist_ok=True)
        self.text.write_text('# Local Prayer\n\nCelebrant\tSynthetic first prayer.\n')

    def test_missing_and_stale_evidence_block_before_render(self):
        request = bulletin_input()
        request['liturgy']['files'] = {'blessing': str(self.text.relative_to(self.church))}
        with patch('skills.bulletin.bulletin_production.interface._run') as render:
            result = produce(self.church, request)
            self.assertEqual(result['errors'][0]['code'], 'unverified_liturgy_source')
            render.assert_not_called()
        ok, reason = _private_source_status(str(self.text.relative_to(self.church)), choice='prayer', church_root=self.church, field='liturgy.sources.prayer')
        self.assertFalse(ok)
        self.assertIn('record', reason)
        verify_liturgy_source(self.church, self.text)
        self.assertEqual(inspect_source(self.church, self.text)['status'], 'verified')
        self.text.write_text('Changed after verification.')
        result = produce(self.church, request)
        self.assertEqual(result['errors'][0]['code'], 'unverified_liturgy_source')

    def test_public_record_binds_original_and_formatted_text(self):
        original = self.church / 'worship/original.txt'
        original.write_text('Synthetic original source.')
        args = dict(source_file=original, label='Synthetic source', location='https://source.invalid/prayer', verified_on='2026-09-08', method='public_source')
        record_source(self.church, self.text, **args)
        self.assertEqual(inspect_source(self.church, self.text)['status'], 'verified')
        original.write_text('Changed original.')
        self.assertEqual(inspect_source(self.church, self.text)['status'], 'needs_input')
        with self.assertRaises(LiturgySourceError):
            record_source(self.church, self.text, **{**args, 'source_file': self.text})
        with self.assertRaises(LiturgySourceError):
            record_source(self.church, self.text, **{**args, 'location': 'from memory'})

    def test_shipped_name_shadow_and_tampered_record_cannot_bypass(self):
        shadow = self.church / 'doxology'
        shadow.write_text('Unverified local shadow.')
        request = bulletin_input()
        request['liturgy'].update(doxology='custom', sources={'doxology': 'doxology'})
        self.assertEqual(produce(self.church, request)['errors'][0]['code'], 'unverified_liturgy_source')
        verify_liturgy_source(self.church, self.text)
        record_path = Path(str(self.text) + '.source.json')
        record = json.loads(record_path.read_text())
        record['source']['path'] = '../outside.txt'
        record_path.write_text(json.dumps(record))
        self.assertEqual(inspect_source(self.church, self.text)['status'], 'needs_input')

    def test_inactive_doxology_source_does_not_block_a_weekly_omission(self):
        request = bulletin_input()
        request['liturgy'].update(doxology='omit', files={'doxology': 'worship/liturgy/missing.md'})
        result = produce(self.church, request)
        self.assertEqual(result['status'], 'ready_for_review', result)

    def test_shipped_source_changes_invalidate_the_input_fingerprint(self):
        from skills.bulletin.bulletin_production.interface import _authority_fingerprint
        renderer = Path(self.temp.name) / 'renderer'
        (renderer / 'liturgy').mkdir(parents=True)
        shipped = renderer / 'liturgy/doxology.md'
        shipped.write_text('First synthetic public source.')
        with patch('skills.bulletin.bulletin_production.interface._renderer_dir', return_value=renderer):
            before = _authority_fingerprint(self.church, bulletin_input())
            shipped.write_text('Changed synthetic public source.')
            self.assertNotEqual(before, _authority_fingerprint(self.church, bulletin_input()))

    def test_record_refuses_paths_outside_private_church(self):
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('Outside source.')
        with self.assertRaises(LiturgySourceError):
            verify_liturgy_source(self.church, outside)


if __name__ == '__main__':
    unittest.main()
