import json
from pathlib import Path
import pytest
from microduck_studio.core import StudioStore
from microduck_studio.visual import RevisionConflict, model_manifest
from microduck_studio.workbench import Workbench, read_data

@pytest.fixture
def setup(tmp_path):
    db=tmp_path/'studio.db'
    store=StudioStore(db)
    project=store.create_project('test',tmp_path)
    return Workbench(store,db), project['id'], store


def recipe(**changes):
    return dict(name='Build A',servo_id='xl330-m288',power_id='regulated-5',controller_id='radxa-zero3w',camera_id='none',**changes)


def test_power_windows_do_not_hide_unknowns(setup):
    wb,pid,_=setup
    d=recipe()
    assert wb.validate(pid,d)['checks']['power_window']=='matched'
    d['power_id']='2s-buck'
    assert wb.validate(pid,d)['checks']['power_window']=='blocked'
    d['servo_id']='sts3215'
    assert wb.validate(pid,d)['checks']['power_window']=='blocked'
    d.update(servo_id='hl2915',power_id='3s-buck')
    result=wb.validate(pid,d)
    assert result['checks']['power_window']=='matched'
    assert any('BAM' in x for x in result['checks']['training_blockers'])
    assert result['checks']['hardware_verified'] is False


def test_recipe_versions_and_projects_are_isolated(setup):
    wb,pid,store=setup
    first=wb.save(pid,recipe(),0)
    assert first['revision']==1
    with pytest.raises(RevisionConflict): wb.save(pid,recipe(),0)
    other=store.create_project('other','/tmp')['id']
    assert wb.versions(other)==[]
    restored=Workbench(store,wb.artifacts.parent/'studio.db')
    assert restored.versions(pid)[0]==first
    assert store.project_report(pid)['hardware'] is None
    with pytest.raises(KeyError):wb.save('missing',recipe(),0)


def test_new_servo_cannot_assert_hardware_verification(setup):
    wb,pid,store=setup
    candidate=dict(name='Test servo 12V',dimensions_mm=[34,20,23],voltage_range_v=[9,14],mass_g=28,protocol='feetech_ttl',source='spec.pdf',qualification='bench_verified',bam_family='xl330')
    saved=wb.add_servo(pid,candidate)
    assert saved['qualification']=='candidate'
    assert saved['bam_family'] is None
    assert saved in wb.catalog(pid)['servos']
    other=store.create_project('other','/tmp')['id']
    assert saved not in wb.catalog(other)['servos']
    for field,value in [('dimensions_mm',[True,20,23]),('voltage_range_v',[14,9]),('mass_g',float('nan')),('source','')]:
        with pytest.raises(ValueError):wb.add_servo(pid,{**candidate,field:value})


def test_guide_covers_real_model_without_marking_assembly_passed():
    guide=read_data('installation-guide.json')
    model=model_manifest()
    assert guide['model_id']==model['modelId']
    groups={p['assemblyId'] for p in model['parts']}
    covered=set()
    for step in guide['steps']:
        assert set(step['assemblies']) <= groups
        assert step['acceptance'] and step['instructions']
        covered.update(step['assemblies'])
    assert covered==groups
    assert set(read_data('model-body-map.json'))==groups


def test_simulation_missing_environment_and_invalid_duration_fail_closed(setup):
    wb,pid,store=setup
    for n in [0,11,True,1.5]:
        with pytest.raises(ValueError):wb.simulation(pid,n)
    with pytest.raises(ValueError,match='环境'): wb.simulation(pid)
    assert not store.project_report(pid)['runs']


def test_trajectory_cannot_cross_projects_or_read_incomplete_file(setup):
    wb,pid,store=setup
    other=store.create_project('other','/tmp')['id']
    run=store.start_run(pid,'reference_simulation')
    with pytest.raises(KeyError):wb.trajectory(other,run['id'])
    with pytest.raises(ValueError):wb.trajectory(pid,run['id'])
    store.finish_run(run['id'],'interrupted',{'trajectory_available':False})
    with pytest.raises(ValueError):wb.trajectory(pid,run['id'])


def test_cancellation_wins_over_a_complete_trajectory(setup, monkeypatch, tmp_path):
    import microduck_studio.workbench as module
    from types import SimpleNamespace
    wb,pid,store=setup
    run=store.start_run(pid,'reference_simulation')
    folder=tmp_path/'run';folder.mkdir()
    (folder/'trajectory.json').write_text(json.dumps({'frames':[{}]*26}))
    monkeypatch.setattr(module,'_collect_process_output',lambda *args,**kw:dict(timed_out=False,stream_errors=[],stdout='',stderr=''))
    module._CANCELLED_RUNS.add(run['id'])
    wb._collect(run['id'],SimpleNamespace(returncode=0),folder,{'seconds':1,'evidence_scope':'training_or_simulation'})
    finished=store.get_run(run['id'])
    assert finished['status']=='interrupted'
    assert finished['result']['trajectory_available'] is False
    assert run['id'] not in module._CANCELLED_RUNS
