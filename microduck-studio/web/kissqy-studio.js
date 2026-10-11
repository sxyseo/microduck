/* Local adapter UI for the Microduck-kissqy training service. */
window.KissqyStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const endpoint = () => `/api/projects/${encodeURIComponent(project)}/kissqy`;
  const states = {waiting:'排队中',starting:'启动中',running:'运行中',stopping:'正在停止',completed:'已完成',failed:'失败',stopped:'已停止',cancelled:'已取消'};
  let project = null, generation = 0, snapshot = null, timer = null, busy = false, requestId = null, projectHardware = null;

  async function request(path, options = {}) {
    const response = await StudioAPI.fetch(path, options);
    const type = response.headers.get('content-type') || '';
    const value = type.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) throw Error(typeof value?.detail === 'string' ? value.detail : `训练台请求失败 (${response.status})`);
    return value;
  }
  const post = (path, body) => request(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const message = (text, warning = false) => {
    const node = $('kissqy-message');
    node.textContent = text;
    node.classList.toggle('warning', warning);
  };
  const fmtTime = value => Number.isFinite(value) ? new Date(value * 1000).toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';

  function renderTasks() {
    const select = $('kissqy-task');
    const tasks = (snapshot?.tasks || []).filter(task => task.enabled === true);
    const selected = select.value;
    select.replaceChildren(new Option(tasks.length ? '选择上游任务' : '当前没有可用任务', ''), ...tasks.map(task => new Option(`${task.name || task.id} · ${task.role || task.engine || '训练任务'}`, task.id)));
    if (tasks.some(task => task.id === selected)) select.value = selected;
  }

  function renderQueue() {
    const queue = snapshot?.queue || {entries:[]};
    const entries = queue.entries || [];
    const active = snapshot?.jobs?.filter(job => job.op === 'train' && ['starting','running','stopping'].includes(job.status)) || [];
    const waiting = entries.filter(entry => entry.status === 'waiting');
    const canStart = !!snapshot?.connected && waiting.length > 0 && waiting.every(entry => entry.linked_to_project);
    const linkedJobIds = new Set((snapshot?.linked_runs || []).map(run => run.job_id).filter(Boolean));
    const canStop = !!snapshot?.connected && active.length > 0 && active.every(job => linkedJobIds.has(job.id));
    const canPause = !!snapshot?.connected && queue.enabled && (!waiting.length || waiting.every(entry => entry.linked_to_project));
    $('kissqy-queue-start').disabled = busy || !canStart;
    $('kissqy-queue-pause').disabled = busy || !canPause;
    $('kissqy-queue-stop').disabled = busy || !canStop;
    $('kissqy-queue-summary').textContent = queue.enabled ? '队列执行中' : active.length ? '训练进行中' : `${waiting.length} 项等待`;
    $('kissqy-queue-list').innerHTML = entries.length ? entries.map((entry, index) => {
      const request = entry.request || {}, progress = entry.progress;
      const pct = Number.isFinite(progress?.percent) ? `${Math.floor(progress.percent)}%` : '';
      const ownership = entry.linked_to_project ? '<span class="kissqy-owned">当前项目</span>' : '<span class="kissqy-unlinked">上游其他记录</span>';
      const runControls = entry.job_id && entry.linked_to_project ? `<div class="kissqy-row-actions"><button type="button" data-kissqy-log="${esc(entry.job_id)}">查看日志</button>${entry.status === 'completed' ? `<a class="kissqy-download" href="${esc(StudioAPI.url(`${endpoint()}/jobs/${encodeURIComponent(entry.job_id)}/model.zip`))}">下载策略包 ZIP</a>` : ''}${['failed','stopped'].includes(entry.status) ? `<button type="button" data-kissqy-retry="${esc(entry.id)}">重试此项</button>` : ''}</div>` : '';
      const progressText = progress ? `${Number(progress.done || 0).toLocaleString()} / ${Number(progress.total || 0).toLocaleString()} 轮 · ${pct}` : `配置快照 ${esc(String(entry.recipe_sha256 || '').slice(0,8) || '已保存')}`;
      return `<article class="kissqy-queue-row"><span class="kissqy-queue-index">${String(index+1).padStart(2,'0')}</span><div class="kissqy-queue-copy"><div class="kissqy-queue-title"><strong>${esc(request.label || snapshot.tasks?.find(task => task.id === request.task)?.name || request.task || '训练任务')}</strong>${ownership}</div><small>${esc(states[entry.status] || entry.status || '状态不可用')} · ${Number(request.num_envs || 0).toLocaleString()} 环境 × ${Number(request.iterations || 0).toLocaleString()} 轮 · ${esc(progressText)}</small>${entry.message ? `<small class="kissqy-entry-message">${esc(String(entry.message).split('\n')[0])}</small>` : ''}${runControls}<div class="kissqy-log-slot"></div></div></article>`;
    }).join('') : '<div class="empty-state">训练队列为空。加入任务后，状态会从上游持久化队列刷新。</div>';
    $('kissqy-queue-updated').textContent = snapshot?.last_checked ? `同步于 ${new Date(snapshot.last_checked).toLocaleTimeString('zh-CN',{hour12:false})}` : '等待同步';
    renderLinkedRuns();
  }

  function renderLinkedRuns() {
    const rows = snapshot?.linked_runs || [];
    $('kissqy-linked-runs').innerHTML = rows.length ? rows.map(run => {
      const controls = run.job_id ? `<div class="kissqy-row-actions"><button type="button" data-kissqy-log="${esc(run.job_id)}">查看日志</button><a class="kissqy-download" href="${esc(StudioAPI.url(`${endpoint()}/jobs/${encodeURIComponent(run.job_id)}/model.zip`))}">下载策略包 ZIP</a></div>` : '<small>已关联队列项；等待训练服务分配运行编号。</small>';
      return `<article class="kissqy-linked-row"><div><strong>${esc(run.label || run.task_id || '外部训练')}</strong><small>队列 ${esc(run.entry_id || '—')} · ${run.linked_at ? esc(new Date(run.linked_at).toLocaleString('zh-CN',{hour12:false})) : ''}</small></div>${controls}<div class="kissqy-log-slot"></div></article>`;
    }).join('') : '<p class="muted">加入训练队列后，外部任务会关联到当前 Studio 项目。</p>';
  }

  function renderHardware() {
    const hardware = projectHardware;
    $('kissqy-hardware').textContent = hardware?.model ? `${hardware.model} · ${hardware.status === 'confirmed' ? '已确认' : '待确认'}` : '硬件型号待确认';
  }

  function render() {
    if (!snapshot) return;
    const online = snapshot.connected === true;
    const status = $('kissqy-connection');
    status.classList.toggle('online', online);
    status.classList.toggle('offline', !online);
    status.textContent = online ? '训练台已连接' : '训练台不可用';
    $('kissqy-version').textContent = online ? (snapshot.service_version || '版本信息不可用') : '—';
    const env = snapshot.environment || {};
    $('kissqy-environment').textContent = online ? `${env.status || '未知'} · ${env.engine || snapshot.profile?.mode || '执行位置未报告'}` : '未连接';
    renderHardware();
    if (!snapshot.connected) {
      $('kissqy-queue-summary').textContent = '连接后读取';
      $('kissqy-add').disabled = true;
      $('kissqy-queue-start').disabled = true;
      $('kissqy-queue-pause').disabled = true;
      $('kissqy-queue-stop').disabled = true;
      $('kissqy-queue-list').innerHTML = `<div class="empty-state">${esc(snapshot.error || '请检查训练服务')}</div>`;
      $('kissqy-linked-runs').innerHTML = (snapshot.linked_runs || []).map(run => `<article class="kissqy-linked-row"><strong>${esc(run.label || run.task_id || '外部训练')}</strong><small>已保存关联 · ${esc(run.job_id || run.entry_id || '—')}</small></article>`).join('') || '<p class="muted">当前项目暂无外部训练记录。</p>';
      return;
    }
    renderTasks();
    $('kissqy-add').disabled = busy || !$('kissqy-task').value;
    renderQueue();
    renderHardware();
  }

  async function refresh() {
    if (!project || busy) return;
    const current = generation, projectAtRequest = project;
    try {
      const value = await request(endpoint());
      if (current !== generation || project !== projectAtRequest) return;
      snapshot = value;
      render();
      if (!value.connected) message(value.error || '训练服务当前不可用；本地已有记录仍保留。', true);
      else if (value.environment?.ready !== true) message('训练服务已连接，但它报告的训练环境尚未就绪。加入队列不会启动训练。', true);
      else message(`已连接 ${value.service_version || '训练服务'}；此处结果仍是训练 / 仿真证据。`, true);
    } catch (error) {
      if (current === generation) {
        snapshot = {connected:false,error:error.message,queue:{entries:[]},jobs:[],linked_runs:snapshot?.linked_runs || []};
        render();
        message(error.message, true);
      }
    }
  }

  async function sendQueueItem() {
    if (!project || busy || !snapshot?.connected) return;
    const context = generation, path = endpoint();
    const task = $('kissqy-task').value;
    if (!task) return message('先从训练台提供的任务目录中选择一项。', true);
    const envs = Number($('kissqy-envs').value), iterations = Number($('kissqy-iterations').value), servoP = Number($('kissqy-servo-p').value);
    if (!Number.isInteger(envs) || envs < 1 || envs > 8192 || !Number.isInteger(iterations) || iterations < 1 || iterations > 409600000 || !Number.isInteger(servoP) || servoP < 1 || servoP > 32) return message('请填写范围内的并行环境、训练轮数和舵机 P。', true);
    requestId ||= crypto.randomUUID();
    const body = {
      task, label:$('kissqy-label').value.trim(), num_envs:envs, iterations,
      training_firmware_p:servoP, training_action_scale:Number($('kissqy-action-scale').value),
      action_filter:{enabled:$('kissqy-filter-enabled').checked,head_alpha:Number($('kissqy-head-alpha').value),legs_alpha:Number($('kissqy-legs-alpha').value)},
      request_id:requestId,
    };
    busy = true; render(); message('正在向训练台添加参数快照；此操作不会启动训练。');
    try {
      const result = await post(`${path}/queue`, body);
      if (context !== generation) return;
      requestId = null;
      message(result.duplicate ? '此请求已在训练队列中，未重复添加。' : `已加入训练队列 ${result.entry_id}；开始训练仍需单独确认。`);
      await refreshAfterOperation(context, path);
    } catch (error) {
      if (context === generation) message(`${error.message} 若结果未确认，请先刷新队列；Studio 会沿用本次请求编号避免重复添加。`, true);
    } finally { if (context === generation) { busy = false; render(); } }
  }

  async function queueControl(action, entryId = null) {
    if (!project || busy) return;
    if (action === 'start' && !window.confirm('这会启动当前项目关联的上游训练队列，可能占用本机或远程 GPU。继续吗？')) return;
    if (action === 'stop' && !window.confirm('这会向上游训练台发送停止请求，可能中止当前训练。继续吗？')) return;
    const context = generation, path = endpoint();
    busy = true; render(); message(action === 'start' ? '正在请求上游开始队列…' : action === 'stop' ? '正在请求上游停止训练…' : '正在请求上游队列操作…');
    try {
      await post(`${path}/queue/control`, {action,entry_id:entryId,confirm:['start','stop'].includes(action)});
      if (context !== generation) return;
      message(action === 'start' ? '启动请求已送达。Studio 正在读取训练进度和状态。' : action === 'stop' ? '停止请求已送达；等待训练进程报告最终状态。' : '队列操作已完成。');
      await refreshAfterOperation(context, path);
    } catch (error) { if (context === generation) message(error.message, true); }
    finally { if (context === generation) { busy = false; render(); } }
  }

  async function refreshAfterOperation(context, path) {
    if (!project) return;
    try {
      const value = await request(path);
      if (generation === context) { snapshot = value; render(); }
    } catch (error) {
      if (generation === context) message(`操作已送达，但状态刷新失败：${error.message}。使用右上角刷新重读队列。`, true);
    }
  }

  async function showLog(jobId, button) {
    if (!project || !jobId) return;
    const context = generation, path = endpoint();
    const slot = button?.closest('.kissqy-queue-row,.kissqy-linked-row')?.querySelector('.kissqy-log-slot');
    if (!slot) return;
    slot.textContent = '正在读取日志…';
    try {
      const log = await request(`${path}/jobs/${encodeURIComponent(jobId)}/log`);
      if (context !== generation) return;
      slot.innerHTML = `<details open><summary>运行日志</summary><pre>${esc(log)}</pre></details>`;
    } catch (error) { if (context === generation) slot.textContent = `日志读取失败：${error.message}`; }
  }

  function init() {
    $('kissqy-refresh').onclick = () => { void refresh(); };
    $('kissqy-add').onclick = () => { void sendQueueItem(); };
    $('kissqy-queue-start').onclick = () => queueControl('start');
    $('kissqy-queue-pause').onclick = () => queueControl('pause');
    $('kissqy-queue-stop').onclick = () => queueControl('stop');
    $('kissqy-task').addEventListener('change', render);
    $('kissqy-queue-list').addEventListener('click', event => {
      const log = event.target.closest('[data-kissqy-log]');
      if (log) showLog(log.dataset.kissqyLog, log);
      const retry = event.target.closest('[data-kissqy-retry]');
      if (retry) queueControl('retry', retry.dataset.kissqyRetry);
    });
    $('kissqy-linked-runs').addEventListener('click', event => {
      const log = event.target.closest('[data-kissqy-log]');
      if (log) showLog(log.dataset.kissqyLog, log);
    });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && project) refresh(); });
  }

  function receiveReport(report) {
    const next = report?.project?.id || null;
    const changed = next !== project;
    if (changed) { generation++; clearTimeout(timer); requestId = null; snapshot = null; project = next; }
    projectHardware = report?.hardware?.data?.servos ? {model:report.hardware.data.servos.model,status:report.hardware.status} : null;
    if (snapshot) {
      renderHardware();
    }
    if (project && (changed || !snapshot)) refresh();
  }

  function reset() {
    generation++; clearTimeout(timer); project = null; snapshot = null; requestId = null; busy = false; projectHardware = null;
    $('kissqy-connection').className = 'kissqy-status'; $('kissqy-connection').textContent = '等待选择项目';
    $('kissqy-version').textContent = '—'; $('kissqy-environment').textContent = '—'; $('kissqy-queue-summary').textContent = '—'; $('kissqy-hardware').textContent = '—';
    $('kissqy-task').replaceChildren(new Option('连接后读取任务目录',''));
    $('kissqy-queue-list').innerHTML = '<div class="empty-state">连接训练台后查看队列。</div>';
    $('kissqy-linked-runs').innerHTML = '<p class="muted">加入训练队列后，外部任务会关联到当前 Studio 项目。</p>';
    $('kissqy-add').disabled = true; $('kissqy-queue-start').disabled = true; $('kissqy-queue-pause').disabled = true; $('kissqy-queue-stop').disabled = true;
    message('训练台连接状态和任务目录会显示在这里。');
  }

  function onNavigate(key) {
    clearInterval(timer);
    if (key !== 'training' || !project) return;
    refresh();
    timer = setInterval(() => { if (!document.hidden && !busy) refresh(); }, 5000);
  }

  return {init,receiveReport,reset,onNavigate};
})();
