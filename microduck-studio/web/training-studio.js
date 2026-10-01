/* Recipe-bound experiments. Server owns readiness, results and cancellation. */
window.TrainingStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let project, generation=0, plan, run, timer, busy=false, sequence=0;
  const request = async (url, body) => {
    const response = await fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求未完成');
    return data;
  };
  const base = () => `/api/projects/${project}/recipe-training/`;
  const message = text => {$('pipeline-status').textContent=text;};
  function gate() {
    const active = run?.status === 'running';
    for (const id of ['pipeline-default','pipeline-refresh','pipeline-prepare','pipeline-revision','pipeline-envs','pipeline-iterations','pipeline-seed','pipeline-kp','pipeline-delay-min','pipeline-delay-max']) $(id).disabled=!project||busy||active;
    $('pipeline-start').disabled=!project||busy||active||!plan;
    $('pipeline-cancel').disabled=!active;
    $('pipeline-load').disabled=!project||busy||active||!$('pipeline-history').value;
  }
  function reset() {
    generation++; clearTimeout(timer); project=null;plan=null;run=null;busy=false;sequence=0;
    if (!$('pipeline-status')) return;
    for (const id of ['pipeline-preview','pipeline-result','pipeline-log']) $(id).replaceChildren();
    $('pipeline-revision').replaceChildren(new Option('先选择项目并保存方案',''));
    $('pipeline-history').replaceChildren(new Option('选择方案训练记录',''));
    $('pipeline-progress').value=0;for(const [id,value] of Object.entries({envs:4,iterations:2,seed:42,kp:200,'delay-min':3,'delay-max':6}))$('pipeline-'+id).value=String(value);message('选择已保存的硬件方案，先核对生效参数。');gate();
  }
  const action = fn => () => {
    if (busy) return;
    const token=generation;busy=true;gate();
    Promise.resolve().then(fn).catch(error=>{if(token===generation)message(error.message);})
      .finally(()=>{if(token===generation){busy=false;gate();}});
  };
  async function recipes() {
    if (!project) return;
    const token=generation;
    const versions = await request(`/api/projects/${project}/build-recipes`);
    if(token!==generation)return;
    const selected=$('pipeline-revision').value;
    $('pipeline-revision').replaceChildren(new Option('选择已保存的方案版本',''), ...versions.map(v=>new Option(`v${v.revision} · ${v.data.name}`,String(v.revision))));
    $('pipeline-revision').value=versions.some(v=>String(v.revision)===selected)?selected:String(versions[0]?.revision||'');
    gate();
  }
  function history(runs) {
    const selected=$('pipeline-history').value;
    const names={running:'进行中',passed:'流程完成',failed:'失败',interrupted:'已中断'};
    $('pipeline-history').replaceChildren(new Option('选择方案训练记录',''),...runs.filter(r=>r.kind==='recipe_training').map(r=>new Option(`${r.started_at.slice(0,19)} · ${r.result.recipe?.data?.name||'方案训练'} · ${names[r.status]||r.status}`,r.id)));
    if ([...$('pipeline-history').options].some(o=>o.value===selected)) $('pipeline-history').value=selected;
    gate();
  }
  async function receiveReport(report) {
    if (!project || project!==report.project.id) {
      reset();project=report.project.id;
      const token=generation;
      try {await recipes();} catch(error) {if(token===generation)message(error.message);}
      if(token!==generation)return;
    }
    const active=report.runs.find(r=>r.kind==='recipe_training'&&r.status==='running');
    if(active&&run?.id!==active.id){run=active;sequence=0;poll(active.id,generation);}
    history(report.runs||[]);
  }
  function values() {
    return {revision:Number($('pipeline-revision').value),parameters:{num_envs:Number($('pipeline-envs').value),iterations:Number($('pipeline-iterations').value),seed:Number($('pipeline-seed').value),kp_fw:Number($('pipeline-kp').value),delay_steps:[Number($('pipeline-delay-min').value),Number($('pipeline-delay-max').value)]}};
  }
  function invalidate() {plan=null;$('pipeline-preview').replaceChildren();$('pipeline-result').replaceChildren();$('pipeline-log').textContent='';$('pipeline-progress').value=0;gate();}
  function renderPlan(value) {
    if(value.status!=='ready') {
      $('pipeline-preview').innerHTML=`<div class="pipeline-blocked"><strong>先补齐这些条件</strong><ul>${value.blockers.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><button data-view="guide">回到硬件与安装方案</button></div>`;
      message('当前方案尚不能开始训练；阻塞项已列出。');return;
    }
    plan=value;
    const a=plan.actuator, p=plan.parameters;
    $('pipeline-preview').innerHTML=`<div class="pipeline-ready"><span class="pill passed">输入快照已准备</span><h3>${esc(plan.recipe.data.name)} · v${plan.recipe.revision}</h3><dl class="pipeline-facts"><div><dt>执行器</dt><dd>${esc(a.family)} / M6</dd></div><div><dt>实际仿真电压</dt><dd>${a.voltage_range_v.join('–')} V</dd></div><div><dt>固件增益 / 延迟</dt><dd>${a.kp_fw} / ${a.delay_steps.join('–')} 步</dd></div><div><dt>训练量</dt><dd>${p.num_envs} 环境 × ${p.iterations} 轮 × 24 步</dd></div><div><dt>运行环境</dt><dd>本地 CPU · 种子 ${p.seed}</dd></div><div><dt>接口</dt><dd>61 观测 / 14 动作 / 50 Hz</dd></div></dl><p>MJCF、网格与 BAM 已保存为独立快照。动作不滤波；电压压降随机化为 0。训练结束后自动导出含归一化的 ONNX，并记录 5 秒同环境回放。</p><p>主控、摄像头和打印件的质量与惯量以指定 MJCF 为准；更改硬件下拉选项不会自动重建结构。</p><details><summary>模型来源与校验值</summary><pre>${esc(JSON.stringify({model:plan.recipe.data.cad_path,bam:plan.recipe.data.bam_path,model_sha256:plan.prepared.model_sha256,bam_sha256:plan.prepared.bam_sha256,versions:plan.prepared.versions},null,2))}</pre></details></div>`;
    message('生效配置已列出。点击“开始本地训练”启动本机独立进程。');
  }
  function renderResult(value) {
    const result=value.result||{}, m=result.manifest;
    if(value.status==='running')return;
    $('pipeline-progress').value=value.status==='passed'?100:$('pipeline-progress').value;
    message(result.error||result.verdict||`实验${value.status}`);
    if(!result.artifacts_available||!m){
      $('pipeline-result').innerHTML=`<div class="inline-note warning">${value.status==='interrupted'?'实验已中断':'实验未完成'} · 没有可用的完整策略包。可重新准备后重试。</div>`;
      $('pipeline-log').textContent=(result.execution?.stderr||result.error||$('pipeline-log').textContent).slice(-12000);return;
    }
    const prefix=base()+value.id+'/';
    $('pipeline-result').innerHTML=`<div class="pipeline-ready"><span class="eyebrow">EXPERIMENT COMPLETE</span><h3>方案 v${result.recipe.revision} 的训练产物已保存</h3><dl class="pipeline-facts"><div><dt>训练完成</dt><dd>${m.completed_iterations} 轮</dd></div><div><dt>ONNX 输出最大误差</dt><dd>${m.onnx_equivalence_max_error.toExponential(2)}</dd></div><div><dt>回放期间自动重置</dt><dd>${m.evaluation.episode_resets} 次</dd></div><div><dt>躯干高度范围</dt><dd>${m.evaluation.height_range_m.map(x=>x.toFixed(3)).join('–')} m</dd></div></dl><p class="inline-note warning">${esc(m.evaluation.note)} 小规模实验只验证流程，不证明步态收敛或实机兼容。</p><div class="visual-actions"><a class="pipeline-download" href="${prefix}policy.onnx" download>下载 ONNX</a><a class="pipeline-download" href="${prefix}manifest.json" download>实验清单</a><a class="pipeline-download" href="${prefix}checkpoint.pt" download>Checkpoint</a>${m.source_snapshot?`<a class="pipeline-download" href="${prefix}sources.zip" download>实验源码</a>`:''}${m.evaluation.geometry_reference_matches?'<button class="primary" id="pipeline-replay">查看 3D 回放</button>':'<span>此模型与原版展示几何不同；可下载轨迹进行核对。</span>'}<a href="${prefix}trajectory.json" download>回放数据</a></div></div>`;
    if($('pipeline-replay')) $('pipeline-replay').onclick=()=>window.InstallationStudio.openTrainingReplay(project,value.id).catch(error=>message(error.message));
  }
  async function poll(id, token) {
    clearTimeout(timer);
    try {
      const [value, events]=await Promise.all([request(`/api/runs/${id}`),request(`/api/runs/${id}/events?after=${sequence}`)]);
      if(token!==generation)return;
      run=value;
      for(const event of events.events){
        sequence=Math.max(sequence,event.sequence);
        if(event.type==='log') $('pipeline-log').textContent=($('pipeline-log').textContent+'\n'+(event.data.text||event.data.line||'')).slice(-12000);
        if(event.type==='metrics'&&Number.isFinite(event.data.progress)) $('pipeline-progress').value=Math.max(0,Math.min(95,95*event.data.progress));
      }
      if(value.status==='running'){
        const params=value.result.parameters, actuator=value.result.actuator;
        $('pipeline-revision').value=String(value.result.recipe.revision);
        for(const [key,id] of [['num_envs','envs'],['iterations','iterations'],['seed','seed']]) $('pipeline-'+id).value=String(params[key]);
        $('pipeline-kp').value=String(actuator.kp_fw);$('pipeline-delay-min').value=String(actuator.delay_steps[0]);$('pipeline-delay-max').value=String(actuator.delay_steps[1]);
        message(`方案 v${value.result.recipe.revision} · ${params.num_envs} 环境 / ${params.iterations} 轮：训练 → ONNX 导出 → 同环境回放。关闭页面后进程仍继续运行。`);
        timer=setTimeout(()=>poll(id,token),1500);
      } else {
        renderResult(value);
        const report=await request(`/api/projects/${project}/report`);
        if(token===generation){history(report.runs);$('report').click();}
      }
      gate();
    } catch(error) {
      if(token===generation){message('读取运行状态失败：'+error.message+'。将自动重试。');timer=setTimeout(()=>poll(id,token),3000);}
    }
  }
  function init() {
    const card=document.createElement('section');card.id='card-pipeline';card.className='card';
    card.innerHTML=`<span class="eyebrow">HARDWARE → TRAINING → ONNX</span><h2>让选定的方案真正进入训练</h2><p>每次实验绑定一个方案版本，保留模型、执行器参数和训练产物。先用短实验确认配置能运行，再判断下一步需要什么证据。</p><ol class="pipeline-steps"><li><b>01</b>选择方案</li><li><b>02</b>检查输入</li><li><b>03</b>本地训练</li><li><b>04</b>导出与回放</li></ol><div class="pipeline-fields"><label>已保存硬件方案<select id="pipeline-revision"><option value="">先选择项目并保存方案</option></select></label><div class="visual-actions"><button id="pipeline-refresh">刷新方案</button><button id="pipeline-default">新增 XL330 参考方案</button></div></div><p class="muted">参考方案只用于软件实验。安装方案和实际硬件确认分别保存。</p><div class="field-grid"><label>CPU 并行环境<input id="pipeline-envs" type="number" min="1" max="32" value="4"></label><label>训练轮数<input id="pipeline-iterations" type="number" min="1" max="1000" value="2"></label><label>随机种子<input id="pipeline-seed" type="number" min="0" value="42"></label></div><details><summary>执行器实验参数</summary><p>值会实际进入 BAM 仿真；寄存器增益的含义依型号而定。</p><div class="field-grid"><label>固件增益<input id="pipeline-kp" type="number" min="1" max="1000" value="200"></label><label>最小延迟步数<input id="pipeline-delay-min" type="number" min="0" max="20" value="3"></label><label>最大延迟步数<input id="pipeline-delay-max" type="number" min="0" max="20" value="6"></label></div></details><div class="visual-actions"><button class="primary" id="pipeline-prepare">检查并准备方案</button><button id="pipeline-start" disabled>开始本地训练</button><button id="pipeline-cancel" disabled>中止实验</button></div><p id="pipeline-status" class="inline-note" role="status"></p><div id="pipeline-preview"></div><progress id="pipeline-progress" max="100" value="0" aria-label="方案训练进度"></progress><div id="pipeline-result"></div><details><summary>实时日志与诊断</summary><pre id="pipeline-log" class="pipeline-log"></pre></details><hr><label>历史方案实验<select id="pipeline-history"><option value="">选择方案训练记录</option></select></label><button id="pipeline-load">查看实验结果</button>`;
    $('card-smoke').before(card);
    $('pipeline-default').onclick=action(async()=>{
      const token=generation, pid=project;
      const [defaults, versions]=await Promise.all([request(base()+'defaults'),request(`/api/projects/${pid}/build-recipes`)]);
      if(token!==generation)return;
      if(!defaults.available)throw Error('本机尚无原版训练环境与 BAM 参数。');
      const saved=await request(`/api/projects/${pid}/build-recipes`,{data:defaults.recipe,expected_revision:versions[0]?.revision||0});
      if(token!==generation)return;
      invalidate();await recipes();if(token!==generation)return;$('pipeline-revision').value=String(saved.revision);message(`已新增参考方案 v${saved.revision}，可以检查输入。`);
    });
    $('pipeline-refresh').onclick=action(async()=>{invalidate();await recipes();});
    $('pipeline-prepare').onclick=action(async()=>{
      const token=generation;invalidate();message('正在编译模型、核对执行器并保存输入快照…');
      const result=await request(base()+'prepare',values());if(token===generation)renderPlan(result);
    });
    $('pipeline-start').onclick=action(async()=>{
      const token=generation, id=plan.plan_id;plan=null;
      const value=await request(base()+'start',{plan_id:id,confirm:true});if(token!==generation)return;
      run=value;sequence=0;$('report').click();$('pipeline-log').textContent='';$('pipeline-result').replaceChildren();$('pipeline-progress').value=0;
      await poll(run.id,token);
    });
    $('pipeline-cancel').onclick=()=>{if(!run||run.status!=='running')return;const token=generation;$('pipeline-cancel').disabled=true;request(`/api/runs/${run.id}/cancel`,{}).then(()=>{if(token===generation)message('中止请求已送达，正在等待进程退出。');}).catch(error=>{if(token===generation){message(error.message);gate();}});};
    $('pipeline-load').onclick=action(async()=>{const token=generation;sequence=0;$('pipeline-log').textContent='';const value=await request(`/api/runs/${$('pipeline-history').value}`);if(token===generation){run=value;renderResult(value);}});
    $('pipeline-history').onchange=gate;
    for(const id of ['pipeline-revision','pipeline-envs','pipeline-iterations','pipeline-seed','pipeline-kp','pipeline-delay-min','pipeline-delay-max'])$(id).addEventListener('input',invalidate);
    reset();
  }
  return {init,reset,receiveReport};
})();
