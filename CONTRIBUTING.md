# Contributing

Thanks for helping. This is a small, standard-library-only Python plugin for [Herdr](https://herdr.dev) 0.9.5 or newer.

## Setup

```sh
git clone https://github.com/carlosiborra/herdr-motion
cd herdr-motion
python3 -m unittest discover -s tests -t .
```

Python 3.9 is the minimum supported version, so avoid newer syntax and standard-library APIs. CI runs the tests on Ubuntu and macOS with Python 3.9 and 3.13.

## Layout

- `bin/herdr-motion`: entry point.
- `src/herdr_motion/app.py`: command line and the worker process.
- `src/herdr_motion/lifecycle.py`, `paths.py`: detached start, stop, locks, and path resolution.
- `src/herdr_motion/daemon.py`: the event loop. It must block without a timeout when nothing animates.
- `src/herdr_motion/engine.py`, `tree.py`, `styles.py`, `config.py`: pure effect logic and settings.
- `src/herdr_motion/picker.py`: the settings popup.
- `src/herdr_motion/theme.py`, `terminal.py`: vendored, self-contained helpers (Herdr theme palettes, terminal handling). They are copied here deliberately so the plugin has no dependency on any other plugin; change them here.
  `tests/test_vendored.py` pins their sha256; if you change one on purpose, update the hash there and add a `CHANGELOG.md` note, otherwise the test fails.

## Guidelines

- Write `herdr` for the command and Herdr for the product; never HerdR.
- No third-party dependencies and no network access.
- Keep the worker event-driven: no polling loops, no idle timers.
- Never read pane output; keep socket use to the methods listed in the README.
- Add or update tests with fakes (see `tests/test_daemon.py`, `tests/test_lifecycle.py`) for any behaviour change, including the failure case.
- Never run a real Herdr session from tests.
- Note user-visible changes in `CHANGELOG.md`.

## Pull requests

Keep them focused, make sure `python3 -m unittest discover -s tests -t .` passes, and describe what you tried in a real Herdr session if the change affects runtime behaviour.
