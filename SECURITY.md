# Security Policy

## Security model

ScanBot3000 Control is a local hardware-control bridge. It does not implement user accounts, API keys, or authentication. REST and WebSocket clients can send commands that reach the Teensy motion controller.

The built-in CORS allowlist covers localhost and common RFC1918 private-address ranges. CORS limits browser origins; it does **not** authenticate a caller and must not be treated as a security boundary.

## Deployment guidance

- Keep the service on a trusted, segmented local network.
- Do not expose port 8001 (or the optional 8000 redirect) directly to the public internet.
- Use an authenticated VPN or reverse proxy/access gateway for remote access.
- Give the service account only the serial-device permissions it needs.
- Keep `.env` and `config/settings.json` local and untracked.
- Maintain independent physical emergency-stop provisions where required by the machine risk assessment.

## Reporting a vulnerability

Use GitHub private vulnerability reporting/Security Advisories when available. Otherwise contact the repository owner through GitHub without publishing exploit details or private infrastructure in an issue.

Redact tokens, private addresses, hostnames, serial numbers, personal data, and identifying paths from logs before sharing them.
