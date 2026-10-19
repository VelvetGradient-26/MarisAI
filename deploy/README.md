# Deploying MarisAI on the EC2 instance

Production runs `docker-compose.prod.yml` (nginx serving the built frontend on port 80, backend and Postgres on the internal compose network) on instance `i-0c7686f701d6b0af1` (ap-south-1, user `ec2-user`, repo at `~/maris/MarisAI`).
The instance has no fixed address: its public IP changes on every start.

## Everyday use

```bash
deploy/start_demo.sh     # start, open SSH for your current IP, print the URL, wait until every surface is warm
deploy/stop_demo.sh      # stop and wait
```

Every container restarts on its own, so starting the instance is the only step.
On start the site serves the last saved data (marked as old) within about two minutes, then refreshes in the background; `deploy/demo_ready.sh` prints a table of every surface and its data age and exits 0 only when all are green.

## One-time setup on the instance

1. Root `.env` next to `docker-compose.prod.yml`, copied from `deploy/env.prod.example`; it sets `COMPOSE_FILE=docker-compose.prod.yml`, so plain `docker compose` commands use the production file.
2. `backend/.env` with the provider credentials (see `backend/.env.example`).
3. IMDSv2 hop limit 2, so the backend container can read the public IP for email links (`aws ec2 modify-instance-metadata-options --instance-id i-0c7686f701d6b0af1 --http-tokens required --http-put-response-hop-limit 2`).
4. `/etc/docker/daemon.json` with `{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}`.

## Deploying a new version

```bash
cd ~/maris/MarisAI
git fetch origin && git reset --hard origin/main && git lfs pull
sudo docker compose build --pull && sudo docker compose up -d
sudo docker image prune -f && sudo docker builder prune -af   # keep the disk clear
```

Never run `docker volume prune` or `docker system prune --volumes`: the Postgres volume holds chat history and alert watches.

## Rollback

A pre-demo snapshot of the root volume exists (`snap-0bf176a33109c62f5`, 20 Oct 2026).
To roll back: stop the instance, create a volume from the snapshot in ap-south-1a, detach the current root volume, attach the new one as `/dev/xvda`, start.
