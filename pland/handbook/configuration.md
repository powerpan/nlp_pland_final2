# What can be configured, and where

You cannot change any of this yourself — there is no tool for it. Tell the human where the switch is.

## Layers (later wins)
1. Built-in defaults.
2. Environment / `.env` (provider, endpoints, API keys). Keys live only in `.env` — the installation's `.env` or
   `PLAND_HOME/.env`, mode 600 — never in a settings file, and are never shown again after saving.
3. **Global defaults** for every agent: the web UI's Settings page, stored in `PLAND_HOME/settings.yaml`
   (`PLAND_HOME` is `~/.pland` unless set). A change applies from the next run, no restart.
4. **Per-bot overrides**: the `settings` block of `profiles/<name>/profile.yaml`; in the web UI the bot's right-hand
   panel → Settings, in the terminal `pland profile set <name> …` or `pland setup` (for the default profile).
   Only fields that were changed are stored; the rest keep following the global defaults.
5. **Per-conversation choices**: model and thinking intensity (the two menus in the composer, or `/model` and
   `/reasoning` in the CLI) and the working folder (the folder button in the header, `/workspace`, `pland -w`).
   They are stored with the conversation and take effect on the next turn. In a group each bot uses its own
   settings, so the group composer has no model menu.

## Identity of a bot (set when creating or editing a bot)
Name (`@handle`, fixed after creation), title, description (teammates see it and use it to decide who gets which
work), SOUL (personality and standing instructions, `SOUL.md`), avatar colour, and whether it is listed as a bot.

## Group settings
Members (1–8 bots), the lead (optional; otherwise the first bot mentioned, else the first member), the
group's shared folder, and **Fast Mode**. New groups start with Fast Mode on. Use the group settings form or the
⚡ chip in the title bar to change it for the next message. See the `collaboration` topic.

## Provider and keys (Settings → Model → Provider and keys, or `pland setup`)
`PLAND_PROVIDER` = `deepseek` (default) or `hkgai`; `DEEPSEEK_API_KEY`, optional `DEEPSEEK_BASE_URL` /
`DEEPSEEK_MODEL`; `HKGAI_API_KEY`, `HKGAI_BASE_URL` (https) and `HKGAI_MODEL` (HKGAI has no built-in defaults).
"Save & test" checks a key with one tiny real call before storing it.

## Appearance (per browser, Settings → Appearance)
Interface language, light / dark / system theme, accent colour, text size, density, whether thinking blocks are
shown, sidebar and panel widths. These live in the browser only and do not affect agents.

## Agent settings
The table below is generated from the running code: field, allowed values, built-in default, and the value in
effect for you right now.
