# Deploying Chess Trainer

Self-hosted deployment using Podman (or Docker) with Caddy for automatic HTTPS.

## Prerequisites

- VPS with 1+ GB RAM (e.g. Hetzner, DigitalOcean, Linode)
- Podman 4+ or Docker 24+ with Compose plugin
- A domain name with DNS A record pointing to the VPS IP
- Ports 80 and 443 open in firewall

All commands below show `podman`; substitute `docker` if preferred.

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/AudensAurantius/chess_trainer.git
cd chess_trainer

# 2. Configure environment
cp deploy/.env.example deploy/.env
# Edit deploy/.env — defaults are fine for most setups

# 3. Set your domain in the Caddyfile
# Replace chess.example.com with your actual domain
nano deploy/Caddyfile

# 4. Build and start
podman compose up -d --build

# 5. Create an invite code for your first user
podman compose exec app chess-trainer auth create-invite
```

The app will be available at `https://your-domain.com` once Caddy obtains a TLS certificate (usually under 30 seconds).

## Creating Invite Codes

Registration requires an invite code (configurable via `CHESS_TRAINER_AUTH_REQUIRE_INVITE`).

```bash
# Generate a new invite code
podman compose exec app chess-trainer auth create-invite
```

Share the code with your beta testers. Each code can be used once.

## Backups

The `deploy/backup.sh` script archives the `chess-data` volume.

```bash
# Run a backup
./deploy/backup.sh

# Schedule daily backups via cron (2 AM)
crontab -e
# Add: 0 2 * * * /path/to/chess_trainer/deploy/backup.sh
```

Backups are stored in `./backups/` by default. Old backups are pruned after 14 days.

Configuration via environment variables:
- `BACKUP_DIR` — backup destination (default: `./backups`)
- `KEEP_DAYS` — retention in days (default: 14, 0 = keep all)
- `VOLUME_NAME` — volume name (default: `chess_trainer_chess-data`)

## Restore from Backup

```bash
# 1. Stop the app
podman compose down

# 2. Remove the existing volume
podman volume rm chess_trainer_chess-data

# 3. Create a fresh volume and restore
podman volume create chess_trainer_chess-data
podman run --rm \
  -v chess_trainer_chess-data:/data \
  -v "$(pwd)/backups:/backup:ro" \
  alpine:3 \
  tar xzf /backup/chess-trainer-YYYYMMDD-HHMMSS.tar.gz -C /data

# 4. Restart
podman compose up -d
```

## Updating

```bash
git pull
podman compose up -d --build
```

The app restarts with the new code. Database volumes are preserved.

## Monitoring

```bash
# View app logs
podman compose logs -f app

# View Caddy logs
podman compose logs -f caddy

# Check container status
podman compose ps
```

For uptime monitoring, consider [UptimeRobot](https://uptimerobot.com/) (free tier: 50 monitors, 5-minute intervals) pointed at your domain's login page.

## Troubleshooting

**Caddy can't obtain a certificate:**
- Verify DNS A record points to the VPS IP: `dig +short your-domain.com`
- Ensure ports 80 and 443 are open: `ss -tlnp | grep -E ':(80|443)'`
- Check Caddy logs: `podman compose logs caddy`

**App returns 502 Bad Gateway:**
- The app container may still be starting: `podman compose logs app`
- Check it's running: `podman compose ps`

**"Permission denied" on /data:**
- The container runs as UID 1000. If restoring a backup, ensure file ownership matches: `podman run --rm -v chess_trainer_chess-data:/data alpine:3 chown -R 1000:1000 /data`

**Can't create invite codes:**
- Ensure auth is enabled: check `CHESS_TRAINER_AUTH_ENABLED=true` in `deploy/.env`

**Cookies not persisting (can't stay logged in):**
- Session cookies require HTTPS (`secure=True`). Access the app via `https://`, not `http://`.
