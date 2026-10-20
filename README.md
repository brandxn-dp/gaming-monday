# Gaming Monday check-in

A small web app: a list of names (managed by an admin) with a **Check in** button for each, plus a GitHub-style **Tracker** tab showing who checked in, how many, and how often.

## Run

```bash
ADMIN_PASSWORD=your-secret docker compose up -d --build
```

Open http://localhost:8080. Go to **Admin**, log in with `ADMIN_PASSWORD` (default `changeme`), and add names.

Check-ins are stored in SQLite at `./data/checkins.db` (mounted into the container), so they survive rebuilds.

### Prebuilt image

Every push to `main` publishes `ghcr.io/brandxn-dp/gaming-monday:latest` via GitHub Actions.

```bash
docker run -d --name gaming-monday -p 8080:8080 -e ADMIN_PASSWORD=your-secret -v /path/to/data:/data ghcr.io/brandxn-dp/gaming-monday:latest
```

### Unraid

Docker tab → **Add Container**, then set:

| Field | Value |
|---|---|
| Name | `gaming-monday` |
| Repository | `ghcr.io/brandxn-dp/gaming-monday:latest` |
| WebUI | `http://[IP]:[PORT:8080]/` |
| Port (container `8080`) | any free host port, e.g. `8080` |
| Path (container `/data`) | `/mnt/user/appdata/gaming-monday` |
| Variable `ADMIN_PASSWORD` | your admin password |
| Variable `APP_TITLE` | optional page title |

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | `changeme` | Password for the Admin tab |
| `APP_TITLE` | `Gaming Monday` | Header / page title |
| `PORT` | `8080` | Host port to expose |

## Tabs

- **Check In** – open on Mondays (until 6 AM Tuesday for late sessions). Each person checks in once per Monday; click again to undo.
- **Tracker** – one square per Monday for the last 52 weeks; darker green = more people (hover for names, click for details). Below it, one strip per person with Mondays attended, attendance % and week streak. Only Mondays count, and a Monday nobody played never breaks a streak.
- **Admin** – add, rename, reorder, hide (keeps history) or delete (removes history) names.
