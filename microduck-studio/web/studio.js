/* Presentation layer. Task readiness and evidence verdicts always come from the service. */
window.Studio = (() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const labels = {recorded:'已记录',incomplete:'未完成',needs_confirmation:'待确认', confirmed:'已确认', ready:'可开始', blocked:'待解锁', success:'已完成', passed:'通过', failed:'失败', interrupted:'已中断', insufficient_evidence:'证据不足', running:'进行中', cancelling:'正在中止', cancelled:'已中止', planned:'计划中', owned:'已到货', installed:'已安装', detected:'已检测', verified:'已验证', unavailable:'不可用', unknown:'未确认', open:'待处理', investigating:'调查中', resolved:'已解决', wont_fix:'不处理', concluded:'已结论', abandoned:'已放弃', local_software:'本机软件证据', training_or_simulation:'训练 / 仿真证据', bench_evidence:'台架导入证据', real_hardware:'硬件检查证据'};
  const names = {recipe_training:'方案训练与 ONNX',reference_simulation:'参考物理仿真记录',preflight:'开发机只读预检', controller_diagnostic:'主控只读诊断', bench_continuous:'连续测试判定', hl2915_read_only_probe:'舵机只读体检', hl2915_bam_record:'BAM 辨识采样', training_smoke:'CPU 小规模验证', training:'模型训练', tensorboard_summary:'训练指标摘要', deployment_preflight:'部署前兼容性检查', deployment:'策略部署', hardware_acceptance:'实机验收记录'};
  const fieldNames = {'servos.model':'舵机型号','servos.count':'舵机数量','controller.model':'主控型号','imu.model':'IMU 型号','power.voltage_v':'供电电压','printed_parts.version':'打印件版本','runtime.version':'运行时版本','training.repo':'训练仓库','training.revision':'训练仓版本'};
  const reasons = {hardware_confirmation_required:'需要先确认实际舵机型号', current_assembly_record_required:'缺少当前硬件对应的装配记录', current_calibration_record_required:'缺少当前硬件对应的标定记录', successful_deployment_required:'需要先完成一次成功部署', ssh_unreachable:'SSH 连接未建立，请检查地址、密钥与权限', service_restarted:'服务曾重启，本次运行已中断', insufficient_duration:'测试时长不足', packets_lost:'检测到通信丢包'};
  const text = value => labels[value] || reasons[value] || fieldNames[value] || value || '不可用';
  const pill = status => `<span class="pill ${esc(status || 'unknown')}">${esc(text(status || 'unknown'))}</span>`;
  const views = {
    overview: ['工作台总览','每一步，都有据可循。','从第一只舵机，到迈出的第一步。继续你的 Microduck 复刻。','YOUR REPLICATION WORKBENCH'],
    visual: ['3D 外观与装配','把你的鸭子，放到眼前。','逐件配色、规划耗材，从模型选中零件并关联装配检查。','DESIGN YOUR MICRODUCK'],
    guide: ['可视化安装','看懂结构，再动手组装。','逐步查看部位与零件，核对硬件、接线和仿真证据。','BUILD YOUR MICRODUCK'],
    hardware: ['我的鸭子','一份档案，贯穿整个复刻。','记录实际硬件与资料来源，未确认的条件会明确保留。','HARDWARE PROFILE'],
    bench: ['舵机实验室','从第一只舵机开始。','确认连接、只读体检、核对证据，让每次测试都可以追溯。','SERVO LAB'],
    controller: ['主控诊断','先让开发环境与主控就绪。','检查工具、版本、服务与权限，按证据定位连接问题。','SYSTEM DIAGNOSTICS'],
    assembly: ['装配与标定','让记录与实际硬件对应。','整理装配证据、关节标定与辨识条件，逐项推进。','ASSEMBLY & CALIBRATION'],
    training: ['仿真与训练','先验证，再扩大实验。','管理小规模验证、受控训练、续训与指标产物。','SIMULATION & TRAINING'],
    deployment: ['部署与验收','每次部署，都先核对兼容性。','检查策略与硬件契约，保留回滚证据与逐级实测记录。','DEPLOYMENT & VALIDATION'],
    records: ['实验与记录','让每一次尝试都有迹可循。','查看运行、比较实验、记录问题，找回当时完整的条件。','EXPERIMENTS & EVIDENCE'],
    knowledge: ['资料与证据','从资料中查证，从记录中定位。','在本地检索源码、文档与证据，保持来源和版本可追溯。','LOCAL KNOWLEDGE'],
    settings: ['项目与设置','为你的工作方式做好准备。','创建项目，管理执行位置与指标偏好。','WORKSPACE SETTINGS']
  };
  const taskViews = {hardware:['hardware','hardware'], preflight:['controller','preflight'], controller_read:['controller','controller'], servo_read:['bench','probe'], assembly:['assembly','assembly'], calibration:['assembly','calibration'], identification:['assembly','identification'], smoke:['training','smoke'], deployment_preflight:['deployment','deployment'], deployment:['deployment','deployment'], acceptance:['deployment','acceptance'], report:['records','report']};
  const stages = [
    ['硬件准备','hardware',['hardware','preflight']], ['单机调试','bench',['servo_read','controller_read']],
    ['装配标定','assembly',['assembly','calibration','identification']], ['仿真训练','training',['smoke']],
    ['兼容部署','deployment',['deployment_preflight','deployment']], ['实机验收','deployment',['acceptance']]
  ];
  let report = null, view = 'overview', selectedTask = null, toastTimer, dirty = new Set(), rendering = false;
  const activeCards = {};
  const initialFields = new Map();
  const tabs = {
    bench: [['probe','通信验证'],['bench','连续测试判定']], controller: [['preflight','开发机预检'],['controller','主控诊断']],
    training: [['pipeline','方案 → ONNX'],['smoke','小规模验证'],['training','模型训练与续训'],['tensorboard','指标摘要']],
    assembly: [['assembly','装配与电气'],['calibration','关节标定'],['identification','执行器辨识']],
    deployment: [['policy','策略包检查'],['deployment','兼容性与部署'],['acceptance','逐级验收']],
    records: [['timeline','运行与对比'],['experiment','实验记录'],['issue','问题台账'],['report','复刻报告']],
    knowledge: [['search','资料与证据搜索'],['source','来源登记']], settings: [['project','项目管理'],['settings','工作台偏好']]
  };
  function selectCard(key, card) {
    if (!tabs[key]) return;
    const chosen = tabs[key].some(([id]) => id === card) ? card : activeCards[key] || tabs[key][0][0];
    activeCards[key] = chosen;
    for (const [id] of tabs[key]) el(`card-${id}`).hidden = id !== chosen;
    document.querySelectorAll(`#view-${key} [data-card]`).forEach(button => {
      const selected = button.dataset.card === chosen;
      button.setAttribute('aria-selected',String(selected)); button.tabIndex = selected ? 0 : -1;
    });
    const guideTask = Object.entries(taskViews).find(([,route]) => route[0] === key && route[1] === chosen);
    selectedTask = guideTask?.[0] || null;
  }
  function connection(online) {
    el('connection').classList.toggle('offline', !online);
    el('connection-text').textContent = online ? '本地服务已连接' : '服务连接中断';
  }
  function notify(message, error = false) {
    el('toast-message').textContent = message;
    el('toast').classList.toggle('error', error);
    el('toast').hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el('toast').hidden = true; }, error ? 9000 : 4500);
  }
  function navigate(key, card, updateHistory = true) {
    if (!views[key]) key = 'overview';
    view = key;
    document.querySelectorAll('[data-panel]').forEach(panel => { panel.hidden = panel.dataset.panel !== key; });
    el('workspace-layout').hidden = ['overview','visual','guide'].includes(key);
    el('workspace-layout').classList.toggle('wide-workspace', key === 'assembly');
    window.VisualStudio?.onNavigate(key);
    window.InstallationStudio?.onNavigate(key);
    document.querySelectorAll('.nav-button').forEach(button => {
      if (button.dataset.view === key) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
    });
    const meta = views[key];
    el('breadcrumb-title').textContent = meta[0]; el('page-title').textContent = meta[1];
    el('page-description').textContent = meta[2]; el('page-eyebrow').textContent = meta[3];
    document.title = `${meta[0]} · Microduck Studio`;
    closeMenu();
    if (updateHistory && location.hash !== `#${key}`) history.pushState(null, '', `#${key}`);
    selectCard(key,card);
    renderGuide();
    if (card) {
      const target = el(`card-${card}`);
      if (target) { target.scrollIntoView({block:'start',behavior:'instant'}); target.setAttribute('tabindex','-1'); target.focus({preventScroll:true}); }
    } else window.scrollTo({top:0,behavior:'instant'});
  }
  function openTask(id) {
    selectedTask = id;
    const route = taskViews[id] || ['records','report'];
    navigate(...route);
  }
  function closeMenu() { document.body.classList.remove('nav-open'); el('menu-toggle').setAttribute('aria-expanded','false'); }
  function renderGuide() {
    const preferred = report?.tasks?.find(task => task.id === selectedTask && taskViews[task.id]?.[0] === view);
    const task = preferred || (!tabs[view] ? report?.tasks?.find(task => taskViews[task.id]?.[0] === view) : null);
    if (!task?.card) {
      el('task-guide').innerHTML = `<h3>${view === 'settings' ? '先建立工作档案' : '围绕真实证据继续'}</h3><p>${view === 'settings' ? '新项目只需要名称和本地仓库路径。硬件不齐也可以开始记录，尚未具备的条件会保留为待确认。' : report ? '记录实验时保留当时的条件与证据编号。通过、失败、中断和证据不足分别显示；原始结果可以随时展开查阅。' : '选择项目后，这里会展示当前任务的步骤、前置条件和验收标准。'}</p><div class="context-links"><button data-view="hardware">硬件档案</button><button data-view="knowledge">检索资料</button></div>`;
      return;
    }
    const card = task.card;
    const blockedBy = (task.blocked_by || []).map(id => report.tasks.find(item => item.id === id)?.title || id);
    el('task-guide').innerHTML = `<h3>${esc(task.title)}</h3>${pill(task.status)}<p>预计 ${esc(card.estimated_minutes)} 分钟 · ${card.read_only ? '只读检查' : '按步骤确认'}</p>${blockedBy.length ? `<div class="inline-note warning">需先完成：${esc(blockedBy.join('、'))}</div>` : ''}<ol>${(card.steps || []).map(step => `<li>${esc(step)}</li>`).join('')}</ol><div class="acceptance"><h3>通过条件</h3><p>${esc(card.acceptance)}</p></div><details><summary>工具、前提与异常处理</summary><p><strong>所需工具</strong><br>${esc((card.tools || []).join('、'))}</p><p><strong>前置条件</strong><br>${esc((card.preconditions || []).join('；'))}</p><p><strong>失败时</strong><br>${esc(card.failure_handling)}</p><p><strong>所需证据</strong><br>${esc((card.evidence_required || []).join('；'))}</p></details><div class="context-links"><button data-view="knowledge">${icon('book')}查找相关资料</button></div>`;
  }
  function taskRow(task) {
    const blockers = (task.blocked_by || []).map(id => report.tasks.find(item => item.id === id)?.title || id);
    const reason = blockers.length ? `需先完成：${blockers.join('、')}` : task.evidence_reasons?.length ? task.evidence_reasons.map(text).join('；') : task.card?.operation_scope || '查看任务详情';
    return `<button class="task-row" data-task="${esc(task.id)}"><span class="row-icon">${icon(task.status === 'success' ? 'check' : task.status === 'failed' ? 'alert' : 'layers')}</span><span class="row-text"><strong>${esc(task.title)}</strong><small>${esc(reason)}</small></span>${pill(task.status)}${icon('chevron')}</button>`;
  }
  function renderJourney() {
    const tasks = report?.tasks || [];
    let currentFound = false;
    el('journey').innerHTML = stages.map(([name, route, ids], index) => {
      const set = tasks.filter(task => ids.includes(task.id));
      const completed = set.length === ids.length && set.every(task => task.status === 'success');
      const current = !currentFound && !completed;
      if (current) currentFound = true;
      const count = set.filter(task => task.status === 'success').length;
      return `<button class="journey-step ${current && report ? 'current' : ''}" data-view="${route}" aria-label="${name}，${report ? `${count}/${ids.length} 项完成` : '待建立档案'}"><span class="step-number">${completed ? icon('check') : String(index + 1).padStart(2,'0')}</span><span>${name}</span><small>${report ? completed ? '阶段已完成' : `${count}/${ids.length} 项完成` : '待建立档案'}</small></button>`;
    }).join('');
  }
  function populateRecordLists(data) {
    const groups = [
      ['run-options', data.runs || [], item => `${names[item.kind] || item.kind} · ${text(item.status)}`],
      ['finished-run-options', (data.runs || []).filter(item => !['running','cancelling'].includes(item.status)), item => `${names[item.kind] || item.kind} · ${text(item.status)}`],
      ['failed-run-options', (data.runs || []).filter(item => ['failed','interrupted'].includes(item.status)), item => `${names[item.kind] || item.kind} · ${text(item.status)}`],
      ['experiment-options', data.experiments || [], item => `${item.title} · ${text(item.status)}`],
      ['issue-options', data.issues || [], item => `${item.title} · ${text(item.status)}`]
    ];
    for (const [id, items, label] of groups) {
      let list = el(id); if (!list) { list = document.createElement('datalist'); list.id = id; document.body.append(list); }
      list.replaceChildren(...items.map(item => new Option(label(item), item.id)));
    }
  }
  function applyReadiness() {
    const confirmed = report?.hardware?.status === 'confirmed';
    const gates = { 'probe-run': !confirmed, 'probe-plan': !confirmed, 'bam-run': !confirmed || !report?.tasks?.some(task => task.id === 'servo_read' && task.status === 'success'), 'deployment-execute': !report?.tasks?.some(task => task.id === 'deployment' && ['ready','failed','interrupted','success'].includes(task.status)) };
    for (const [id, blocked] of Object.entries(gates)) {
      const button = el(id); button.dataset.gated = String(blocked); button.disabled = blocked;
      button.title = blocked ? '先完成任务指引中列出的前置条件；服务端仍会独立核验。' : '';
    }
    let note = el('probe-gate-note');
    if (!note) { note = document.createElement('p'); note.id = 'probe-gate-note'; note.className = 'inline-note warning'; el('card-probe').append(note); }
    note.hidden = !!confirmed;
    note.innerHTML = `${icon('alert')}<span>先在“我的鸭子”中确认舵机型号，再生成与执行设备计划。</span><button data-view="hardware">去确认</button>`;
  }
  function renderReport(data) {
    window.VisualStudio?.receiveReport(data);
    window.InstallationStudio?.receiveReport(data);
    window.TrainingStudio?.receiveReport(data);
    report = data; connection(true); rendering = true;
    const tasks = data.tasks || [], runs = data.runs || [], hardware = data.hardware;
    const next = tasks.find(task => ['ready','needs_confirmation'].includes(task.status));
    el('next-title').textContent = next?.title || '当前没有可开始的任务';
    el('next-description').textContent = next?.card?.operation_scope || '查看阻塞原因与历史证据，确认下一项检查。';
    el('next-badge').outerHTML = pill(next?.status || 'blocked').replace('class="pill', 'id="next-badge" class="pill');
    el('next-duration').textContent = next?.card?.estimated_minutes ? `约 ${next.card.estimated_minutes} 分钟` : '先检查前置条件';
    el('next-risk').textContent = next?.card?.read_only ? '只读检查' : next?.id === 'hardware' ? '人工确认' : '按任务范围操作';
    el('next-action').innerHTML = `${next ? '开始这一步' : '查看全部任务'} ${icon('arrow')}`;
    el('next-action').onclick = () => next ? openTask(next.id) : (el('all-tasks').hidden = false);
    el('duck-name').textContent = data.project.name;
    el('active-project-name').textContent = data.project.name;
    el('active-project-name').title = data.project.root;
    el('download-report').href = `/api/projects/${encodeURIComponent(data.project.id)}/report.md`;
    el('download-report').hidden = false;
    el('duck-status').outerHTML = pill(hardware?.status || 'needs_confirmation').replace('class="pill','id="duck-status" class="pill');
    el('duck-model').textContent = hardware?.data?.servos?.model || '舵机型号待确认';
    el('metric-complete').innerHTML = `${tasks.filter(task => task.status === 'success').length} <em>/ ${tasks.length}</em>`;
    el('metric-blocked').textContent = tasks.filter(task => task.status === 'blocked').length;
    el('metric-runs').textContent = runs.length;
    el('metric-issues').textContent = (data.issues || []).filter(issue => ['open','investigating'].includes(issue.status)).length;
    const attention = tasks.filter(task => ['needs_confirmation','failed','interrupted','ready'].includes(task.status)).slice(0,3);
    if (attention.length < 3) attention.push(...tasks.filter(task => task.status === 'blocked').slice(0,3-attention.length));
    el('attention-list').innerHTML = attention.map(taskRow).join('') || '<div class="empty-state">当前没有待处理的任务，完整证据仍可在记录中查看。</div>';
    el('all-task-rows').innerHTML = tasks.map(taskRow).join('');
    el('recent-runs').innerHTML = runs.length ? runs.slice(0,3).map(run => `<button class="task-row" data-run="${esc(run.id)}"><span class="row-icon">${icon('folder')}</span><span class="row-text"><strong>${esc(names[run.kind] || run.kind)}</strong><small>${esc(text(run.result?.evidence_scope || 'unknown'))} · ${esc(new Date(run.started_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}))}</small></span>${pill(run.status)}${icon('chevron')}</button>`).join('') : '<div class="empty-state"><strong>还没有实验记录</strong>完成一次检查后，条件与结果会保存在这里。</div>';
    el('last-updated').textContent = `状态更新于 ${new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} · 以实际证据为准`;
    let completeness = el('hardware-completeness');
    if (!completeness) { completeness = document.createElement('div'); completeness.id = 'hardware-completeness'; completeness.className = 'inline-note'; el('card-hardware').prepend(completeness); }
    const missing = hardware?.completeness?.missing_fields;
    completeness.textContent = missing?.length ? `档案待补充：${missing.map(text).join('、')}` : hardware ? '档案字段已齐全，具体能力仍需逐项验证。' : '尚未建立硬件档案，可以先记录已知信息。';
    populateRecordLists(data); renderJourney(); renderGuide(); applyReadiness();
    el('project-picker').hidden = true;
    rendering = false;
  }
  function clear() {
    report = null; selectedTask = null;
    el('next-title').textContent = '建立你的“我的鸭子”档案';
    el('next-description').textContent = '选择已有项目，或创建一份硬件档案。后续任务与实验都将围绕它展开。';
    el('next-badge').outerHTML = '<span id="next-badge" class="pill needs_confirmation">开始复刻</span>';
    el('next-action').innerHTML = `开始设置 ${icon('arrow')}`;
    el('next-action').onclick = () => { el('project-picker').hidden = false; navigate('settings'); };
    el('next-duration').textContent = '约 5 分钟'; el('next-risk').textContent = '仅记录资料';
    for (const id of ['metric-complete','metric-blocked','metric-runs','metric-issues']) el(id).textContent = '—';
    el('duck-name').textContent = '我的 Microduck'; el('duck-status').outerHTML = '<span id="duck-status" class="pill needs_confirmation">未选择项目</span>'; el('duck-model').textContent = '硬件路线待核实';
    el('active-project-name').textContent = '选择一个项目'; el('active-project-name').removeAttribute('title');
    el('download-report').hidden = true; el('download-report').removeAttribute('href');
    el('last-updated').textContent = '每个结论都有来源，每次验证都有记录。';
    if (el('hardware-completeness')) el('hardware-completeness').textContent = '尚未建立硬件档案，可以先记录已知信息。';
    el('attention-list').innerHTML = '<div class="empty-state">选择项目后，在这里查看前置条件与阻塞原因。</div>';
    el('recent-runs').innerHTML = '<div class="empty-state"><strong>第一份记录，从下一步开始</strong>完整保存条件、数据、规则与结论。</div>';
    el('all-task-rows').replaceChildren();
    el('project-picker').hidden = false; el('all-tasks').hidden = true;
    populateRecordLists({}); renderJourney(); renderGuide(); applyReadiness();
  }
  function reset() {
    window.VisualStudio?.reset();
    window.InstallationStudio?.reset();
    window.TrainingStudio?.reset();
    dirty.clear(); clear();
    for (const [id,value] of initialFields) {
      const field = el(id); if (field.type === 'checkbox') field.checked = value; else field.value = value;
    }
    el('toast').hidden = true;
    for (const id of ['run-timeline-id','run-left-id','run-right-id','exp-update-id','exp-link-run-id','exp-left-id','exp-right-id','issue-update-id','issue-link-run-id','issue-run-id','record-detail-id','training-parent-run','training-checkpoint']) el(id).value = '';
    for (const id of ['run-timeline-body','run-compare-body','record-detail-body','search-body','record-search-body','status']) el(id).textContent = '尚未选择记录';
    el('result-summary').textContent = '操作完成后，这里会显示结果、证据范围和下一步。';
    el('run-live-chart').replaceChildren(); el('run-compare-chart').replaceChildren();
    el('run-live-caption').textContent = '尚未选择运行；缺失指标显示不可用。';
    el('run-live-metric').replaceChildren(new Option('等待指标',''));
    syncTargets();
  }
  function result(value) {
    if (typeof value === 'string') { el('result-summary').textContent = value; notify(value.slice(0,100), /失败|错误|请先|不可|不足/.test(value)); return; }
    const data = value?.result || value || {}, status = value?.status || data.status;
    const error = !!value?.detail || ['failed','interrupted','insufficient_evidence'].includes(status);
    const detail = typeof value?.detail === 'string' ? value.detail : value?.detail ? JSON.stringify(value.detail) : '';
    const facts = data.guidance?.current_facts || [];
    const why = data.reasons || [];
    const nextChecks = data.guidance?.next_checks || [];
    const checks = data.checks || [];
    const list = values => `<ul>${values.map(item => `<li>${esc(text(item))}</li>`).join('')}</ul>`;
    el('result-summary').innerHTML = `${status ? pill(status) : `<span class="pill ${error ? 'error' : 'ready'}">${error ? '未完成操作' : data.command ? '计划已生成' : '操作已完成'}</span>`}${detail ? `<p>${esc(detail)}</p>` : ''}${data.evidence_scope ? `<p>证据范围：${esc(text(data.evidence_scope))}</p>` : ''}${facts.length ? list(facts) : why.length ? list(why) : ''}${checks.length ? list(checks.map(check => `${check.name || check.title || check.id}：${check.ok === true ? '可用' : check.ok === false ? '不可用' : text(check.status)}`)) : ''}${nextChecks.length ? `<h3>下一项检查</h3>${list(nextChecks)}` : ''}${data.command ? '<p>请展开原始结果核对计划与目标设备。生成计划不会执行操作。</p>' : ''}${data.rule_version ? `<p>验收规则：<code>${esc(data.rule_version)}</code></p>` : ''}${value?.id ? `<p>记录编号：<code>${esc(value.id)}</code></p>` : ''}${!status && !detail && !data.command ? '<p>详细内容已保留，可展开下方原始结果查看。</p>' : ''}`;
    notify(detail || (status ? `本次结果：${text(status)}` : data.command ? '计划已生成，请查看右侧结果' : '操作已完成，请查看右侧结果'), error);
  }
  function groupFields(ids, containerClass = 'form-grid') {
    const fields = ids.map(id => el(id)?.closest('label')).filter(Boolean);
    if (!fields.length) return;
    const group = document.createElement('div'); group.className = containerClass;
    fields[0].before(group); group.append(...fields); return group;
  }
  function foldFields(ids, title) {
    const fields = ids.map(id => el(id)?.closest('label')).filter(Boolean);
    if (!fields.length) return;
    const details = document.createElement('details'); details.className = 'advanced';
    const summary = document.createElement('summary'); summary.textContent = title;
    fields[0].before(details); details.append(summary,...fields); return details;
  }
  const componentNames = {controller:'主控', servo_bench:'单舵机台架', joint_group:'关节组', imu:'IMU', camera:'摄像头', whole_robot:'整机'};
  function hydrateComponents(components) {
    Object.keys(componentNames).forEach(key => { const select = el(`component-${key}`); if (select) select.value = components[key]?.state || ''; });
  }
  function setupComponents() {
    const field = el('hardware-components').closest('label');
    const container = document.createElement('div');
    container.innerHTML = `<h3 class="section-title">部件准备进度</h3><p class="muted" style="font-size:12px;margin-top:7px">按实际情况记录；摄像头可以作为独立支线推进。</p><div class="component-grid">${Object.entries(componentNames).map(([key,name]) => `<label>${name}<select id="component-${key}" data-component="${key}"><option value="">未记录</option>${['planned','owned','installed','detected','verified','failed'].map(state => `<option value="${state}">${text(state)}</option>`).join('')}</select></label>`).join('')}</div>`;
    field.before(container);
    foldFields(['hardware-components'],'高级：查看或编辑部件原始数据');
    container.addEventListener('change', event => {
      const key = event.target.dataset.component; if (!key) return;
      let components;
      try { components = JSON.parse(el('hardware-components').value || '{}'); } catch { notify('部件原始数据格式错误，请先修正 JSON。',true); return; }
      if (!components || Array.isArray(components) || typeof components !== 'object') { notify('部件原始数据必须是对象。',true); return; }
      if (event.target.value) components[key] = {...(components[key] || {}),state:event.target.value}; else delete components[key];
      el('hardware-components').value = JSON.stringify(components,null,2);
    });
    el('hardware-components').addEventListener('change', () => { try { hydrateComponents(JSON.parse(el('hardware-components').value)); } catch { notify('部件 JSON 格式错误',true); } });
  }
  function setupEvidenceForms() {
    const benchField = el('bench').closest('label'), benchForm = document.createElement('div');
    benchForm.innerHTML = '<div class="form-grid"><label>发送总数<input id="bench-sent" type="number" min="0" step="1" placeholder="填写实测计数"></label><label>丢包总数<input id="bench-lost" type="number" min="0" step="1" placeholder="填写实测计数，允许 0"></label><label>实际完整时长（秒）<input id="bench-duration" type="number" min="0" step="any" placeholder="填写实际时长"></label></div><p class="muted" style="font-size:12px;margin-top:15px">至少 60 秒且零丢包，仍需满足硬件确认和完整证据要求。未提供的数据保持不可用。</p>';
    benchField.before(benchForm); foldFields(['bench'],'原始计数与其他证据（JSON）');
    const benchFields = {'bench-sent':'packets_sent','bench-lost':'packets_lost','bench-duration':'duration_s'};
    benchForm.addEventListener('input', event => {
      const key = benchFields[event.target.id]; if (!key) return;
      try { const raw = JSON.parse(el('bench').value); raw[key] = event.target.value === '' ? null : Number(event.target.value); el('bench').value = JSON.stringify(raw,null,2); }
      catch { notify('原始数据 JSON 格式错误，请先修正。',true); }
    });
    el('bench').addEventListener('change', () => {
      try { const raw = JSON.parse(el('bench').value); for (const [id,key] of Object.entries(benchFields)) el(id).value = raw[key] ?? ''; }
      catch { notify('原始数据 JSON 格式错误。',true); }
    });
    const issueField = el('issue-data').closest('label'), issueForm = document.createElement('div');
    issueForm.innerHTML = '<label>问题标题<input id="issue-title" placeholder="例如：主控 SSH 连接失败"></label><label>实际症状<textarea id="issue-symptom" placeholder="发生了什么？当时在执行哪一步？"></textarea></label><div class="form-grid"><label>严重程度<select id="issue-severity"><option value="warning">需要排查</option><option value="info">一般记录</option><option value="critical">阻塞 / 高风险</option></select></label><label>下一项检查<input id="issue-next-check" placeholder="填写可执行的下一项检查"></label></div>';
    issueField.before(issueForm); foldFields(['issue-data'],'高级：可能原因与证据引用');
    el('issue-data').value = JSON.stringify({title:'',severity:'warning',symptom:'',suspected_causes:[],next_checks:[],evidence_refs:[]},null,2);
    issueForm.addEventListener('input', event => {
      try {
        const data = JSON.parse(el('issue-data').value);
        const fields = {'issue-title':'title','issue-symptom':'symptom','issue-severity':'severity','issue-next-check':'next_checks'};
        const key = fields[event.target.id]; if (!key) return;
        data[key] = key === 'next_checks' ? event.target.value.trim() ? [event.target.value.trim()] : [] : event.target.value;
        el('issue-data').value = JSON.stringify(data,null,2);
      } catch { notify('问题原始数据 JSON 格式错误，请先修正。',true); }
    });
    el('issue-data').addEventListener('change', () => {
      try { const data = JSON.parse(el('issue-data').value); el('issue-title').value = data.title || ''; el('issue-symptom').value = data.symptom || ''; el('issue-severity').value = data.severity || 'warning'; el('issue-next-check').value = (data.next_checks || []).join('；'); }
      catch { notify('问题原始数据 JSON 格式错误。',true); }
    });
    const deploymentNote = document.createElement('div'); deploymentNote.className = 'inline-note';
    deploymentNote.innerHTML = '<span>先在“策略包检查”中填写策略路径。部署目标使用“主控诊断”中的 SSH 配置。</span><button data-view="deployment" data-target-card="policy">策略路径</button><button data-view="controller" data-target-card="controller">目标主控</button>';
    el('card-deployment').querySelector('h2').after(deploymentNote);
  }
  function syncRuns(runs) {
    el('active-run-bar').hidden = !runs.bench && !runs.training;
    el('stop-bench').hidden = !runs.bench; el('stop-training').hidden = !runs.training;
  }
  function syncTargets() {
    for (const [target,ids] of [['training-target',['training-wsl-distro','training-wsl-path']], ['settings-target',['settings-wsl-distro','settings-wsl-path']]]) {
      ids.forEach(id => { el(id).closest('label').hidden = el(target).value !== 'wsl'; });
    }
  }
  function init() {
    clear();
    for (const [key, items] of Object.entries(tabs)) {
      const bar = document.createElement('div'); bar.className = 'workspace-tabs'; bar.setAttribute('role','tablist'); bar.setAttribute('aria-label',`${views[key][0]}功能`);
      bar.innerHTML = items.map(([id,label]) => `<button role="tab" id="tab-${id}" data-card="${id}" aria-controls="card-${id}">${label}</button>`).join('');
      el(`view-${key}`).prepend(bar);
      for (const [id] of items) { el(`card-${id}`).setAttribute('role','tabpanel'); el(`card-${id}`).setAttribute('aria-labelledby',`tab-${id}`); }
      bar.addEventListener('click', event => { const button = event.target.closest('[data-card]'); if (button) { selectCard(key,button.dataset.card); renderGuide(); } });
      bar.addEventListener('keydown', event => {
        const buttons = [...bar.querySelectorAll('button')], index = buttons.indexOf(document.activeElement);
        if (index < 0 || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].click(); buttons[next].focus();
      });
    }
    document.addEventListener('click', event => {
      const viewButton = event.target.closest('[data-view]');
      if (viewButton) { selectedTask = null; navigate(viewButton.dataset.view,viewButton.dataset.targetCard); }
      const taskButton = event.target.closest('[data-task]'); if (taskButton) openTask(taskButton.dataset.task);
      const runButton = event.target.closest('[data-run]');
      if (runButton) { navigate('records','timeline'); el('run-timeline-id').value = runButton.dataset.run; el('run-timeline').click(); const run = report?.runs.find(item => item.id === runButton.dataset.run); if (run) { el('status').textContent = JSON.stringify(run,null,2); result(run); } }
    });
    el('menu-toggle').onclick = () => { const open = document.body.classList.toggle('nav-open'); el('menu-toggle').setAttribute('aria-expanded',String(open)); };
    el('menu-dismiss').onclick = closeMenu;
    el('toast-close').onclick = () => { el('toast').hidden = true; };
    el('stop-bench').onclick = () => el('probe-cancel').click();
    el('stop-training').onclick = () => el('training-cancel').click();
    el('edit-project').onclick = () => { el('project-picker').hidden = !el('project-picker').hidden; if (!el('project-picker').hidden) el('project-list').focus(); };
    el('refresh-overview').onclick = () => el('report').click();
    el('quick-search').onclick = () => { navigate('knowledge'); el('search-query').focus(); };
    el('toggle-all-tasks').onclick = () => { el('all-tasks').hidden = !el('all-tasks').hidden; if (!el('all-tasks').hidden) el('all-tasks').scrollIntoView({block:'start'}); };
    document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); el('quick-search').click(); } if (event.key === 'Escape') closeMenu(); });
    window.addEventListener('popstate', () => navigate(location.hash.slice(1),null,false));
    el('search-query').addEventListener('keydown', event => { if (event.key === 'Enter') el('search-run').click(); });
    el('record-search-query').addEventListener('keydown', event => { if (event.key === 'Enter') el('record-search').click(); });
    setupComponents();
    setupEvidenceForms();
    groupFields(['servo-model','servo-count','servos','controller-model','imu-model','power-voltage','printed-version']);
    foldFields(['runtime-version','training-repo','training-revision'],'软件版本与复现信息');
    groupFields(['probe-ids','probe-seconds']); groupFields(['controller-user','controller-port']);
    groupFields(['training-recipe','training-target','training-num-envs','training-iterations','training-gpus','training-seed']);
    groupFields(['training-wsl-distro','training-wsl-path']);
    foldFields(['training-parent-run','training-checkpoint'],'从已有 checkpoint 续训');
    foldFields(['exp-baseline','exp-context'],'实验基线与完整条件');
    foldFields(['settings-thresholds'],'高级：告警阈值');
    for (const id of ['run-left-id','run-right-id','exp-link-run-id','issue-link-run-id']) el(id).setAttribute('list','finished-run-options');
    for (const id of ['run-timeline-id','training-parent-run']) el(id).setAttribute('list','run-options');
    el('issue-run-id').setAttribute('list','failed-run-options');
    for (const id of ['exp-update-id','exp-left-id','exp-right-id']) el(id).setAttribute('list','experiment-options');
    el('issue-update-id').setAttribute('list','issue-options');
    for (const input of document.querySelectorAll('input[list]')) input.placeholder = '选择已有记录，或输入记录编号';
    for (const key of ['hardware','settings','training']) el(`card-${key}`).addEventListener('input', () => { if (!rendering) dirty.add(key); });
    for (const id of ['save-hardware','settings-save','probe-plan','controller-plan','preflight','training-plan','training-full-plan','exp-create','issue-save','search-run','report','create']) el(id).classList.add('primary');
    el('training-target').addEventListener('change',syncTargets);
    el('settings-target').addEventListener('change',syncTargets);
    syncTargets();
    document.querySelectorAll('.card input, .card select, .card textarea').forEach(field => {
      if (field.id && !field.closest('#card-project')) initialFields.set(field.id,field.type === 'checkbox' ? field.checked : field.value);
    });
    // Every existing async operation gets local busy/error feedback without changing confirmations.
    document.querySelectorAll('.card button').forEach(button => {
      const handler = button.onclick; if (!handler || handler.constructor.name !== 'AsyncFunction') return;
      button.onclick = async event => {
        if (button.dataset.busy === 'true') return;
        const selectedProject = el('project-list').value;
        button.dataset.busy = 'true'; button.setAttribute('aria-busy','true'); button.disabled = true;
        try { await handler.call(button,event); }
        catch (error) { if (el('project-list').value === selectedProject) { connection(false); result(`操作未完成：${error.message}。请检查本地服务后重试。`); } }
        finally { button.dataset.busy = 'false'; button.removeAttribute('aria-busy'); button.disabled = button.dataset.gated === 'true'; }
      };
    });
    navigate(location.hash.slice(1) || 'overview',null,false);
  }
  return {init, navigate, renderReport, result, clear, reset, connection, hydrateComponents, syncTargets, syncRuns, isDirty: key => dirty.has(key), saved: key => dirty.delete(key)};
})();
