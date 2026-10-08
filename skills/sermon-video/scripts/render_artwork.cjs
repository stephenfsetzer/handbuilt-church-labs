#!/usr/bin/env node
// Render native artwork documents using the caller's installed browser runtime, and measure where
// everything landed. The measurements go to assets/layout.json, which `verify` checks for overlaps.
const path = require('path');
const fs = require('fs');
const {pathToFileURL} = require('url');
const args = process.argv.slice(2);
function argument(name) {
  const i = args.indexOf(name);
  if (i < 0 || !args[i + 1]) throw new Error(`Missing ${name}`);
  return args[i + 1];
}
// Elements to measure on each page. Text is measured tightly around the words, not around its container, and
// each line of it is recorded too, so a short line beside the play button is not mistaken for a long one.
const SELECTORS = {
  thumbnail: {logo: '.logo', church: '.church', kicker: '.kicker', title: 'h1', meta: '.meta',
              preacher: '.preacher', portrait: '.portrait', footer: '.footer'},
  'lower-third': {panel: '.panel'},
  intro: {logo: '.logo', church: '.church', title: 'h1', preacher: '.preacher', meta: '.meta'},
  outro: {logo: '.logo', church: '.church', title: 'h1', footer: '.footer'},
};
function measure(selectors) {
  const boxes = {};
  for (const [key, selector] of Object.entries(selectors)) {
    const element = document.querySelector(selector);
    if (!element) continue;
    let rect, lines = null;
    if (element.tagName === 'IMG' || key === 'panel') rect = element.getBoundingClientRect();
    else {
      const range = document.createRange(); range.selectNodeContents(element); rect = range.getBoundingClientRect();
      lines = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);   // one box per line of text
    }
    const box = r => ({x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)});
    if (rect.width > 0 && rect.height > 0) {
      boxes[key] = box(rect);
      if (lines && lines.length) boxes[key].lines = lines.map(box);
    }
  }
  return boxes;
}
(async () => {
  const root = path.resolve(argument('--run-dir'));
  const {chromium} = require(argument('--playwright-module'));
  // --channel chrome (or msedge) uses the browser already installed on the computer. Without it, Playwright
  // needs its own downloaded Chromium, which may not match the installed Playwright version.
  const channel = args.includes('--channel') ? argument('--channel') : undefined;
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const layout = {};
  try {
    for (const name of ['thumbnail', 'intro', 'outro', 'lower-third']) {
      const viewport = name === 'thumbnail' ? {width: 1280, height: 720} : {width: 1920, height: 1080};
      const page = await browser.newPage({viewport});
      await page.goto(pathToFileURL(path.join(root, name + '.html')).href);
      await page.evaluate(() => document.fonts.ready);
      const broken = await page.locator('img').evaluateAll(images => images.filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src));
      if (broken.length) throw new Error(`Missing artwork image: ${broken.join(', ')}`);
      layout[name] = {canvas: [viewport.width, viewport.height], elements: await page.evaluate(measure, SELECTORS[name])};
      await page.screenshot({path: path.join(root, 'assets', name + '.png'), omitBackground: name === 'lower-third'});
      await page.close();
    }
    fs.writeFileSync(path.join(root, 'assets', 'layout.json'), JSON.stringify(layout, null, 1) + '\n');
    console.log(JSON.stringify({status: 'artwork_rendered', run_dir: root}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
