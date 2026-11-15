# Changelog

## 0.3.0

- Plugin id is now `carlosiborra.motion` (namespaced, so it cannot clash with other `herdr-motion` plugins). Bind actions as `carlosiborra.motion.<action>`.

A redesign of how the plugin runs; effects themselves are unchanged.

- **Startup is one-shot.** `[[startup]]` runs `bin/herdr-motion --start`, which launches the worker detached (own session, output to `worker.log` in the plugin state directory) and returns at once. Previously the hook ran the daemon in the foreground.
- **New `--stop` and `--status`, and a `stop` action.** One worker per server through a lock in the state directory; a pid file records it.
- **Event-driven.** Removed the 20 ms layout polling and the 0.25 s session snapshot polling. The worker blocks on the event subscription with no idle timers. Trade-off: HerdR's event batching (about 100 ms) is now visible before a new pane's grow starts.
- **Lifecycle.** The worker exits when the event stream closes, on signals, and when the plugin is disabled or uninstalled (checked on events, at most every 5 s). No more minute-long reconnect loop.
- **Removed HerdR Layouts coupling** and the auto-layout feature (`follow_auto`): no imports from, or files read or created in, another plugin.
- **Move flash is opt-in** (`flash_moves`, default off), tracked in the state directory and cleared on worker start, `--stop` and exit, and given a time limit in HerdR.
- **Failed writes** now snap the split to its final ratio once before dropping the animation.
- **Paths.** Settings in `HERDR_PLUGIN_CONFIG_DIR`, runtime files in `HERDR_PLUGIN_STATE_DIR`, socket from `HERDR_SOCKET_PATH`, theme from HerdR's `config.toml` honoring `XDG_CONFIG_HOME`; the plugin id comes from `HERDR_PLUGIN_ID`.
- Manifest: version 0.3.0, description "Smooth split-ratio effects when panes open, close, and resize".
- Standalone repository with CI, license and contributor docs.

## 0.2.0

- Auto layouts that followed pane counts through HerdR Layouts, and a focused-tab watcher that polled for splits and closes.

## 0.1.0

- First release: grow-on-open and rebalance-on-close split-ratio animations, move flash, eight styles, and the settings picker popup.
