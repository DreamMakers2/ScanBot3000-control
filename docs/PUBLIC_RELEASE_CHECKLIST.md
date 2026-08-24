# Public Release Checklist

## Repository state

- [x] Canonical repository name and UI branding use `ScanBot3000-control` / `ScanBot3000 Control`.
- [x] Old `Davinci-Orbis-3000` clone paths and service branding removed from the retained tree.
- [x] Apache License 2.0 + Commons Clause 1.0, NOTICE, CONTRIBUTING, SECURITY, setup, requirements, architecture, API, troubleshooting, and prompting docs are present.
- [x] Vendored uPlot MIT license is included alongside the vendored assets.

## Privacy/security

- [x] `.env` and runtime `config/settings.json` remain ignored.
- [x] Sample configuration contains generic `/dev/serial0` and axis labels only.
- [x] Current-tree review found no committed passwords, credentials, API keys, real private-network host addresses, personal email addresses, or identifying developer home paths.
- [x] Generic RFC1918 address patterns in CORS code are retained because they define application behavior and are not real deployment identifiers.
- [x] Systemd configuration is a template with generic example path/account values and explicit edit instructions.

## History

- [x] Existing development history was reviewed before release.
- [x] Historical commit metadata contained personal/example author email identities and old project branding.
- [x] `main` is rewritten to one parentless `Initial public release` commit containing only the sanitized current tree.
- [x] No additional repository branches were present during the audit.
- [x] No tag namespace was returned by the available Git-ref check during the audit.

## Accuracy

- [x] Hardware baseline is documented as Raspberry Pi 4B 2 GB because that is the recorded deployment.
- [x] Exact Raspberry Pi OS/browser/storage minimums are marked unknown rather than invented.
- [x] Python dependency lower bounds are copied from `requirements.txt`.
- [x] API paths and UART defaults match current source/configuration.
- [x] Security docs state clearly that the service is unauthenticated and can command physical motion.

## Final operator review

Before changing visibility, review the rendered README, the unauthenticated-network warning, the systemd template values, and hardware wiring against the physical machine.
