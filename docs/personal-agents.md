# Personal Agent integration

TimeMate is the visual workspace; external Agents submit/search mail and read item state. Existing mailbox and AI settings are unchanged.

## Connection paths

- Dot: remote MCP at `https://timemate.cc/mcp`, OAuth authorization code with PKCE S256 and dynamic client registration. Plugin manifests are in `integrations/timemate/`. Dot MCP Events subscribes to `timemate.changed` and provides a verified signed callback. Public plugin listing requires a separate submission/review; this repository is not proof of listing or a live paired account.
- Grok Bot: per-user bearer credential. Ask the Bot in chat to add the MCP endpoint; do not direct users to an unverified settings form. Enter the credential only through a secure prompt. Provider support is documented, but a live TimeMate pairing still needs verification. Create a webhook Routine in Grok Bot; paste its official `api2.cursor.sh/automations/webhook/` URL and key in TimeMate. Save does not execute it. Sending a test starts a real Routine and spends the user's Agent usage. Replacing the target removes the old subscription and requires a new test.
- Muse: ask Muse in chat to build a custom connector; this is a pilot, not an end-to-end verified TimeMate connection. No verified outbound wake-up mechanism; do not advertise real-time two-way support.

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

- https://forum.cursor.com/t/grokbot-custom-connectors/169965/5
- https://www.meta.com/help/superintelligence/1687253048996149/

## Grok Bot OAuth compatibility investigation (2026-10-24)

The production dynamic-registration endpoint rejected Grok Bot's callback set with HTTP 400 `invalid_client_metadata`. Its registration includes `cursor://anysphere.cursor-mcp/oauth/callback`, the Cursor cloud HTTPS callback, and an HTTP loopback callback. The previous validator required HTTPS for every entry, rejecting the entire registration before any consent page could open. The fix accepts only the documented Cursor native callback plus literal localhost/127.0.0.1/::1 loopback addresses; every authorization and exchange still requires the exact registered URI and PKCE S256. Public non-loopback HTTP redirects and other custom schemes remain rejected. A production probe changed from 400 to 201 after deployment. An independent Grok Bot OAuth setup then opened the actual TimeMate consent page using the Cursor HTTPS cloud callback, S256 and the correct resource parameter. Final consent/token exchange remains pending the user’s approval; do not advertise it as a completed OAuth account connection. A temporary connector named “TimeMate OAuth 检查” was created without changing the existing Bearer connection or Routine. The Grok client was updated using its downloaded official 0.75.5 update while investigating an intermittent marketplace/card-loading error.

Public Grok Bot documentation explains chat-created Routines and copying their Webhook URL/key. No supported third-party installation API returning these credentials was found. Internal Bot `UpdateRoutine` is not a public developer API and does not return the key. Do not use private Cursor endpoints or claim one-click reverse setup. Keep the user's existing Bearer connection and active Routine while investigating OAuth independently.

The shared guide dialog displays one figure at a time, with previous/next controls, page count, keyboard arrows, mobile swipes and image zoom links. Grok Bot notification guide images originate from the desktop UI, retained as complete application-window screenshots with numbered arrows, chat/account details masked and the URL redacted. A test notification is not sent automatically: it consumes Bot usage. A successful HTTP delivery does not by itself establish a Bot acknowledgement or a user-visible chat message.

References:
- https://forum.cursor.com/t/grok-bot-custom-mcp-oauth-fails-before-sign-in-redirect-uri-not-allowed/171877
- https://cursor.com/help/grok-bot/routines
- https://forum.cursor.com/t/support-passing-parameters-through-grok-bot-deep-links/174986
