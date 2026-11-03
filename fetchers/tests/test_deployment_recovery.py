"""Offline persisted-data/deployment recovery boundaries."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.due_refresh import prepare_due, load_policy
from src.scheduling import default_tasks
from src.pages_package import pack_snapshot, unpack_snapshot
from src.snapshots import export_snapshot


class DeploymentRecoveryTests(unittest.TestCase):
    def test_saved_failed_deploy_unchanged_next_run_repairs_then_skips(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            export_snapshot(Path(__file__).resolve().parents[2]/'frontend/public/data', root/'seed')
            base = pack_snapshot(root/'seed', root/'base.zip', now=now)
            selected = unpack_snapshot(root/'base.zip', base['sha256'], root/'base-data', now=now)
            online = {'state':'verified', 'marker':{'content_id': selected['content_id']},
                      'content_created_at':selected['content_created_at']}
            def update(kind, images):
                p=images/kind/'latest.json'; d=json.loads(p.read_bytes())
                d['title'] += ' real semantic change'
                p.write_text(json.dumps(d), encoding='utf-8')
            config=default_tasks()
            from src.scheduling import new_state, record_result
            scheduler=new_state(selected['content_id'],now,config)
            for kind in config:
                if kind != 'sst': record_result(scheduler,kind,now,True,task_config=config)
            initial_state={'schema_version':1,'content_id':selected['content_id'],'scheduler':scheduler,'history':{}}
            first=prepare_due(root/'base.zip',base['sha256'],root/'first',mode='refresh',policy=load_policy(),
                              task_config=config,update=update,now=now+timedelta(seconds=1),deployment_document=online,
                              state_document=initial_state)
            self.assertTrue(first['deploy']); self.assertTrue(first['save_snapshot'])
            archive=root/'first/output/weather-snapshot.zip'
            persisted=archive.read_bytes()  # Saved + readback succeeded; deploy then failed.
            from src.cloud_snapshots import CloudSnapshots
            class SavedClient:
                def list_artifacts(self,name):
                    return [{'id':1 if name=='weather-snapshot' else 2,'workflow_run':{'id':2}}]
                def get_run(self,run_id):
                    return {'id':run_id,'path':'.github/workflows/pages-manual.yml','head_branch':'main',
                            'event':'workflow_dispatch','status':'completed','conclusion':'failure','run_number':2}
                def download_artifact(self,record): return persisted
                def download_state(self,record): return json.dumps(first['scheduler_state']).encode()
            env={'RUNNER_TEMP':str(root/'recovered'),'DEFAULT_BRANCH':'main','GITHUB_RUN_ID':'3','GITHUB_RUN_NUMBER':'3'}
            recovered=CloudSnapshots(SavedClient(),env,now=now+timedelta(minutes=1)).resolve()
            self.assertEqual(recovered['sha256'],first['sha256'])
            restored=json.loads((root/'recovered/source-state.json').read_text())
            self.assertEqual(restored,first['scheduler_state'])
            source=Mock(side_effect=AssertionError('not due: must not fetch'))
            second=prepare_due(root/'recovered/pages-input/weather-snapshot.zip',recovered['sha256'],root/'second',mode='refresh',policy=load_policy(),
                               task_config=config,update=source,now=now+timedelta(minutes=1),
                               state_document=restored,deployment_document=online)
            self.assertTrue(second['deploy']); self.assertFalse(second['save_snapshot'])
            self.assertFalse(second['data_changed'])
            self.assertEqual(second['deployment_reason'],'saved_version_not_online')
            self.assertFalse((root/'second/output/weather-snapshot.zip').exists())
            self.assertEqual(archive.read_bytes(),persisted)
            self.assertEqual((root/'second/site-data/images/sst/latest.json').read_bytes(),
                             (root/'first/site-data/images/sst/latest.json').read_bytes())
            # Simulate a successful deploy by changing only the online marker.
            online={'state':'verified','marker':{'content_id':second['content_id']},
                    'content_created_at':second['content_created_at']}
            third=prepare_due(archive,first['sha256'],root/'third',mode='refresh',policy=load_policy(),
                              task_config=config,update=source,now=now+timedelta(minutes=2),
                              state_document=second['scheduler_state'],deployment_document=online)
            self.assertFalse(third['deploy']); self.assertFalse(third['save_snapshot'])
            self.assertEqual(third['deployment_reason'],'already_online')
            source.assert_not_called()

    def test_deployment_decision_fails_closed_without_known_order(self):
        from src.due_refresh import deployment_decision
        content={'content_id':'a'*64,'content_created_at':'2026-11-02T10:00:00+00:00'}
        for state in ('unavailable','invalid','untrusted','version_unknown','newer_run'):
            self.assertFalse(deployment_decision('refresh',False,content,{}, {'state':state})[0])
        online={'state':'verified','marker':{'content_id':'b'*64},'content_created_at':'2026-11-02T11:00:00+00:00'}
        self.assertFalse(deployment_decision('refresh',False,content,{},online)[0])
        online['content_created_at']='2026-11-02T09:00:00+00:00'
        self.assertFalse(deployment_decision('refresh',False,content,
                    {'sst':{'state':'retained_after_failure'}},online)[0])
        self.assertTrue(deployment_decision('refresh',False,content,{'sst':{'state':'checked_unchanged'}},online)[0])
        self.assertFalse(deployment_decision('refresh',False,content,
                    {'sst':{'state':'retained_after_failure'},'radar':{'state':'not_due'}},online)[0])

    def test_corrupt_online_state_never_leaks_arbitrary_diagnostic(self):
        from src.due_refresh import deployment_decision
        for state in ('SECRET',{'token':'PRIVATE'},None):
            self.assertEqual(deployment_decision('refresh',True,{}, {}, {'state':state}), (False,'online_invalid'))

    def test_changed_content_from_older_seed_cannot_roll_back_online_resources(self):
        from src.due_refresh import deployment_decision
        content={'content_id':'a'*64,'content_created_at':'2026-11-02T11:00:00+00:00'}
        online={'state':'verified','marker':{'content_id':'b'*64},'content_created_at':'2026-11-02T10:00:00+00:00'}
        seed={'content_id':'c'*64,'content_created_at':'2026-11-02T09:00:00+00:00'}
        self.assertFalse(deployment_decision('refresh',True,content,{},online,selected_content=seed)[0])

    def test_older_seed_cannot_be_saved_with_fresh_timestamp_to_bypass_next_run(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory);now=datetime.now(timezone.utc)
            export_snapshot(Path(__file__).resolve().parents[2]/'frontend/public/data',root/'seed')
            base=pack_snapshot(root/'seed',root/'base.zip',now=now-timedelta(hours=2))
            def update(kind,images):
                p=images/kind/'latest.json';data=json.loads(p.read_bytes());data['title']+=' changed'
                p.write_text(json.dumps(data),encoding='utf-8')
            online={'state':'verified','marker':{'content_id':'b'*64},'content_created_at':(now-timedelta(hours=1)).isoformat()}
            with self.assertRaisesRegex(ValueError,'seed_version_not_newer'):
                prepare_due(root/'base.zip',base['sha256'],root/'work',mode='refresh',policy=load_policy(),
                            task_config={'sst':default_tasks()['sst']},update=update,now=now,deployment_document=online)
            self.assertFalse((root/'work/output/weather-snapshot.zip').exists())

    def test_unknown_online_baseline_cannot_save_timestamp_laundered_candidate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory);now=datetime.now(timezone.utc)
            export_snapshot(Path(__file__).resolve().parents[2]/'frontend/public/data',root/'seed')
            base=pack_snapshot(root/'seed',root/'base.zip',now=now)
            def update(kind,images):
                p=images/kind/'latest.json';data=json.loads(p.read_bytes());data['title']+=' changed'
                p.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'online_unavailable'):
                prepare_due(root/'base.zip',base['sha256'],root/'work',mode='refresh',policy=load_policy(),
                            task_config={'sst':default_tasks()['sst']},update=update,now=now+timedelta(seconds=1),
                            deployment_document={'state':'unavailable'})
            self.assertFalse((root/'work/output/weather-snapshot.zip').exists())
            decision=json.loads((root/'work/deployment-decision.json').read_text())
            self.assertFalse(decision['save_snapshot']);self.assertFalse(decision['deploy'])
