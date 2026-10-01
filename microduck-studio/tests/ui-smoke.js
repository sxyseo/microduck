async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  await page.goto('http://127.0.0.1:8765');
  await page.setViewportSize({width: 1440, height: 1000});
  check(await page.getByRole('navigation', {name: '工作台导航'}).count() === 1, '阶段导航应可访问');
  await page.getByRole('button', {name: '我的鸭子', exact: true}).click();
  check(await page.locator('#servo-model').isVisible(), '硬件入口应展示型号表单');
  check(!await page.locator('#training-full-dir').isVisible(), '硬件页不应混入训练表单');
  await page.locator('#servo-model').fill('unsaved-ui-check');
  await page.getByRole('button', {name: '舵机实验室', exact: true}).click();
  check(await page.locator('#probe-port').isVisible(), '舵机实验室应展示端口确认');
  await page.getByRole('button', {name: '我的鸭子', exact: true}).click();
  check(await page.locator('#servo-model').inputValue() === 'unsaved-ui-check', '导航必须保留未保存的输入');
  await page.getByRole('button', {name: '工作台总览', exact: true}).click();
  check(await page.locator('#next-action').isVisible(), '总览应直接提供下一步操作');
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({width, height: 1000});
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px 不应横向溢出`);
  }
  await page.setViewportSize({width: 375, height: 900});
  await page.locator('#menu-toggle').click();
  await page.getByRole('button', {name: '部署与验收', exact: true}).click();
  await page.getByRole('tab', {name: '兼容性与部署', exact: true}).click();
  check(!await page.locator('#deployment-execute').isVisible(), '手机不应显示运动部署启动入口');
  await page.setViewportSize({width: 1440, height: 1000});
  check(await page.locator('#deployment-execute').isVisible(), '桌面应显示部署入口及前置条件状态');
  await page.getByRole('button', {name: '工作台总览', exact: true}).click();
  return {passed: true, checks: ['阶段导航', '分区隔离', '未保存输入保留', '下一步入口', '四档屏幕无溢出', '移动端操作边界']};
}
