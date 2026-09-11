const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath:
      '/Users/abel/Library/Caches/ms-playwright/chromium_headless_shell-1237/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  });
  const shots = [
    { name: 'desktop-full', viewport: { width: 1440, height: 900 }, dsf: 1 },
    { name: 'mobile-full', viewport: { width: 390, height: 844 }, dsf: 2 },
  ];
  for (const s of shots) {
    const page = await browser.newPage({
      viewport: s.viewport,
      deviceScaleFactor: s.dsf,
    });
    await page.goto('https://duck.whatled.com/', { waitUntil: 'networkidle', timeout: 60000 });
    await page.evaluate(() => {
      document.querySelectorAll('.reveal').forEach((el) => el.classList.add('in'));
      document.querySelectorAll('[data-w]').forEach((b) => (b.style.width = b.getAttribute('data-w')));
    });
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `${s.name}.png`, fullPage: true });
    console.log(`${s.name}.png done`);
    await page.close();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
