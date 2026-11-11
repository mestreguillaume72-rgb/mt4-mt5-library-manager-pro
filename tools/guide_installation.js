// Génère « packaging/macos/installation/Guide d'installation.pdf » depuis guide.html.
// Usage : node tools/guide_installation.js   (nécessite Playwright + Chromium)
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

(async () => {
  const folder = path.resolve(__dirname, "..", "packaging", "macos", "installation");
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(pathToFileURL(path.join(folder, "guide.html")).href);
  await page.waitForLoadState("networkidle");
  const target = path.join(folder, "Guide d'installation.pdf");
  await page.pdf({ path: target, format: "A4", printBackground: true, preferCSSPageSize: true });
  await browser.close();
  console.log(`Guide écrit : ${target}`);
})();
