# Ponytail Integration

[Ponytail](https://github.com/DietrichGebert/ponytail) is an optional upstream
plugin for Claude Code and Codex. It is not vendored, required, or installed by
default by Mneme.

After reviewing the upstream project, users who want the optional agent-plugin
integration can request it explicitly:

```bash
./scripts/install.sh --profile global --profile-confirmed --agent-plugins
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global -ProfileConfirmed -AgentPlugins
```

The installer uses the available client CLIs and continues if an optional
plugin step fails. Use `--memory-only` or `-MemoryOnly` for an installation that
does not modify client or plugin configuration.

Ponytail remains subject to its upstream license, release process, and security
model.
