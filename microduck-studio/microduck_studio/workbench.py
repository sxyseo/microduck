"""Versioned assembly recipes and local reference simulation; no device access."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from .visual import model_manifest, model_reference, RevisionConflict
from .core import _ACTIVE_PROCESS_LOCK, _ACTIVE_PROCESSES, _CANCELLED_RUNS, _collect_process_output

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
_LOCK = threading.Lock()

def read_data(name):
    return json.loads((DATA / name).read_text())

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

class Workbench:
    def __init__(self, store, db_path):
        self.store = store
        self.artifacts = Path(db_path).parent / (Path(db_path).stem + '-workbench')
        with store._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS build_recipes (project_id TEXT, revision INTEGER, data TEXT, PRIMARY KEY(project_id, revision))')
            conn.execute('CREATE TABLE IF NOT EXISTS servo_candidates (project_id TEXT, id TEXT, data TEXT, PRIMARY KEY(project_id,id))')

    def catalog(self, project_id=None):
        result = read_data('hardware-catalog.json')
        if project_id:
            if not self.store.get_project(project_id): raise KeyError(project_id)
            with self.store._connect() as conn:
                rows = conn.execute('SELECT data FROM servo_candidates WHERE project_id=? ORDER BY rowid', (project_id,)).fetchall()
            result['servos'].extend(json.loads(row['data']) for row in rows)
        return result

    def add_servo(self, project_id, data):
        if not self.store.get_project(project_id): raise KeyError(project_id)
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('请填写完整型号（含电压版本），最多 100 字')
        dimensions = data.get('dimensions_mm')
        voltage = data.get('voltage_range_v')
        if not isinstance(dimensions, list) or len(dimensions) != 3 or not all(finite(x, .1, 500) for x in dimensions):
            raise ValueError('尺寸需要三个有效的毫米数值')
        if not isinstance(voltage, list) or len(voltage) != 2 or not all(finite(x, .1, 100) for x in voltage) or voltage[0] > voltage[1]:
            raise ValueError('请填写有效的最低和最高额定电压')
        if not finite(data.get('mass_g'), .1, 5000):
            raise ValueError('请填写实测或规格书中的质量')
        if data.get('protocol') not in {'dynamixel2_ttl','feetech_ttl','other'}:
            raise ValueError('通信协议不可用')
        source = data.get('source')
        if not isinstance(source, str) or not source.strip() or len(source) > 1000:
            raise ValueError('新型号必须登记规格来源')
        # Family equivalence must be implemented and verified, never asserted by a form.
        value = {k:data[k] for k in ('name','dimensions_mm','voltage_range_v','mass_g','protocol','source')}
        value.update(id='custom-' + uuid.uuid4().hex[:12], kind='servo', bam_family=None,
                     qualification='candidate', note='用户登记候选；待台架验证与专用执行器模型适配。')
        with self.store._connect() as conn:
            conn.execute('INSERT INTO servo_candidates VALUES (?,?,?)', (project_id,value['id'],json.dumps(value,ensure_ascii=False)))
        return value

    def validate(self, project_id, data):
        catalog = self.catalog(project_id)
        selected = {}
        for singular, plural in [('servo','servos'),('power','powers'),('controller','controllers'),('camera','cameras')]:
            found = next((x for x in catalog[plural] if x['id'] == data.get(singular+'_id')), None)
            if found is None:
                raise ValueError('请选择有效的' + singular)
            selected[singular] = found
        if not isinstance(data.get('name'), str) or not data['name'].strip() or len(data['name']) > 120:
            raise ValueError('方案名称应为 1–120 字')
        reasons = []
        servo, power = selected['servo'], selected['power']
        voltage = servo['voltage_range_v']
        power_ok = bool(voltage and power['servo_range_v'][0] >= voltage[0] and power['servo_range_v'][1] <= voltage[1])
        if not power_ok:
            reasons.append('舵机与电源的完整电压窗口不匹配，或具体电压版本尚未确认')
        if not servo['dimensions_mm']:
            reasons.append('缺少完整 SKU 的尺寸，不能确认结构装配')
        if servo['id'] != 'xl330-m288':
            reasons.append('当前 3D 展示为原版 XL330；此舵机需要对应改件、孔位与惯量核对')
        for key in ('cad_path','bam_path','evidence'):
            if not isinstance(data.get(key,''), str) or len(data.get(key,'')) > 4000:
                raise ValueError('路径或证据格式不可用')
        for key in ('cad_path','bam_path'):
            if not data.get(key): reasons.append('缺少' + ('结构 MJCF 模型' if key == 'cad_path' else '本型号 BAM 辨识文件'))
        if not servo.get('bam_family'):
            reasons.append('此型号尚无已登记 BAM 执行器适配；不能替换为相似舵机参数')
        return {'schema_version':1,'name':data['name'].strip(),
                **{k:data[k] for k in ('servo_id','power_id','controller_id','camera_id')},
                **{k:data.get(k,'') for k in ('cad_path','bam_path','evidence')},
                'components':selected,'model_reference':model_reference(),
                'checks':{'power_window':'matched' if power_ok else 'blocked','training_blockers':reasons,
                          'qualification':'candidate','hardware_verified':False},
                'policy_contract':{'observations':61,'actions':14,'control_hz':50,'action_filter':False},
                'next_steps':['核对结构、质量与惯量','只读体检与受限台架测试','BAM 辨识及独立数据验证','小规模训练、导出与契约检查','分阶段实机验收']}

    def versions(self, project_id):
        if not self.store.get_project(project_id): raise KeyError(project_id)
        with self.store._connect() as conn:
            rows = conn.execute('SELECT revision,data FROM build_recipes WHERE project_id=? ORDER BY revision DESC',(project_id,)).fetchall()
        return [{'revision':r['revision'],'data':json.loads(r['data'])} for r in rows]

    def save(self, project_id, data, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0: raise ValueError('版本号应为非负整数')
        value = self.validate(project_id, data)
        value['recorded_at'] = datetime.now(timezone.utc).isoformat()
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            revision = conn.execute('SELECT COALESCE(MAX(revision),0) FROM build_recipes WHERE project_id=?',(project_id,)).fetchone()[0]
            if revision != expected_revision: raise RevisionConflict('方案已在其他页面更新，请重新加载后保存')
            conn.execute('INSERT INTO build_recipes VALUES (?,?,?)',(project_id,revision+1,json.dumps(value,ensure_ascii=False)))
        return {'revision':revision+1,'data':value}

    def policies(self, project_id):
        project = self.store.get_project(project_id)
        if not project: raise KeyError(project_id)
        training = Path(project['root']) / 'microduck-replica/upstream/microduck_rl'
        result, seen = [], set()
        for path in sorted((training/'logs/rsl_rl/velocity').glob('*/*.onnx')):
            if not path.is_file(): continue
            key = digest(path)
            if key in seen: continue
            seen.add(key)
            result.append({'id':key,'name':path.parent.name + ' / ' + path.name,'path':str(path.resolve())})
            if len(result) == 60: break
        return result

    def simulation(self, project_id, seconds=5, policy_id=None):
        project = self.store.get_project(project_id)
        if not project: raise KeyError(project_id)
        if type(seconds) is not int or not 1 <= seconds <= 10:
            raise ValueError('参考仿真时长须为 1–10 秒')
        training = Path(project['root']) / 'microduck-replica/upstream/microduck_rl'
        python = training / '.venv/bin/python'
        scene = training / 'src/mjlab_microduck/robot/microduck/scene_walk.xml'
        if not python.is_file() or not scene.is_file():
            raise ValueError('项目根目录中未找到 microduck_rl 的本地 Python 环境和原版模型，请先完成环境检查')
        policy = None
        if policy_id:
            policy = next((p for p in self.policies(project_id) if p['id'] == policy_id),None)
            if not policy: raise ValueError('策略不存在或文件已变化，请重新选择')
        with _LOCK:
            with self.store._connect() as conn:
                if conn.execute("SELECT id FROM runs WHERE kind='reference_simulation' AND status='running'").fetchone():
                    raise ValueError('已有参考仿真正在运行，请等待或中止')
            run = self.store.start_run(project_id,'reference_simulation')
            folder = self.artifacts / run['id']
            folder.mkdir(parents=True, exist_ok=False)
            snapshot = {'schema_version':1,'seconds':seconds,'scene':str(scene),'model_reference':model_reference(),
                        'evidence_scope':'training_or_simulation','purpose':'reference_gravity_drop',
                        'note':'原版模型的 MuJoCo 重力与接触演示，无策略控制；不是当前硬件或行走验收。'}
            if policy:
                snapshot.update(policy=policy, purpose='reference_onnx_replay', training_dir=str(training),
                    actuator={'family':'xl330','model':'m6','vin':5.0,'kp':200,'delay_steps':[3,6]},
                    note='原版 XL330 参考模型 + 本地 ONNX，5 V BAM 仿真。训练域可能不同；只记录回放，不证明当前硬件兼容或行走通过。')
            (folder/'config.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
            result = {**snapshot,'directory':str(folder)}
            self.store.update_run_result(run['id'], result)
            command = [str(python),str(ROOT/'workers/reference_simulation.py'),str(folder/'config.json'),str(folder/'trajectory.json')]
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,env={**os.environ,'PYTHONUNBUFFERED':'1'})
            except Exception as exc:
                self.store.finish_run(run['id'],'failed',{**result,'error':str(exc)})
                raise ValueError(str(exc)) from exc
            with _ACTIVE_PROCESS_LOCK: _ACTIVE_PROCESSES[run['id']] = process
            threading.Thread(target=self._collect,args=(run['id'],process,folder,result),daemon=True).start()
        return self.store.get_run(run['id'])

    def _collect(self, run_id, process, folder, result):
        try:
            output = _collect_process_output(process, 90)
            (folder/'execution.json').write_text(json.dumps(output,ensure_ascii=False,default=str,indent=2))
            complete = process.returncode == 0 and not output['timed_out'] and not output['stream_errors'] and (folder/'trajectory.json').is_file()
            if complete:
                trajectory = json.loads((folder/'trajectory.json').read_text())
                complete = len(trajectory.get('frames',[])) == result['seconds'] * 25 + 1
            # Serialize cancellation and terminal status, as the existing executors do.
            with _ACTIVE_PROCESS_LOCK:
                cancelled = run_id in _CANCELLED_RUNS
                status = 'interrupted' if cancelled else 'passed' if complete else 'failed'
                self.store.finish_run(run_id,status,{**result,'execution':output,'trajectory_available':complete and not cancelled,
                    'verdict':'参考仿真已记录；不构成当前硬件适配或实机验收' if complete and not cancelled else '未生成完整仿真证据'})
        except Exception as exc:
            self.store.finish_run(run_id,'failed',{**result,'error':str(exc),'trajectory_available':False})
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.pop(run_id,None)
                _CANCELLED_RUNS.discard(run_id)

    def trajectory(self, project_id, run_id):
        run = self.store.get_run(run_id)
        if run['project_id'] != project_id or run['kind'] != 'reference_simulation': raise KeyError(run_id)
        if run['status'] != 'passed' or not run['result'].get('trajectory_available'): raise ValueError('本次仿真尚无完整轨迹')
        return json.loads((self.artifacts/run_id/'trajectory.json').read_text())
