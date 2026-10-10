# K South League (Embakasi West)

Express API + Turso (libSQL) database + the site in `public/index.html`.

## Run it locally (no Turso needed)
```bash
npm install
cp .env.example .env        # then set ADMIN_PASSWORD (leave the Turso lines blank for a local file DB)
npm run seed                # loads the starter teams, fixtures, news and banners
npm start                   # http://localhost:3000, admin at http://localhost:3000/#/admin
```

## Use Turso
```bash
turso auth login
turso db create k-south-league
turso db show k-south-league --url          # -> TURSO_DATABASE_URL
turso db tokens create k-south-league       # -> TURSO_AUTH_TOKEN
```
Put both in `.env`, then run `npm run seed` once. Tables are created automatically on start.

## Deploy
Any Node host works (Render, Railway, Fly.io, a VPS). Build command `npm install`, start command `npm start`,
and set these environment variables: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `ADMIN_PASSWORD`, `SESSION_SECRET`.

## How it fits together
- `GET /api/data` is public and returns teams, fixtures, news, players and banners.
- Writes (`PUT /api/:table/:id`, `DELETE /api/:table/:id`, `PUT /api/site`) need the admin token from `POST /api/login`.
- Tables: `teams`, `fixtures`, `news`, `players` (team, name, num, pos), `site`. Shirt numbers are unique per team.
- Player photos are next: add a `photo` column to `players` in `db.js` and a field in `TABLES.players`.
