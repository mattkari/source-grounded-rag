# Running the assistant continuously on a Raspberry Pi

The web UI is a single Python process with a file-based index — no database, no
model weights, no GPU. That makes a Pi a reasonable permanent home for it.

**Before you start, one dependency:** the image serves `app.py`, the Streamlit
UI, which lives on branch `claude/streamlit-web-ui-eyheeg` and is not on `main`
yet. Merge that branch first, or build from a checkout that contains it. Without
`app.py` the container starts and Streamlit immediately reports that the file
does not exist.

---

## 1. Check the Pi

```bash
uname -m          # must print aarch64
free -m           # 1 GB is enough; 2 GB is comfortable
```

**`aarch64` is not optional.** Streamlit pulls in `pyarrow` and `numpy`. Both
publish prebuilt wheels for 64-bit ARM and none for 32-bit `armv7l`. On a 32-bit
Raspberry Pi OS, pip falls back to compiling from source — a build that takes
hours and usually ends with the kernel killing it for running out of memory. If
`uname -m` prints `armv7l`, reinstall with the 64-bit image before going further.

Install Docker if it is not already there:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # log out and back in for this to take effect
```

## 2. Clone and configure

```bash
git clone https://github.com/mattkari/source-grounded-rag.git
cd source-grounded-rag

cp .env.example .env
chmod 600 .env                     # readable only by you
nano .env                          # fill in the two API keys
```

The keys stay in that file on the Pi. They are never copied into the image:
anything set with `ENV` or `ARG` in a Dockerfile is visible to anyone who can
run `docker history`, so credentials arrive at run time instead.

## 3. Build and start

```bash
docker compose up -d --build
```

First build takes a few minutes while the wheels download. After that:

```bash
docker compose ps                  # STATUS should become "healthy"
docker compose logs -f             # Ctrl+C stops following, not the container
curl -s localhost:8501/_stcore/health   # prints: ok
```

`restart: unless-stopped` means the container comes back after a crash and after
a reboot, without any systemd unit of your own.

## 4. Reach it

The default binds to `127.0.0.1` — the service is reachable only from the Pi
itself. That is deliberate: the app has **no authentication**, and every question
spends money on an OpenAI embedding call plus an Anthropic generation call.
Pick how you want to open it up:

| Option | Change | Trade-off |
|---|---|---|
| **SSH tunnel** (default) | none — `ssh -L 8501:127.0.0.1:8501 pi@raspberrypi`, then open `localhost:8501` | Nothing exposed. Fine for one person at a desk. |
| **Tailscale** | install Tailscale on the Pi, keep `BIND_ADDRESS=127.0.0.1`, reach it at the tailnet address | Phone and laptop anywhere, nothing public. Best default for personal use. |
| **LAN** | `BIND_ADDRESS=0.0.0.0` in `.env`, then `docker compose up -d` | Any device on your network can use it — and spend your budget. |
| **Public URL** | Cloudflare Tunnel with Access, or a reverse proxy enforcing authentication | Only do this with auth in front. A port-forward straight to 8501 puts your API keys behind a form anyone can find. |

There is no rate limiting in the application. Whatever sits in front of it is
the only thing standing between a stranger and your API bill.

## 5. Day-to-day

```bash
docker compose logs --tail 100     # recent activity
docker compose restart             # bounce it
docker compose down                # stop and remove the container
git pull && docker compose up -d --build    # deploy an update
```

Logs are capped at 3 × 10 MB so they cannot fill an SD card.

**Changing the document collection.** The image bakes in the committed `index/`.
After re-running `python ingest.py` on a machine with the PDF, commit the new
`index/` and rebuild on the Pi. The Pi never needs the source PDF — `data/` is
excluded from the build context by `.dockerignore`, which also keeps the thesis
itself out of any image you might distribute.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Build dies compiling `pyarrow` or `numpy` | 32-bit OS. Check `uname -m`. |
| Container restarts in a loop, logs say `app.py does not exist` | The web UI branch is not merged — see the note at the top. |
| Every question returns "Something went wrong retrieving the answer" | A key is missing or wrong. Open *Technical details* under the message; it names the cause. |
| "The research collection could not be loaded" | `index/` missing from the build, or built with a different embedding model than `config.py` names. |
| Healthcheck never turns healthy | Streamlit bound to the wrong interface. Inside the container it must be `0.0.0.0`; the Dockerfile sets that. |

## What this does not do

- **No authentication, no rate limiting, no multi-user isolation.** Session
  state is per browser session and is lost on restart, which is intended.
- **No secret rotation.** Replacing a key means editing `.env` and running
  `docker compose up -d`.
- **No offline operation.** Every question needs both APIs. The container is
  idle and free when nobody is asking; there is no background job.
