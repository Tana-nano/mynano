// Browser check of the drop screen (not run by pytest).
// Usage: NODE_PATH=<global node_modules> node tools/browser_check.mjs <out dir> <zip with findings> <a unitypackage>
// Screenshots go to <out dir>; results are saved below <out dir>/docs. Needs Playwright for Node.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright"); // require() honours NODE_PATH
const [OUT, ZIP, PKG] = process.argv.slice(2);
const here = path.dirname(fileURLToPath(import.meta.url));
const srv = spawn("python3", [path.join(here, "browser_serve.py"), path.join(OUT, "docs")], { stdio: ["pipe", "pipe", "inherit"] });
const url = await new Promise((ok) => srv.stdout.once("data", (d) => ok(d.toString().trim())));
const b = await chromium.launch();
const shots = async (pg, name) => { await pg.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }); };
for (const [name, w, scheme] of [["home", 1280, "light"], ["home-dark", 1280, "dark"], ["home-narrow", 400, "light"]]) {
  const pg = await b.newPage({ viewport: { width: w, height: 820 }, colorScheme: scheme });
  await pg.goto(url); await shots(pg, name); await pg.close();
}
const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
pg.on("console", (m) => console.log("console:", m.text()));
pg.on("pageerror", (e) => console.log("pageerror:", e.message));
await pg.goto(url);
// drag over: overlay
await pg.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(["x"], "a.zip")); window.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true })); });
await shots(pg, "dragover");
await pg.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(["x"], "a.zip")); window.dispatchEvent(new DragEvent("dragleave", { dataTransfer: dt, bubbles: true })); });
// pick a file
await Promise.all([pg.waitForURL(/results/), pg.setInputFiles("#pick-files", ZIP)]);
await shots(pg, "result");
const res = pg.url();
for (const [name, w, scheme] of [["result-dark", 1280, "dark"], ["result-narrow", 400, "light"]]) {
  const p2 = await b.newPage({ viewport: { width: w, height: 900 }, colorScheme: scheme });
  await p2.goto(res); await shots(p2, name); await p2.close();
}
// drop a synthetic file onto the result page (entry API returns null for synthetic files)
const data = fs.readFileSync(PKG).toString("base64");
await Promise.all([pg.waitForURL((u) => u.toString() !== res), pg.evaluate(([b64, name]) => {
  const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const dt = new DataTransfer(); dt.items.add(new File([bin], name));
  window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
}, [data, path.basename(PKG)])]);
console.log("dropped ->", await pg.title());
// error: unsupported file
await pg.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(["x"], "memo.txt"));
  window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); });
await pg.waitForSelector("#status.error");
await pg.screenshot({ path: path.join(OUT, "error.png") });
// open-folder button
await pg.goto(res); await pg.click("#open-folder"); await pg.waitForTimeout(300);
srv.stdin.end();
await pg.goto(res).catch(() => {});
await b.close();
