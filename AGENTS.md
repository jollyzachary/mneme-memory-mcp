# Mneme Agent Install Rule

If you are an AI agent working in this repo, do not install or configure Mneme
until the user has explicitly chosen a setup profile.

Before running `scripts/install.sh`, `scripts/install.ps1`, or making equivalent
manual changes to Claude, Codex, MCP, Hermes, or Mneme memory config, stop and
ask the user which setup they want:

- `global`: machine-wide memory with global Claude/Codex instructions
- `project`: project/env-scoped memory from `.env`
- `server`: local server install only with manual wiring

Do not assume `global`. Do not infer the choice from the operating system, the
current repo, or prior installs.

After the user answers, rerun the installer with both the selected profile and
the explicit confirmation flag:

```bash
./scripts/install.sh --profile project --profile-confirmed
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile project -ProfileConfirmed
```

For non-interactive automation, use `MNEME_SETUP_PROFILE` only together with
`MNEME_PROFILE_CONFIRMED=1`, and only after the user has answered.
