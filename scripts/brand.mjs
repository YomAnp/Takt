import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const require = createRequire(
  new URL("../apps/frontend/package.json", import.meta.url),
);
const { chromium } = require("@playwright/test");
const directory = new URL("../apps/frontend/public/brand/", import.meta.url);
const logo = await readFile(new URL("logo.svg", directory), "utf8");
const browser = await chromium.launch({ channel: "chrome", headless: true });

try {
  for (const [name, size, type] of [
    ["avatar.jpg", 1024, "jpeg"],
    ["apple-touch-icon.png", 180, "png"],
  ]) {
    const page = await browser.newPage({
      viewport: { width: size, height: size },
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<style>html,body{margin:0;width:100%;height:100%;background:#f5f4eb}svg{display:block;width:100%;height:100%}</style>${logo}`,
    );
    const image = await page.screenshot({
      type,
      ...(type === "jpeg" ? { quality: 95 } : {}),
    });
    const destination = new URL(name, directory);
    await writeFile(destination, image);
    console.log(fileURLToPath(destination));
    await page.close();
  }
} finally {
  await browser.close();
}
