import "dotenv/config";
import { createClient } from "@libsql/client";

export const db = createClient({
  url: process.env.TURSO_DATABASE_URL || "file:local.db",
  authToken: process.env.TURSO_AUTH_TOKEN || undefined,
});

export const POSITIONS = ["GK", "DEF", "MID", "FWD"];

/* Column rules per table. s = text, i = integer, i? = integer or null */
export const TABLES = {
  teams: { cols: { name: "s", short: "s", c: "s", manager: "s", ground: "s", bio: "s", ord: "i", badge: "s", theme: "s", icon: "s" }, req: ["name", "short"] },
  fixtures: { cols: { home: "s", away: "s", date: "s", time: "s", venue: "s", hg: "i?", ag: "i?", week: "i?" }, req: ["home", "away", "date"] },
  news: { cols: { title: "s", tag: "s", date: "s", color: "s", summary: "s", body: "s" }, req: ["title"] },
  players: { cols: { team: "s", name: "s", num: "i?", pos: "s" }, req: ["team", "name", "pos"] },
  stats: { cols: {}, req: [], bulk: true }, /* written only through saveMatchStats */
};

export async function init() {
  await db.batch(
    [
      `CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, name TEXT NOT NULL, short TEXT NOT NULL, c TEXT DEFAULT '#1971c2', manager TEXT DEFAULT '', ground TEXT DEFAULT '', bio TEXT DEFAULT '', ord INTEGER DEFAULT 0, badge TEXT DEFAULT '', theme TEXT DEFAULT '', icon TEXT DEFAULT '')`,
      `CREATE TABLE IF NOT EXISTS fixtures (id TEXT PRIMARY KEY, home TEXT NOT NULL, away TEXT NOT NULL, "date" TEXT NOT NULL, "time" TEXT DEFAULT '', venue TEXT DEFAULT '', hg INTEGER, ag INTEGER, week INTEGER)`,
      `CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, title TEXT NOT NULL, tag TEXT DEFAULT 'News', "date" TEXT DEFAULT '', color TEXT DEFAULT '#ff5a1f', summary TEXT DEFAULT '', body TEXT DEFAULT '')`,
      `CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, team TEXT NOT NULL, name TEXT NOT NULL, num INTEGER, pos TEXT NOT NULL)`,
      `CREATE UNIQUE INDEX IF NOT EXISTS players_team_num ON players(team, num) WHERE num IS NOT NULL`,
      `CREATE TABLE IF NOT EXISTS stats (id TEXT PRIMARY KEY, fixture TEXT NOT NULL, team TEXT NOT NULL, player TEXT NOT NULL, played INTEGER DEFAULT 0, goals INTEGER DEFAULT 0, assists INTEGER DEFAULT 0, yellow INTEGER DEFAULT 0, red INTEGER DEFAULT 0)`,
      `CREATE INDEX IF NOT EXISTS stats_fixture ON stats(fixture)`,
      `CREATE TABLE IF NOT EXISTS site (k TEXT PRIMARY KEY, v TEXT NOT NULL)`,
    ],
    "write"
  );
  /* older databases: add the badge/theme columns if they're missing */
  const have = (await db.execute("PRAGMA table_info(teams)")).rows.map((r) => r.name);
  for (const col of ["badge", "theme", "icon"])
    if (!have.includes(col)) await db.execute(`ALTER TABLE teams ADD COLUMN ${col} TEXT DEFAULT ''`);
  const fx = (await db.execute("PRAGMA table_info(fixtures)")).rows.map((r) => r.name);
  if (!fx.includes("week")) await db.execute("ALTER TABLE fixtures ADD COLUMN week INTEGER");
}

const rows = (rs) => rs.rows.map((r) => Object.fromEntries(rs.columns.map((c) => [c, r[c]])));

export async function readAll() {
  const out = {};
  for (const t of Object.keys(TABLES)) out[t] = rows(await db.execute(`SELECT * FROM ${t}`));
  const s = await db.execute({ sql: "SELECT v FROM site WHERE k = 'site'", args: [] });
  out.site = s.rows.length ? JSON.parse(s.rows[0].v) : {};
  return out;
}

const text = (v, max) => String(v ?? "").slice(0, max);

export function clean(table, body) {
  const spec = TABLES[table];
  const row = {};
  for (const [col, kind] of Object.entries(spec.cols)) {
    const v = body[col];
    if (kind === "s") row[col] = text(v, col === "body" ? 20000 : col === "bio" ? 2000 : 300).trim();
    else if (kind === "i") row[col] = Number.isFinite(+v) ? Math.max(0, Math.min(999, Math.trunc(+v))) : 0;
    else row[col] = v === null || v === undefined || v === "" || !Number.isFinite(+v) ? null : Math.max(0, Math.min(999, Math.trunc(+v)));
  }
  for (const r of spec.req) if (!row[r]) throw Object.assign(new Error(`${r} is required`), { status: 400 });
  if (table === "fixtures") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date)) throw Object.assign(new Error("date must be YYYY-MM-DD"), { status: 400 });
    if (row.home === row.away) throw Object.assign(new Error("a team can't play itself"), { status: 400 });
    if ((row.hg === null) !== (row.ag === null)) throw Object.assign(new Error("enter both scores or neither"), { status: 400 });
    if (row.week === 0) row.week = null;
  }
  if (table === "players") {
    if (!POSITIONS.includes(row.pos)) throw Object.assign(new Error("position must be GK, DEF, MID or FWD"), { status: 400 });
    if (row.num !== null && row.num > 99) throw Object.assign(new Error("shirt numbers run 0 to 99"), { status: 400 });
  }
  return row;
}

export async function upsert(table, id, row) {
  const cols = Object.keys(row);
  const sql = `INSERT INTO ${table} (id, ${cols.map((c) => `"${c}"`).join(", ")}) VALUES (?, ${cols.map(() => "?").join(", ")})
    ON CONFLICT(id) DO UPDATE SET ${cols.map((c) => `"${c}" = excluded."${c}"`).join(", ")}`;
  try {
    await db.execute({ sql, args: [id, ...cols.map((c) => row[c])] });
  } catch (e) {
    if (/UNIQUE/i.test(String(e.message))) throw Object.assign(new Error("That shirt number is already taken in this team"), { status: 409 });
    throw e;
  }
}

export const remove = (table, id) => db.execute({ sql: `DELETE FROM ${table} WHERE id = ?`, args: [id] });
export const saveSite = (obj) =>
  db.execute({ sql: "INSERT INTO site (k, v) VALUES ('site', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", args: [JSON.stringify(obj)] });

/* Remove stat rows that belong to a deleted fixture or player */
export async function cascade(table, id) {
  if (table === "fixtures") await db.execute({ sql: "DELETE FROM stats WHERE fixture = ?", args: [id] });
  if (table === "players") await db.execute({ sql: "DELETE FROM stats WHERE player = ?", args: [id] });
}

/* Replace every stat line for one match in a single transaction. Clean sheets are derived from the score, not stored. */
const num = (v, max) => Math.max(0, Math.min(max, Number.isFinite(+v) ? Math.trunc(+v) : 0));
export async function saveMatchStats(fixtureId, rows) {
  const fx = (await db.execute({ sql: "SELECT home, away FROM fixtures WHERE id = ?", args: [fixtureId] })).rows[0];
  if (!fx) throw Object.assign(new Error("Fixture not found"), { status: 404 });
  if (!Array.isArray(rows) || rows.length > 60) throw Object.assign(new Error("rows must be a list of up to 60 players"), { status: 400 });
  const pl = (await db.execute({ sql: "SELECT id, team FROM players WHERE team IN (?, ?)", args: [fx.home, fx.away] })).rows;
  const owner = Object.fromEntries(pl.map((p) => [p.id, p.team]));
  const stmts = [{ sql: "DELETE FROM stats WHERE fixture = ?", args: [fixtureId] }];
  const seen = new Set();
  for (const r of rows) {
    const player = String(r.player ?? "");
    if (!owner[player] || seen.has(player)) continue;
    seen.add(player);
    const v = { played: num(r.played, 1), goals: num(r.goals, 30), assists: num(r.assists, 30), yellow: num(r.yellow, 2), red: num(r.red, 1) };
    if (v.goals || v.assists || v.yellow || v.red) v.played = 1;
    if (!v.played) continue;
    stmts.push({
      sql: "INSERT INTO stats (id, fixture, team, player, played, goals, assists, yellow, red) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
      args: [`${fixtureId}_${player}`, fixtureId, owner[player], player, v.played, v.goals, v.assists, v.yellow, v.red],
    });
  }
  await db.batch(stmts, "write");
}
