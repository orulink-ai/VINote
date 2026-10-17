# Interactive Raspberry Pi Deployment - Design Document

## Overview

Add an interactive, guided deployment flow for VINote to Raspberry Pi, replacing the current batch-style scripts that require pre-configuration. The new scripts will provide step-by-step prompts, connection validation, and user confirmation before each major action.

## Design Decisions

| Decision | Choice |
|----------|--------|
| Interaction style | Step-by-step guided with validation after each step |
| SSH key handling | Auto-detect on failure, prompt with setup instructions |
| Deployment scope | User selectable: backend only, or frontend + backend |
| Platform support | Both PowerShell (.ps1) and Bash (.sh) versions |
| Remote checks | Docker daemon + Docker Compose availability |
| Git handling | User choice: commit / stash / skip push / cancel |
| Visual style | Plain text + ANSI colors with emoji status indicators |
| Pre-execution preview | Summary display with user confirmation |
| Config persistence | Save to local.env for future runs |
| Error recovery | Full retry from beginning |

## Architecture

### File Structure

```
deploy/pi/
├── deploy-pi.sh              # Existing, non-interactive, for CI/CD
├── deploy-pi.ps1             # Existing, non-interactive, for CI/CD
├── deploy-pi-interactive.sh  # NEW, interactive Bash version
├── deploy-pi-interactive.ps1 # NEW, interactive PowerShell version
├── local.env                 # Persisted config (gitignored)
└── local.env.example         # Template for new users
```

### Interaction Flow (9 Steps)

```
Step 1/9: Configure Connection
Step 2/9: Test SSH Connection
Step 3/9: Select Deployment Scope
Step 4/9: Git Status Check
Step 5/9: Preview & Confirm
Step 6/9: Remote Environment Check
Step 7/9: Push Code (if applicable)
Step 8/9: Upload Files
Step 9/9: Execute Deployment
```

## Detailed Flow

### Step 1: Configure Connection

Prompt user for:
- `PI_HOST` (required) - Raspberry Pi IP address or hostname
- `PI_USER` (required) - SSH username, default: `pi`
- `PI_PORT` (optional) - SSH port, default: `22`

If `local.env` already exists with values, pre-fill and allow editing.

**Output:** Save to `deploy/pi/local.env`

---

### Step 2: Test SSH Connection

Attempt: `ssh -o ConnectTimeout=5 -o BatchMode=yes -p {PORT} {USER}@{HOST} echo ok`

**On success:** Display ✅ Connected

**On failure:** Detect cause and prompt:

```
❌ Connection failed.

Possible reasons:
1. Wrong IP address or hostname
2. SSH service not running on Pi
3. SSH key not configured

Have you configured SSH key authentication?
  [1] Yes, continue anyway
  [2] No, show me how to set it up
  [3] Cancel deployment
```

If user selects option 2, display SSH key setup instructions:

```
=== SSH Key Setup Guide ===

1. On your local machine, generate a key pair:
   ssh-keygen -t ed25519 -C "your_email@example.com"

2. Copy the public key to your Pi:
   ssh-copy-id -p {PORT} {USER}@{HOST}

3. Test connection:
   ssh -p {PORT} {USER}@{HOST}

For more details, visit:
https://www.raspberrypi.com/documentation/computers/remote-access.html
```

---

### Step 3: Select Deployment Scope

Display options:

```
Select deployment scope:
  [1] Backend only (API + services on port 8900)
  [2] Frontend + Backend (full stack, default)

Note: Frontend will be built and served by nginx.
```

Read user choice, default: `2`

---

### Step 4: Git Status Check

Run: `git status --short` in repo root

**If clean:** Display ✅ Working tree clean, continue

**If not clean:** Prompt:

```
⚠️ Working tree has uncommitted changes.

  [1] Commit changes (opens editor)
  [2] Stash changes
  [3] Skip pushing (continue with local state)
  [4] Cancel deployment
```

- Option 1: Run `git commit`, require non-empty message
- Option 2: Run `git stash push -m "Auto-stash before deploy $(date)"`
- Option 3: Set `SKIP_PUSH=true`, continue
- Option 4: Exit

---

### Step 5: Preview & Confirm

Display deployment summary:

```
=== Deployment Summary ===

Target:         pi@192.168.1.50:22
Branch:         main
Scope:          Frontend + Backend
Remote Dir:     /home/pi/vinote
Local Env:      .env
Git Push:       Yes

Ready to deploy?
  [Y] Yes, deploy now
  [N] No, cancel

>
```

If user enters `N`, exit. Any other input proceeds.

---

### Step 6: Remote Environment Check

Run on remote via SSH:

```bash
# Check Docker daemon
docker info >/dev/null 2>&1 && echo "DOCKER_OK=1" || echo "DOCKER_OK=0"
docker compose version >/dev/null 2>&1 && echo "COMPOSE_OK=1" || echo "COMPOSE_OK=0"
```

**If docker daemon not running:**
```
❌ Docker daemon is not running on the Pi.

Please start Docker on your Raspberry Pi:
  sudo systemctl start docker
  sudo systemctl enable docker

Then restart this deployment.
  [1] Retry checks
  [2] Continue anyway (may fail)
  [3] Cancel
```

**If docker compose not available:**
```
❌ Docker Compose is not installed on the Pi.

Please install Docker Compose:
  sudo apt-get update && sudo apt-get install -y docker-compose

Or use the Docker Compose plugin:
  sudo apt-get install -y docker-compose-plugin
```

---

### Step 7: Push Code (if not skipped)

Run: `git push origin {BRANCH}`

**On failure:** Prompt:
```
❌ Failed to push to origin.

  [1] Retry
  [2] Skip pushing, continue with local files
  [3] Cancel
```

---

### Step 8: Upload Files

Sequential operations with status:

```
Uploading .env file...
  [====================] 100%

Creating source archive...
  [====================] 100%

Uploading source archive...
  [====================] 100%
```

Error handling: If scp fails, retry once, then prompt:
```
❌ Upload failed.

  [1] Retry
  [2] Cancel
```

---

### Step 9: Execute Deployment

Remote execution:

```bash
cd /home/pi/vinote
export COMPOSE_PROJECT_NAME=vinote
export DOCKER_DEFAULT_PLATFORM=linux/arm/v7

# Selective build based on Step 3 choice
if [ "$SCOPE" = "full" ]; then
  docker compose up -d --build
else
  docker compose up -d --build backend
fi
```

**On success:** Display:

```
✅ Deployment complete!

Access VINote:
  - Frontend: http://192.168.1.50:3100
  - Backend:  http://192.168.1.50:8900
  - MCP:      http://192.168.1.50:8900/mcp

To check status on Pi:
  ssh pi@192.168.1.50
  cd ~/vinote && docker compose ps
```

**On failure:** Display error and prompt:
```
❌ Deployment failed: {error message}

  [1] Retry deployment
  [2] View logs (docker compose logs)
  [3] Cancel
```

---

## Component Inventory

### Shared Functions (extracted for reuse)

Both scripts will share logic for:
- `test_ssh_connection()` - Test connectivity with timeout
- `check_docker_remote()` - Verify Docker daemon and compose
- `read_non_empty()` - Read input requiring non-empty value
- `confirm_choice()` - Yes/No confirmation prompt
- `print_step()` - Print current step header
- `print_status()` - Print success/failure with emoji
- `persist_config()` - Save PI_HOST, PI_USER, PI_PORT to local.env
- `load_config()` - Load existing config from local.env

### Color Codes (ANSI)

| Status | Color | Emoji |
|--------|-------|-------|
| Success | Green | ✅ |
| Failure | Red | ❌ |
| Warning | Yellow | ⚠️ |
| Info | Cyan | ℹ️ |
| Progress | Default | 🚀 |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        Step 1                               │
│  Read/Confirm: PI_HOST, PI_USER, PI_PORT                   │
│                        ↓                                    │
│                   Save to local.env                         │
├─────────────────────────────────────────────────────────────┤
│                        Step 2                               │
│  ssh -o ConnectTimeout=5 ... echo ok                       │
│                        ↓                                    │
│  Fail? → SSH Key Setup Prompt → Retry or Cancel            │
├─────────────────────────────────────────────────────────────┤
│                        Step 3                               │
│  Select: backend-only / full-stack                         │
│                        ↓                                    │
│                   Store SCOPE variable                      │
├─────────────────────────────────────────────────────────────┤
│                        Step 4                               │
│  git status --short                                         │
│                        ↓                                    │
│  Dirty? → Commit / Stash / Skip / Cancel                   │
├─────────────────────────────────────────────────────────────┤
│                        Step 5                               │
│  Display summary, await Y/y confirmation                     │
│                        ↓                                    │
│                        N → Exit                             │
├─────────────────────────────────────────────────────────────┤
│                     Steps 6-9                               │
│  Environment Check → Git Push → Upload → Deploy             │
│                        ↓                                    │
│                   Success / Retry                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Error Handling

| Scenario | Action |
|----------|--------|
| SSH connection fails | Detect, offer SSH key setup guide |
| Docker daemon not running | Stop, show systemctl commands |
| Docker compose missing | Stop, show install commands |
| Git push fails | Offer retry or skip |
| scp upload fails | Retry once, then prompt |
| docker compose up fails | Show logs option, offer retry |

---

## Configuration Persistence

File: `deploy/pi/local.env` (gitignored)

```bash
PI_HOST=192.168.1.50
PI_USER=pi
PI_PORT=22
```

On subsequent runs, pre-fill prompts with these values.

---

## Backward Compatibility

The existing `deploy-pi.ps1` and `deploy-pi.sh` remain unchanged for:
- CI/CD pipelines
- Automated deployment scripts
- Users who prefer non-interactive mode

New `deploy-pi-interactive.ps1` and `deploy-pi-interactive.sh` become the default "user-friendly" entry point.

---

## Acceptance Criteria

1. Script launches and displays "Step 1/9: Configure Connection"
2. Pre-filled values shown if local.env exists
3. Empty IP address triggers re-prompt with error message
4. SSH connection failure shows SSH key setup instructions
5. Git dirty state triggers choice menu
6. Preview summary displays all key info before execution
7. Each step completes with success/failure indicator
8. Failed Docker daemon check stops deployment with instructions
9. Deployment success shows access URLs
10. Configuration persists to local.env after successful connection step
