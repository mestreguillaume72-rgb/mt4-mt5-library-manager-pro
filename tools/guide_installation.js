// Génère les guides PDF depuis leur guide.html : macOS et Windows.
// Usage : node tools/guide_installation.js   (nécessite Playwright + Chromium)
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

const guides = [
  [path.resolve(__dirname, "..", "packaging", "macos", "installation"), "Guide d'installation.pdf"],
  [path.resolve(__dirname, "..", "packaging", "windows"), "Guide d'installation Windows.pdf"],
];

(async () => {
  const browser = await chromium.launch();
  for (const [folder, name] of guides) {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(path.join(folder, "guide.html")).href);
    await page.waitForLoadState("networkidle");
    const target = path.join(folder, name);
    await page.pdf({ path: target, format: "A4", printBackground: true, preferCSSPageSize: true });
    await page.close();
    console.log(`Guide écrit : ${target}`);
  }
  await browser.close();
})();
