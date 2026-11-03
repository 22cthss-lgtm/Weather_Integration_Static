from datetime import datetime, timedelta
from dataclasses import replace
from pathlib import Path
import copy,json,sys,tempfile,unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.current_day import publish_current_history
from src.history_reconciliation import history_scope
from src.services.cwa_service import CWAService
from src.snapshots import validate_resource,export_snapshot,restore_snapshot

NOW=datetime.fromisoformat('2026-11-03T12:00:00+08:00')
POLICY={'interval_seconds':3600,'max_rechecks':3,'max_slots_per_run':12,'current_day_only':True}

class HistoryContractTests(unittest.TestCase):
    def test_mixed_snapshot_preserves_legacy_bytes_and_v2_partition(self):
        from src.pages_package import pack_snapshot,unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root=Path(root)
            export_snapshot(Path(__file__).resolve().parents[2]/'frontend/public/data',root/'seed')
            original={p.relative_to(root/'seed/data').as_posix():p.read_bytes() for p in (root/'seed/data').rglob('*.json')}
            # CI seeds public with the live candidate before running tests.
            # Pick an absent fixture day instead of overwriting a live day.
            clock=NOW
            while f'images/radar/history/{clock.date()}.json' in original:
                clock-=timedelta(days=1)
            latest=replace(self.latest(),image_time=clock.isoformat())
            with history_scope(POLICY,{},clock),patch.object(CWAService,'check_image_url',return_value=True):
                v2=publish_current_history(CWAService(),latest,root/'seed/data/images')
            export_snapshot(root/'seed/data',root/'mixed')
            package=pack_snapshot(root/'mixed',root/'mixed.zip')
            unpack_snapshot(root/'mixed.zip',package['sha256'],root/'restored')
            for name,raw in original.items():
                self.assertEqual((root/'restored'/name).read_bytes(),raw)
            actual=json.loads((root/f'restored/images/radar/history/{clock.date()}.json').read_text())
            self.assertEqual(actual,v2)

    def test_valid_latest_is_written_when_pending_history_remains(self):
        from src.current_day import update_current_product
        for kind in ('radar','satellite','rainfall'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
                with history_scope(POLICY,{},NOW) as ctx, \
                     patch.object(CWAService,f'fetch_{kind}',return_value=iter([self.latest(kind)])), \
                     patch.object(CWAService,'check_image_url',return_value=True), \
                     patch('src.current_day.update_daily_rainfall'):
                    update_current_product(kind,root)
                    self.assertTrue(ctx.outcomes[kind]['latest_ok'])
                latest=json.loads((Path(root)/kind/'latest.json').read_text())
                history=json.loads((Path(root)/kind/'history/2026-11-03.json').read_text())
                self.assertEqual(latest['image_time'],self.latest(kind).image_time)
                self.assertTrue(history['pending'])
                self.assertFalse(history['complete'])

    def latest(self,kind='radar',clock='12:00'):
        return CWAService().build_payload(kind,'Latest','https://www.cwa.gov.tw/latest.png',
                    'https://www.cwa.gov.tw/',f'2026-11-03T{clock}:00+08:00')

    def test_pending_missing_failed_are_separate_without_changing_probe_budget(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root,history_scope(POLICY,{},NOW):
            outcomes=[False,RuntimeError('PRIVATE')]+[True]*10
            with patch.object(service,'check_image_url',side_effect=outcomes) as check:
                result=publish_current_history(service,self.latest(),root)
            self.assertEqual(check.call_count,12)
            self.assertEqual(result['schema_version'],2)
            self.assertEqual(len(result['pending']),60)
            self.assertEqual(result['missing'],['2026-11-03T00:00:00+08:00'])
            self.assertEqual(result['failed'],['2026-11-03T00:10:00+08:00'])
            self.assertEqual(result['official_missing'],[])
            self.assertEqual(result['legacy_unknown'],[])
            validate_resource('images/radar/history/2026-11-03.json',result)
            for field in ('pending','missing','failed','official_missing','legacy_unknown'):
                bad=copy.deepcopy(result);bad[field].append(result['items'][0]['image_time'])
                with self.assertRaises(ValueError):validate_resource('images/radar/history/2026-11-03.json',bad)
            bad=copy.deepcopy(result);bad['complete']=True
            with self.assertRaises(ValueError):validate_resource('images/radar/history/2026-11-03.json',bad)

    def test_legacy_ambiguous_gaps_stay_unknown_without_trusted_state(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            with patch.object(service,'check_image_url',side_effect=lambda url: '1200' in url):
                legacy=publish_current_history(service,self.latest(),root,now=NOW)
            # Freeze an old v1 document: its failed array may contain pending.
            legacy={k:v for k,v in legacy.items() if k not in ('schema_version','pending','official_missing','legacy_unknown')}
            path=Path(root)/'radar/history/2026-11-03.json';path.write_text(json.dumps(legacy),encoding='utf-8')
            validate_resource('images/radar/history/2026-11-03.json',legacy)
            with history_scope(POLICY,{},NOW),patch.object(service,'check_image_url',return_value=True) as check:
                upgraded=publish_current_history(service,self.latest(),root)
            self.assertEqual(check.call_count,12)
            self.assertEqual(len(upgraded['legacy_unknown']),60)
            self.assertEqual(upgraded['pending'],[])
            self.assertEqual(upgraded['failed'],[])

    def test_trusted_gap_state_can_classify_legacy_public_failed(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            with history_scope(POLICY,{},NOW) as ctx,patch.object(service,'check_image_url',return_value=True):
                result=publish_current_history(service,self.latest(),root)
                saved=ctx.gaps
            old={k:v for k,v in result.items() if k not in ('schema_version','pending','official_missing','legacy_unknown')}
            old['failed']+=result['pending'];old['complete']=False
            (Path(root)/'radar/history/2026-11-03.json').write_text(json.dumps(old),encoding='utf-8')
            with history_scope(POLICY,saved,NOW),patch.object(service,'check_image_url',return_value=True):
                result=publish_current_history(service,self.latest(),root)
            self.assertEqual(len(result['pending']),48)
            self.assertEqual(result['legacy_unknown'],[])

    def test_official_exclusions_are_not_actual_404_and_never_probed(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root,history_scope(POLICY,{},NOW):
            with patch.object(service,'check_image_url',return_value=True) as check:
                result=publish_current_history(service,self.latest('satellite'),root)
            self.assertEqual(result['official_missing'],['2026-11-03T10:40:00+08:00'])
            self.assertEqual(result['missing'],[])
            self.assertEqual(check.call_count,12)

    def test_legacy_gap_with_inconsistent_private_failure_evidence_stays_unknown(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            with patch.object(service,'check_image_url',side_effect=lambda url:'1200' in url):
                result=publish_current_history(service,self.latest(),root,now=NOW)
            old={k:v for k,v in result.items() if k not in ('schema_version','pending','official_missing','legacy_unknown')}
            (Path(root)/'radar/history/2026-11-03.json').write_text(json.dumps(old),encoding='utf-8')
            state={'radar':{'2026-11-03':{'10:50':{'classification':'failed','attempts':0,'last_attempt_at':None,'next_retry_at':None}}}}
            with history_scope(POLICY,state,NOW),patch.object(service,'check_image_url',return_value=True):
                result=publish_current_history(service,self.latest(),root)
            self.assertIn('2026-11-03T10:50:00+08:00',result['legacy_unknown'])
            self.assertEqual(result['failed'],[])

    def test_explicit_rescan_keeps_success_instead_of_overlapping_new_missing(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            with patch.object(service,'check_image_url',return_value=True):
                publish_current_history(service,self.latest(clock='00:20'),root,now=NOW)
            with patch.object(service,'check_image_url',side_effect=lambda url:'0020' in url):
                result=publish_current_history(service,self.latest(clock='00:20'),root,now=NOW)
            self.assertEqual(len(result['items']),3)
            self.assertEqual(result['missing'],[])
            self.assertTrue(result['complete'])

    def test_v2_classifications_survive_missing_private_state_until_reprobed(self):
        service=CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            with history_scope(POLICY,{},NOW),patch.object(service,'check_image_url',return_value=False):
                first=publish_current_history(service,self.latest(),root)
            with history_scope({**POLICY,'max_slots_per_run':1},{},NOW),patch.object(service,'check_image_url',return_value=True):
                result=publish_current_history(service,self.latest(),root)
            self.assertEqual(len(first['pending']),len(result['pending']))
            self.assertEqual(result['legacy_unknown'],[])
            self.assertEqual(result['failed'],[])
            self.assertEqual(result['missing'],first['missing'][1:])
            for version in (1,3,True):
                bad=copy.deepcopy(result);bad['schema_version']=version
                with self.assertRaises(ValueError):validate_resource('images/radar/history/2026-11-03.json',bad)

if __name__=='__main__':unittest.main()
