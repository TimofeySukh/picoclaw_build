# PicoClaw Local

This repository contains a local-first PicoClaw setup that runs inside Docker and uses the model currently loaded in LM Studio.

It is designed for people who want:
- local-only usage
- LM Studio as the model backend
- simple helper commands for start, stop, restart, and CLI access
- approval prompts for privileged actions

## What This Setup Does

This setup:
- runs PicoClaw in Docker
- connects to LM Studio at `http://127.0.0.1:1234`
- automatically uses the model currently loaded in LM Studio
- provides terminal helper commands:
  - `picoclaw_on`
  - `picoclaw_off`
  - `picoclaw_restart`
  - `picoclaw_restart --no_reset`
  - `picoclaw_cli`
- shows approval prompts in the terminal UI for:
  - `root` commands inside the container
  - commands executed on the host outside Docker

## Requirements

Install these first:
- Docker
- Colima
- LM Studio
- `zsh`
- Python 3

## Quick Start

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd picoclaw
```

If your local directory has a different name, use that directory name instead of `picoclaw`.

### 2. Start Colima

If Colima is not already running:

```bash
colima start
```

### 3. Start LM Studio

Open LM Studio and:
- load a model
- enable the local server
- make sure the server is available at `http://127.0.0.1:1234`

You can verify that with:

```bash
curl http://127.0.0.1:1234/v1/models
```

### 4. Add the helper commands to your shell

The helper scripts live in the repository `scripts/` directory. The simplest setup is to symlink them into `~/.local/bin` and make sure that directory is in your `PATH`.

Create the directory if needed:

```bash
mkdir -p ~/.local/bin
```

Create the symlinks:

```bash
ln -sf "$(pwd)/scripts/picoclaw_on" ~/.local/bin/picoclaw_on
ln -sf "$(pwd)/scripts/picoclaw_off" ~/.local/bin/picoclaw_off
ln -sf "$(pwd)/scripts/picoclaw_restart" ~/.local/bin/picoclaw_restart
ln -sf "$(pwd)/scripts/picoclaw_cli" ~/.local/bin/picoclaw_cli
```

If `~/.local/bin` is not already in your shell `PATH`, add this to `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload your shell:

```bash
exec zsh
```

## Daily Usage

### Start PicoClaw

```bash
picoclaw_on
```

What it does:
- checks LM Studio
- detects the currently loaded model
- updates the local PicoClaw config
- starts the approval bridge
- starts the Docker container

### Open the terminal UI

```bash
picoclaw_cli
```

This opens the terminal interface for chatting with the agent.

### Stop PicoClaw

```bash
picoclaw_off
```

This:
- stops the Docker container
- brings the compose stack down
- resets conversation context

### Restart PicoClaw

```bash
picoclaw_restart
```

This:
- refreshes the model from LM Studio
- restarts the container
- resets context

To restart without clearing context:

```bash
picoclaw_restart --no_reset
```

## Approval Model

The approval behavior is:
- normal commands inside Docker: allowed without approval
- `root` commands inside Docker: approval required
- commands on the host machine outside Docker: approval required

When approval is required, the terminal UI shows a popup. Use the arrow keys to choose:
- `Approve`
- `Deny`
- `Later`

Then press `Enter`.

## Helper Commands

Available commands:

```bash
picoclaw_on
picoclaw_off
picoclaw_restart
picoclaw_restart --no_reset
picoclaw_cli
```

## Important Files

Main entry points:
- `compose.yml`
- `scripts/picoclaw_on`
- `scripts/picoclaw_off`
- `scripts/picoclaw_restart`
- `scripts/picoclaw_cli`
- `scripts/picoclaw_cli.py`
- `scripts/picoclaw_lmstudio.py`

Runtime data:
- `docker/data/config.json`
- `docker/data/hostexec/`
- `docker/data/logs/`

## Troubleshooting

### LM Studio is not detected

Check:

```bash
curl http://127.0.0.1:1234/v1/models
```

If that fails, LM Studio is not serving correctly yet.

### Docker commands fail

Check Colima:

```bash
colima status
```

Check Docker:

```bash
docker ps
```

If needed:

```bash
colima start
```

### Full reset

If something feels stuck:

```bash
picoclaw_off
picoclaw_on
picoclaw_cli
```

## Notes

- This setup is intended for local use.
- The active model is taken from LM Studio at startup time.
- If you load a different model in LM Studio, run `picoclaw_restart` so PicoClaw picks it up.
