const { chromium } = require('playwright-core');
(async () => {
  const browser = await chromium.launch({
    executablePath: '/Users/abel/Library/Caches/ms-playwright/chromium_headless_shell-1237/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  });
  for (const [name, vp, dsf] of [['desktop', {width:1440,height:900}, 1], ['mobile', {width:390,height:844}, 2]]) {
    const page = await browser.newPage({ viewport: vp, deviceScaleFactor: dsf });
    await page.goto('https://duck.whatled.com/', { waitUntil: 'networkidle', timeout: 60000 });
    const r = await page.evaluate(() => {
      const top = (sel) => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().top + scrollY) : null; };
      const b = document.querySelector('.budget');
      return { vw: innerWidth, chips: top('.chips'), progress: top('#progress'), sprint: top('.sprint'), bom: top('.bom-grid'), budget: top('.budget'), budgetEnd: b ? Math.round(b.getBoundingClientRect().bottom + scrollY) : null, docH: document.documentElement.scrollHeight };
    });
    console.log(name, JSON.stringify(r));
    await page.close();
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
