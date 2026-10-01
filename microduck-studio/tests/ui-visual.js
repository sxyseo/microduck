// Writes only to an isolated database served on 8766. No hardware or motion calls.
async (hostPage) => {
  const page = await hostPage.context().newPage();
  const base = 'http://127.0.0.1:8766', errors = [], checks = [];
  const check = (condition, message) => { if (!condition) throw new Error(message); checks.push(message); };
  const onError = error => errors.push(error.message);
  const onDialog = dialog => dialog.accept();
  page.on('pageerror', onError); page.on('dialog', onDialog);
  const create = async name => (await (await page.request.post(`${base}/api/projects`, {data:{name,root:'/tmp/microduck-studio-ui-fixture'}})).json()).id;
  const a = await create(`可视化 A ${Date.now()}`), b = await create(`可视化 B ${Date.now()}`);
  const selectProject = async id => {
    if (!await page.locator('#project-list').isVisible()) await page.locator('#edit-project').click();
    await page.locator('#project-list').selectOption(id);
    await page.waitForFunction(expected => document.getElementById('project-list').value === expected,id);
  };
  const visual = async () => {
    await page.locator('.nav-button[data-view="visual"]').click();
    await page.waitForFunction(()=>document.querySelector('iframe')?.contentWindow?.colorStudio && !document.getElementById('visual-save').disabled);
    return page.frames().find(f=>f.url().includes('/color-studio/'));
  };
  const saveVisual = async () => {
    const response = page.waitForResponse(r=>r.url().endsWith('/visual-configs') && r.request().method()==='POST');
    await page.locator('#visual-save').click(); return (await response).json();
  };
  try {
    await page.goto(base); await page.evaluate(id=>{ localStorage.setItem('microduckStudioProjectId',id); sessionStorage.clear(); },a);
    await page.reload(); await page.setViewportSize({width:1440,height:1100});
    let f = await visual();
    check(await f.locator('#part-count').innerText() === '36','3D 模型载入并显示 36 个打印件');
    const part = await f.evaluate(()=>window.colorStudio.getModel().parts.find(p=>p.role==='primary').id);
    const original = await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part);
    await f.locator('#hex-color').fill('#7A9572'); await f.locator('#hex-color').dispatchEvent('change');
    check(await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part)==='#7A9572','可逐件修改配色');
    await f.locator('#undo').click(); check(await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part)===original,'撤销恢复旧颜色');
    await f.locator('#redo').click();
    await f.locator('#inventory-open').click(); await f.locator('#add-stock').click();
    await f.locator('.stock-name').fill('实有哑光绿'); await f.locator('.stock-name').dispatchEvent('change');
    await f.locator('.inventory-close').click();
    await page.locator('#visual-name').fill('苔绿试装方案');
    const first = await saveVisual();
    check(first.revision===1 && first.data.inventory.items[0].name==='实有哑光绿','配色和耗材共同保存为项目版本');
    await f.locator('#hex-color').fill('#D7986C'); await f.locator('#hex-color').dispatchEvent('change');
    const second = await saveVisual(); check(second.revision===2,'修改保存创建新版本');
    await page.locator('#visual-version').selectOption('1'); await page.locator('#visual-load-version').click();
    check(await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part)==='#7A9572','旧版恢复为可编辑草稿');
    await selectProject(b); f = await visual();
    check(await f.evaluate(()=>window.colorStudio.getInventory().items.length)===0,'项目 B 不继承项目 A 的耗材');
    check((await (await page.request.get(`${base}/api/projects/${b}/visual-configs`)).json()).versions.length===0,'新项目没有伪造保存记录');
    await selectProject(a); f = await visual();
    check(await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part)==='#7A9572','切换项目保留未保存的恢复草稿');
    await page.reload(); f = await visual();
    check(await f.evaluate(()=>window.colorStudio.getInventory().items[0].name)==='实有哑光绿','刷新后恢复项目耗材和草稿');
    const concurrent = await page.request.post(`${base}/api/projects/${a}/visual-configs`, {data:{data:second.data,expected_revision:2}});
    check(concurrent.status()===200,'可模拟其他窗口的新版本');
    const conflict = await saveVisual(); check(!!conflict.detail,'旧草稿遇到版本冲突时拒绝覆盖');
    check(await f.evaluate(id=>window.colorStudio.getPalette().parts[id].color,part)==='#7A9572','保存冲突保留当前草稿');
    await page.locator('#visual-add-check').click();
    check(await page.locator('#assembly-checks [data-check]').count()===1,'所选零件可建立装配检查');
    await page.locator('[data-check="0"] [data-field="status"]').selectOption('passed');
    let resultWait=page.waitForResponse(r=>r.url().endsWith('/assemblies') && r.request().method()==='POST');
    await page.locator('#assembly-save').click(); check((await resultWait).status()===400,'没有证据的检查不能通过');
    await page.locator('[data-check="0"] [data-field="evidence"]').fill('模拟验证样例：间隙 0.6 mm；实物未验证');
    resultWait=page.waitForResponse(r=>r.url().endsWith('/assemblies') && r.request().method()==='POST');
    await page.locator('#assembly-save').click(); const assembly=await(await resultWait).json();
    check(assembly.data.checks[0].part_ids[0]===part && assembly.data.model_binding.scope==='reference_geometry_only','装配记录保留零件 ID 和参考模型来源');
    await page.locator('#tab-calibration').click(); await page.locator('#joint-add-row').click();
    check(await page.locator('[data-joint="0"] [data-field="zero_deg"]').inputValue()==='', '新关节没有伪造零位');
    await page.locator('[data-joint="0"] [data-field="name"]').fill('left_hip');
    await page.locator('[data-joint="0"] [data-field="id"]').fill('1');
    await page.locator('[data-joint="0"] [data-field="direction"]').selectOption('-1');
    await page.locator('[data-joint="0"] [data-field="zero_deg"]').fill('2.5');
    await page.locator('[data-joint="0"] [data-field="lower"]').fill('-25');
    await page.locator('[data-joint="0"] [data-field="upper"]').fill('35');
    await page.locator('#calibration-operator').fill('软件测试');
    resultWait=page.waitForResponse(r=>r.url().endsWith('/calibrations') && r.request().method()==='POST');
    await page.locator('#calibration-save').click(); check((await resultWait).status()===400,'硬件未确认时标定仍受服务端门禁约束');
    await page.locator('.nav-button[data-view="hardware"]').click();
    await page.locator('#servo-model').fill('HL-2915'); await page.locator('#servo-count').fill('2'); await page.locator('#save-hardware').click();
    await page.waitForFunction(()=>document.getElementById('duck-model').textContent==='HL-2915');
    await page.locator('.nav-button[data-view="assembly"]').click(); await page.locator('#tab-calibration').click();
    resultWait=page.waitForResponse(r=>r.url().endsWith('/calibrations') && r.request().method()==='POST');
    await page.locator('#calibration-save').click(); const cal=await(await resultWait).json();
    check(cal.data.joints[0].direction===-1 && cal.data.joints[0].zero_deg===2.5 && cal.data.joints[0].limits_deg[0]===-25 && !cal.data.verified,'关节表格按真实输入保存且不会自动标记实物验证');
    await page.locator('#imu-enabled').check();
    check(await page.locator('#imu-angle-0').inputValue()==='', 'IMU 开启后保留未测量值');
    await page.locator('#imu-frame').fill('base_link');
    for (const [i,v] of ['0','90','0'].entries()) await page.locator(`#imu-angle-${i}`).fill(v);
    resultWait=page.waitForResponse(r=>r.url().endsWith('/calibrations') && r.request().method()==='POST');
    await page.locator('#calibration-save').click(); const imu=await(await resultWait).json();
    check(imu.data.imu.rpy_deg[1]===90,'IMU 姿态表单能保存角度');
    f=await visual();
    await f.locator('#explode').evaluate(el=>{el.value='60'; el.dispatchEvent(new Event('input',{bubbles:true}));});
    check(await f.locator('#explode-value').innerText()==='60%','模型支持装配展开');
    await f.locator('#explode').evaluate(el=>{el.value='0'; el.dispatchEvent(new Event('input',{bubbles:true}));});
    await f.locator('#hardware').uncheck(); await f.locator('#hardware').check();
    const overflow=[];
    for (const width of [1440,1024,390]) {
      await page.setViewportSize({width,height:900});
      await page.waitForTimeout(250);
      overflow.push(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    check(overflow.every(Boolean),'桌面、平板、手机外观工作区无页面横向溢出');
    await page.setViewportSize({width:1440,height:1100});
    await page.locator('.nav-button[data-view="assembly"]').click(); await page.locator('#tab-calibration').click();
    check(await page.locator('.joint-range i').count()===1,'关节限位范围显示零位标记');
    check(errors.length===0,`浏览器无脚本异常：${errors.join(';')}`);
    return {projects:[a,b],checks,errors};
  } finally { page.off('pageerror',onError); page.off('dialog',onDialog); await page.close(); }
}
