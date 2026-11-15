# Security policy

## Supported versions

Only the latest release receives fixes.

## Scope

Herdr Motion is a local plugin. It connects only to Herdr's Unix socket, runs no network code, reads no pane contents, and writes its own settings and state files in the plugin config and state directories. Reports about those boundaries are in scope: path handling, signalling a process that is not the worker, files written outside those directories, or anything that reads pane output or input.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability"). Include the version, your platform and steps to reproduce. Expect an acknowledgement within a week.
