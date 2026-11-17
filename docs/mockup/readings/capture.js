// Screenshots of the meter readings mockup (docs/mockup/readings/index.html) for the review, in img/.
//   node docs/mockup/readings/capture.js
// Stops with an error if a page writes an error in the console. Needs Playwright with Chromium.
const path = require('path');
const {chromium} = require('playwright');

const HERE = __dirname, URL = 'file://' + path.join(HERE, 'index.html');
const errors = [];

async function page(browser, {width = 1280, height = 900, theme = 'light', mobile = false} = {}) {
  const ctx = await browser.newContext(mobile ? {viewport: {width: 390, height: 844}, deviceScaleFactor: 2, isMobile: true, hasTouch: true}
    : {viewport: {width, height}, deviceScaleFactor: 2});
  await ctx.addInitScript(t => { try { localStorage.setItem('arkan-ui.theme', t); } catch (e) {} }, theme);
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', e => errors.push(String(e)));
  return p;
}
async function go(p, hash) {
  await p.goto(URL + '#' + hash);
  await p.waitForTimeout(900);
}
const shot = (p, name, full = true, h = 0) => p.screenshot({path: path.join(HERE, 'img', name + '.png'), fullPage: full,
  ...(h ? {clip: {x: 0, y: 0, width: p.viewportSize().width, height: h}} : {})});

(async () => {
  const browser = await chromium.launch();
  const p = await page(browser);
  await go(p, 'readings');
  // Power meter 2 is due: its reading now (13:00), about a normal day and 5 hours after the last one; water typed the Indonesian way
  const last = await p.evaluate(() => MMJ.meters.map(m => m.last.value));
  await p.fill('#mmv-pm2', (last[1] + 201.6).toFixed(1));
  await p.fill('#mmv-water', (last[0] + 6.214).toFixed(3).replace(/^(\d+)(\d{3})\./, '$1.$2,'));
  await p.waitForTimeout(200);
  await shot(p, 'desk-enter-typed');
  // What the checks say: a figure lower than the last one (red, not saved), a day far above the usual (amber, saved with a note)
  await p.fill('#mmv-water', (last[0] - 1.2).toFixed(3));
  await p.fill('#mmv-pm2', (last[1] + 520.4).toFixed(1));
  await p.waitForTimeout(200);
  await p.locator('.mmgrid').screenshot({path: path.join(HERE, 'img', 'desk-enter-checks.png')});
  await p.fill('#mmv-water', '');
  await p.fill('#mmv-pm2', (last[1] + 201.6).toFixed(1));
  await p.click('#mmSave');
  await p.waitForTimeout(700);
  await shot(p, 'desk-enter-saved', true, 1000);
  await p.waitForTimeout(3300);   // the toast goes

  await go(p, 'water');
  await shot(p, 'desk-water', true, 1500);
  await p.click('button[data-mmmode="read"]');
  await p.waitForTimeout(300);
  await p.locator('section.card.mt-16').first().screenshot({path: path.join(HERE, 'img', 'desk-water-between.png')});
  await p.click('button[data-mmmode="day"]');
  await p.click('button[data-span="31"]');
  await p.waitForTimeout(500);
  await p.click('tr:has(.pill.info) button[data-mmedit]');   // the reading corrected by an admin: its history in the sheet
  await p.waitForTimeout(300);
  await p.fill('#mmsW', 'Second check on the meter');
  await p.waitForTimeout(200);
  await shot(p, 'desk-correct', false);

  await p.keyboard.press('Escape');
  await go(p, 'pm2');   // with the reading saved above: yesterday has its figure now
  await shot(p, 'desk-pm2', true, 1500);
  const q = await page(browser);
  await go(q, 'pm2');
  await q.locator('.tiles').first().screenshot({path: path.join(HERE, 'img', 'desk-pm2-due.png')});

  const d = await page(browser, {theme: 'dark'});
  await go(d, 'water');
  await shot(d, 'dark-water', false);

  const m = await page(browser, {mobile: true});
  await go(m, 'readings');
  await shot(m, 'phone-enter', false);
  await go(m, 'water');
  await shot(m, 'phone-water', false);

  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('screenshots in', path.join(HERE, 'img'));
})();
