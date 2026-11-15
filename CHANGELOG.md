# Changelog

## 0.3.2

- Naming: the product is written "Herdr" everywhere (README, docs, manifest name, user-facing strings), and the command stays `herdr`.
- Vendored helpers: HerdR → Herdr spelling only (`theme.py` hash updated in `tests/test_vendored.py`; `terminal.py` unchanged).
- README rewritten with a tagline, short feature list, install steps and project page link.
- Idle claim made precise: event-driven, no polling or timers while idle. Measured on Herdr 0.9.5 (macOS): the idle worker showed 0.0% CPU and 0.08 s total CPU time after a split and several idle seconds.

## 0.3.1

- New `start` action (`carlosiborra.motion.start`): starts the worker after an install or update without restarting the Herdr server. It is a no-op when a worker already serves the session.
- Added a demo GIF (`docs/demo.gif`) and README badges.
- Added bug report and feature request issue templates.
- Added `tests/test_vendored.py`, a sha256 drift guard for the vendored `theme.py` and `terminal.py`, documented in CONTRIBUTING.

## 0.3.0

- Plugin id is now `carlosiborra.motion` (namespaced, so it cannot clash with other `herdr-motion` plugins). Bind actions as `carlosiborra.motion.<action>`.

A redesign of how the plugin runs; effects themselves are unchanged.

- **Startup is one-shot.** `[[startup]]` runs `bin/herdr-motion --start`, which launches the worker detached (own session, output to `worker.log` in the plugin state directory) and returns at once. Previously the hook ran the daemon in the foreground.
- **New `--stop` and `--status`, and a `stop` action.** One worker per server through a lock in the state directory; a pid file records it.
- **Event-driven.** Removed the 20 ms layout polling and the 0.25 s session snapshot polling. The worker blocks on the event subscription with no idle timers. Trade-off: Herdr's event batching (about 100 ms) is now visible before a new pane's grow starts.
- **Lifecycle.** The worker exits when the event stream closes, on signals, and when the plugin is disabled or uninstalled (checked on events, at most every 5 s). No more minute-long reconnect loop.
- **Removed Herdr Layouts coupling** and the auto-layout feature (`follow_auto`): no imports from, or files read or created in, another plugin.
- **Move flash is opt-in** (`flash_moves`, default off), tracked in the state directory and cleared on worker start, `--stop` and exit, and given a time limit in Herdr.
- **Failed writes** now snap the split to its final ratio once before dropping the animation.
- **Paths.** Settings in `HERDR_PLUGIN_CONFIG_DIR`, runtime files in `HERDR_PLUGIN_STATE_DIR`, socket from `HERDR_SOCKET_PATH`, theme from Herdr's `config.toml` honoring `XDG_CONFIG_HOME`; the plugin id comes from `HERDR_PLUGIN_ID`.
- Manifest: version 0.3.0, description "Smooth split-ratio effects when panes open, close, and resize".
- Standalone repository with CI, license and contributor docs.

## 0.2.0

- Auto layouts that followed pane counts through Herdr Layouts, and a focused-tab watcher that polled for splits and closes.

## 0.1.0

- First release: grow-on-open and rebalance-on-close split-ratio animations, move flash, eight styles, and the settings picker popup.
