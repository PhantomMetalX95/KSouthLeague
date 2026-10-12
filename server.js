import "dotenv/config";
import express from "express";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { registerFantasy, googleVerifier } from "./fantasy.js";
import { init, readAll, clean, upsert, remove, saveSite, cascade, saveMatchStats, TABLES } from "./db.js";

const app = express();
const PASS = process.env.ADMIN_PASSWORD || "";
const SECRET = process.env.SESSION_SECRET || PASS;
const DAY = 24 * 3600 * 1000;
/* refuse to unlock admin with a missing, short or placeholder password */
const WEAK = !PASS || PASS.length < 8 || PASS === "change-me-to-something-long";
const dir = path.dirname(fileURLToPath(import.meta.url));

app.disable("x-powered-by");
app.use(express.json({ limit: "100kb" }));

/* --- admin auth: password -> signed 7-day token --- */
const sign = (exp) => crypto.createHmac("sha256", SECRET).update(String(exp)).digest("hex");
const same = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
const tries = new Map();
function limited(ip) {
  const now = Date.now(), t = (tries.get(ip) || []).filter((x) => now - x < 15 * 60 * 1000);
  tries.set(ip, t);
  return t.length >= 10;
}
app.post("/api/login", (req, res) => {
  if (WEAK) return res.status(503).json({ error: "Admin is locked: set ADMIN_PASSWORD on the server (8+ characters, not the example value)" });
  if (limited(req.ip)) return res.status(429).json({ error: "Too many attempts. Try again in 15 minutes." });
  const given = String(req.body?.password ?? "");
  if (!same(crypto.createHash("sha256").update(given).digest("hex"), crypto.createHash("sha256").update(PASS).digest("hex"))) {
    tries.get(req.ip).push(Date.now());
    return res.status(401).json({ error: "Wrong password" });
  }
  const exp = Date.now() + 7 * DAY;
  res.json({ token: `${exp}.${sign(exp)}` });
});
function admin(req, res, next) {
  const [exp, sig] = String(req.get("authorization") || "").replace(/^Bearer /, "").split(".");
  if (!WEAK && exp && sig && +exp > Date.now() && same(sig, sign(exp))) return next();
  res.status(401).json({ error: "Please sign in again" });
}

app.get("/api/me", admin, (_req, res) => res.json({ ok: true }));

/* --- public read --- */
app.get("/api/data", async (_req, res, next) => {
  try { res.set("Cache-Control", "no-store").json(await readAll()); } catch (e) { next(e); }
});

/* --- fantasy league (Google sign-in) --- */
registerFantasy(app, {
  admin,
  secret: process.env.SESSION_SECRET || "",
  clientId: process.env.GOOGLE_CLIENT_ID || "",
  verify: process.env.GOOGLE_CLIENT_ID ? googleVerifier(process.env.GOOGLE_CLIENT_ID) : null,
});

/* --- admin writes --- */
const okId = (id) => /^[A-Za-z0-9_-]{1,60}$/.test(id);
app.put("/api/site", admin, async (req, res, next) => {
  try { await saveSite(req.body || {}); res.json({ ok: true }); } catch (e) { next(e); }
});
app.put("/api/match-stats/:fixture", admin, async (req, res, next) => {
  try {
    if (!okId(req.params.fixture)) return res.status(404).json({ error: "Not found" });
    await saveMatchStats(req.params.fixture, req.body?.rows);
    res.json({ ok: true });
  } catch (e) { next(e); }
});
app.put("/api/:table/:id", admin, async (req, res, next) => {
  try {
    const { table, id } = req.params;
    if (!TABLES[table] || TABLES[table].bulk || !okId(id)) return res.status(404).json({ error: "Not found" });
    await upsert(table, id, clean(table, req.body || {}));
    res.json({ ok: true });
  } catch (e) { next(e); }
});
app.delete("/api/:table/:id", admin, async (req, res, next) => {
  try {
    const { table, id } = req.params;
    if (!TABLES[table] || TABLES[table].bulk || !okId(id)) return res.status(404).json({ error: "Not found" });
    await remove(table, id);
    await cascade(table, id);
    res.json({ ok: true });
  } catch (e) { next(e); }
});

app.use(express.static(path.join(dir, "public")));
app.use((err, _req, res, _next) => {
  if (err.status) return res.status(err.status).json({ error: err.message });
  console.error(err);
  res.status(500).json({ error: "Server error" });
});

await init();
const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`K South League running on http://localhost:${port}`);
  if (WEAK) console.warn("ADMIN_PASSWORD is missing, too short or still the example value: the admin page stays locked.");
});
