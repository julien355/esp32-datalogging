// Screenshots of the current per phase mockup (docs/mockup/current/index.html) for the review, in img/.
//   node docs/mockup/current/capture.js
// Stops with an error if a page writes an error in the console. Needs Playwright with Chromium.
const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const HERE = __dirname, URL = 'file://' + path.join(HERE, 'index.html'), IMG = path.join(HERE, 'img');
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
  await p.waitForTimeout(1200);
}
const shot = (p, name, h = 0) => p.screenshot({path: path.join(IMG, name + '.png'), fullPage: !h,
  ...(h ? {clip: {x: 0, y: 0, width: p.viewportSize().width, height: h}, fullPage: true} : {})});
// From a heading of the page (an id, or the start of a heading's text) down to the next one (or a number of pixels), the content's width.
// Looked up at the time of the shot: a full-page screenshot resizes the window, and the page is drawn again.
async function part(p, name, from, to, pad = 8) {
  await p.waitForTimeout(700);
  const box = await p.evaluate(([a, b]) => {
    const find = x => x.startsWith('#') ? document.querySelector(x) : [...document.querySelectorAll('#content h2')].find(h => h.textContent.startsWith(x));
    const top = find(a).getBoundingClientRect().top + scrollY, c = document.getElementById('content').getBoundingClientRect();
    const end = typeof b === 'number' ? top + b : find(b).getBoundingClientRect().top + scrollY;
    return {x: c.left + scrollX, y: top, width: c.width, height: end - top};
  }, [from, to]);
  await p.screenshot({path: path.join(IMG, name + '.png'), clip: {x: box.x - pad, y: box.y - pad, width: box.width + 2 * pad, height: box.height}, fullPage: true});
}

(async () => {
  fs.mkdirSync(IMG, {recursive: true});
  const browser = await chromium.launch();
  const p = await page(browser);
  await go(p, 'current');
  await shot(p, 'desk-current-top', 1560);                       // head, tiles, each phase, balancing
  await shot(p, 'desk-current');                                 // the whole page
  await part(p, 'desk-current-charts', 'Current per phase, hour', 'Day by day');
  await part(p, 'desk-current-days', 'Day by day', 'Current alarms');
  await part(p, 'desk-current-checks', '#cchecks', 560);
  await p.waitForTimeout(700);
  await p.click('button[data-cday="2026-11-07"]');               // the highest current of the period
  await p.waitForTimeout(600);
  await part(p, 'desk-current-day', '#cday', 640, 0);
  await p.click('button[data-cday="2026-11-05"]');               // L3 without current
  await p.waitForTimeout(600);
  await part(p, 'desk-current-zero', '#cday', 640, 0);

  await go(p, 'now');                                            // Live now: the current card's new line
  await p.waitForTimeout(400);
  await p.locator('section.card:has(h2:text("Current (A)"))').screenshot({path: path.join(IMG, 'desk-now-current.png')});
  await go(p, 'quality');                                        // Power quality: the imbalance tile links here
  await p.locator('.kpi:has-text("Current imbalance")').screenshot({path: path.join(IMG, 'desk-quality-tile.png')});

  const d = await page(browser, {theme: 'dark'});
  await go(d, 'current');
  await shot(d, 'dark-current', 1560);

  const m = await page(browser, {mobile: true});
  await go(m, 'current');
  await shot(m, 'phone-current', 2400);

  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('screenshots in', IMG);
})();
