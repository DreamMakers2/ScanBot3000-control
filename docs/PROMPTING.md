# AI / Agent Prompting

## API/code review

```text
Review this ScanBot3000-control change against the actual FastAPI routes, settings model, UART behavior, and firmware command contract. Identify security, validation, serial, CORS, and physical-motion implications. Do not invent authentication, hardware guarantees, or API behavior not present in code.
```

## Public-data audit

```text
Audit this control-server diff for public release. Flag secrets, tokens, real private IPs/hostnames, MAC addresses, personal paths/usernames, .env values, settings.json, logs, serial numbers, or internal service names. Keep obvious placeholders and generic RFC1918 regex patterns when they are part of code behavior.
```

## Documentation

```text
Update setup/requirements/API documentation using only repository evidence. Separate the verified Raspberry Pi 4B 2 GB deployment from unverified minimums or alternate SBCs. Preserve exact endpoint paths, payload validation, UART parameters, and security limitations.
```

Redact private infrastructure and credentials before sending logs or configuration to any AI system.
