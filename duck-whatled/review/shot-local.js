const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath:
      '/Users/abel/Library/Caches/ms-playwright/chromium_headless_shell-1237/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  });
  const shots = [
    { name: 'local-home-desktop', url: 'http://127.0.0.1:8787/', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'local-home-mobile', url: 'http://127.0.0.1:8787/', viewport: { width: 390, height: 844 }, dsf: 2 },
    { name: 'local-newbie', url: 'http://127.0.0.1:8787/learn/newbie.html', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'local-advanced', url: 'http://127.0.0.1:8787/learn/advanced.html', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'local-servo', url: 'http://127.0.0.1:8787/learn/servo-debug.html', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'local-training', url: 'http://127.0.0.1:8787/learn/training-guide.html', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'local-newbie-mobile', url: 'http://127.0.0.1:8787/learn/newbie.html', viewport: { width: 390, height: 844 }, dsf: 2 },
  ];
  for (const s of shots) {
    const page = await browser.newPage({ viewport: s.viewport, deviceScaleFactor: s.dsf });
    await page.goto(s.url, { waitUntil: 'networkidle', timeout: 60000 });
    await page.evaluate(() => {
      document.querySelectorAll('.reveal').forEach((el) => el.classList.add('in'));
      document.querySelectorAll('[data-w]').forEach((b) => (b.style.width = b.getAttribute('data-w')));
    });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${s.name}.png`, fullPage: true });
    console.log(`${s.name}.png done`);
    await page.close();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
