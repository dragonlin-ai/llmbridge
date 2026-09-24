<!-- The top blocks (icon / title / intro / badges / language switch) are centred: a GitHub HTML
     block ends at a blank line, so the Markdown inside <div> is still parsed and heading
     anchors are unaffected. -->
<div align="center">

<img src=".github/images/llmbridge-logo.svg" alt="llmbridge" width="120" height="120">

# LLM Routing Gateway (llmbridge)

> An **OpenAI-compatible LLM gateway with intelligent routing**: each request is first
> classified by the **Jev decision model** (task type + complexity), then forwarded to the
> most suitable *and* cheapest downstream model — the decision happens **before the first
> token is emitted**, and the whole path is observable, degradable, and auditable.

<p>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.4-42b883">
  <img alt="decider" src="https://img.shields.io/badge/decider-Jev%20%C2%B7%20TypeSafe%20AI-7c3aed">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-green">
</p>

[简体中文](README.md) | **English**

</div>

<details>
<summary><b>Contents</b></summary>

- [What this is / what it is not](#what-this-is--what-it-is-not)
- [**Decision core: Jev**](#decision-core-jev)
- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Read before deploying](#-read-before-deploying)
- [Deployment](#deployment)
- [Configuration](#configuration)
- [CLI](#cli)
- [API surface](#api-surface)
- [Tool-calling boundary](#tool-calling-boundary)
- [Project layout](#project-layout)
- [Documentation index](#documentation-index)
- [Known limitations](#known-limitations)
- [Community](#-community)
- [License](#license)

</details>

---

## What this is / what it is not

**It is** a **forwarding and decision layer** that sits between your application and the
major model vendors. Your application talks to a single OpenAI-compatible endpoint; the
gateway decides which model serves the request, how to fall back on failure, and what it cost.

**It is not** an agent framework, and it does not execute tools on your behalf.
The `tools` field is forwarded downstream as-is, and any `tool_calls` returned by the
upstream model are passed straight back to the caller (standard OpenAI semantics — see
"Tool-calling boundary" below). The gateway routes and forwards; it does not orchestrate.

---

## Decision core: Jev

> **"Which model should serve this request?" is not answered by a keyword table, nor by asking a
> generation model to write JSON that we then parse — it is answered by a model built specifically
> for decisions: Jev.**
> The answer is not text; it is a **typed value with a calibrated probability**. That is the single
> biggest difference between this gateway and its peers.

### 1. What Jev is

**Jev** is the **System One** decision model released on **2026-09-15** by **TypeSafe AI**
(San Francisco; founder Diogo Almeida, ex-OpenAI, worked on ChatGPT / RLHF). It **complements**
a generative model rather than replacing one:

| | The usual approach: an LLM as judge | **Jev (used here)** |
|---|---|---|
| How it works | Autoregressive token generation, then JSON parsing | **Non-autoregressive**: one forward pass returns the decision; it **generates no text at all** |
| Output | Prose plus JSON that needs re-validation or retries | **Typed decisions** (the choice always lands inside the given enum) + **calibrated probabilities** |
| Latency | Seconds (frontier models, on a 3–329s scale) | **70–500ms** officially; measured here at **0.4–1.2s** per call including the round trip |
| Is the confidence usable? | Made up — noise, nothing more | **Calibrated through RLCD**: a stated 0.9 really lands about 90% of the time — **so a threshold is finally meaningful** |
| Explainability | Attaches a natural-language rationale | **No rationale** (that is what buys the speed and the cost) |
| Failure mode | May emit out-of-enum values or malformed output | Cannot fail at the type level — but **can still pick the wrong option** |

Pricing: **$0.042 per million input tokens**; **output tokens are free**.

### 2. Three primitives (ask them together in one request — latency barely moves)

| Primitive | Answers | Returns | Used here for |
|---|---|---|---|
| **Choice** | Pick one of a fixed set | `choice` + `probabilities` + `confidence` | `task_type` — one of 6 task classes |
| **Score** | Rate against a rubric | `score` + `probabilities` | `complexity` — simple / medium / complex |
| **Noul** | Yes / no | `noul` (a 0–1 probability) | `has_code`, `is_sensitive` |

### 3. How this project uses it

**One call, four atomic questions in parallel** (the real request body sent by
`app/deciders/jev_decider.py`):

```jsonc
POST https://api.typesafe.ai/v1/systemone        // Authorization: Bearer $JEV_API_KEY
{
  "state": "<user input, truncated to 1000 chars>", // minimal input: no history, no system prompt
  "model": "jev-latest",
  "questions": {
    "task_type":    { "type": "choice", "criteria": { /* general / code_generation / translation
                                                        / summarize / complex_reasoning / long_context */ } },
    "complexity":   { "type": "score",  "criteria": ["simple", "medium", "complex"] },
    "has_code":     { "type": "noul" },
    "is_sensitive": { "type": "noul" }
  }
}
```

With `task_type` + confidence + complexity + the two feature flags in hand, **which concrete model
gets called is decided in code** — a mapping table weighted by cost / latency / health — rather than
letting Jev pick a `model_id` directly. Three reasons:

1. The model pool can grow or shrink without touching the decider;
2. `task_type` is a stable concept, `model_id` is not;
3. Weights and thresholds stay tunable **and auditable** (you change code, not a prompt nobody can read).

The shape of the whole decision chain:

```
user input
   │
   ├─▶ Jev: one call, four atomic questions in parallel
   │     task_type(Choice) · complexity(Score) · has_code(Noul) · is_sensitive(Noul)
   │     └─▶ typed decision + calibrated probability (no text, no rationale)
   │
   └─▶ in code: task_type → capability-tag mapping × cost / latency / health weights
         └─▶ a concrete model_id (auditable, replayable, tunable)
```

### 4. Why the design is worth a closer look

1. **The decision lands before the first token** — no penalty on time-to-first-token, and no
   "promise first, retract later" retry dance.
2. **Confidence is usable as a threshold**: below `ROUTE_CONFIDENCE_THRESHOLD_T2` the request takes the
   L3 fallback. Every response carries `x-router-*` metadata headers, and `request_log` stores the
   layer that was hit plus `fallback_reason`.
3. **Failures always leave a trace**: Jev unreachable / key rejected / out-of-enum answer all write
   `fallback_reason=DECIDER_*` and log a warning — it is **never disguised as "low confidence"**
   (otherwise "the decider is down" and "the decider guessed wrong" look identical from the outside,
   and that is brutally expensive to debug).
4. **The decider is pluggable**: the routing layer depends only on `BaseDecider`. Two implementations
   ship — `mock` (zero-dependency, offline-capable, **the default**) and `jev` — and they pass the same
   contract tests. The console switches between them with no code change.
5. **The probability distribution is replayable**: Jev gives no rationale, but the stored
   `probabilities` beat a made-up explanation. The evaluation dashboard runs the real decider
   concurrently and reports accuracy plus a confusion matrix.

### 5. Integration and current status (stated plainly)

| Item | Value |
|---|---|
| Model id | `jev-latest` (returned `jev-1.13.0` in a live call on 2026-09-21) |
| Endpoint | `POST https://api.typesafe.ai/v1/systemone`, Bearer auth |
| Console settings | 5 fields on the "Decider" page: `JUDGE_PROVIDER` / `JEV_API_KEY` / `JEV_BASE_URL` / `DECIDER_TIMEOUT_MS` (3000 ms) / `ROUTE_CONFIDENCE_THRESHOLD_T2` (0.5). **Database settings override `.env` and take effect on save** |
| Connectivity check | The "Test" button reuses the real `health_check()` — it is **not mock talking to itself** |
| Key storage | AES-256-GCM encrypted at rest; never echoed back through an API |

> **⚠️ Two things you must know**
>
> 1. **Jev's public API is not yet available in mainland China** (reported 2026-09-20), and
>    `api.typesafe.ai` is an offshore service — connecting from inside mainland China means
>    **user input leaves the country**, which is a compliance question. This project defaults to
>    `JUDGE_PROVIDER=mock`; for production inside mainland China, keep mock or implement a local
>    decider behind the `BaseDecider` interface.
> 2. **Measure accuracy against your own eval set.** The vendor self-reports ~68% (its own benchmark,
>    no independent verification), which is **below this project's 85% acceptance bar**. The console's
>    evaluation dashboard reports accuracy and a confusion matrix directly — **do not assume; measure**.

---

## Features

| Capability | Description |
|---|---|
| **Decision core · Jev** | Decisions are made by **Jev (TypeSafe AI System One)**: non-autoregressive, generates no text, returns **calibrated probabilities**, 70–500 ms officially → see [Decision core: Jev](#decision-core-jev) |
| **Three-layer routing** | `L1 rule short-circuit → L2 decider ([Jev](#decision-core-jev)) → L3 fallback`; the decision is made **before** the first token is emitted |
| **Isolated entrypoints** | `/v1` (public, OpenAI-compatible, **never leaks 5xx stack traces**) and `/admin` (internal, full error detail) are kept strictly apart |
| **Built-in vendor catalog** | 13 vendors / 24 access channels / 55 models — **add one API key and you're connected**, no manual model setup |
| **Key security** | Vendor keys are stored AES-256-GCM encrypted; no secret is ever echoed back through a public endpoint |
| **Observability** | Every response carries `x-router-*` metadata headers; request logs record the layer hit, the actual model, tokens, and cost |
| **Cost accounting** | Aggregated by model / by layer / by day, sharing **one definition** with the overview page (preview-console diagnostic traffic excluded) |
| **Evaluation dashboard** | Built-in eval set; runs Mock or the real decider concurrently and reports accuracy plus a confusion matrix |
| **Degradation & fallback** | Upstream failures fall back by priority and retry; if everything fails, no 5xx is exposed. 100% fallback coverage |
| **Zero-config bootstrap** | First start creates the schema, the default admin, and the full vendor catalog automatically — idempotent and re-runnable |
| **Dependency-free i18n** | Bilingual console (Chinese/English) without vue-i18n (hand-rolled `t()` / `setLang()`) |

---

## Architecture

```
                    ┌──────────────── /v1（public · OpenAI-compatible）─────────┐
Client ────────────▶│  auth → rate limit → routing decision → forward → SSE   │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
        ┌──────────────────────────────────────▼──────────────────────────────────┐
        │                     Router Engine（exactly one implementation）           │
        │   L1 rule short-circuit ──hit──▶                          ┌─ hit ─┐    │
        │   （keyword / length / regex）                              │       │    │
        │   L2 decider Jev ──confidence ≥ T2──▶ task_type + scores ──┤       │    │
        │   L3 fallback    ──confidence < T2──▶ DEFAULT_MODEL_ID    ─┴─ hit ─┴─▶  │
        └──────────────────────────────────────┬──────────────────────────────────┘
                                               │  sole candidate source: load_routable_models()
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  Adapter pool（protocol differences live only here）      │
                    │  OpenAICompatAdapter · non-streaming + SSE streaming      │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  Downstream pool: 13 vendors / 24 channels / 55 models    │
                    │  api · package · batch · coding_plan · token_plan         │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  Data: PostgreSQL (primary) / SQLite (zero-dep fallback)  │
                    │  request_log · provider · model · route_rule · sys_config │
                    └─────────────────────────────────────────────────────────┘

                    ┌──────────────── /admin（internal · console）─────────────┐
                    │  vendors · models · rules · logs · playground · eval ·    │
                    │  usage & cost                                             │
                    └──────────────────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ (3.13 on the dev machine) / FastAPI / Uvicorn / SQLAlchemy 2.x (async) |
| Database | PostgreSQL 14+ (primary, psycopg3 driver); SQLite (zero-dependency fallback, no external service) |
| Cache / rate limit | Redis 7+ (optional; degrades gracefully when absent) |
| Frontend | Vue 3.4 + Vite 5 + TypeScript 5.4 + Element Plus 2.6 + Pinia 2.1 + Vue Router 4 |
| Routing core | In-house three-layer decision (L1 rules / L2 Jev / L3 fallback), single implementation |
| Cryptography | AES-256-GCM (vendor keys) + JWT (console sessions) |
| Web server | Nginx (bundled in the Docker Compose form; **installed and configured automatically** for bare-metal) |
| Deployment | systemd (script install) · Docker Compose · Apple container (macOS) · from source |

---

## 🚨 Read before deploying

1. **Change the default credentials `admin / admin123` immediately after the first login.**
2. **Back up `ENCRYPTION_MASTER_KEY`.** Vendor API keys are encrypted with it; if it is lost,
   every stored key becomes **permanently undecryptable** (you will have to re-enter each one).
   Never commit this value to git.
3. **Enable HTTPS in production** and keep `ALLOW_LOCAL_BASE_URL=false`.
   That flag permits vendor `base_url` values pointing at `http://` and private-network hosts —
   an SSRF surface. Only turn it on for development machines that need a local gateway.
4. **The model pool starts empty — by design.** A fresh install seeds vendors only
   (13 vendors / 24 channels), no models. Which model IDs you can use and at what price depends
   on your own accounts; the gateway will not guess. Add at least one model on the "Models" page
   and give a channel a key, or the routing candidate pool stays empty.
5. **Prices for subscription-type channels are reference values**, derived from plan quotas —
   **not real marginal cost.** Terms restrictions (e.g. "interactive use in coding tools only")
   are stored verbatim with the channel and flagged in the console.
6. **Only connect upstream services you are entitled to use**, and verify compliance with each
   vendor's terms of service and applicable law.

---

## Deployment

Four options — pick the one that matches your environment:

| Option | Best for | Prerequisites | In one line |
|---|---|---|---|
| **1 · Script install** (recommended) | Production on a Linux server | Linux + Python 3.11+ | one `curl` |
| **2 · Docker Compose** (recommended) | Production anywhere, minimal host setup | Docker + Compose v2, registry access | **one `docker run` pulls images from the cloud — no source, no local build** |
| └ Form A · build from source (optional) | You have the repo and will change code | same as above, plus `github.com` access | `bash deploy/docker-deploy.sh --source` |
| **3 · Apple container** | Local development / trial on Apple Silicon | macOS 26+ and `container` 1.1.0+ | three subcommands |
| **4 · Build from source** | Customization, offline delivery | Python 3.11+ / Node.js 20+ | see below |

> Full procedures and acceptance records:
> [`docs/阶段五-部署与交付/05-安装打包说明.md`](docs/阶段五-部署与交付/05-安装打包说明.md) (Chinese).

---

### Option 1: Script installation (recommended)

Targets **bare-metal Linux** with systemd. The script pulls the source, creates the service
user, builds the virtualenv, installs dependencies, generates `.env` with random secrets,
initializes the database, **installs Node.js and builds the console frontend**, registers +
starts the systemd service, **installs and configures Nginx automatically** (writes the site
config, opens SELinux and the firewall), and finally **prints the console URL**.

In other words: **you install it and it just works — no follow-up commands.** The run ends with
`Console URL  http://<server-ip>/`, which opens straight into the admin UI.

#### Prerequisites

- Linux with systemd (without systemd the script suggests `--no-service`)
- Python **3.11+** (detected; the script prints install commands per distro if missing)
- Node.js — **no need to preinstall it**: the script tries the distro repo first and falls back
  to the official prebuilt tarball (official mirror first, then a China-friendly mirror),
  installing into `/usr/local/lib/nodejs` and symlinking into `/usr/local/bin` —
  **without overwriting files owned by your package manager**. Pass `--no-node-install` to manage
  Node yourself
- Nginx — **no need to preinstall it**: the script installs and configures it via the system
  package manager (`apt` / `dnf` / `yum` / `zypper` / `apk`). If you'd rather use your own web
  server, pass `--no-nginx` to skip this step

#### Install

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
```

From an existing clone — uses the local source tree, no download:

```bash
sudo bash deploy/install.sh
```

Common options:

```bash
sudo bash deploy/install.sh --port 9000            # backend listens on 9000
sudo bash deploy/install.sh --dir /srv/llmbridge   # install dir (default /opt/llmbridge)
sudo bash deploy/install.sh --postgres "postgresql+psycopg://user:pass@127.0.0.1:5432/llmbridge"
sudo bash deploy/install.sh --nginx-port 8080      # console port (default 8081)
sudo bash deploy/install.sh --no-nginx             # do not install/configure Nginx; use your own
sudo bash deploy/install.sh --no-node-install      # do not install Node.js; use the existing one
sudo bash deploy/install.sh --node-version v22.14.0  # pin the Node.js version to install
sudo bash deploy/install.sh --npm-registry https://registry.npmjs.org  # pin the npm registry
sudo bash deploy/install.sh --with-models          # also seed the catalog's reference models/prices
sudo bash deploy/install.sh --skip-frontend        # skip the frontend build
sudo bash deploy/install.sh --frontend-only        # frontend build only (also fixes Node/Nginx)
sudo bash deploy/install.sh --no-service           # lay down code + venv, do not register systemd
sudo bash deploy/install.sh --help
```

> Database default: the script probes local port `5432`. If it is **open**, PostgreSQL is
> configured; if **closed**, it falls back to SQLite at `<install dir>/llmbridge.db` so that
> "install and open the console" actually works. For production, pass `--postgres` explicitly
> or edit `DATABASE_URL` in `.env` and restart.

#### After installing: open the console

The backend only exposes the `/v1` and `/admin` **APIs** — it does not serve static files.
The console is a separate SPA that needs a web server. **The script has already done all of
that**, and it prints the address when it finishes:

```text
Installation complete

  Console URL  http://<server-ip>/   <- opens straight into the admin UI
  Credentials  admin / admin123 (change the password right after the first login)
```

Configuring Nginx, the script also handles the three things that most often block people:

- **Nginx not installed** — installed automatically via the system package manager;
- **The distro's default site owns `default_server` on port 80** — moved aside, otherwise you
  land on the Nginx welcome page and the reverse proxy is never used;
- **SELinux / firewall blocking** — it runs `setsebool -P httpd_can_network_connect 1` and
  opens the port (on RHEL / CentOS, skipping this means every request returns 502).

> If the server sits behind a **cloud security group**, you still have to open the port in the
> cloud console — that cannot be done from inside the machine.
>
> With Caddy or any other web server (or when passing `--no-nginx`), two requirements apply:
> serve `<install dir>/admin-web/dist` statically with an `index.html` fallback for unmatched
> paths, and reverse-proxy `/v1/`, `/admin/`, and `/health` to `127.0.0.1:<port>`.
> The template lives at `deploy/nginx-standalone.conf`
> (`__API_PORT__` / `__LISTEN_PORT__` / `__DIST_DIR__`).

#### Upgrade

Re-run the same command. **Code is updated; `.env`, the database, and stored keys are untouched:**

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
```

If the previous run stopped at "frontend not built / Nginx not configured", this one command
finishes both — and touches nothing else:

```bash
sudo bash /opt/llmbridge/deploy/install.sh --frontend-only
```

#### Uninstall

```bash
sudo bash /opt/llmbridge/deploy/install.sh --uninstall     # stop service, remove unit, keep data
sudo bash /opt/llmbridge/deploy/install.sh --purge -y      # also delete the install dir and data
```

#### Useful commands

```bash
systemctl status llmbridge          # status
systemctl restart llmbridge         # restart (required after editing .env)
journalctl -u llmbridge -f          # live logs

/opt/llmbridge/.venv/bin/llmbridge-seed                 # run bootstrap manually (idempotent)
/opt/llmbridge/.venv/bin/llmbridge-catalog --dry-run    # preview catalog seeding, write nothing
```

---

### Option 2: Docker Compose (recommended)

The default form is **pull images from the cloud**: no source code, no local build, no Node.js —
the target host only needs **Docker + Compose v2** and registry access (defaults to Aliyun
ACR; `--registry` can point at any third-party registry). One command brings up
**api + PostgreSQL + Redis + Nginx** (four containers).

(If you already **have the source** and want to rebuild after changing code, add `--source`
to use "Form A · build from source" at the end of this section.)

#### Prerequisites

- Docker Engine 20.10+ (or Docker Desktop), daemon running
- Docker Compose **v2** (the `docker compose` subcommand form)
- Registry access (default `registry.cn-hangzhou.aliyuncs.com/winyeahs`; `--registry` to use any third-party registry)

#### Quick start (cloud pull, recommended)

```bash
docker run --rm --entrypoint cat \
  registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
  /opt/llmbridge/deploy/docker-deploy.sh | bash -s --
```

That is all. It writes the compose file, generates `.env` (random `JWT_SECRET` /
`ENCRYPTION_MASTER_KEY` / `POSTGRES_PASSWORD`), runs `compose pull`, then `compose up -d`,
polls `/health` until ready, and prints the console URL and default account.

Equivalent to explicitly adding `--image` — `--image` is now the default behavior and can be
omitted. `--entrypoint cat` is required: the api image's default entrypoint initializes the
database before starting the server; the script is piped into the **target host's own bash** —
the container performs no deployment action.

> **This command makes zero GitHub requests**: both the script and the images come from the
> registry, so it is also the recommended path for target hosts in mainland China.

Common variants (record the pipe once, reuse it for every subcommand):

```bash
LB='docker run --rm --entrypoint cat registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 /opt/llmbridge/deploy/docker-deploy.sh'

$LB | bash -s -- --port 8080              # console port (default 8081)
$LB | bash -s -- --dir /srv/llmbridge     # deploy directory
$LB | bash -s -- --tag 1.0.0-<git-short-sha>  # pin an immutable tag (recommended for prod)
$LB | bash -s -- status                   # status + health check (api image already local, offline)
$LB | bash -s -- logs api                 # follow one service's logs
$LB | bash -s -- down                     # stop (volumes preserved)
$LB > docker-deploy.sh                    # write the script out, review before running
```

> Run subcommands from the same directory (the default deploy directory is `./llmbridge`, like
> `docker compose`). To review the script first: `$LB > docker-deploy.sh`, then
> `bash docker-deploy.sh --help`.

**Switching registries (any third-party registry besides Aliyun)**: use
`--registry <host>/<namespace>`; the script builds the `llmbridge-api` / `llmbridge-web`
image references and pulls from that address:

```bash
docker run --rm --entrypoint cat \
  <third-party-registry-host>/<namespace>/llmbridge-api:1.0.0 \
  /opt/llmbridge/deploy/docker-deploy.sh | bash -s -- --registry <third-party-registry-host>/<namespace>
```

Private registry: any of the forms above can pass `REGISTRY_USER` / `REGISTRY_PASSWORD`;
the script logs in automatically before pulling (`--password-stdin`, nothing written to disk):

```bash
REGISTRY_USER=<account> REGISTRY_PASSWORD=<password> bash docker-deploy.sh --registry <host>/<namespace>
```

**Lighter option** (optional): a separate ~8 MB installer image, `llmbridge-deploy`, prints
the same script. It requires **that repository to be public** in the registry — a fresh Aliyun
ACR repository is private by default, whose anonymous token carries no pull permission (401).
After switching it public (console → Container Registry → namespace → repository → edit):

```bash
docker run --rm registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-deploy:1.0.0 \
  | bash -s --
```

(If you would rather not touch that setting, ignore this — the api-image command above runs the
same script.)

##### Publish the images (publisher side, once)

```bash
# Log in to the registry (docker reads the password itself; no script and no file sees it)
docker login --username=<your-account> registry.cn-hangzhou.aliyuncs.com

# Build and push api + web + deploy (defaults to linux/amd64,linux/arm64)
bash deploy/publish-image.sh --tag 1.0.0

# x86-only fleets: pin a single platform (cross-arch builds run under QEMU and are slower)
bash deploy/publish-image.sh --tag 1.0.0 --platform linux/amd64

# Print the exact commands without running them
bash deploy/publish-image.sh --tag 1.0.0 --dry-run
```

The script tags each image twice: `1.0.0` and `1.0.0-<git-short-sha>`. The former can be
overwritten by a later push; **the latter is immutable** — that is what lets you get back
to the exact revision you shipped (prefer it, or a digest, in production).

It pushes to `registry.cn-hangzhou.aliyuncs.com/winyeahs/` by default; override it:

```bash
bash deploy/publish-image.sh --registry registry.cn-hangzhou.aliyuncs.com/<your-namespace> --tag 1.0.0
```

> ⚠️ Never put the registry password into a script, `.env`, or the repo — a plaintext
> credential in a repository is a public credential. For CI, pass `REGISTRY_USER` /
> `REGISTRY_PASSWORD` as environment variables (the script feeds them to
> `docker login --password-stdin`), or use a short-lived registry token.
>
> ⚠️ The `docker-container` BuildKit driver does **not** read the host's `daemon.json`,
> so a host that can `docker pull python:3.13-slim` is not automatically able to build.
> Behind a restricted network, builds die fetching base-image metadata
> (`auth.docker.io ... Bad Gateway`). The script writes
> `~/.docker/buildx/llmbridge-buildkitd.toml` with `docker.io` mirrors for the builder
> and recreates it when the config changes. Override with
> `LLMBRIDGE_REGISTRY_MIRRORS="https://a,https://b" bash deploy/publish-image.sh`.

#### What's in the images

The three images in the registry make up the complete delivery; the target host needs no
source code and performs no local build:

| Image | Contents |
|---|---|
| `llmbridge-api` | Backend (FastAPI + routing engine + migration scripts) + **the install script** (`/opt/llmbridge/deploy/`) |
| `llmbridge-web` | nginx + the built frontend `dist` and `nginx.conf` baked in |
| `llmbridge-deploy` | **Installer** (optional): no application code, just that one install script (~8 MB) |

> **Why the install script travels inside an image**: the script itself has to reach the
> target host first, and `raw.githubusercontent.com` is unreachable from mainland China —
> `curl ... | bash` simply cannot work there. The registry is the one address a target host
> is guaranteed to reach (it has to pull the application images from it anyway), so the
> script ships inside the api image; and since the install then pulls that very same image,
> **fetching the script costs no extra bytes**.

#### Deploy directory and manual equivalent

The deploy directory ends up holding just two things: the compose file and `.env`:

```text
llmbridge/
├── .env
└── deploy/docker-compose.image.yml
```

Manual equivalent (run from the root of the deploy directory):

```bash
docker compose --env-file ./.env -f deploy/docker-compose.image.yml pull
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

> `--env-file ./.env` is required here too: `.env` sits at the deploy-directory root while
> the compose file lives in `deploy/`, so Compose would otherwise look for `deploy/.env`.
> (The install script passes the flag itself, so the one-command path is unaffected.)

#### Access

Open `http://<server-ip>:<HTTP_PORT>/` (`HTTP_PORT` defaults to 8081) and log in with
`admin / admin123`. The public API lives at the same entrypoint:
`http://<ip>:<HTTP_PORT>/v1/chat/completions`.

#### Upgrade and roll back

Upgrade: change `LLMBRIDGE_TAG` in `.env` to the new version (prefer the immutable
`1.0.0-<git-short-sha>` tag), then pull and bring the stack up:

```bash
sed -i 's/^LLMBRIDGE_TAG=.*/LLMBRIDGE_TAG=1.0.1/' .env
docker compose --env-file ./.env -f deploy/docker-compose.image.yml pull
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

Roll back: set `LLMBRIDGE_TAG` back to the previous immutable tag and rerun the two lines
above. Data volumes are untouched; no database change is needed.

#### Data and migration

PostgreSQL and Redis data live in Docker **named volumes** (`llmbridge_pgdata` /
`llmbridge_redisdata`); recreating containers does not lose data. Moving to a new machine:

```bash
# Source server
docker compose --env-file ./.env -f deploy/docker-compose.image.yml stop
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /data .

# New server: restore into the same volume, then bring the stack up
docker volume create llmbridge_pgdata
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar xzf /backup/pgdata.tar.gz -C /data
```

For the SQLite forms (Option 1 default, Option 3 default), just copy `<data dir>/llmbridge.db`.

#### Troubleshooting

- **`pull` reports no such manifest**: confirm the tag was published (the publish script
  prints digests at the end; `docker manifest inspect <image>:<tag>` also works) and that
  the target host's architecture is among the published platforms.
- **Console is 404 / blank**: in the cloud-pull form the `dist` lives inside the
  `llmbridge-web` image, so "forgot to build the frontend" cannot happen. Check that the
  `web` container is up.
- **`exec format error`**: image architecture does not match the host (e.g. arm64 image on
  x86). Re-publish with the right `--platform`, or produce amd64 and arm64 together.

#### Form A: build from source (optional)

If you already **have the source** and want to rebuild after changing code (instead of
pulling ready-made images from the registry), add `--source` to use this form. **Images are
built on the target host**, and the frontend `dist` is bind-mounted into nginx — so the target
host must either hold the source tree or be able to reach GitHub (the script downloads it).

Prerequisites: same as the cloud-pull form (Docker + Compose v2); if you do not have the
source locally, the host also needs `github.com` access.

Quick start (inside a repo, using the current source):

```bash
bash deploy/docker-deploy.sh --source
```

Or download the source from any machine and build locally:

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/docker-deploy.sh | bash -s -- --source
```

The script downloads the source into `./llmbridge`, generates `.env` with random
`JWT_SECRET` / `ENCRYPTION_MASTER_KEY` / `POSTGRES_PASSWORD`, builds the frontend with a
`node:22-alpine` container, runs `docker compose up -d --build`, polls `/health` until ready,
and prints the access URL.

> ⚠️ This path needs `github.com` to be reachable (it downloads both the script and the
> source). **From mainland China, or whenever the target host should not touch GitHub, use
> the cloud-pull form above** — that path makes no GitHub request at all.

Options and subcommands (Form A):

```bash
bash deploy/docker-deploy.sh --source --port 8080     # console port (default 8081)
bash deploy/docker-deploy.sh --source --dir /srv/llmbridge
bash deploy/docker-deploy.sh --source --skip-frontend # when admin-web/dist already exists
bash deploy/docker-deploy.sh --source status          # container status + health check
bash deploy/docker-deploy.sh --source logs api        # follow one service's logs
bash deploy/docker-deploy.sh --source upgrade         # pull + rebuild + restart (data preserved)
bash deploy/docker-deploy.sh --source down            # stop (volumes preserved)
bash deploy/docker-deploy.sh --source purge           # stop and **delete volumes** (irreversible)
```

Manual deployment (Form A):

```bash
# 1) Get the code
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

# 2) Configure (change three things in production)
cp .env.example .env
#   JWT_SECRET / ENCRYPTION_MASTER_KEY — generate random values
#     python -c "import secrets;print(secrets.token_urlsafe(32))"
#     openssl rand -base64 32
#   POSTGRES_PASSWORD — must match the password inside DATABASE_URL
#   HTTP_PORT — public console port (default 8081)

# 3) Build the frontend (nginx bind-mounts admin-web/dist; without it the console is blank)
cd admin-web && npm ci && npm run build && cd ..

# 4) Bring up the stack
docker compose --env-file ./.env -f deploy/docker-compose.yml up -d --build
```

> ⚠️ **`--env-file ./.env` is not optional.** As soon as `-f` points at the `deploy/`
> subdirectory, Compose looks for `.env` **in the directory holding the compose file**
> (`deploy/.env`) when performing **variable interpolation** — the repo-root `.env` is
> invisible to it, and you get
> `required variable POSTGRES_PASSWORD is missing a value`.
> Note that `env_file: ../.env` inside `docker-compose.yml` only sets the **container's**
> environment; it does not affect Compose's own interpolation.
> **Every `docker compose -f deploy/...` command below is the same.**

Generating secrets:

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"   # JWT_SECRET
openssl rand -base64 32                                        # ENCRYPTION_MASTER_KEY
openssl rand -base64 24 | tr -d '/+='                          # POSTGRES_PASSWORD
```

> ⚠️ The `127.0.0.1` host in `.env`'s `DATABASE_URL` is for running the backend directly on
> the host. Compose overrides it with the service name `db` — no manual edit needed.

Upgrade (Form A):

```bash
git pull
cd admin-web && npm ci && npm run build && cd ..
docker compose --env-file ./.env -f deploy/docker-compose.yml up -d --build
```

> `--build` is required: the frontend `dist/` is bind-mounted into nginx, so
> **frontend changes need a rebuild — restarting the container is not enough.**

Useful commands (Form A):

```bash
docker compose --env-file ./.env -f deploy/docker-compose.yml ps               # status
docker compose --env-file ./.env -f deploy/docker-compose.yml logs -f api      # backend logs
docker compose --env-file ./.env -f deploy/docker-compose.yml restart api      # restart backend
docker compose --env-file ./.env -f deploy/docker-compose.yml down             # stop (volumes preserved)
docker compose --env-file ./.env -f deploy/docker-compose.yml down -v          # stop and delete data (dangerous)
```

#### Switching between Form A and the cloud-pull form

Both compose files share the project name `llmbridge`, so they **share the same data
volumes** (`llmbridge_pgdata` / `llmbridge_redisdata`) — switching forms does not lose data.
But the service names differ (Form A has `nginx`, the cloud-pull form has `web`), so stop
first:

```bash
docker compose --env-file ./.env -f deploy/docker-compose.yml down       # before switching A → cloud-pull
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

An `orphan containers` warning during the next up usually means this step was skipped.

---
### Option 3: Apple container (macOS)

On Apple Silicon Macs running macOS 26, Apple's native `container` (1.1.0+) can run the full
gateway. This option targets **local development and hands-on operation**; use Option 1 or 2
for production.

#### Prerequisites

- Apple Silicon Mac with macOS 26 or later
- Apple `container` 1.1.0+: `brew install container`
  (or download from [apple/container releases](https://github.com/apple/container/releases))
- Run `container system start` once (the script also attempts this automatically)

#### Quick start

```bash
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

./deploy/apple-container.sh init      # check environment + generate secrets + build the image
./deploy/apple-container.sh up        # start the container and wait for /health
./deploy/apple-container.sh status    # container, image, and health status
```

Then open `http://127.0.0.1:8000/` and log in with `admin / admin123`.

The default shape is a **single container with SQLite**, with data on the host under
`./llmbridge-data/` (removing the container does not lose data). It deliberately does not
orchestrate PostgreSQL + Redis + app as separate containers: Apple container is a per-container
CLI with no compose-style dependency ordering or health-gated startup, so managing three tiers
means hand-writing startup polling — brittle and hard to debug. Use Option 2 when you need the
full topology.

#### Useful commands

```bash
./deploy/apple-container.sh logs              # follow logs
./deploy/apple-container.sh shell             # shell into the container
./deploy/apple-container.sh restart
./deploy/apple-container.sh upgrade           # pull code + rebuild image + restart (data preserved)
./deploy/apple-container.sh down              # stop and remove the container (keeps the data dir)
./deploy/apple-container.sh purge             # also delete the data dir (irreversible)
```

Tunable environment variables:

```bash
LLMBRIDGE_PORT=9000 ./deploy/apple-container.sh up    # host port
LLMBRIDGE_BIND=0.0.0.0 ./deploy/apple-container.sh up # expose publicly (bring your own TLS proxy)
LLMBRIDGE_DATA_DIR=/path ./deploy/apple-container.sh up
```

#### Switching to PostgreSQL

Start a PG container (or point at a remote one), then edit the config file and restart:

```bash
vim ./llmbridge-data/.env      # DATABASE_URL=postgresql+psycopg://user:pass@host:5432/llmbridge
./deploy/apple-container.sh restart
```

> Do not use `postgresql+asyncpg://` — asyncpg is not a dependency and will only fail when a
> connection is actually opened.

---

### Option 4: Build from source

For customization, extension work, or producing an offline release package.

#### Prerequisites

| Component | Version |
|---|---|
| Python | **3.11+** |
| Node.js | 20+ (console frontend only; auto-installed by the script form) |
| PostgreSQL | 14+ (falls back to SQLite automatically if absent) |
| Redis | 7+ (optional) |

#### Run from source

```bash
# 1) Get the code
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

# 2) Create a virtualenv and install editable (code changes need no reinstall)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"      # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux / macOS

# 3) Configure
cp .env.example .env
# Change in production: JWT_SECRET, ENCRYPTION_MASTER_KEY, the password in DATABASE_URL

# 4) Start (first start bootstraps schema / default admin / vendor catalog, idempotent)
llmbridge-serve --host 127.0.0.1 --port 8000
```

Verify the backend:

```bash
curl -f http://127.0.0.1:8000/health
# {"status":"ok"}

curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Explain quantum entanglement in one sentence"}]}'
```

Build and run the console:

```bash
cd admin-web
npm ci
npm run dev -- --host 127.0.0.1     # dev mode with HMR: http://127.0.0.1:5173
npm run build                       # production assets: admin-web/dist
```

> **Windows + PostgreSQL, important**: starting with `uvicorn app.main:app` will fail to reach
> the database. uvicorn's default loop factory returns a `ProactorEventLoop`, which psycopg3
> refuses — the symptom is "the service starts, `/health` returns 200, but any database access
> returns 500". Use `llmbridge-serve`, which wires in the correct `SelectorEventLoop`. If you
> insist on bare uvicorn you must pass `--loop app.core.eventloop:selector_loop_factory`.

#### Development mode

```bash
# Backend with hot reload
llmbridge-serve --host 127.0.0.1 --port 8000 --reload

# Console with HMR (vite proxies /admin and /v1 to :8000)
cd admin-web && npm run dev -- --host 127.0.0.1

# Tests
pytest
```

On Windows you can also use the bundled scripts:

```powershell
.\deploy\windows\start-backend.ps1     # backend only
.\deploy\windows\start-dev.ps1         # backend + console frontend
```

#### Building distributables

```bash
python -m build                        # standard wheel / sdist → dist/
python scripts/build_release.py        # project script: assemble an offline zip
```

`build_release.py` produces `release/llmbridge-<version>-<date>.zip` containing the backend
code, database scripts, deployment assets, and the built frontend, plus `BUILD-INFO.txt` and
`SHA256SUMS.txt` (integrity manifest). Options:

```bash
python scripts/build_release.py --skip-frontend    # frontend already built, skip npm
python scripts/build_release.py --no-archive       # assemble the directory without zipping
```

---

## Configuration

Everything is configured through environment variables — see [`.env.example`](.env.example).
The ones that matter most:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./llmbridge.db` | Use `postgresql+psycopg://…` for PostgreSQL (**never asyncpg**). Change in production |
| `POSTGRES_PASSWORD` | `change-me` | Docker Compose only (injected into the db and api containers) |
| `HTTP_PORT` | `8081` | Docker Compose only: public console port |
| `AUTO_BOOTSTRAP` | `true` | Create schema / admin / vendor catalog on startup, idempotent. Set `false` when a DBA owns the database |
| `JWT_SECRET` | `dev-only-change-me` | **Change in production.** Console session signing key |
| `ENCRYPTION_MASTER_KEY` | `dev-only-change-me…` | **Change in production.** AES-256-GCM master key for vendor keys — **unrecoverable if lost** |
| `ALLOW_LOCAL_BASE_URL` | `false` | Allow vendor `base_url` over `http://` and private hosts. **Must be false in production** |
| `REDIS_URL` | empty | Leave empty to disable cache / rate limiting (graceful degradation) |
| `JUDGE_PROVIDER` | `mock` | Which decider to use: `mock` = built-in dependency-free decider (works offline); `jev` = the **Jev decision model** (TypeSafe AI's official API). See [Decision core: Jev](#decision-core-jev) |
| `JEV_API_KEY` | empty | API key for Jev. Required when `judge_provider=jev`; when empty the gateway silently falls back to mock (the dashboard flags the mismatch) |
| `JEV_BASE_URL` | `https://api.typesafe.ai/v1/systemone` | Jev endpoint. **⚠️ Offshore service — connecting from mainland China sends user input abroad** |
| `DECIDER_TIMEOUT_MS` | `3000` | Decider timeout. Measured at 0.4–1.2 s per call, so 3000 ms is comfortable |
| `ROUTE_CONFIDENCE_THRESHOLD_T2` | `0.5` | L2 confidence threshold; below this the request falls back to L3 |
| `DEFAULT_MODEL_ID` | `1` | Final fallback model id when all candidates fail. **Must be a real id from the model pool** |
| `ENABLE_TOOL_EXECUTION` | `false` | See "Tool-calling boundary" |
| `REQUEST_TIMEOUT_MS` | `30000` | Upstream request timeout |

---

## CLI

| Command | Purpose |
|---|---|
| `llmbridge-serve [--host] [--port] [--workers] [--reload]` | Start the gateway. Ships the psycopg3-compatible event loop, so this one command works cross-platform. **Performs the first-run bootstrap automatically** (schema / default admin / eval samples / vendor catalog), all idempotent |
| `llmbridge-seed [--force]` | Run the same bootstrap manually. Idempotent; skips everything already in place. Use this explicitly in operations when `AUTO_BOOTSTRAP=false` |
| `llmbridge-catalog [--with-models] [--dry-run] [--overwrite] [--keep-names] [--prune-orphans] [--report PATH]` | Seed the vendor catalog. Idempotent, claims existing rows via three-level matching, never touches stored keys. Seeds **channels only** by default |

Operational scripts in the source tree:

```bash
python scripts/seed_provider_catalog.py --dry-run   # same as above (thin shell over app/data/catalog_seed.py)
python scripts/migrate_sqlite_to_pg.py              # migrate SQLite data to PostgreSQL
python scripts/migrate_add_provider_channels.py     # add channel fields to legacy databases
python scripts/build_release.py                     # build an offline release package
python scripts/verify_registry.py --tag 1.0.0        # confirm the tag really exists (not the push exit code)
python scripts/verify_deploy.py --port 8099          # post-install **functional** check (console/login/db/bootstrap)
python scripts/check_compose_sync.py                 # verify the embedded compose copy matches its source
```

---

## API surface

Public (`/v1`, OpenAI-compatible):

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | The only public endpoint. `model: "auto"` triggers intelligent routing; a concrete model name short-circuits straight to it |

Internal (`/admin`, JWT required) — 24 paths / 35 operations in total:

```
/admin/auth/login                  /admin/providers[/{id}][/test]
/admin/models[/{id}][/references]  /admin/rules[/{id}][/priorities]
/admin/logs[/{trace_id}]           /admin/samples
/admin/api-keys[/{id}]             /admin/options
/admin/stats/overview              /admin/usage/report
/admin/route/preview               /admin/eval/report
/admin/decider/settings[/test]
```

**Response metadata headers** (`x-router-*`; the first four are always present):

| Header | Always | Description |
|---|---|---|
| `x-router-trace-id` | ✅ | Unique trace id, matching the logs page and `request_log` rows |
| `x-router-layer` | ✅ | Layer hit: `L1` / `L2` / `L3` |
| `x-router-model` | ✅ | The model that **actually served** the request (distinct from the decision value; after degradation the former wins) |
| `x-router-confidence` | ✅ | Confidence; always `1.0` for L1, fallback semantics for L3 |
| `x-router-task-type` | L2 only | Task type; L1 short-circuits and explicit model requests never reach the decider |
| `x-router-tools` | Tools only | Number of tool-execution rounds (when `ENABLE_TOOL_EXECUTION=true`) |

---

## Tool-calling boundary

The gateway is **pass-through by default** (`ENABLE_TOOL_EXECUTION=false`):

- `tools` / `tool_choice` in the request are forwarded downstream unchanged;
- The response body, native `tool_calls`, and SSE bytes are returned **byte-for-byte unmodified**;
- Tools are executed by **the caller** — standard OpenAI semantics, and the recommended usage.

If you set `ENABLE_TOOL_EXECUTION=true`, the gateway executes the whitelisted `WebFetch` itself
(with SSRF blocking — private, loopback, and link-local addresses are rejected) and continues the
conversation for multiple rounds. **This only suits callers with no tool loop of their own** —
once enabled the gateway swallows intermediate rounds and rewrites the body, making "the model
said one sentence" and "the tool did not run" indistinguishable in the response.

---

## Project layout

```
llmbridge/
├── app/                      Backend (FastAPI)
│   ├── api/v1/               Public entrypoint: OpenAI-compatible + SSE
│   ├── api/admin/            Internal entrypoint: all console APIs
│   ├── router_engine/        Routing core (L1/L2/L3 orchestration, single implementation)
│   ├── deciders/             Decider implementations (mock / Jev)
│   ├── adapters/             Downstream protocol adapters (differences live only here)
│   ├── services/             Keys, billing, log buffer, quota cache, DB-backed config, tools, bootstrap
│   ├── data/provider_catalog.py   Built-in vendor catalog constants (read-only)
│   ├── data/catalog_seed.py       Catalog seeding (in-package; shared by CLI and startup)
│   ├── db/                   ORM models and session
│   ├── core/                 Config, crypto, security, event loop
│   └── cli.py                Command-line entrypoints
├── admin-web/                Console frontend (Vue 3 + Vite + Element Plus)
├── scripts/                  Idempotent ops scripts (catalog / migrations / release build / delivery checks)
├── deploy/                   Deployment assets
│   ├── install.sh            ★ Option 1: Linux one-shot install (systemd)
│   ├── docker-deploy.sh      ★ Option 2: Docker Compose one-shot deploy (default cloud pull; `--source` for local source build)
│   ├── publish-image.sh      ★ Publisher side of Form B: build and push the api + web + deploy images
│   ├── apple-container.sh    ★ Option 3: macOS Apple container
│   ├── Dockerfile            Backend image
│   ├── Dockerfile.web        Frontend image (nginx + dist and nginx.conf baked in)
│   ├── Dockerfile.deploy     Installer image (prints docker-deploy.sh only, ~8 MB)
│   ├── docker-compose.yml    Orchestration (api / db / redis / nginx) · Form A, builds locally
│   ├── docker-compose.image.yml  Orchestration (api / db / redis / web) · Form B, no build stage
│   ├── nginx.conf            Reverse proxy for the Compose form (SSE-critical; baked into the web image)
│   ├── nginx-standalone.conf Site-config template for the bare-metal form
│   ├── entrypoint.sh         Container entrypoint: initialize, then start
│   ├── healthcheck.py        Health probe (stdlib only)
│   ├── linux/                systemd unit
│   └── windows/              Local start scripts
├── docs/                     Full delivery documentation (requirements → design → dev → test → deploy)
├── tests/                    Automated tests
├── .env.example              Environment variable template
├── MANIFEST.in               sdist contents manifest
└── pyproject.toml            Build configuration and dependencies
```

---

## Documentation index

| Document | Contents |
|---|---|
| [`docs/README.md`](docs/README.md) | **Project master document** (current baseline): architecture, API, conventions, acceptance in one place |
| [`docs/阶段一-需求与规划/`](docs/阶段一-需求与规划/) | Requirements, UI design, project plan, acceptance criteria, risk register |
| [`docs/阶段二-设计与架构/`](docs/阶段二-设计与架构/) | Architecture, API design, database design, security plan |
| [`docs/阶段三-开发与实现/`](docs/阶段三-开发与实现/) | Implementation notes, code review, end-to-end verification records |
| [`docs/阶段四-测试与验证/`](docs/阶段四-测试与验证/) | Test plan, cases, defect reports, quality assessment |
| [`docs/阶段五-部署与交付/`](docs/阶段五-部署与交付/) | **Installation & packaging guide**, deployment doc, user manual, operations manual |

---

## Known limitations

- **Jev's official API is not available in mainland China yet**, and `api.typesafe.ai` is an offshore
  service — connecting from there means **user input leaves the country**, which is a compliance
  question. This project defaults to `JUDGE_PROVIDER=mock`; for production inside mainland China keep
  mock, or implement a local decider behind the `BaseDecider` interface (see
  [Decision core: Jev](#decision-core-jev)). Also: the vendor self-reports ~68% decision accuracy,
  **below this project's 85% acceptance bar** — measure it on your own eval set; the console reports
  accuracy and a confusion matrix directly.
- **Streaming token usage depends on the upstream**: if the client does not send
  `stream_options.include_usage`, some vendors omit `usage`, and that log row records 0 tokens /
  0 cost — that is *missing data*, not *zero consumption*.
- **Plain HTTP fetching cannot render JavaScript-only sites** (relevant only when
  `ENABLE_TOOL_EXECUTION=true`).
- **The model pool is empty by default**: a fresh install seeds vendors only, never models
  (available models and billing semantics differ per account). Add at least one model on the
  "Models" page and give a channel a key, or the candidate pool stays empty — `/v1` requests
  then take the fallback path and report the error as-is, and the console overview shows 0.
  `DEFAULT_MODEL_ID` in `.env` must point at a **real** model id.
- **`alembic/` is reserved but not enabled**: schema creation currently goes through ORM
  `create_all` (startup bootstrap / `llmbridge-seed`); legacy database upgrades go through
  `scripts/migrate_*.py`.
- **Option 3 (Apple container) has not been verified end-to-end on real hardware**: the script
  follows the Apple `container` CLI and passes static shell checks, but the development machine
  is Windows, so macOS-specific paths could not be executed. Watch the script output on first use.
- Vendor reference prices come from official public pages; **subscription plan prices are
  quota-derived reference values**, not real marginal cost. Terms restrictions (e.g. "interactive
  use in coding tools only") are stored verbatim with the channel and flagged in the console.

---

## 🤝 Community

We welcome every developer and user: ask questions, share what you learned, contribute code,
or just tell us what you built with it.

<div align="center">
<img src=".github/images/微信交流.jpg" width="300" alt="WeChat contact">
<p align="center">Scan to reach us on WeChat</p>
</div>

**More links:**

- **Bugs & feature requests (Issues):** open them at [GitHub Issues](https://github.com/dragonlin-ai/llmbridge/issues).
- **Discussions:** deeper technical talk at [GitHub Discussions](https://github.com/dragonlin-ai/llmbridge/discussions).
- **Contact:** for business or anything else, email `93634776@qq.com`.

---

## License

[Apache License 2.0](LICENSE)
