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

- **Check In** – today's list. Each person can check in once per day; click again to undo.
- **Tracker** – a year-long heatmap where darker green = more people that day (hover for names, click for details), followed by one heatmap per person with total check-ins, attendance % (of days anyone checked in since their first), and current streak.
- **Admin** – add, rename, reorder, hide (keeps history) or delete (removes history) names.
