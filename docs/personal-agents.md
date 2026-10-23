# Personal Agent integration

TimeMate is the visual workspace; external Agents submit/search mail and read item state. Existing mailbox and AI settings are unchanged.

## Connection paths

- Dot: remote MCP at `https://timemate.cc/mcp`, OAuth authorization code with PKCE S256 and dynamic client registration. Plugin manifests are in `integrations/timemate/`. Dot MCP Events subscribes to `timemate.changed` and provides a verified signed callback. Public plugin listing requires a separate submission/review; this repository is not proof of listing or a live paired account.
- Grok Bot: per-user bearer credential in the Agent's secure connection settings. Create a webhook Routine in Grok Bot; paste its official `api2.cursor.sh/automations/webhook/` URL and key in TimeMate. Save does not execute it. Sending a test starts a real Routine and spends the user's Agent usage. Replacing the target removes the old subscription and requires a new test.
- Muse: custom connector pilot only. No verified outbound wake-up mechanism; do not advertise real-time two-way support.

## Data and permissions

Default scopes: `mail:read mail:write items:read changes:read`. `items:write` is opt-in. Every call resolves the authorized user's existing separate database. No mailbox credentials or model keys are exposed. Imported mail uses a stable external ID for deduplication. Proposed items remain candidates until the user adds them. Item changes use a version check against concurrent edits.

Personal grants expire after 90 days. OAuth access tokens last one hour; refresh tokens rotate; the grant still requires reauthorization after 90 days. Credentials are hashed, callback signing secrets encrypted with the existing master key. Revocation removes tokens and subscriptions. Account deletion removes all related records.

## Delivery

Database schema 12 adds a transactional metadata journal for mail/item changes, including writes through existing UI routes. No historical events are backfilled. A separate worker checks every 10 seconds. Notifications contain IDs and operation metadata, not email bodies. Read current data through MCP after a notification. Persist pending payloads and reuse event IDs after restarts/retries; receivers must deduplicate. After eight failed attempts delivery pauses; the settings page permits retry. HTTP success means accepted, not finished. `acknowledge_feedback` records that the Agent says it read the change, not that it completed a downstream task.

MCP subscriptions expire within seven days and must be renewed. Public HTTPS callback addresses are checked against private/internal addresses, DNS is pinned for the actual connection, redirects are refused, and payloads use Standard Webhooks signatures. Journal entries stay with the user's data until account deletion; delivery receipts are retained for 30 days.

## Deployment and acceptance

No new environment variables: existing `MAIL_ORIGIN`, persistent data directory and encryption master key are reused. Run only the existing single-process cloud entrypoint; multiple notification workers are not supported. Take the normal database backup before migrations. Rolling back application code leaves the journal tables/triggers in place; do not downgrade schema numbers manually.

Tests: `python -m unittest discover -s tests`; `NODE_PATH=<node_modules> node tests/test_agents_browser.cjs`. Tests use temporary accounts, simulated providers/callbacks and a real local Flask HTTP server. They verify isolation, PKCE/replay, revoke, conflict protection, retry persistence, callback replacement and desktop/mobile flows. They do not prove an actual Dot/Grok/Muse account connection.

Production checks: confirm deployment commit, fetch OAuth metadata and guide, verify unauthenticated MCP returns 401, then complete one authorized live Agent connection. Import a disposable test email, change its state in TimeMate, observe the provider receive the event and the TimeMate acknowledgement state. Public listing and each user's final consent remain separate steps.

Official references:
- https://developers.openai.com/plugins/build/mcp-events
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/deploy/submission
- https://cursor.com/help/grok-bot/routines
