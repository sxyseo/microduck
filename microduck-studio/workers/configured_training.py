"""Local CPU training from immutable recipe inputs; never controls a device."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from dataclasses import asdict, replace
import importlib.metadata


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def display_matches(archive, root):
    """A mutable task default cannot establish compatibility with an older GLB."""
    try:
        binding = json.loads((root / 'data/display-reference.json').read_text())
        return (sha(archive) == binding['model_archive_sha256']
                and all((root / name).is_file() and sha(root / name) == expected
                        for name, expected in binding['display_sha256'].items()))
    except (OSError, KeyError, json.JSONDecodeError):
        return False


def bundle(spec, destination):
    """MjSpec.to_zip only includes explicit assets, not files read by the compiler."""
    spec.compile()
    base = Path(spec.modelfiledir)
    assets, sources = {}, {}
    for kind, items, directory in [('mesh', spec.meshes, spec.compiler.meshdir),
                                    ('texture', spec.textures, spec.compiler.texturedir),
                                    ('hfield', spec.hfields, '')]:
        for i, item in enumerate(items):
            if not item.file:
                continue
            source = (base / directory / item.file).resolve()
            content = source.read_bytes()
            sources[str(source)] = hashlib.sha256(content).hexdigest()
            # Implicit mesh names derive from file names; preserve references.
            item.name = item.name or Path(item.file).stem
            item.file = f'assets/{kind}_{i}{source.suffix}'
            assets[item.file] = content
    spec.compiler.meshdir = spec.compiler.texturedir = ''
    spec.assets = assets
    spec.to_zip(str(destination))
    return sources


def environment(config):
    import mujoco
    import mjlab_microduck  # noqa: F401; populate the registry before robot imports
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg
    cfg = load_env_cfg(config['task'])
    agent = load_rl_cfg(config['task'])
    robot = cfg.scene.entities['robot']
    robot.spec_fn = lambda: mujoco.MjSpec.from_zip(config['model_archive'])
    a = config['actuator']
    robot.articulation.actuators = (replace(robot.articulation.actuators[0],
        motor_name=None, model=None, json_path=config['bam_snapshot'],
        kp_fw=a['kp_fw'], vin=None, vin_range=tuple(a['voltage_range_v']),
        vin_min=a['voltage_range_v'][0], vin_drop_gain_range=(0.0, 0.0),
        delay_min_lag=a['delay_steps'][0], delay_max_lag=a['delay_steps'][1]),)
    cfg.scene.num_envs = config['parameters']['num_envs']
    cfg.seed = agent.seed = config['parameters']['seed']
    cfg.sim.nan_guard.enabled = True
    agent.logger = 'tensorboard'
    agent.upload_model = False
    agent.resume = False
    agent.max_iterations = config['parameters']['iterations']
    agent.num_steps_per_env = 24
    agent.save_interval = max(1, min(25, agent.max_iterations))
    agent.run_name = 'studio_recipe'
    return cfg, agent


def prepare(config, folder):
    import mujoco
    import numpy as np
    import mjlab_microduck  # noqa: F401
    from mjlab.tasks.registry import load_env_cfg
    from bam.model import load_model
    cfg = load_env_cfg(config['task'])
    reference = cfg.scene.entities['robot'].spec_fn()
    spec = mujoco.MjSpec.from_file(config['recipe']['data']['cad_path'])
    model, expected = spec.compile(), reference.compile()
    names = lambda m: [m.joint(i).name for i in range(m.njnt)]
    if names(model) != names(expected) or (model.nq, model.nv, model.nu) != (21, 20, 14):
        raise ValueError('MJCF 必须保留当前步行任务的自由关节与 14 个关节名称、顺序及执行器；不同拓扑需要专用任务适配')
    if not np.array_equal(model.jnt_type, expected.jnt_type):
        raise ValueError('MJCF 关节类型与步行任务不一致')
    sensors = lambda m: [(m.sensor(i).name, int(m.sensor_type[i]), int(m.sensor_dim[i])) for i in range(m.nsensor)]
    if sensors(model) != sensors(expected):
        raise ValueError('MJCF 的 IMU / 传感器接口与当前任务不一致')
    bam = json.loads(Path(config['bam_snapshot']).read_text())
    if bam.get('actuator') != config['actuator']['family'] or bam.get('model') != 'm6':
        raise ValueError('BAM 文件的 actuator / model 与方案的已登记执行器不匹配（当前支持 M6）')
    for key, value in bam.items():
        if key not in ('actuator', 'model') and (type(value) not in (int, float) or not np.isfinite(value)):
            raise ValueError(f'BAM 参数 {key} 必须为有限数值')
    bam_model = load_model(config['bam_snapshot'])
    missing = set(bam_model.get_parameter_values()) - set(bam)
    if missing:
        raise ValueError('BAM 缺少辨识参数，不能使用默认值补齐：' + ', '.join(sorted(missing)))
    sources = bundle(spec, Path(config['model_archive']))
    # Round-trip compilation proves that includes and meshes are self-contained.
    rebuilt = mujoco.MjSpec.from_zip(config['model_archive']).compile()
    if names(rebuilt) != names(expected):
        raise ValueError('模型快照的关节发生变化')
    reference_matches = display_matches(config['model_archive'], Path(__file__).resolve().parents[1])
    effective, _ = environment(config)
    control_hz = 1 / (effective.decimation * effective.sim.mujoco.timestep)
    if abs(control_hz - 50) > 1e-6:
        raise ValueError('当前任务不满足 50 Hz 控制约定')
    return {'completed': True, 'joint_names': names(model)[1:], 'sensor_signature': sensors(model),
            'geometry_reference_matches': reference_matches, 'asset_sources': sources,
            'model_sha256': sha(config['model_archive']), 'bam_sha256': sha(config['bam_snapshot']),
            'control_hz': control_hz, 'actuator': config['actuator'],
            'versions': {p: importlib.metadata.version(p) for p in ('mujoco', 'mjlab', 'better-actuator-models', 'torch', 'onnxruntime', 'rsl-rl-lib')}}


def replay(env, session, folder, config, prepared):
    """Feed the exported ONNX back into the same environment and record real states."""
    import mujoco
    import numpy as np
    import torch
    native = env.unwrapped.sim.mj_model
    state = mujoco.MjData(native)
    body_map = json.loads((Path(__file__).resolve().parents[1] / 'data/model-body-map.json').read_text())
    body_ids = {key: mujoco.mj_name2id(native, mujoco.mjtObj.mjOBJ_BODY, 'robot/' + name) for key, name in body_map.items()}
    can_display = prepared['geometry_reference_matches'] and all(i >= 0 for i in body_ids.values())
    convert = np.array([[1000,0,0,0], [0,0,1000,0], [0,-1000,0,0], [0,0,0,1]], dtype=float)
    inv_convert = np.linalg.inv(convert)
    def pose(i):
        out = np.eye(4); out[:3,:3] = state.xmat[i].reshape(3,3); out[:3,3] = state.xpos[i]; return out
    state.qpos[:] = 0
    state.qpos[3] = 1
    mujoco.mj_forward(native, state)
    bind = {key: np.linalg.inv(pose(i)) for key, i in body_ids.items()} if can_display else {}
    frames, resets = [], 0
    obs, _ = env.reset()
    robot = env.unwrapped.scene['robot']
    for step in range(251):
        qpos = env.unwrapped.sim.data.qpos[0].cpu().numpy()
        if not np.isfinite(qpos).all():
            raise ValueError('回放状态不是有限数值')
        if step % 2 == 0:
            state.qpos[:] = qpos
            mujoco.mj_forward(native, state)
            frame = {'time': step / 50, 'height_m': float(robot.data.root_link_pos_w[0,2]), 'episode_resets': resets}
            if can_display:
                frame['bodies'] = {key: (convert @ pose(i) @ bind[key] @ inv_convert).flatten(order='F').round(6).tolist() for key,i in body_ids.items()}
            frames.append(frame)
        if step == 250:
            break
        actions = np.concatenate([session.run(None, {session.get_inputs()[0].name: row[None]})[0]
                                  for row in obs['actor'].cpu().numpy()], axis=0)
        if actions.shape != (env.num_envs, 14) or not np.isfinite(actions).all():
            raise ValueError('ONNX 回放动作无效')
        with torch.inference_mode():
            obs, rewards, dones, _ = env.step(torch.from_numpy(actions))
        if not torch.isfinite(rewards).all():
            raise ValueError('回放奖励不是有限数值')
        resets += int(dones[0].item())
    heights = [f['height_m'] for f in frames]
    result = {'completed': True, 'fps': 25, 'seconds': 5, 'frames': frames, 'ground_y': 0,
              'geometry_reference_matches': can_display, 'episode_resets': resets,
              'height_range_m': [min(heights), max(heights)], 'source': 'exported_onnx_in_training_environment',
              'note': '训练环境中的 ONNX 回放，保留随机化与自动重置；完成回放不代表学会行走。'}
    write(folder / 'trajectory.json', result)
    return {k:v for k,v in result.items() if k != 'frames'}


def train(config, folder):
    import numpy as np
    import torch
    import onnxruntime as ort
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_runner_cls
    from mjlab.rl.exporter_utils import get_base_metadata, attach_metadata_to_onnx
    from mjlab.utils.os import dump_yaml
    from mjlab.utils.torch import configure_torch_backends
    configure_torch_backends()
    torch.set_num_threads(2)
    prepared = config['prepared']
    for path, expected in [(config['model_archive'], prepared['model_sha256']), (config['bam_snapshot'], prepared['bam_sha256'])]:
        if sha(path) != expected:
            raise ValueError('准备后的输入文件已变化，请重新准备方案')
    cfg, agent = environment(config)
    dump_yaml(folder / 'params/env.yaml', asdict(cfg))
    dump_yaml(folder / 'params/agent.yaml', asdict(agent))
    env = RslRlVecEnvWrapper(ManagerBasedRlEnv(cfg=cfg, device='cpu'), clip_actions=agent.clip_actions)
    try:
        obs = env.get_observations()['actor']
        if obs.shape[-1] != 61 or env.num_actions != 14:
            raise ValueError('环境不满足 61 维观测 / 14 维动作')
        metadata = get_base_metadata(env.unwrapped, run_path=str(folder))
        if metadata['joint_names'] != prepared['joint_names']:
            raise ValueError('实际训练关节顺序与准备阶段不一致')
        runner = (load_runner_cls(config['task']) or MjlabOnPolicyRunner)(env, asdict(agent), str(folder), 'cpu')
        runner.learn(num_learning_iterations=agent.max_iterations, init_at_random_ep_len=True)
        if runner.current_learning_iteration + 1 != agent.max_iterations:
            raise ValueError('训练迭代未达到计划要求')
        checkpoint = folder / 'checkpoint.pt'
        runner.save(str(checkpoint))
        runner.export_policy_to_onnx(str(folder), 'policy.onnx')
        attach_metadata_to_onnx(str(folder / 'policy.onnx'), metadata)
        session = ort.InferenceSession(str(folder / 'policy.onnx'), providers=['CPUExecutionProvider'])
        if len(session.get_inputs()) != 1 or session.get_inputs()[0].shape != [1, 61] or session.get_outputs()[0].shape != [1, 14]:
            raise ValueError('导出的 ONNX 接口不满足 [1,61] → [1,14]')
        # Compare actual observations through the runner's normalized policy and ONNX.
        with torch.inference_mode():
            observation = env.get_observations()
            reference = runner.get_inference_policy(device='cpu')(observation).cpu().numpy()
        actual = np.concatenate([session.run(None, {session.get_inputs()[0].name: row[None]})[0] for row in observation['actor'].cpu().numpy()])
        if not np.isfinite(actual).all() or not np.allclose(reference, actual, atol=1e-4, rtol=1e-4):
            raise ValueError('ONNX 与训练策略的含归一化输出不一致')
        with torch.inference_mode():
            evaluation = replay(env, session, folder, config, prepared)
        manifest = {'schema_version': 1, 'recipe': config['recipe'], 'plan_id': config['plan_id'],
            'task': config['task'], 'parameters': config['parameters'], 'actuator': config['actuator'],
            'inputs': prepared, 'source_sha256': config['source_sha256'], 'git_snapshot':config['git_snapshot'], 'source_snapshot':config['source_snapshot'],
            'contract': {**metadata, 'observations':61, 'actions':14, 'control_hz':50, 'action_filter':False,
                         'joint_units':'radians', 'imu_frame':'training MJCF sensor/body frame; physical calibration required'},
            'onnx_sha256': sha(folder/'policy.onnx'), 'checkpoint_sha256': sha(checkpoint),
            'onnx_equivalence_max_error': float(np.max(np.abs(reference-actual))), 'evaluation': evaluation,
            'evidence_scope':'training_or_simulation', 'hardware_verified':False, 'deployment_ready':False,
            'completed_iterations':agent.max_iterations, 'completed':True}
        write(folder / 'manifest.json', manifest)
        print(json.dumps({'studio_stage':'complete', 'iterations':agent.max_iterations, 'onnx':manifest['onnx_sha256']}), flush=True)
        return manifest
    finally:
        env.close()


if __name__ == '__main__':
    mode, config_path, out = sys.argv[1:]
    config = json.loads(Path(config_path).read_text())
    folder = Path(out)
    if mode == 'prepare':
        write(folder / 'prepared.json', prepare(config, folder))
    elif mode == 'train':
        train(config, folder)
    else:
        raise ValueError('Unknown worker mode')
