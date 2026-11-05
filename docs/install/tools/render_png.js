const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({deviceScaleFactor:2});
  const out = process.argv[2];
  for (const f of process.argv.slice(3)) {
    await p.goto('file://' + path.resolve(f));
    const s = await p.$('svg');
    await s.screenshot({ path: path.join(out, path.basename(f, '.svg') + '.png') });
  }
  await b.close();
})();
