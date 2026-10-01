"""Bounded, headless native MuJoCo reference physics. No device or policy writes."""
import json
from pathlib import Path
import sys
import hashlib
import importlib.util
import mujoco
import numpy as np

config = json.loads(Path(sys.argv[1]).read_text())
scene = Path(config['scene'])
model = mujoco.MjModel.from_xml_path(str(scene))
model.opt.timestep = .005
# Display the actual unpowered model under gravity and contact. Do not fake a gait.
model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
data = mujoco.MjData(model)
policy = bam_ctrl = None
if config.get('policy'):
    policy_path = Path(config['policy']['path'])
    if hashlib.sha256(policy_path.read_bytes()).hexdigest() != config['policy']['id']:
        raise ValueError('Policy changed after the snapshot')
    source = Path(config['training_dir'])/'scripts/infer_policy.py'
    spec = importlib.util.spec_from_file_location('studio_reference_inference',source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    bam_model = module.load_bam_model(kp_fw=200,vin=5,max_current=None)
    model,data,bam_ctrl,_ = module.load_mujoco_with_bam(str(scene),bam_model,timestep=.005,vin_drop_gain=0,vin_min=3.7)
    np.random.seed(42)
    policy = module.PolicyInference(model,data,str(policy_path),bam_ctrl=bam_ctrl,
        delay_min_lag=3,delay_max_lag=6,use_projected_gravity=True,new_cmd_obs=True)
    if policy.walking_session.get_inputs()[0].shape[-1] != 61 or policy.walking_session.get_outputs()[0].shape[-1] != 14:
        raise ValueError('Reference replay requires a 61-D observation and 14-D action policy')
# Include the source model's body collision group in ground contacts for this
# reference environment. Keep visual meshes non-colliding and record the override.
floor_id = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'floor')
if floor_id < 0: raise ValueError('Reference scene has no ground plane')
model.geom_conaffinity[floor_id] |= 2
body_map = json.loads((Path(__file__).resolve().parents[1]/'data/model-body-map.json').read_text())
ids = {key:mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,name) for key,name in body_map.items()}
if any(i < 0 for i in ids.values()): raise ValueError('Body map does not match the model')
# GLB source was exported at qpos=0, with the free-joint quaternion set to identity.
data.qpos[:] = 0
data.qpos[3] = 1
mujoco.mj_forward(model,data)
def pose(i):
    m = np.eye(4); m[:3,:3] = data.xmat[i].reshape(3,3); m[:3,3] = data.xpos[i]; return m
bind = {key:np.linalg.inv(pose(i)) for key,i in ids.items()}
conversion = np.array([[1000,0,0,0],[0,0,1000,0],[0,-1000,0,0],[0,0,0,1]],dtype=float)
inverse_conversion = np.linalg.inv(conversion)
key = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_KEY,'STAND')
if key >= 0: mujoco.mj_resetDataKeyframe(model,data,key)
else: mujoco.mj_resetData(model,data)
data.qpos[2] += .035
if policy:
    data.qpos[:7] = [0,0,.125,1,0,0,0]
    for i,qpos_idx in enumerate(policy.joint_qpos_indices): data.qpos[qpos_idx] = policy.default_pose[i]
    bam_ctrl.reset(data.qpos)
    policy.set_position_targets(policy.default_pose)
    policy.set_vel_cmd(.1,0,0)
mujoco.mj_forward(model,data)
frames = []
for frame in range(config['seconds']*25+1):
    if not np.isfinite(data.qpos).all(): raise ValueError('Non-finite simulation state')
    frames.append({'time':round(float(data.time),4),'height_m':round(float(data.qpos[2]),5),
        'bodies':{key:(conversion @ pose(i) @ bind[key] @ inverse_conversion).flatten(order='F').round(6).tolist() for key,i in ids.items()}})
    if frame < config['seconds']*25:
        for substep in range(8):
            if policy:
                if substep % 4 == 0:
                    policy.update_behavior(.02)
                    action = policy.infer()
                    if not np.isfinite(action).all(): raise ValueError('Non-finite policy action')
                    policy.apply_action(action)
                bam_ctrl.update()
            mujoco.mj_step(model,data)
# Includes and mesh files also determine this model. Record their hashes for this run.
source_hashes = {str(p.relative_to(scene.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(scene.parent.rglob('*')) if p.is_file() and p.suffix.lower() in {'.xml','.stl','.obj','.ply'}}
result = {**config,'engine':'MuJoCo '+mujoco.__version__,'fps':25,'frames':frames,'source_sha256':source_hashes,
          'geometry_scope':'original_reference_only','ground_y':0,'completed':True,
          'contact_override':{'floor_conaffinity':int(model.geom_conaffinity[floor_id]),'note':'Ground contacts include source body collision group 2; this reference environment is not the training environment.'}}
result['worker_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
if policy:
    import bam
    bam_path = Path(bam.__file__).parent/'params/xl330/m6.json'
    result['bam_sha256'] = hashlib.sha256(bam_path.read_bytes()).hexdigest()
    result['inference_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
print(json.dumps({'completed':True,'frames':len(frames),'seconds':config['seconds'],'policy_control':policy is not None}))
