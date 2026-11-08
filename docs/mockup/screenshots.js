// Screenshots of the site pages for the dashboard mockup (README.md in this folder).
//   node docs/mockup/screenshots.js http://127.0.0.1:8800 docs/mockup/img
const {chromium} = require('playwright');
const [base = 'http://127.0.0.1:8800', out = 'docs/mockup/img'] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch();
  const desk = await b.newPage({viewport: {width: 1280, height: 800}, deviceScaleFactor: 2});
  await desk.goto(base + '/live/'); await desk.waitForSelector('table');
  await desk.screenshot({path: out + '/live-all.png'});
  await desk.goto(base + '/live/adab/'); await desk.waitForSelector('.card');
  await desk.screenshot({path: out + '/live-adab.png', fullPage: true});
  for (const v of ['power', 'day', 'energy', 'week', 'temperature']) {   // the history pages of the side menu
    await desk.goto(base + '/live/adab/#' + v); await desk.waitForSelector('svg.chart, .cmp');
    await desk.screenshot({path: `${out}/site-${v}.png`});
  }
  const phone = await b.newPage({viewport: {width: 390, height: 844}, deviceScaleFactor: 2});
  await phone.goto(base + '/live/adab/'); await phone.waitForSelector('.card');
  await phone.screenshot({path: out + '/live-adab-phone.png'});
  await b.close();
})();
