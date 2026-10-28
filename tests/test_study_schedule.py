"""Optional FSRS integration tests; local package only, no model calls."""
import copy
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from devtools.workers import WorkerError
from newton.study import demo_bundle
from newton.study_contract import raw_bundle
from newton.study_library import sources
from newton.study_schedule import schedule
from newton.study_store import StudyStore

NOW=datetime(2026,10,28,12,tzinfo=timezone.utc)

class ScheduleTests(unittest.TestCase):
    def setup_deck(self,folder,engine='simple'):
        store=StudyStore(folder);p=store.create({'review_scheduler':engine})
        a=store.add_bundle(p['id'],demo_bundle(),sources({}));b=a['bundle']['blocks'][2]
        store.accept_deck(p['id'],a['id'],b['id'])
        return store,p['id'],a['id'],b['id'],b['cards'][0]['id']
    def test_old_profiles_still_use_fixed_schedule(self):
        with TemporaryDirectory() as folder:
            s,i,a,b,c=self.setup_deck(folder)
            d=s.read(i);d['profile'].pop('review_scheduler');s.save(d)
            s.review(i,a,b,c,'Good',now=NOW)
            result=s.read(i)
            card=result['artifacts'][0]['bundle']['blocks'][2]['cards'][0]
            self.assertEqual(card['next_due'],(NOW+timedelta(days=3)).isoformat())
            self.assertEqual(result['profile']['review_scheduler'],'simple')
            self.assertEqual(result['reviews'][-1]['scheduler'],'simple-v1')
    def test_missing_package_fails_atomically_without_changing_schedule(self):
        with TemporaryDirectory() as folder:
            s,i,a,b,c=self.setup_deck(folder,'fsrs');before=s.path(i).read_bytes()
            with patch('newton.study_schedule.version',side_effect=__import__('importlib.metadata',fromlist=['PackageNotFoundError']).PackageNotFoundError):
                with self.assertRaisesRegex(WorkerError,'not_installed'):s.review(i,a,b,c,'Good',now=NOW)
            self.assertEqual(before,s.path(i).read_bytes())
    def test_wrong_version_and_invalid_time_fail_clearly(self):
        card={'id':'a'*32}
        with patch('newton.study_schedule.version',return_value='999'):
            with self.assertRaisesRegex(WorkerError,'version_unsupported'):schedule(card,'Good',NOW,'fsrs')
        with self.assertRaisesRegex(WorkerError,'timezone'):schedule(card,'Good',datetime(2026,1,1))
    @unittest.skipUnless(find_spec('fsrs'),'optional fsrs package not installed')
    def test_actual_fsrs_matches_upstream_and_persists_across_reload(self):
        from fsrs import Card, Rating, Scheduler
        with TemporaryDirectory() as folder:
            s,i,a,b,c=self.setup_deck(folder,'fsrs')
            expected,_=Scheduler(enable_fuzzing=False,desired_retention=.9).review_card(Card(card_id=int(c[:15],16),due=NOW),Rating.Good,review_datetime=NOW)
            s.review(i,a,b,c,'Good',now=NOW)
            saved=StudyStore(folder).read(i);card=saved['artifacts'][0]['bundle']['blocks'][2]['cards'][0]
            self.assertEqual(card['next_due'],expected.due.isoformat())
            self.assertEqual(card['scheduling']['card'],expected.to_dict())
            self.assertEqual(saved['reviews'][-1]['scheduler'],'fsrs-6.3.2')
            s.review(i,a,b,c,'Easy',now=NOW+timedelta(days=2))
            later=s.read(i)['artifacts'][0]['bundle']['blocks'][2]['cards'][0]
            self.assertNotEqual(card['scheduling'],later['scheduling'])
            self.assertGreater(datetime.fromisoformat(later['next_due']),NOW+timedelta(days=2))
    @unittest.skipUnless(find_spec('fsrs'),'optional fsrs package not installed')
    def test_deterministic_schedule_edit_reset_and_safe_export(self):
        card={'id':'a'*32};original=copy.deepcopy(card)
        self.assertEqual(schedule(card,'Good',NOW,'fsrs'),schedule(card,'Good',NOW,'fsrs'))
        self.assertEqual(card,original)
        with TemporaryDirectory() as folder:
            s,i,a,b,c=self.setup_deck(folder,'fsrs');s.review(i,a,b,c,'Good',now=NOW)
            portable=json.loads(s.export_deck(i,a,b));self.assertNotIn('scheduling',str(portable))
            s.edit_card(i,a,b,c,{'back':'Edited answer'})
            edited=s.read(i)['artifacts'][0]['bundle']['blocks'][2]
            self.assertNotIn('scheduling',edited['cards'][0]);self.assertIsNone(edited['cards'][0]['next_due']);self.assertFalse(edited['active'])
    @unittest.skipUnless(find_spec('fsrs'),'optional fsrs package not installed')
    def test_backdated_fsrs_review_preserves_saved_progress(self):
        with TemporaryDirectory() as folder:
            s,i,a,b,c=self.setup_deck(folder,'fsrs');s.review(i,a,b,c,'Good',now=NOW);before=s.path(i).read_bytes()
            with self.assertRaisesRegex(WorkerError,'before_last_review'):s.review(i,a,b,c,'Again',now=NOW-timedelta(days=1))
            self.assertEqual(before,s.path(i).read_bytes())
