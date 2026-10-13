/* K South fantasy league: scoring, team rules, and the API. Pure functions first, routes at the bottom. */
import crypto from "node:crypto";
import { OAuth2Client } from "google-auth-library";
import { db, readAll } from "./db.js";

export const CFG = {
  squad: 10, starters: 7, budget: 50000, clubLimit: 2,
  comp: { GK: 2, DEF: 3, MID: 3, FWD: 2 },                 // squad shape
  formation: { DEF: [2, 3], MID: [2, 3], FWD: [1, 2] },    // allowed range among the 7 starters (plus 1 GK)
  freeTransfers: 2, hitCost: 4, deadlineMinutes: 60,
  appearance: 1, goal: { GK: 6, DEF: 6, MID: 5, FWD: 4 }, assist: 3,
  cs: { GK: 4, DEF: 4, MID: 1, FWD: 0 }, yellow: -1, red: -3, penMissed: -2, captain: 2,
};

const played = (f) => f.hg != null && f.ag != null;
const kickoff = (f) => new Date(`${f.date}T${/^\d{2}:\d{2}$/.test(f.time || "") ? f.time : "09:00"}:00+03:00`).getTime(); // Nairobi time

export function lineupOk(ids, P) {
  if (ids.length !== CFG.starters) return false;
  const c = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const id of ids) { const p = P.get(id); if (!p) return false; c[p.pos]++; }
  const f = CFG.formation;
  return c.GK === 1 && c.DEF >= f.DEF[0] && c.DEF <= f.DEF[1] && c.MID >= f.MID[0] && c.MID <= f.MID[1] && c.FWD >= f.FWD[0] && c.FWD <= f.FWD[1];
}

/* Work out gameweeks, deadlines and every player's points for every gameweek. */
export function analyse({ fixtures, players, stats }) {
  const dates = [...new Set(fixtures.map((f) => f.date))].sort();
  const wk = (f) => (f.week > 0 ? +f.week : dates.indexOf(f.date) + 1);
  const byWeek = new Map();
  for (const f of fixtures) { const n = wk(f); if (!byWeek.has(n)) byWeek.set(n, []); byWeek.get(n).push(f); }
  const hasStats = new Set(stats.map((s) => s.fixture));
  const P = new Map(players.map((p) => [p.id, p]));
  const fxById = new Map(fixtures.map((f) => [f.id, f]));
  const weeks = [...byWeek.keys()].sort((a, b) => a - b).map((n) => {
    const fx = byWeek.get(n);
    const done = fx.filter((f) => played(f) && hasStats.has(f.id)).length;
    return { n, fx, deadline: Math.min(...fx.map(kickoff)) - CFG.deadlineMinutes * 60000, done, total: fx.length, status: done === fx.length ? "done" : done > 0 ? "live" : "upcoming" };
  });
  const pts = new Map(), appeared = new Set();
  for (const s of stats) {
    const f = fxById.get(s.fixture), p = P.get(s.player);
    if (!f || !p) continue;
    if (!(s.played || s.goals || s.assists || s.yellow || s.red || s.pen_missed)) continue;
    const key = wk(f) + "|" + s.player;
    let v = CFG.appearance + (s.goals | 0) * CFG.goal[p.pos] + (s.assists | 0) * CFG.assist + (s.yellow | 0) * CFG.yellow + (s.red | 0) * CFG.red + (s.pen_missed | 0) * CFG.penMissed;
    if (played(f) && (s.team === f.home ? +f.ag : +f.hg) === 0) v += CFG.cs[p.pos];
    pts.set(key, (pts.get(key) || 0) + v);
    appeared.add(key);
  }
  /* played = took part; dnp = their match is finished and they were not on the sheet; none = no match; pending = not known yet */
  const status = (pid, n) => {
    if (appeared.has(n + "|" + pid)) return "played";
    const p = P.get(pid);
    if (!p) return "none";
    const fx = (byWeek.get(n) || []).filter((f) => f.home === p.team || f.away === p.team);
    if (!fx.length) return "none";
    return fx.every((f) => played(f) && hasStats.has(f.id)) ? "dnp" : "pending";
  };
  return { weeks, P, pts, status, wk };
}

/* Starters who did not play are replaced by bench players who did, keeping a legal formation. */
export function autoSubs(picks, st, P) {
  const bench = picks.slice(7), used = new Set(), subs = [];
  let cur = picks.slice(0, 7);
  for (const o of picks.slice(0, 7)) {
    if (!["dnp", "none"].includes(st(o))) continue;
    const cands = P.get(o).pos === "GK" ? [bench[0]] : bench.slice(1);
    for (const b of cands) {
      if (!b || used.has(b) || st(b) !== "played") continue;
      const next = cur.map((id) => (id === o ? b : id));
      if (lineupOk(next, P)) { cur = next; used.add(b); subs.push({ out: o, in: b }); break; }
    }
  }
  return { start: cur, subs };
}

export function scoreTeam(row, n, A) {
  const st = (id) => A.status(id, n);
  const { start, subs } = autoSubs(row.picks, st, A.P);
  const capDead = ["dnp", "none"].includes(st(row.captain));
  const cap = capDead && st(row.vice) === "played" ? row.vice : row.captain;
  const per = {};
  for (const id of row.picks) per[id] = A.pts.get(n + "|" + id) || 0;
  const total = start.reduce((s, id) => s + per[id] * (id === cap ? CFG.captain : 1), 0);
  return { start, subs, cap, per, total };
}

/* rows: this manager's saved teams, any order. A team stays in force until a later one is saved. */
export function season(rows, A) {
  const mine = [...rows].sort((a, b) => a.week - b.week), out = {};
  let total = 0;
  for (const w of A.weeks) {
    if (w.status === "upcoming") continue;
    const r = [...mine].filter((x) => x.week <= w.n).pop();
    if (!r) continue;
    const s = scoreTeam(r, w.n, A), hits = r.week === w.n ? r.hits | 0 : 0;
    out[w.n] = { pts: s.total - hits, hits, picks: r.picks, captain: r.captain, vice: r.vice, start: s.start, subs: s.subs, cap: s.cap, per: s.per };
    total += s.total - hits;
  }
  return { weeks: out, total };
}

export function validateTeam(body, { players, base, openWeek }) {
  if (openWeek == null) return { error: "The season has finished, so teams are locked." };
  const { picks, captain, vice } = body || {};
  if (!Array.isArray(picks) || picks.length !== CFG.squad) return { error: `Pick exactly ${CFG.squad} players.` };
  if (new Set(picks).size !== picks.length) return { error: "A player can only be picked once." };
  const P = new Map(players.map((p) => [p.id, p])), pl = picks.map((id) => P.get(id));
  if (pl.some((p) => !p)) return { error: "One of those players doesn't exist." };
  const comp = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
  pl.forEach((p) => comp[p.pos]++);
  for (const k of Object.keys(CFG.comp)) if (comp[k] !== CFG.comp[k]) return { error: `Your squad needs ${CFG.comp[k]} ${k}.` };
  const clubs = {};
  pl.forEach((p) => (clubs[p.team] = (clubs[p.team] || 0) + 1));
  if (Object.values(clubs).some((n) => n > CFG.clubLimit)) return { error: `No more than ${CFG.clubLimit} players from one club.` };
  if (!lineupOk(picks.slice(0, 7), P)) return { error: "That starting seven isn't a legal formation." };
  if (P.get(picks[7]).pos !== "GK" || pl[8].pos === "GK" || pl[9].pos === "GK") return { error: "The bench is the spare goalkeeper first, then two outfield players." };
  if (!picks.slice(0, 7).includes(captain) || !picks.slice(0, 7).includes(vice) || captain === vice) return { error: "Choose a different captain and vice-captain from your starting seven." };
  const changed = base ? picks.filter((id) => !base.includes(id)).length : 0;
  const value = pl.reduce((s, p) => s + (p.price || 0), 0);
  if ((!base || changed > 0) && value > CFG.budget) return { error: `Over budget by KSh ${(value - CFG.budget).toLocaleString("en-KE")}.` };
  return { ok: true, value, changed, hits: base ? Math.max(0, changed - CFG.freeTransfers) * CFG.hitCost : 0 };
}

/* The whole picture for the fantasy page. Pure: pass in the data. */
export function computeState({ fixtures, players, stats, users, teamRows, meId, now = Date.now() }) {
  const A = analyse({ fixtures, players, stats });
  const openWeek = A.weeks.find((w) => w.deadline > now)?.n ?? null;
  const rowsBy = new Map();
  for (const r of teamRows) { if (!rowsBy.has(r.user)) rowsBy.set(r.user, []); rowsBy.get(r.user).push(r); }
  const pp = {};
  for (const p of players) {
    const w = {}; let t = 0;
    for (const wkk of A.weeks) { const v = A.pts.get(wkk.n + "|" + p.id); if (v != null) { w[wkk.n] = v; t += v; } }
    pp[p.id] = { t, w };
  }
  const seasons = users.filter((u) => u.teamName).map((u) => ({ u, s: season(rowsBy.get(u.id) || [], A) }));
  const board = seasons.map(({ u, s }) => ({ team: u.teamName, mgr: u.name, total: s.total, w: Object.fromEntries(Object.entries(s.weeks).map(([n, v]) => [n, v.pts])), me: u.id === meId }))
    .sort((a, b) => b.total - a.total || a.team.localeCompare(b.team));
  /* The highest-scoring team of each gameweek is public once that gameweek's deadline has passed (never before). */
  const top = {};
  for (const w of A.weeks) {
    if (w.status === "upcoming" || w.deadline > now) continue;
    let best = null;
    for (const c of seasons) {
      const x = c.s.weeks[w.n];
      if (!x) continue;
      if (!best || x.pts > best.x.pts || (x.pts === best.x.pts && (c.s.total > best.s.total || (c.s.total === best.s.total && c.u.teamName.localeCompare(best.u.teamName) < 0)))) best = { ...c, x };
    }
    if (best) top[w.n] = { team: best.u.teamName, mgr: best.u.name, ...best.x };
  }
  let me = null;
  const u = users.find((x) => x.id === meId);
  if (u) {
    const mine = (rowsBy.get(u.id) || []).sort((a, b) => a.week - b.week);
    const exact = mine.find((r) => r.week === openWeek), prev = [...mine].filter((r) => r.week < openWeek).pop();
    const team = exact ? { ...exact, saved: true } : prev ? { week: openWeek, picks: prev.picks, captain: prev.captain, vice: prev.vice, hits: 0, saved: false } : null;
    const s = season(mine, A);
    me = { teamName: u.teamName, mgr: u.name, needsName: !u.teamName, team, base: prev ? prev.picks : null, weeks: s.weeks, total: s.total };
  }
  return { cfg: CFG, weeks: A.weeks.map((w) => ({ n: w.n, deadline: new Date(w.deadline).toISOString(), status: w.status, done: w.done, total: w.total })), openWeek, pp, board, top, me };
}

/* ---------------------------------------------------------------- API */
const b64 = (s) => Buffer.from(s).toString("base64url");

export function googleVerifier(clientId) {
  const c = new OAuth2Client(clientId);
  return async (token) => {
    const t = await c.verifyIdToken({ idToken: token, audience: clientId });
    const p = t.getPayload();
    if (!p || !p.sub) throw new Error("bad token");
    return { sub: p.sub, name: p.given_name || p.name || "Manager" };
  };
}

const bad = (status, error) => Object.assign(new Error(error), { status });
const clean = (s, n) => String(s ?? "").replace(/<[^>]*>/g, "").replace(/[\u0000-\u001f<>]/g, "").replace(/\s+/g, " ").trim().slice(0, n);

export function registerFantasy(app, { admin, secret, clientId, verify, now = () => Date.now() }) {
  const enabled = !!(secret && secret.length >= 16 && clientId && verify);
  const sign = (id, exp) => crypto.createHmac("sha256", secret).update(`fu.${b64(id)}.${exp}`).digest("hex");
  const who = (req) => {
    const [tag, id, exp, sig] = String(req.get("authorization") || "").replace(/^Bearer /, "").split(".");
    if (!enabled || tag !== "fu" || !id || !exp || !sig || +exp < now()) return null;
    const uid = Buffer.from(id, "base64url").toString();
    const want = sign(uid, exp);
    return sig.length === want.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want)) ? uid : null;
  };
  const need = (req) => { const u = who(req); if (!u) throw bad(401, "Please sign in with Google again."); return u; };
  const load = async (meId) => {
    const all = await readAll();
    const us = (await db.execute("SELECT id, name, team_name FROM fantasy_users")).rows.map((r) => ({ id: r.id, name: r.name, teamName: r.team_name }));
    const tr = (await db.execute("SELECT user_id, week, picks, captain, vice, hits FROM fantasy_teams")).rows.map((r) => ({ user: r.user_id, week: r.week, picks: JSON.parse(r.picks), captain: r.captain, vice: r.vice, hits: r.hits }));
    return computeState({ fixtures: all.fixtures, players: all.players, stats: all.stats, users: us, teamRows: tr, meId, now: now() });
  };
  const wrap = (fn) => async (req, res, next) => { try { await fn(req, res); } catch (e) { next(e); } };

  app.get("/api/fantasy/config", (_req, res) => res.json({ enabled, googleClientId: enabled ? clientId : "", cfg: CFG, reason: enabled ? "" : "Fantasy isn't switched on yet. The server needs GOOGLE_CLIENT_ID and a SESSION_SECRET of 16+ characters." }));

  app.post("/api/fantasy/login", wrap(async (req, res) => {
    if (!enabled) throw bad(503, "Fantasy isn't switched on yet.");
    let g;
    try { g = await verify(String(req.body?.credential || "")); } catch { throw bad(401, "Google sign-in failed. Please try again."); }
    await db.execute({ sql: "INSERT OR IGNORE INTO fantasy_users (id, name, team_name, created) VALUES (?, ?, '', ?)", args: [g.sub, clean(g.name, 30) || "Manager", new Date(now()).toISOString()] });
    const exp = now() + 30 * 24 * 3600 * 1000;
    res.json({ token: `fu.${b64(g.sub)}.${exp}.${sign(g.sub, exp)}` });
  }));

  app.get("/api/fantasy/state", wrap(async (req, res) => res.set("Cache-Control", "no-store").json(await load(who(req)))));

  app.put("/api/fantasy/profile", wrap(async (req, res) => {
    const id = need(req), name = clean(req.body?.teamName, 24);
    if (name.length < 3) throw bad(400, "Team names need at least 3 characters.");
    const dup = (await db.execute({ sql: "SELECT 1 FROM fantasy_users WHERE lower(team_name) = lower(?) AND id <> ?", args: [name, id] })).rows.length;
    if (dup) throw bad(409, "That team name is taken.");
    await db.execute({ sql: "UPDATE fantasy_users SET team_name = ? WHERE id = ?", args: [name, id] });
    res.json({ ok: true });
  }));

  app.put("/api/fantasy/team", wrap(async (req, res) => {
    const id = need(req), s = await load(id);
    if (!s.me || s.me.needsName) throw bad(400, "Choose a team name first.");
    const all = await readAll();
    const v = validateTeam(req.body, { players: all.players, base: s.me.base, openWeek: s.openWeek });
    if (v.error) throw bad(400, v.error);
    await db.execute({ sql: "INSERT INTO fantasy_teams (user_id, week, picks, captain, vice, hits, updated) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, week) DO UPDATE SET picks = excluded.picks, captain = excluded.captain, vice = excluded.vice, hits = excluded.hits, updated = excluded.updated",
      args: [id, s.openWeek, JSON.stringify(req.body.picks), req.body.captain, req.body.vice, v.hits, new Date(now()).toISOString()] });
    res.json({ ok: true, hits: v.hits, value: v.value });
  }));

  app.delete("/api/fantasy/me", wrap(async (req, res) => {
    const id = need(req);
    await db.batch([{ sql: "DELETE FROM fantasy_teams WHERE user_id = ?", args: [id] }, { sql: "DELETE FROM fantasy_users WHERE id = ?", args: [id] }], "write");
    res.json({ ok: true });
  }));

  /* admin tools (use the admin password) */
  app.get("/api/fantasy/admin/users", admin, wrap(async (_req, res) => {
    res.json((await db.execute("SELECT id, name, team_name, created FROM fantasy_users ORDER BY created")).rows.map((r) => ({ id: r.id, mgr: r.name, teamName: r.team_name, created: r.created })));
  }));
  app.put("/api/fantasy/admin/users/:id", admin, wrap(async (req, res) => {
    const name = clean(req.body?.teamName, 24);
    if (name.length < 3) throw bad(400, "Team names need at least 3 characters.");
    await db.execute({ sql: "UPDATE fantasy_users SET team_name = ? WHERE id = ?", args: [name, req.params.id] });
    res.json({ ok: true });
  }));
  app.delete("/api/fantasy/admin/users/:id", admin, wrap(async (req, res) => {
    await db.batch([{ sql: "DELETE FROM fantasy_teams WHERE user_id = ?", args: [req.params.id] }, { sql: "DELETE FROM fantasy_users WHERE id = ?", args: [req.params.id] }], "write");
    res.json({ ok: true });
  }));
  app.post("/api/fantasy/admin/prices", admin, wrap(async (req, res) => {
    const st = [];
    for (const pos of ["GK", "DEF", "MID", "FWD"]) {
      const v = Math.trunc(+req.body?.[pos]);
      if (Number.isFinite(v) && v >= 0 && v <= 100000) st.push({ sql: "UPDATE players SET price = ? WHERE pos = ?", args: [v, pos] });
    }
    if (!st.length) throw bad(400, "Send a price for at least one position.");
    await db.batch(st, "write");
    res.json({ ok: true });
  }));
}
