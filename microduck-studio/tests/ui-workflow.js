// Run only against the isolated validation server, never the daily database.
async (page) => {
  const base = 'http://127.0.0.1:8766';
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()); });
  await page.goto(base);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#next-action').click();
  const name = `UI 验证 ${Date.now()}`;
  await page.locator('#name').fill(name);
  await page.locator('#root').fill('/tmp/microduck-studio-ui-fixture');
  await page.locator('#create').click();
  await page.waitForFunction(expected => document.getElementById('duck-name').textContent === expected, name);
  const project = await page.locator('#project-list').inputValue();
  check(!!project, '创建项目后应选中真实项目');
  await page.getByRole('button',{name:'我的鸭子',exact:true}).click();
  await page.locator('#servo-count').fill('2');
  await page.locator('#component-servo_bench').selectOption('owned');
  await page.locator('#save-hardware').click();
  await page.waitForFunction(() => document.getElementById('save-hardware').getAttribute('aria-busy') !== 'true');
  await page.getByRole('button',{name:'舵机实验室',exact:true}).click();
  check(await page.locator('#probe-run').isDisabled(), '未确认硬件必须保持执行门禁');
  await page.getByRole('button',{name:'我的鸭子',exact:true}).click();
  await page.locator('#servo-model').fill('HL-2915');
  await page.locator('#save-hardware').click();
  await page.waitForFunction(() => document.getElementById('duck-model').textContent === 'HL-2915');
  let report = await (await page.request.get(`${base}/api/projects/${project}/report`)).json();
  check(report.hardware.data.components.servo_bench.state === 'owned', '可视化部件表单必须保留正确状态');
  await page.locator('#controller-model').fill('未保存的主控');
  await page.locator('#refresh-overview').click();
  await page.waitForFunction(() => document.getElementById('report').getAttribute('aria-busy') !== 'true');
  check(await page.locator('#controller-model').inputValue() === '未保存的主控', '报告刷新不能覆盖未保存硬件');
  await page.getByRole('button',{name:'舵机实验室',exact:true}).click();
  await page.getByRole('tab',{name:'连续测试判定',exact:true}).click();
  check(await page.locator('#bench-sent').inputValue() === '', '新测试不能预填模拟计数');
  await page.locator('#bench-run').click();
  await page.waitForFunction(() => document.getElementById('result-summary').textContent.includes('证据不足'));
  await page.locator('#bench-sent').fill('100'); await page.locator('#bench-lost').fill('0'); await page.locator('#bench-duration').fill('10');
  await page.locator('#bench-run').click();
  await page.waitForFunction(() => document.getElementById('bench-run').getAttribute('aria-busy') !== 'true');
  report = await (await page.request.get(`${base}/api/projects/${project}/report`)).json();
  check(report.runs[0].status !== 'passed' && report.runs[0].result.raw.duration_s === 10, '不足时长不能因零丢包而通过');
  await page.getByRole('button',{name:'实验与记录',exact:true}).click();
  await page.getByRole('tab',{name:'问题台账',exact:true}).click();
  await page.locator('#issue-title').fill('通信观察不足 60 秒');
  await page.locator('#issue-symptom').fill('测试只完成了 10 秒');
  await page.locator('#issue-next-check').fill('准备完整时长的原始证据');
  await page.locator('#issue-save').click();
  await page.waitForFunction(() => !!document.getElementById('issue-update-id').value);
  report = await (await page.request.get(`${base}/api/projects/${project}/report`)).json();
  check(report.issues[0].title === '通信观察不足 60 秒', '问题表单必须保存到项目记录');
  await page.getByRole('button',{name:'资料与证据',exact:true}).click();
  await page.locator('#search-query').fill('HL-2915'); await page.locator('#search-query').press('Enter');
  await page.waitForFunction(() => document.getElementById('search-body').textContent.includes('guide.md'));
  // Unknown telemetry must stay unavailable instead of becoming a numeric zero.
  await page.evaluate(() => {
    collectTimelineMetrics('null-metric-check', [{type:'metrics',data:{step:1,metrics:{temperature_c:null}}}],true);
  });
  check(await page.locator('#run-live-chart polyline').count() === 0, 'null 遥测不能画出零值曲线');
  // Network feedback must release the control and never claim the operation succeeded.
  await page.route('**/api/projects/*/search?*', route => route.abort());
  await page.locator('#search-query').press('Enter');
  await page.waitForFunction(() => document.getElementById('result-summary').textContent.includes('操作未完成'));
  check(await page.locator('#search-run').isEnabled(), '请求失败后按钮必须恢复可用');
  await page.unroute('**/api/projects/*/search?*');
  // Empty selection must remove prior project state, IDs, charts and evidence.
  await page.locator('#edit-project').click(); await page.locator('#project-list').selectOption('');
  check(await page.locator('#metric-runs').innerText() === '—', '取消项目选择不能保留之前的指标');
  check(await page.locator('#issue-update-id').inputValue() === '', '项目切换必须清空旧记录编号');
  // Check every section and subtab with the actual forms, including long JSON evidence.
  const sections = ['hardware','bench','controller','assembly','training','deployment','records','knowledge','settings'];
  for (const width of [375,768,1024,1440]) {
    await page.setViewportSize({width,height:1000});
    for (const section of sections) {
      if (width < 701) await page.locator('#menu-toggle').click();
      await page.locator(`.nav-button[data-view="${section}"]`).click();
      const tabButtons = page.locator(`#view-${section} [role=tab]`);
      for (let i=0; i<await tabButtons.count(); i++) {
        await tabButtons.nth(i).click();
        check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px ${section} 子页 ${i} 存在横向溢出`);
      }
    }
  }
  check(errors.length === 0, `页面脚本错误：${errors.join('; ')}`);
  check(!writes.some(url => /\/bench\/(probe|bam)$|\/training\/(run|smoke)$|\/deployment\/execute$|\/controller\/diagnostic$/.test(url)), 'UI 验证不得打开硬件或启动训练部署');
  return {passed:true, project, checks:['项目创建','硬件保存与执行门禁','部件状态持久化','刷新保留未保存输入','证据不足与时长判定','问题保存','本地检索','缺失遥测不补零','网络失败反馈','项目状态清理','所有分区与子页四档布局','无硬件训练部署操作'], errors};
}
