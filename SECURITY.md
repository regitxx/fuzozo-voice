# Privacy and reporting

Do not commit `config.json`, `.env*`, device enrollment, raw logs, firmware,
recordings or model caches. The ignore rules exclude these. Device logs may
contain Wi-Fi or vendor authentication data even when a command seems harmless.
Share minimal redacted error messages, firmware version and reproduction steps.

The panel binds only to 127.0.0.1, verifies Host/Origin and requires a per-process
request token. Do not expose it with port forwarding or a public tunnel. API
keys stay in server-side environment variables. This is experimental device
control code, not a hardened multi-user service.

Use GitHub's private vulnerability reporting for sensitive security reports;
use ordinary issues for redacted non-sensitive bugs. Never post secrets in an
issue. Test only devices and services you own or are authorized to investigate.
