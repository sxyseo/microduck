import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from microduck_studio.core import StudioStore, _CANCELLED_RUNS
from microduck_studio.workbench import Workbench, digest
from microduck_studio.training_pipeline import TrainingPipeline, parameters
import microduck_studio.training_pipeline as pipeline_module


@pytest.fixture
def setup(tmp_path):
    store = StudioStore(tmp_path/'studio.db')
    project = store.create_project('recipe experiment',tmp_path)
    wb = Workbench(store,tmp_path/'studio.db')
    pipeline = TrainingPipeline(wb)
    training = pipeline.location(project['id'])
    (training/'.venv/bin').mkdir(parents=True)
    (training/'.venv/bin/python').write_text('test only')
    (training/'robot.xml').write_text('test model')
    (training/'bam.json').write_text('{"actuator":"xl330","model":"m6"}')
    data = pipeline.defaults(project['id'])['recipe']
    data.update(cad_path=str(training/'robot.xml'),bam_path=str(training/'bam.json'))
    wb.save(project['id'],data,0)
    return pipeline, wb, store, project['id']


@pytest.mark.parametrize('data',[
    {'num_envs':True},{'iterations':0},{'num_envs':33},{'seed':-1},
    {'kp_fw':float('nan')},{'kp_fw':True},{'delay_steps':[6,3]},{'delay_steps':[0,True]},[],
])
def test_parameters_reject_unsafe_or_ambiguous_values(data):
    with pytest.raises(ValueError):parameters(data)


def fake_preparer(monkeypatch):
    def popen(command,**kwargs):
        assert kwargs['env']['CUDA_VISIBLE_DEVICES']==''
        assert kwargs['env']['WANDB_MODE']=='disabled'
        assert isinstance(command,list) and command[2]=='prepare'
        config=json.loads(Path(command[3]).read_text())
        Path(config['model_archive']).write_bytes(b'isolated model and meshes')
        prepared={'completed':True,'model_sha256':digest(config['model_archive']),
                  'bam_sha256':digest(config['bam_snapshot']),'geometry_reference_matches':True}
        (Path(command[4])/'prepared.json').write_text(json.dumps(prepared))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(pipeline_module.subprocess,'Popen',popen)
    monkeypatch.setattr(pipeline_module,'capture_git_snapshot',lambda _: {'available':False})
    monkeypatch.setattr(pipeline_module,'_collect_process_output',lambda *a,**kw:dict(stdout='',stderr='',timed_out=False,stream_errors=[]))


def prepared(setup,monkeypatch):
    fake_preparer(monkeypatch)
    pipeline,_,_,pid=setup
    result=pipeline.prepare(pid,{'revision':1})
    assert result['status']=='ready'
    return result


def test_unknown_hardware_does_not_silently_use_xl330(setup):
    pipeline,wb,store,pid=setup
    value=wb.versions(pid)[0]['data'];value.update(servo_id='hl2915',power_id='3s-buck')
    wb.save(pid,value,1)
    result=pipeline.prepare(pid,{'revision':2})
    assert result['status']=='blocked'
    assert any('专用 BAM' in s for s in result['blockers'])
    assert store.project_report(pid)['hardware'] is None
    assert not store.project_report(pid)['runs']


def test_prepared_voltage_snapshot_and_recipe_revision_are_explicit(setup,monkeypatch):
    plan=prepared(setup,monkeypatch)
    pipeline,wb,store,pid=setup
    assert plan['actuator']['voltage_range_v']==[5,5]
    assert plan['actuator']['voltage_drop_gain_range']==[0,0]
    assert plan['recipe']['revision']==1
    assert plan['hardware_verified'] is False
    original=Path(plan['recipe']['data']['bam_path'])
    original.write_text('source changed after snapshot')
    pipeline.verify_inputs(plan)  # preserved snapshot remains reproducible
    wb.save(pid,{**wb.versions(pid)[0]['data'],'name':'next version'},1)
    assert pipeline.plan(pid,plan['plan_id'])[0]['recipe']['revision']==1
    assert store.project_report(pid)['hardware'] is None


def test_input_tampering_and_cross_project_plan_rejected(setup,monkeypatch):
    plan=prepared(setup,monkeypatch)
    pipeline,_,store,pid=setup
    other=store.create_project('other','/tmp')['id']
    with pytest.raises(KeyError):pipeline.plan(other,plan['plan_id'])
    with pytest.raises(ValueError):pipeline.start(pid,{'plan_id':plan['plan_id'],'confirm':False})
    old_plan={k:v for k,v in plan.items() if k!='source_snapshot'}
    with pytest.raises(ValueError,match='旧输入快照'):pipeline.verify_inputs(old_plan)
    Path(plan['bam_snapshot']).write_text('changed')
    with pytest.raises(ValueError,match='变化'):pipeline.start(pid,{'plan_id':plan['plan_id'],'confirm':True})
    assert not store.project_report(pid)['runs']


def test_expanded_training_requires_same_configuration_smoke(setup,monkeypatch):
    fake_preparer(monkeypatch)
    pipeline,_,_,pid=setup
    result=pipeline.prepare(pid,{'revision':1,'parameters':{'iterations':6}})
    assert result['status']=='blocked'
    assert '小规模实验' in result['blockers'][0]


def test_training_lock_is_shared_with_existing_training(setup,monkeypatch):
    plan=prepared(setup,monkeypatch)
    pipeline,_,store,pid=setup
    running=store._start_training_run(pid,'training')
    with pytest.raises(ValueError,match='已有训练'):pipeline.start(pid,{'plan_id':plan['plan_id'],'confirm':True})
    store.finish_run(running['id'],'failed',{})
    running=store._start_training_run(pid,'recipe_training')
    with pytest.raises(RuntimeError):store._start_training_run(pid,'training_smoke')
    store.finish_run(running['id'],'interrupted',{})


def test_launch_failure_is_terminal_and_plan_is_single_use(setup,monkeypatch):
    plan=prepared(setup,monkeypatch)
    pipeline,_,store,pid=setup
    def fail(*args,**kwargs):raise OSError('cannot launch')
    monkeypatch.setattr(pipeline_module.subprocess,'Popen',fail)
    with pytest.raises(ValueError,match='启动失败'):pipeline.start(pid,{'plan_id':plan['plan_id'],'confirm':True})
    run=store.project_report(pid)['runs'][0]
    assert run['status']=='failed'
    assert run['result']['artifacts_available'] is False
    with pytest.raises(ValueError,match='已执行'):pipeline.start(pid,{'plan_id':plan['plan_id'],'confirm':True})


@pytest.mark.parametrize('cancelled',[False,True])
def test_cancellation_overrides_complete_files_and_artifacts_are_verified(setup,monkeypatch,cancelled):
    plan=prepared(setup,monkeypatch)
    pipeline,wb,store,pid=setup
    run=store._start_training_run(pid,'recipe_training');folder=wb.artifacts/run['id'];folder.mkdir(parents=True)
    (folder/'policy.onnx').write_bytes(b'test policy');(folder/'checkpoint.pt').write_bytes(b'test weights')
    (folder/'manifest.json').write_text(json.dumps({'completed':True,'completed_iterations':2,
        'onnx_sha256':digest(folder/'policy.onnx'),'checkpoint_sha256':digest(folder/'checkpoint.pt')}))
    (folder/'trajectory.json').write_text(json.dumps({'completed':True,'frames':[{}]*126}))
    if cancelled:_CANCELLED_RUNS.add(run['id'])
    pipeline.collect(run['id'],SimpleNamespace(returncode=0),folder,plan,{'artifacts_available':False})
    result=store.get_run(run['id'])
    assert result['status']==('interrupted' if cancelled else 'passed')
    assert result['result']['artifacts_available'] is (not cancelled)
    assert result['result']['evidence_scope']=='training_or_simulation'
    if cancelled:
        with pytest.raises(ValueError):pipeline.artifact(pid,run['id'],'policy.onnx')
    else:
        assert pipeline.artifact(pid,run['id'],'policy.onnx')==folder/'policy.onnx'
        with pytest.raises(KeyError):pipeline.artifact('another',run['id'],'policy.onnx')
        (folder/'policy.onnx').write_bytes(b'changed')
        with pytest.raises(ValueError,match='变化'):pipeline.artifact(pid,run['id'],'policy.onnx')


def test_restart_does_not_promote_partial_output(setup):
    pipeline,wb,store,pid=setup
    run=store._start_training_run(pid,'recipe_training')
    store.update_run_result(run['id'],{'artifacts_available':False})
    restarted=StudioStore(store.db_path)
    state=restarted.get_run(run['id'])
    assert state['status']=='interrupted'
    assert state['result']['artifacts_available'] is False


def test_display_binding_rejects_changed_models_even_if_task_default_also_changes(tmp_path):
    import importlib.util
    path=Path(__file__).parents[1]/'workers/configured_training.py'
    spec=importlib.util.spec_from_file_location('configured_worker',path)
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    (tmp_path/'data').mkdir();archive=tmp_path/'model.zip';archive.write_bytes(b'verified model')
    display=tmp_path/'robot.glb';display.write_bytes(b'verified display')
    binding={'model_archive_sha256':digest(archive),'display_sha256':{'robot.glb':digest(display)}}
    (tmp_path/'data/display-reference.json').write_text(json.dumps(binding))
    assert worker.display_matches(archive,tmp_path)
    archive.write_bytes(b'new task model')
    assert not worker.display_matches(archive,tmp_path)
    archive.write_bytes(b'verified model');display.write_bytes(b'new display')
    assert not worker.display_matches(archive,tmp_path)


def test_historical_replay_checks_current_display_but_raw_data_remains_downloadable(setup,monkeypatch,tmp_path):
    pipeline,wb,store,pid=setup
    run=store._start_training_run(pid,'recipe_training');folder=wb.artifacts/run['id'];folder.mkdir(parents=True)
    path=folder/'trajectory.json';path.write_text('{"completed":true}')
    display=tmp_path/'display.glb';display.write_bytes(b'verified display')
    binding={'model_archive_sha256':'original','display_sha256':{'display.glb':digest(display)}}
    store.finish_run(run['id'],'passed',{'artifacts_available':True,'artifact_sha256':{'trajectory.json':digest(path)},
        'manifest':{'inputs':{'geometry_reference_matches':True,'model_sha256':'original'}}})
    monkeypatch.setattr(pipeline_module,'ROOT',tmp_path)
    monkeypatch.setattr(pipeline_module,'read_data',lambda _:binding)
    assert pipeline.artifact(pid,run['id'],'trajectory.json',True)==path
    display.write_bytes(b'new geometry')
    with pytest.raises(ValueError,match='展示模型不匹配'):pipeline.artifact(pid,run['id'],'trajectory.json',True)
    assert pipeline.artifact(pid,run['id'],'trajectory.json')==path


def test_uncommitted_source_contents_are_preserved_in_plan(setup,monkeypatch):
    import zipfile
    pipeline,_,_,pid=setup
    training=pipeline.location(pid);source=training/'src/tasks.py';source.parent.mkdir();source.write_text('CUSTOM_VALUE = 123\n')
    plan=prepared(setup,monkeypatch)
    with zipfile.ZipFile(plan['source_snapshot']['path']) as archive:
        assert archive.read('training/src/tasks.py')==b'CUSTOM_VALUE = 123\n'
        assert 'studio/workers/configured_training.py' in archive.namelist()
    source.write_text('CUSTOM_VALUE = 456\n')
    with pytest.raises(ValueError,match='变化'):pipeline.verify_inputs(plan)
