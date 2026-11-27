// falstad_measure.js — cross-check of stage0_check.py inside Falstad CircuitJS (headless Chrome).
// Setup once: cd hardware/sim && npm init -y && PUPPETEER_SKIP_DOWNLOAD=1 npm install puppeteer-core
// Run: node hardware/sim/falstad_measure.js hardware/sim/standalone_frontend.falstad.txt <screenshot-dir>
// For several DUT/Rr cases: load a variant of the Falstad circuit, let it settle, sample
// node A (op-amp out), both ADC pins (1 nF caps) and the Rr current over 2 drive cycles.
const puppeteer = require("puppeteer-core");
const fs = require("fs");
const [, , circuitFile, shotDir] = process.argv;
const base = fs.readFileSync(circuitFile, "utf8").trim().split("\n");

const DUT_Y = { "R_1k": 224, "diode": 288, "LED": 352, "short": 416, "C_100n": 480, "L_100m": 544 };
const RR_X = { 220: 624, 1000: 688, 10000: 752, 100000: 816 };
const CASES = [["R_1k", 1000], ["diode", 1000], ["LED", 1000], ["short", 220], ["R_1k", 100000], ["C_100n", 1000, 1000]];

function variant(dut, rr, freq) {
  return base.map(l => {
    let m = l.match(/^s 400 (\d+) 448 \d+ 0 \d false$/);
    if (m) return `s 400 ${m[1]} 448 ${m[1]} 0 ${+m[1] === DUT_Y[dut] ? 0 : 1} false`;
    m = l.match(/^s (\d+) 480 \d+ 528 0 \d false$/);
    if (m) return `s ${m[1]} 480 ${m[1]} 528 0 ${+m[1] === RR_X[rr] ? 0 : 1} false`;
    if (freq && l.startsWith("R 48 240 0 240 0 1 50 ")) return l.replace(" 1 50 ", ` 1 ${freq} `);
    return l;
  }).join("\n") + "\n";
}
// element indices in file order (line 0 is the "$" header)
const idx = (re, n = 0) => base.slice(1).map((l, i) => re.test(l) ? i : -1).filter(i => i >= 0)[n];
const I_OPAMP = idx(/^a /), I_PIN1 = idx(/^c .* 1e-9 /, 0), I_PIN2 = idx(/^c .* 1e-9 /, 1);
const I_RR = Object.fromEntries(Object.entries(RR_X).map(([rr, x]) => [rr, idx(new RegExp(`^r ${x} 528 ${x} 592 `))]));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    headless: "new", defaultViewport: { width: 1700, height: 1000 },
  });
  const page = await browser.newPage();
  await page.goto("https://www.falstad.com/circuit/circuitjs.html", { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForFunction(() => window.CircuitJS1 && window.CircuitJS1.importCircuit, { timeout: 60000 });
  console.log("case            | V(A) min..max   | ADC34 min..max | ADC35 min..max | I(Rr) peak");
  for (const [dut, rr, freq] of CASES) {
    const f = freq || 50;
    await page.evaluate(t => window.CircuitJS1.importCircuit(t, false), variant(dut, rr, freq));
    const r = await page.evaluate(async (ia, ip1, ip2, irr, period) => {
      const api = window.CircuitJS1;
      const num = s => { const m = s.match(/(-?[\d.]+)\s*([pnuμmkM]?)/); const k = { p: 1e-12, n: 1e-9, u: 1e-6, "μ": 1e-6, m: 1e-3, "": 1, k: 1e3, M: 1e6 }; return +m[1] * k[m[2]]; };
      const pick = (e, key) => { const line = e.getInfo().find(x => x.startsWith(key)); return line ? num(line.split("=")[1]) : NaN; };
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      while (api.getTime() < 2 * period) await sleep(50);          // settle
      const t0 = api.getTime(); const s = { a: [], p1: [], p2: [], i: [] };
      while (api.getTime() < t0 + 2 * period) {
        const el = api.getElements();
        s.a.push(pick(el[ia], "Vout")); s.p1.push(pick(el[ip1], "Vd")); s.p2.push(pick(el[ip2], "Vd"));
        s.i.push(pick(el[irr], "I")); await sleep(5);
      }
      const mm = v => [Math.min(...v), Math.max(...v)];
      return { n: s.a.length, a: mm(s.a), p1: mm(s.p1), p2: mm(s.p2), i: Math.max(...s.i.map(Math.abs)) };
    }, I_OPAMP, I_PIN1, I_PIN2, I_RR[rr], 1 / f);
    const fx = x => x.toFixed(3).padStart(6);
    console.log(`${(dut + " Rr" + rr + (freq ? " " + freq + "Hz" : "")).padEnd(16)}| ${fx(r.a[0])}..${fx(r.a[1])} | ${fx(r.p1[0])}..${fx(r.p1[1])} | ${fx(r.p2[0])}..${fx(r.p2[1])} | ${(r.i * 1e3).toFixed(2)} mA  (${r.n} samples)`);
    await page.screenshot({ path: `${shotDir}/case_${dut}_${rr}${freq ? "_" + freq : ""}.png` });
  }
  await browser.close();
})().catch(e => { console.error("FAILED:", e.message); process.exit(1); });
