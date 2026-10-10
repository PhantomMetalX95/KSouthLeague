/* Loads starter teams, fixtures, news and banners. Skips if teams already exist (use --force to overwrite). */
import { db, init, clean, upsert, saveSite } from "./db.js";

const V = "Embakasi West";
const teams = [
  ["t0", "Civo United FC", "CIV", "#d4a64a", "civo"], ["t1", "Elland", "ELL", "#0b57a8", "elland"], ["t2", "Samba Boys", "SAM", "#1c1c1e", "samba"],
  ["t3", "Baraka", "BAR", "#ffd21f", "baraka"], ["t4", "2nd Avenue", "2AV", "#d7191f", "avenue"], ["t5", "Mandem", "MAN", "#e8590c", ""],
].map(([id, name, short, c, theme], ord) => ({ id, name, short, c, ground: V, ord, theme, badge: theme ? `/badges/${theme}.png` : "" }));
const fx = (id, home, away, date, time, hg = null, ag = null) => ({ id, home, away, date, time, venue: V, hg, ag });
const fixtures = [
  fx("f1", "t0", "t1", "2026-09-26", "09:00", 3, 2), fx("f2", "t2", "t3", "2026-09-26", "10:00", 1, 1), fx("f3", "t4", "t5", "2026-09-26", "11:00", 0, 2),
  fx("f4", "t1", "t2", "2026-10-03", "09:00", 2, 0), fx("f5", "t3", "t4", "2026-10-03", "10:00", 4, 1), fx("f6", "t5", "t0", "2026-10-03", "11:00", 1, 1),
  fx("f7", "t0", "t2", "2026-10-17", "09:00"), fx("f8", "t1", "t4", "2026-10-17", "10:00"), fx("f9", "t3", "t5", "2026-10-17", "11:00"),
];
const news = [
  { id: "season-kicks-off", title: "Season kicks off", tag: "League", date: "2026-09-26", color: "#ff5a1f", summary: "Six teams, one trophy. Here is what to expect from the opening weeks.", body: `Six teams, fifteen matches each and one trophy.\n\nThe K South League is back for another season of fast, loud seven-a-side football in ${V}.` },
  { id: "matchday-2-roundup", title: "Matchday 2 round-up", tag: "Report", date: "2026-10-03", color: "#2f9e44", summary: "Baraka put four past 2nd Avenue to go top of the table.", body: "Baraka won 4-1 against 2nd Avenue.\n\nElland beat Samba Boys 2-0, while Mandem and Civo United FC shared a 1-1 draw." },
  { id: "registrations-open", title: "Registrations open", tag: "Notice", date: "2026-10-05", color: "#1971c2", summary: "Squads are being confirmed. Managers can register players before matchday 4.", body: "Team managers can register players before matchday 4.\n\nShirt numbers and positions are on each team page. Player photos are coming next." },
];
const site = {
  ann: { on: true, text: "Matchday 3 is on Saturday 17 October.", link: "#/matches", label: "See fixtures" },
  promo: { on: true, title: "Squads are filling up", text: "Browse every team's shirt numbers and positions.", link: "#/teams", label: "Browse teams", big: "MD4" },
  ribbon: `Seven a side · ${V} · Est. 2024`,
};

await init();
const n = (await db.execute("SELECT COUNT(*) AS n FROM teams")).rows[0].n;
if (n > 0 && !process.argv.includes("--force")) {
  console.log("Teams already exist, skipping. Use `npm run seed -- --force` to overwrite.");
  process.exit(0);
}
for (const [table, list] of [["teams", teams], ["fixtures", fixtures], ["news", news]])
  for (const { id, ...r } of list) await upsert(table, id, clean(table, r));
await saveSite(site);
console.log("Seeded", teams.length, "teams,", fixtures.length, "fixtures,", news.length, "news posts.");
