# Contributing to ScanBot3000 Control

Contributions that improve reliability, API correctness, portability, documentation, UI clarity, or safety are welcome.

## Development workflow

1. Create a clean Python virtual environment and install `requirements.txt`.
2. Keep changes compatible with the documented Teensy console protocol.
3. Exercise affected REST/WebSocket paths with the UART disconnected where possible, then validate hardware-dependent changes on the real stack when available.
4. Update `docs/API.md` when request/response behavior changes.
5. Keep firmware and kinematics documentation synchronized when shared contracts change.

## Public-data rules

Do not commit `.env`, `config/settings.json`, credentials, tokens, private URLs, real private-network addresses, hostnames, MAC addresses, Wi-Fi details, serial numbers, personal data, identifying filesystem paths, runtime logs, or virtual environments. Use placeholders such as `<host>` and generic device paths in examples.

## Pull-request checklist

- [ ] Service starts in a clean virtual environment.
- [ ] Affected API/WebSocket behavior is documented.
- [ ] Motion-command validation remains consistent with firmware behavior.
- [ ] No local configuration, credentials, logs, or identifying environment data is included.
- [ ] Vendored third-party license notices remain present.
