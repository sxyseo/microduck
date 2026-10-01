"""Recipe-bound local experiments with immutable inputs and explicit evidence scope."""
from __future__ import annotations
import json
import hashlib
import zipfile
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
from .core import _ACTIVE_PROCESS_LOCK, _ACTIVE_PROCESSES, _CANCELLED_RUNS, _collect_process_output, capture_git_snapshot
from .workbench import ROOT, digest, finite, read_data

_PLAN_LOCK = threading.Lock()
TASK = 'Mjlab-Velocity-Flat-MicroDuck'
WORKER = ROOT / 'workers/configured_training.py'


def parameters(data):
    if not isinstance(data, dict): raise ValueError('训练参数必须为对象')
    result = {}
    for key, default, low, high in [('num_envs',4,1,32), ('iterations',2,1,1000), ('seed',42,0,2147483647)]:
        value = data.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} 应为 {low}–{high} 的整数')
        result[key] = value
    kp = data.get('kp_fw', 200)
    delay = data.get('delay_steps', [3,6])
    if not finite(kp, 1, 1000):
        raise ValueError('固件增益应为 1–1000 的有限数值')
    if not isinstance(delay, list) or len(delay) != 2 or not all(type(v) is int and 0 <= v <= 20 for v in delay) or delay[0] > delay[1]:
        raise ValueError('延迟步数应为 0–20 的递增整数范围')
    return result, kp, delay


def source_hashes(training):
    paths = [WORKER, ROOT/'data/model-body-map.json', ROOT/'data/display-reference.json']
    paths.extend(p for p in (ROOT/'microduck-color-studio/dist/models').glob('*') if p.is_file())
    for subdir in ('src', 'scripts'):
        paths.extend(p for p in (training/subdir).rglob('*.py') if p.is_file())
    paths.extend(p for p in [training/'pyproject.toml', training/'uv.lock'] if p.is_file())
    return {str(p.resolve()): digest(p) for p in sorted(set(paths))}


class TrainingPipeline:
    def __init__(self, workbench):
        self.wb, self.store = workbench, workbench.store
        with self.store._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS recipe_training_plans (id TEXT PRIMARY KEY, project_id TEXT, data TEXT, run_id TEXT)')

    def location(self, project_id):
        project = self.store.get_project(project_id)
        if not project: raise KeyError(project_id)
        return Path(project['root']) / 'microduck-replica/upstream/microduck_rl'

    def defaults(self, project_id):
        training = self.location(project_id)
        bam = next(iter((training/'.venv/lib').glob('python*/site-packages/bam/params/xl330/m6.json')), None)
        return {'recipe': {'name':'原版 XL330 · 5 V 参考训练方案', 'servo_id':'xl330-m288', 'power_id':'regulated-5',
                'controller_id':'radxa-zero3w', 'camera_id':'none',
                'cad_path':str(training/'src/mjlab_microduck/robot/microduck/robot_walk.xml'),
                'bam_path':str(bam) if bam else '', 'evidence':'上游原版结构和 XL330 M6 参考参数；未验证当前实物'},
                'parameters':{'num_envs':4,'iterations':2,'seed':42,'kp_fw':200,'delay_steps':[3,6]},
                'available':bool(bam and (training/'.venv/bin/python').is_file())}

    def prepare(self, project_id, data):
        training = self.location(project_id)
        revision = data.get('revision')
        if type(revision) is not int or revision < 1:
            raise ValueError('请选择已保存的硬件方案版本')
        recipe = next((v for v in self.wb.versions(project_id) if v['revision'] == revision), None)
        if not recipe: raise ValueError('方案版本不存在')
        params, kp, delay = parameters(data.get('parameters', {}))
        value = recipe['data']
        servo, power = value['components']['servo'], value['components']['power']
        blockers = []
        if value['checks']['power_window'] != 'matched': blockers.append('舵机额定范围与完整电源窗口不匹配')
        if not servo.get('bam_family'): blockers.append(f'{servo["name"]} 缺少专用 BAM 执行器实现；不能借用其他型号参数')
        elif servo['bam_family'] != 'xl330': blockers.append('当前步行任务仅核验了 XL330 BAM 接口；其他执行器需要专用任务适配')
        for key, name in [('cad_path','结构 MJCF'), ('bam_path','BAM M6 文件')]:
            path = Path(value.get(key, ''))
            if not path.is_absolute() or not path.is_file(): blockers.append(f'{name} 需要有效的本机绝对路径')
        python = training/'.venv/bin/python'
        if not python.is_file(): blockers.append('缺少 microduck_rl 本地 Python 环境')
        if blockers: return {'status':'blocked','blockers':blockers,'revision':revision}
        plan_id = uuid.uuid4().hex
        folder = self.wb.artifacts / ('plan-' + plan_id)
        folder.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(value['bam_path'], folder/'bam.json')
            config = {'schema_version':1, 'plan_id':plan_id, 'task':TASK, 'recipe':recipe,
                'parameters':params, 'device':'cpu', 'training_dir':str(training),
                'model_archive':str(folder/'model.zip'), 'bam_snapshot':str(folder/'bam.json'),
                'actuator':{'family':servo['bam_family'],'model':'m6','kp_fw':kp,
                            'voltage_range_v':power['servo_range_v'], 'delay_steps':delay,
                            'voltage_drop_gain_range':[0,0]},
                'source_sha256':source_hashes(training), 'git_snapshot':capture_git_snapshot(training), 'hardware_verified':False, 'deployment_ready':False}
            # Preserve uncommitted source contents, not just the commit and hashes.
            source_zip = folder/'sources.zip'
            with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED) as archive:
                count = 0
                for absolute, expected in config['source_sha256'].items():
                    source = Path(absolute)
                    if source.suffix != '.py' and source.name not in {'pyproject.toml','uv.lock','model-body-map.json','display-reference.json'}:
                        continue
                    content = source.read_bytes()
                    if hashlib.sha256(content).hexdigest() != expected:
                        raise ValueError('保存源码期间文件发生变化，请重新准备')
                    name = ('training/' + str(source.relative_to(training.resolve())) if source.is_relative_to(training.resolve())
                            else 'studio/' + str(source.relative_to(ROOT.resolve())))
                    archive.writestr(name,content)
                    count += 1
            config['source_snapshot'] = {'path':str(source_zip),'sha256':digest(source_zip),'file_count':count}
            path = folder/'config.json'
            path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            process = subprocess.Popen([str(python),str(WORKER),'prepare',str(path),str(folder)],
                cwd=training, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                env={**os.environ, 'PYTHONUNBUFFERED':'1','CUDA_VISIBLE_DEVICES':'','WANDB_MODE':'disabled'})
            output = _collect_process_output(process, 90)
            (folder/'preparation-log.json').write_text(json.dumps(output,ensure_ascii=False,default=str))
            if process.returncode != 0 or output['timed_out'] or output['stream_errors']:
                reason = next((line for line in reversed((output['stderr'] or output['stdout']).splitlines()) if line.strip()), '准备超时或日志采集失败')
                return {'status':'blocked','blockers':[reason], 'revision':revision}
            config['prepared'] = json.loads((folder/'prepared.json').read_text())
            if not config['prepared'].get('completed'): raise ValueError('模型准备未完成')
            if source_hashes(training) != config['source_sha256']: raise ValueError('准备期间训练代码发生变化，请重新准备')
            if params['iterations'] > 5 and not self.has_smoke(project_id, config):
                return {'status':'blocked', 'revision':revision,
                        'blockers':['先用同一方案、模型、BAM 和执行器参数完成 1–5 轮小规模实验，再扩大训练。']}
            config.update(status='ready',blockers=[])
            path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            config['config_sha256'] = digest(path)
            with self.store._connect() as conn:
                conn.execute('INSERT INTO recipe_training_plans VALUES (?,?,?,NULL)',(plan_id,project_id,json.dumps(config,ensure_ascii=False)))
            return config
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'准备输入失败：{exc}') from exc

    def has_smoke(self, project_id, config):
        for run in self.store.project_report(project_id)['runs']:
            result = run['result']
            m = result.get('manifest') or {}
            if (run['kind'] == 'recipe_training' and run['status'] == 'passed'
                and result.get('artifacts_available') and 1 <= m.get('completed_iterations',0) <= 5
                and m.get('recipe') == config['recipe'] and m.get('actuator') == config['actuator']
                and m.get('source_sha256') == config['source_sha256']
                and m.get('inputs',{}).get('model_sha256') == config['prepared']['model_sha256']
                and m.get('inputs',{}).get('bam_sha256') == config['prepared']['bam_sha256']):
                try:
                    self.artifact(project_id,run['id'],'manifest.json')
                    self.artifact(project_id,run['id'],'policy.onnx')
                    return True
                except ValueError:
                    continue
        return False

    def plan(self, project_id, plan_id):
        if not isinstance(plan_id, str) or len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
            raise ValueError('无效的准备方案编号')
        with self.store._connect() as conn:
            row = conn.execute('SELECT * FROM recipe_training_plans WHERE id=? AND project_id=?',(plan_id,project_id)).fetchone()
        if not row: raise KeyError(plan_id)
        return json.loads(row['data']), row['run_id']

    def verify_inputs(self, plan):
        if not isinstance(plan.get('source_snapshot'), dict):
            raise ValueError('旧输入快照未保存源码，请重新检查并准备方案')
        paths = {**plan['source_sha256'], plan['source_snapshot']['path']:plan['source_snapshot']['sha256'], plan['model_archive']:plan['prepared']['model_sha256'],
                 plan['bam_snapshot']:plan['prepared']['bam_sha256'],
                 str(Path(plan['model_archive']).parent/'config.json'):plan['config_sha256']}
        if any(not Path(p).is_file() or digest(p) != h for p,h in paths.items()):
            raise ValueError('模型、参数或训练代码已变化，请重新检查并准备方案')
        if source_hashes(Path(plan['training_dir'])) != plan['source_sha256']:
            raise ValueError('训练代码清单已变化，请重新检查并准备方案')

    def start(self, project_id, data):
        self.location(project_id)
        if data.get('confirm') is not True: raise ValueError('请先检查生效配置，再点击开始本地训练')
        with _PLAN_LOCK:
            plan, previous = self.plan(project_id, data.get('plan_id'))
            if previous: raise ValueError('此准备方案已执行，请重新准备以创建下一次实验')
            self.verify_inputs(plan)
            if plan['parameters']['iterations'] > 5 and not self.has_smoke(project_id, plan):
                raise ValueError('所需小规模实验的证据已变化，请重新验证')
            try:
                run = self.store._start_training_run(project_id, 'recipe_training')
            except RuntimeError as exc:
                raise ValueError('已有训练在运行，请等待或中止后再开始') from exc
            result = {'plan_id':plan['plan_id'], 'recipe':plan['recipe'], 'parameters':plan['parameters'],
                      'actuator':plan['actuator'], 'stage':'training', 'hardware_verified':False,
                      'deployment_ready':False, 'artifacts_available':False}
            try:
                with self.store._connect() as conn:
                    conn.execute('UPDATE recipe_training_plans SET run_id=? WHERE id=?',(run['id'],plan['plan_id']))
                folder = self.wb.artifacts/run['id']
                folder.mkdir(parents=True,exist_ok=False)
                shutil.copyfile(plan['source_snapshot']['path'], folder/'sources.zip')
                config_path = Path(plan['model_archive']).parent/'config.json'
                result['directory'] = str(folder)
                self.store.update_run_result(run['id'],result)
                process = subprocess.Popen([str(Path(plan['training_dir'])/'.venv/bin/python'),str(WORKER),'train',str(config_path),str(folder)],
                    cwd=plan['training_dir'], stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,
                    env={**os.environ,'PYTHONUNBUFFERED':'1','CUDA_VISIBLE_DEVICES':'','WANDB_MODE':'disabled'})
                with _ACTIVE_PROCESS_LOCK: _ACTIVE_PROCESSES[run['id']] = process
                threading.Thread(target=self.collect,args=(run['id'],process,folder,plan,result),daemon=True).start()
            except Exception as exc:
                self.store.finish_run(run['id'],'failed',{**result,'error':str(exc)})
                raise ValueError(f'训练启动失败：{exc}') from exc
        return self.store.get_run(run['id'])

    def collect(self, run_id, process, folder, plan, result):
        try:
            output = _collect_process_output(process, 3600,
                on_log=lambda row: self.store._record_live_run_event(run_id,'log',row),
                on_metrics=lambda row: self.store._record_live_run_event(run_id,'metrics',row))
            (folder/'execution.json').write_text(json.dumps(output,ensure_ascii=False,default=str,indent=2))
            complete = process.returncode == 0 and not output['timed_out'] and not output['stream_errors']
            manifest = None
            if complete:
                self.verify_inputs(plan)
                manifest = json.loads((folder/'manifest.json').read_text())
                trajectory = json.loads((folder/'trajectory.json').read_text())
                complete = (manifest.get('completed') is True and manifest['completed_iterations'] == plan['parameters']['iterations']
                    and manifest['onnx_sha256'] == digest(folder/'policy.onnx')
                    and manifest['checkpoint_sha256'] == digest(folder/'checkpoint.pt')
                    and trajectory.get('completed') is True and len(trajectory.get('frames',[])) == 126)
            with _ACTIVE_PROCESS_LOCK:
                cancelled = run_id in _CANCELLED_RUNS
                status = 'interrupted' if cancelled else 'passed' if complete else 'failed'
                self.store.finish_run(run_id,status,{**result,'execution':output,'stage':'complete' if complete and not cancelled else status,
                    'artifacts_available':complete and not cancelled, 'manifest':manifest if complete and not cancelled else None,
                    'artifact_sha256':{p.name:digest(p) for p in folder.iterdir() if p.is_file()} if complete and not cancelled else {},
                    'verdict':'训练、归一化 ONNX 导出与同环境回放已完成；未验证步态或实物' if complete and not cancelled else '实验未完成，不能作为通过证据'})
        except Exception as exc:
            with _ACTIVE_PROCESS_LOCK:
                self.store.finish_run(run_id,'interrupted' if run_id in _CANCELLED_RUNS else 'failed',
                                      {**result,'error':str(exc),'artifacts_available':False})
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.pop(run_id,None)
                _CANCELLED_RUNS.discard(run_id)

    def artifact(self, project_id, run_id, name, display=False):
        run = self.store.get_run(run_id)
        if run['project_id'] != project_id or run['kind'] != 'recipe_training': raise KeyError(run_id)
        if name not in {'policy.onnx','manifest.json','trajectory.json','checkpoint.pt','execution.json','sources.zip'}: raise KeyError(name)
        if run['status'] != 'passed' or not run['result'].get('artifacts_available'): raise ValueError('此实验没有完整可用的产物')
        if display:
            binding = read_data('display-reference.json')
            inputs = (run['result'].get('manifest') or {}).get('inputs', {})
            if (name != 'trajectory.json' or not inputs.get('geometry_reference_matches')
                or inputs.get('model_sha256') != binding['model_archive_sha256']
                or any(not (ROOT/p).is_file() or digest(ROOT/p) != h for p,h in binding['display_sha256'].items())):
                raise ValueError('本次轨迹与当前展示模型不匹配；可下载轨迹数据核对，不能套用当前 3D 外观')
        path = self.wb.artifacts/run_id/name
        if not path.is_file() or digest(path) != run['result'].get('artifact_sha256',{}).get(name):
            raise ValueError('实验产物缺失或已变化')
        return path
