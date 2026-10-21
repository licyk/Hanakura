# Civitai Browser Sign-In and Authorization Without User Configuration

Prepared: 2026-10-21.

Status: M1–M3 implemented and covered offline. M0 ended here as **no candidate verified**; that outcome and the scope-5 gate are **superseded by `plan1.md`**: the user's live run showed ComfyNodes refusing `scope=5` and signing in with `scope=1`, after which a download worked, so the ComfyNodes profile is now enabled with a default scope of 1. Sections 4, 6 and 12 below keep the original requirement, the investigation and the failed probes as they were; read `plan1.md` for the current decisions and the live checks still pending.

## 1. Goals and scope

A user clicks **Sign in with Civitai** in Hanakura, signs in and grants consent on Civitai's website, and returns to Hanakura with the account connected. Hanakura then uses the authorization for model browsing, identification, and downloads. Ordinary users should not have to register an OAuth application, enter a client ID, or copy an API key.

First investigate and validate existing public-client implementations, especially the official `civitai-comfy-nodes` project. Do not assume users must register their own applications before evaluating these options. Equally, do not treat another client's successful sign-in as proof that Hanakura can use its identity to download every model requiring authentication.

The plan distinguishes two goals:

1. **No configuration for ordinary users:** the project supplies a working default client, and each user authorizes their own account. A Hanakura application registered once by its maintainer also meets this goal.
2. **No new application registration by the maintainer either:** reuse an existing public client. This depends on its permitted redirects, grants, scopes, and intended use, and must be validated first.

The first implementation stage delivers browser sign-in for the local Web UI. Later stages add device authorization for remote deployments and the CLI. Existing manual API tokens, custom OAuth clients, and host application settings remain supported.

The plan does not introduce a hosted relay, collect user passwords, read browser cookies, automatically request spending permissions, purchase models, or consume Buzz.

## 2. Existing implementation and research findings

### 2.1 Existing Hanakura capabilities

| File | Current responsibility | Planned treatment |
| --- | --- | --- |
| `hanakura/core/auth/oauth_client.py` | Authorization URLs, PKCE, code exchange, refresh, revocation, and user information | Reuse; add client selection, response validation, and device protocol support |
| `hanakura/core/auth/service.py` | Manual/OAuth selection, credential access, refresh locking, connection, and disconnection | Keep the single credential entry point; add transaction cancellation and configuration consistency checks |
| `hanakura/core/auth/transactions.py` | In-memory state, PKCE verifier, browser binding, expiry, and single consumption | Extend with flow type, client snapshot, and cancellation semantics |
| `hanakura/core/auth/store.py` | Credential persistence and cross-process locking | Retain secure storage; make credential ownership explicit |
| `hanakura/core/auth/models.py` | Shared API/CLI request, response, and status models | Add capabilities, flow state, and actionable errors |
| `hanakura/core/settings/models.py` | `oauth_client_id=None` and default `oauth_scope=5` | Add default-client resolution while retaining explicit overrides |
| `hanakura/api/routers/auth.py` | Start, callback, status, disconnect, and method endpoints | Extend flow selection, cancellation, and required callback adaptation |
| `hanakura/webui/src/components/CivitaiAuthPanel.vue` | Connection button, manual token, and custom client ID | Make sign-in the default action and collapse developer configuration |
| `hanakura/webui/src/api/queries/auth.ts` | Sign-in mutations and status queries | Add session tracking and polling cleanup |
| `hanakura/cli/commands/search.py` | `auth connect` currently mostly prints connection instructions | Later invoke an actual authorization flow |

Hanakura already implements Public client + PKCE authorization. The missing default client identity currently makes `oauth_configured` false and disables the connection button.

The existing API callback is `/api/v1/auth/civitai/callback`, with the public deployment prefix when embedded. Its browser-binding cookie is scoped to the authentication path. Replacing the client ID alone does not ensure either redirect matching or delivery of that cookie to another callback path.

### 2.2 Relevant existing projects

| Project | Behavior established from source | What this does not establish |
| --- | --- | --- |
| Civitai Comfy Nodes | Bundled public client ID; authorization code + PKCE; local `/civitai/callback` listener; token exchange and storage | Whether its client permits Hanakura's `scope=5`, is suitable for another application, or supports Hanakura's authenticated downloads |
| Civitai Link Desktop | Bundled `civitai-link-desktop`; opens the complete device verification URL and polls for tokens | Whether Link/Vault permissions can replace Hanakura's ordinary model API authorization |
| Civitai CLI | Bundled `civitai-cli`; device authorization and automatic refresh | Whether its default or maximum scope meets Hanakura's model-reading requirements |
| Hoshimi | Provider-specific bundled clients, dedicated login protocols, or dynamic identity flows | Whether those provider protocols can be transferred to Civitai |

The public candidate client ID in Comfy Nodes is `2d61872c-9aa9-4dbc-93c3-899c222842c1`. It is an application identifier, not a user token or client secret. It is listed here as a candidate to validate, not as an unconditional product default.

Comfy Nodes requests `UserRead | AIServicesRead | AIServicesWrite | BuzzRead` as its baseline, plus `LinkConnect` for its official client. This differs from Hanakura's `UserRead | ModelsRead = 5`. **Requested scopes are not a complete listing of a client's allowed scopes.** This source alone cannot prove that `scope=5` will either succeed or fail.

The Comfy Nodes README still contains text requiring `CIVITAI_OAUTH_CLIENT_ID`, while the current source provides a default. Use pinned source revisions and live validation, and record documentation discrepancies.

## 3. Stage zero: validate client reuse

Complete this stage before enabling a default sign-in entry point. Record results in this document; do not describe pending checks as implemented capabilities.

### 3.1 Evidence and validation environment

- Record the date, upstream commit, client name, authorization host, redirect rules, and requested scopes. Do not record account credentials.
- Use an isolated temporary data directory without overwriting existing Hanakura, Comfy Nodes, or Link credentials.
- Inspect the official authorization discovery document and the candidate's registration or configuration evidence in public source.
- The user completes actual sign-in on Civitai's website. Without that authorization, mark account-dependent checks as unverified; anonymous API success is not a substitute.
- Check upstream licenses before reusing code. Prefer implementing the protocol within Hanakura's existing modules instead of copying unrelated application logic.

### 3.2 Validation checklist

| Check | Method | Passing condition |
| --- | --- | --- |
| Client identity | Establish the candidate ID, consent-screen application name, and upstream purpose | Valid identity and clear applicability; users can identify the application they authorize |
| Minimum permissions | Request `scope=5`; inspect authorization responses and final token scope | UserRead and ModelsRead granted without depending on generation, spending, or administration privileges |
| Redirect rules | Check `/civitai/callback`, Hanakura's existing callback, loopback hostnames, and different ports | Explicitly document accepted and rejected combinations rather than infer them from overview documentation |
| Authorization code and PKCE | Complete browser authorization and token exchange; use mocks for invalid verifier cases | Tokens issued correctly; invalid verification cannot connect an account |
| HTTP requirements | Check form encoding, Origin, Accept, Host, and actual errors | Supported request format completes exchange and refresh without disabling Hanakura's local protections |
| Account identity | Call official userinfo or another applicable identity endpoint | Displayed account matches the account used for authorization |
| Model API | Read model information, identify by hash, and exercise applicable authenticated queries | The token is accepted through Hanakura's actual request path |
| Authenticated download | Download a model the user is already entitled to access | Confirm token use, retrieve the file, and verify the available checksum |
| Refresh and revocation | Refresh, access again, then disconnect and inspect local/remote results | Rotated credentials persist correctly; distinguish local removal from remote revocation |
| Device authorization | Independently verify the candidate's device grant support | Authorization and required API operations succeed; PKCE success does not establish device support |

Download validation must include a public file and a file the user may access but anonymous callers genuinely cannot download without signing in. Check the anonymous response as a control. Prefer small files. A Range request can validate access and partial transfer, but cannot replace full-file and checksum verification.

Do not automatically escalate to Full, generation, or Buzz-spending permissions when authorization fails. An anonymously downloadable model is not evidence of authenticated download support.

### 3.3 Decisions and exit conditions

1. **The candidate meets minimum scope, redirect, and applicability requirements:** adopt the validated Public client and retain its actual authorization application name; proceed with local Web UI implementation.
2. **It only supports sign-in or a subset of required operations:** record that it does not meet the complete goal. Do not present it as a usable model-download account connection.
3. **Existing clients are unsuitable:** report the specific failure. Registering one Hanakura Public client as maintainer is an alternative that still removes user configuration; it does not meet the separate goal of avoiding maintainer registration.
4. **No account or live validation is available:** offline design and mock validation may proceed, but default-client availability remains unverified. Do not declare the complete configuration-free flow finished.

Do not automatically register applications, contact upstream maintainers, or relabel another application's consent identity as Hanakura.

## 4. Client configuration and credential ownership

Add `hanakura/core/auth/clients.py` to describe validated client profiles: client ID, display name, supported flows, minimum permissions, callback strategy, and validation evidence. Populate capabilities only when confirmed.

Continue using `SettingsService` for host-pinned overrides, environment variables, and file precedence. Apply product defaults only after resolving those settings:

- An explicit `oauth_client_id` selects the user- or host-supplied custom client. Never silently replace it with a bundled client.
- With no explicit ID, select the validated bundled client. Report unavailability if no working default exists.
- Add `oauth_enabled: bool = True` as an explicit disable switch. Disabling prevents new authorizations without deleting credentials or switching accounts. When OAuth is selected but unavailable, report that condition rather than silently using anonymous access or another account.
- Keep the default `oauth_scope=5`. Explicit custom settings may request other scopes; product defaults must not broaden permissions.
- `oauth_configured` indicates whether an effective client can be resolved. Separate capability fields describe whether a particular flow can run in the current deployment.

Bind credentials to the issuing client ID and fixed authorization issuer, and store the same snapshot in each pending transaction. If configuration changes during authorization, cancel or reject completion; never exchange an old authorization code using a new client.

Refresh and revoke using the credential's issuing client. Changing clients must not send old tokens to the new client.

The existing credential record already includes a client ID. Verify that all relevant callers use it. For older records missing required ownership information, migrate only when the origin is unambiguous; otherwise request authorization again. Include configuration changes, disconnects, and login completion in the existing locking and version checks so older requests cannot overwrite newer user choices.

## 5. Local Web UI: authorization code + PKCE

### 5.1 Main flow

1. The frontend loads account status, the effective credential source, and supported sign-in methods.
2. Clicking sign-in calls the protected `POST /api/v1/auth/civitai/start` endpoint.
3. The backend stores state, verifier, client snapshot, redirect URI, browser binding, and expiry. The frontend receives only the authorization URL and expiry information.
4. The browser navigates to the fixed Civitai authorization host, which handles account sign-in and consent.
5. The callback verifies the transaction, browser binding, single consumption, deadline, and configuration version before exchanging the code and checking required scopes.
6. Switch to OAuth only after successful server-side credential storage. On failure, preserve the previous credentials and authentication selection.
7. Return to the original Hanakura settings page, display success or an actionable error, and refresh account and model-query caches.

Retain the existing five-minute transaction lifetime, PKCE S256, HttpOnly/SameSite=Lax binding cookie, and server-side credential storage. Codes, state, and verifiers are transient authorization data, never log entries, download-record fields, or persistent settings.

### 5.2 Callback adaptation

Prefer the existing API callback. If the chosen client only accepts `/civitai/callback`, add an exact GET alias for standalone local servers only after stage zero confirms flexible loopback port matching. Both routes call the same core completion method.

Address these requirements together:

- Use the successfully bound port, not an unbound configured port.
- Keep the initiating hostname compatible with the browser-binding cookie. `localhost` and `127.0.0.1` are not the same cookie host.
- If a canonical local hostname is needed, navigate there before creating the transaction and setting its cookie. Never include Hanakura's access token in the navigation URL.
- Keep the original cookie path for the original callback. A root-level alias requires a cookie path covering that alias and a distinct cookie name. Delete it with matching attributes and avoid collisions between instances.
- Exempt only the exact callback GET from application-token authentication. Continue checking Host, state, browser binding, and the transaction. Do not exempt all of `/civitai` or `/api`.
- Set `Cache-Control: no-store` and `Referrer-Policy: no-referrer`, then redirect to an application path without authorization parameters.
- Prevent local server, development proxy, and reverse-proxy access logs from recording callback query parameters. Normalize and redact upstream errors before logging or presenting them.

If the client requires fixed ports that cannot share the existing listener, do not substitute a temporary HTTPServer without browser binding. Mark that combination unsupported in the first stage and use an available device or custom-client route. Design a separate callback receiver only if a later requirement justifies it.

### 5.3 Embedding and path prefixes

Preserve `api_prefix`, ASGI mount, `root_path`, and trusted host-supplied `public_base_url` behavior. An embedded application must not install `/civitai/callback` at its host's root without host configuration.

Custom clients may retain the existing prefixed callback. If a bundled client's fixed root callback is incompatible with the deployment prefix, report why and prefer a validated device flow. Any new Vite proxy rule must forward the exact callback path rather than a broad prefix.

## 6. Remote deployments and CLI: device authorization

Device authorization handles browsers running on a different machine and deployments without a common registered callback. It still requires a valid client and an enabled device grant. Do not mistake the browser machine's localhost for the remote Hanakura server.

Add `hanakura/core/auth/device.py` with the following behavior:

- Request device authorization and retain `device_code` on the server. Return only the user-facing verification URI, user code, deadline, and a local session ID that contains no upstream credentials.
- Prefer `verification_uri_complete`; otherwise show the verification address and short code. Accept only the expected Civitai HTTPS verification host, not an arbitrary upstream-provided URL.
- Let a core-owned background task control upstream polling. The frontend queries local state only; page refreshes and extra tabs must not increase upstream request frequency.
- Honor the returned `interval`. Wait on `authorization_pending`; back off on HTTP 429 according to the current official protocol, and handle compatible `slow_down` responses as well.
- Bound retries for network errors and 5xx responses by the original device deadline. Denial, expiry, or cancellation enters a terminal state immediately.
- Reuse the scope validation, account lookup, and credential commit logic on success.
- Never persist a late success after cancellation, disconnect, restart, or relevant configuration changes.
- Bound concurrent sessions per data directory and stop tasks when services close. Do not persist pending transactions; restart requires a fresh authorization.

Use transaction states such as `pending / exchanging / connected / denied / expired / cancelled / failed`, separate from long-lived account connection state. One tab's failure must not overwrite another session's completed account connection.

Later extend `hanakura auth connect` with `--flow auto|browser|device`, `--no-open`, and `--json`:

- `auto` selects from confirmed capabilities. The first CLI implementation prefers device authorization instead of starting the entire Web UI for one command.
- Reusing a running Web UI for browser authorization requires its normal authentication. Reject `--flow browser` clearly if no usable callback is available.
- If opening a browser fails, display the authorization address. Ctrl+C cancels the transaction and prevents late credential writes.
- JSON output uses the core models and never includes access tokens, refresh tokens, device codes, or verifiers. Login links and user codes deliberately shown for interaction must not also become diagnostic log records.
- Register command names and help in `cli/app.py`, keep command functions thin, and update command-tree and help tests for new options.

## 7. API and Web UI changes

### 7.1 API contract

Keep the existing status, start, callback, disconnect, and method routes. Add capability and session data through explicit models.

| Endpoint/model | Proposed change |
| --- | --- |
| `CivitaiAuthStatus` | Supported flows, deployment-specific unavailability reason, bundled/custom client source, and actual consent application name; no credentials |
| `StartRequest` | Optional `flow`, defaulting to `auto`, while retaining `return_to` |
| `AuthStart` | Retain authorization URL and expiry fields; add optional flow, session ID, and device-prompt fields while preserving the existing browser response |
| `GET /api/v1/auth/civitai/sessions/{id}` | Read a login session owned by the initiating caller; never trigger upstream polling |
| `POST /api/v1/auth/civitai/sessions/{id}/cancel` | Cancel that session with idempotent handling |

Session reads and cancellation require application authentication and verification of the initiating browser binding. A session ID alone is not permission to inspect or cancel it. Device start must establish binding too, so arbitrary local web pages cannot inspect authorization or induce an unintended account connection.

Routes only parse requests, call core methods, and translate errors. New models inherit `Record` and preserve Pydantic v1/v2 behavior. Regenerate `hanakura/webui/src/api/schema.d.ts` under Pydantic v2 after API output changes.

### 7.2 UI behavior

- Show **Sign in with Civitai** as the primary action without first requiring a client ID.
- Collapse custom client ID, callback, and flow controls into advanced configuration. Keep manual API tokens as a separate option.
- Prefer same-tab browser navigation to retain the current binding and restore settings on return. If a new window is used, handle popup blocking and offer a clickable link.
- For device authorization, show waiting status, the short code when needed, an open-website action, cancel, and remaining time. Stop polling after success, failure, expiry, or cancellation.
- Show connected state only after code exchange, required-scope validation, and credential commit. Display the account and effective credential source.
- When an environment variable or host-pinned configuration takes precedence, show that override and disable ineffective controls. Do not imply that a newly authorized account now controls downloads if an override still wins.
- Distinguish insufficient permissions, redirect mismatch, unavailable client, network failure, denial, and expiry. Do not translate every failure into an API-key prompt.
- Do not automatically open an application-registration page or switch authentication methods after denial or failure.
- Update English and Chinese translations and follow the existing UI wrappers, theme tokens, and compact layout conventions.

## 8. Credentials and download behavior

All source requests and downloads continue obtaining credentials through `CivitaiAuthService`. Do not introduce a second token source in frontend components or download records.

- Send `Authorization: Bearer`, never tokens in query parameters.
- The editable model-source base URL must neither change the OAuth issuer nor receive credentials on an arbitrary host.
- Remove authorization headers when redirects leave the Civitai source host. Preserve signed download URLs, resume handling, and SHA256 verification.
- A 401 may trigger at most one renewal and retry. Do not hide 403 responses, missing permissions, or unavailable model entitlements behind repeated refresh attempts.
- Persist access and refresh tokens together, using the existing thread and process locks to protect rotation.
- Disconnect first removes local credentials and cancels pending authorization. Report remote revocation failures separately rather than claiming revocation succeeded.
- Preserve manual tokens. OAuth disconnect, expiry, or network failure must not automatically select a token that might belong to another account.
- Reject new connections whose token response lacks required granted scopes. Do not fill an absent or ambiguous granted scope with the requested value and present it as authorization; follow the protocol validated in stage zero.

## 9. Expected file changes

| Area | Expected files |
| --- | --- |
| Client and core flows | New `hanakura/core/auth/clients.py` and `device.py`; changes to `oauth_client.py`, `service.py`, `transactions.py`, `models.py`, and `store.py` where needed |
| Configuration and lifecycle | `hanakura/core/settings/models.py`, settings output/update mappings, `hanakura/core/context.py`, and actual service-shutdown entry points |
| API and path security | `hanakura/api/routers/auth.py`, `hanakura/api/security.py`, application route registration, and path helpers |
| CLI | `hanakura/cli/app.py` and `hanakura/cli/commands/search.py` |
| Web UI | `CivitaiAuthPanel.vue`, `api/queries/auth.ts`, session components if needed, `i18n/en.ts`, `i18n/zh-CN.ts`, and `api/schema.d.ts` |
| Deployment and development | Exact callback proxy in `hanakura/webui/vite.config.ts` if needed; retain host-prefix behavior |
| Documentation | README authentication guidance, OAuth/known-gap notes in `AGENTS.md`, and validation results in this plan |

This is an implementation map, not a requirement to create empty modules or modify unrelated files. `webui/src/stores/auth.ts` and the general `AuthDialog.vue` manage access to Hanakura itself and must not be repurposed as Civitai account state.

## 10. Testing and acceptance

### 10.1 Offline automated coverage

| Layer | Required behavior |
| --- | --- |
| Client resolution | Bundled/custom/disabled precedence; minimum scopes; matching issuance and refresh clients |
| Authorization transactions | PKCE, state, browser binding, expiry, replay, cancellation, configuration changes, late callbacks, concurrent sign-in, and disconnect races |
| Device authorization | Pending, denial, expiry, 429, slow_down, network recovery, missing fields, invalid verification URLs, and no writes after cancellation |
| Credential storage | Old-record compatibility, rotation, thread/process locking, no restoration after disconnect, file permissions, and environment overrides |
| API | Start/status/cancel authorization, session ownership, exact GET callback exemptions, Host/Origin protection, and no credential disclosure |
| Callback deployment | localhost/127.0.0.1, actual bound port, cookie paths, URL cleanup, API prefixes, ASGI mounts, and trusted public_base_url |
| CLI | Actual connect branches, no-open, redacted JSON, cancellation, failure exit codes, command registration, and lightweight imports |
| Web UI | Button availability, waiting/cancel/expiry, polling cleanup, override state, errors, and translation consistency |
| Downloads | Credentials only to the source host, redirect stripping, one 401 retry, no 403 loop, and no manual-token regressions |

Prefer extending `tests/core/test_auth.py`, `tests/core/test_settings.py`, `tests/api/test_api.py`, `tests/api/test_mount.py`, `tests/api/test_embed.py`, and `tests/cli/test_cli.py`. Use controlled clocks and MockTransport for device polling so ordinary tests neither wait in real time nor call Civitai.

Add focused frontend interaction tests rather than assertions that merely repeat implementation details. Mark live validation as `live`; default CI must not use accounts or contact upstream services.

### 10.2 Checks after implementation

Run in the project development environment:

```bash
python scripts/dev.py typegen
python scripts/dev.py check
git diff --check
```

In the current workspace, use `/root/micromamba/envs/py311/bin/python` in place of `python`; use bun for the Web UI. Generate types and run the full check under Pydantic v2. Also validate Python 3.10 and the compatible Pydantic v1/FastAPI environment through the existing CI matrix. Do not bypass failures by upgrading unrelated dependencies or weakening checks.

### 10.3 Live acceptance matrix

- With a fresh data directory, no manual token, and no user-entered client ID, complete website authorization, display the account, and exercise the required model API and authenticated download.
- Sign-in works with the actual bound port when the default port is occupied, or reports a specific unsupported-port condition.
- Both an existing Civitai website session and a browser that must sign in first can complete authorization.
- Denial, page closure, timeout, cancellation, restart, and refresh failure neither replace the old account nor restore disconnected authorization.
- Remote Web UI authorization succeeds through device flow or is explicitly listed as unsupported. Local success does not establish remote support.
- Prefixed and host-mounted configurations remain functional; unsupported combinations receive deployment-specific explanations.
- Credentials survive a restart, and refresh/disconnect behavior matches the UI.
- Logs, API JSON, browser storage, and the download database contain no access/refresh tokens, verifiers, or device codes. Authorization URLs and callbacks remain confined to the necessary short-lived browser flow.

## 11. Implementation order and milestones

| Milestone | Work | Completion condition |
| --- | --- | --- |
| M0 | Pin upstream revisions; validate candidate identity, scopes, callbacks, and real downloads | Record evidence and classify reuse as viable, failed, or unverified; select the default identity |
| M1 | Client resolution, configuration precedence, transactions, and credential ownership | Core offline tests pass; existing manual/custom OAuth behavior remains supported |
| M2 | Local Web UI sign-in, required callback adaptation, state, and errors | A fresh local installation completes website authorization and authenticated download without user configuration |
| M3 | Device flow, cancellation, session ownership, CLI, and remote deployments | Supported combinations complete authorization; unavailable capabilities are not misleadingly offered |
| M4 | Type generation, compatibility checks, documentation, and end-to-end acceptance | Full check passes; live evidence and limitations are documented |

Until M0 passes, independent core design and offline testing may proceed, but an unverified default ID must not be enabled. Maintainer registration is an optional alternative, not an automatic replacement for the original goal.

Each milestone produces reviewable changes and validation results. Commits, pushes, version bumps, and publication are outside the default scope of this plan.

## 12. Implementation results

| Item | Result |
| --- | --- |
| Validation date and upstream commits | 2026-10-21. civitai/civitai `50edece`, civitai-comfy-nodes `1bcb195`, civitai-link-desktop `9f39a5d`; production discovery at `https://auth.civitai.com/.well-known/openid-configuration` |
| Selected client identity and actual consent-screen name | **None selected.** Candidate kept, unverified: `2d61872c-9aa9-4dbc-93c3-899c222842c1`, named "Civitai ComfyNodes" in its source; the consent screen was not seen |
| Existing client reused / new application registered by maintainer | Neither. No client was registered, and none was relabelled as Hanakura |
| Requested scope / actual granted scope | Requested `5`. Granted: not observed (no signed-in account was used) |
| Supported redirect hosts, paths, and port rules | Source only (`redirect-uri.ts`): exact match, except a loopback redirect (`localhost`, `127.0.0.1`, `::1`) matches a registered loopback one on any port and any of those names with the same scheme and path. ComfyNodes registers `/civitai/callback`, so Hanakura's `/api/v1/auth/civitai/callback` cannot match it. Production behaviour not observed |
| Local, remote, embedded, and CLI coverage | Implemented and tested offline: browser sign-in on local servers (custom client at Hanakura's callback; a bundled client at `/civitai/callback` on a root-owning loopback server only), device sign-in for remote browsers and `hanakura auth connect`, prefixed, mounted and `public_base_url` deployments. Live: none |
| Identity lookup and authenticated download | Not verified live |
| Refresh, cancellation, disconnection, and revocation | Offline only. Civitai documents revoke as always answering 200, so disconnect reports a failure but never claims success as proof |
| Offline checks / live verification / skipped work | Offline: the final `dev.py check` passes, including lint, Python and Vue type checks, 336 Python tests, 204 frontend tests, and `typegen-check` against the staged schema. Regression coverage includes the initial device verification URL, failed cancellation requests, and shared callback cookies across pending sign-ins. Pydantic v1 + FastAPI 0.125 on Python 3.10: pytest and ty passed during implementation. Live: the probes below only. Skipped: every account-dependent check in 3.2 |
| Remaining limitations and alternatives | See 12.2 |

### 12.1 Live probes (anonymous, 2026-10-21)

`POST https://auth.civitai.com/api/auth/oauth/device` with `client_id` and `scope`, which reveals each client's device grant and permission ceiling without an account (a successful answer only creates a code that expires unused after 15 minutes; codes were not recorded):

| Client | `scope=5` | `scope=1` | Reading |
| --- | --- | --- | --- |
| `2d61872c-…` (ComfyNodes) | 400 `unauthorized_client` | 400 `unauthorized_client` | No device grant. Browser flow only; its ceiling for ModelsRead is unknown |
| `civitai-link-desktop` | 400 `invalid_scope` ("exceeds client permissions") | 200 | Device grant, but ModelsRead is above its ceiling: **fails** minimum permissions |
| `civitai-cli` | 400 `invalid_scope` | 200 | Same: **fails** minimum permissions |

The authorization endpoint redirects an anonymous browser to `/login` before validating the client, redirect or scope, so the ComfyNodes checks need a signed-in account. From source: the authorize handler also enforces a per-client access mode ("disabled" or "testers" only) for third-party clients, and the comment names the Comfy app as such a client; whether it is open to everyone is part of what must be checked.

Also established from source: the download route (`/api/download/models/[id]`) and the public v1 REST routes accept an OAuth bearer as the user's session without checking its scope bits, while tRPC procedures require theirs. A `UserRead`-only token might therefore download today, but Hanakura keeps requiring ModelsRead: relying on an unenforced scope is not a supported integration, and it can change without notice.

### 12.2 To finish M0 and M2

Superseded: step 1 was run by the user with the outcome `plan1.md` §2 records (`scope=5` refused with `invalid_scope`, `scope=1` signed in, a download succeeded), and `plan1.md` replaced step 2's scope-5 condition. The steps are kept as written.

1. With a Civitai account, open an authorization for the ComfyNodes client with `scope=5`, `redirect_uri=http://127.0.0.1:<any port>/civitai/callback`, PKCE S256, and note: the consent screen's application name and listed permissions, whether `invalid_scope` or `access_denied` (access mode) comes back, and the token response's `scope`. Then download one file that needs an account and verify its SHA256.
2. If everything passes, set `verified=True` on that profile in `hanakura/core/auth/clients.py`, record the evidence here, and update AGENTS.md §15. Nothing else needs to change: the root callback, its cookie, the deployment checks and the interface already follow the profile.
3. If it fails, the remaining route to "no configuration for users" is a Hanakura public client registered once by the maintainer, with Hanakura's own callback and the device grant; that is a maintainer decision this work did not take.

## 13. References

The following commits were retrieved from the GitHub API while preparing this plan. Deployment status, client permissions, and production database configuration still require live verification; repository source is not evidence of production results.

- [Civitai Comfy Nodes authorization implementation, pinned revision](https://github.com/civitai/civitai-comfy-nodes/blob/1bcb19524567b1c821b8e24a92e198a6e3c0858f/civitai_comfy_nodes/oauth.py): public client, PKCE, loopback callback, token persistence, and refresh.
- [Comfy Nodes README](https://github.com/civitai/civitai-comfy-nodes/blob/1bcb19524567b1c821b8e24a92e198a6e3c0858f/README.md): connection entry point and Link behavior; some authentication wording differs from the implementation.
- [Link Desktop device flow](https://github.com/civitai/civitai-link-desktop/blob/9f39a5de406a549a7178c671fc45d1d950cdfd5c/src/main/oauth/device-flow.ts) and [client constants](https://github.com/civitai/civitai-link-desktop/blob/9f39a5de406a549a7178c671fc45d1d950cdfd5c/src/main/oauth/constants.ts): browser consent and background polling.
- [Civitai OAuth developer guide](https://github.com/civitai/civitai/blob/50edeced265cd63e99e488204032813a36a7e225/docs/auth/oauth-developer-docs.md): registration, authorization code, device flow, scopes, and revocation.
- [Civitai redirect matching](https://github.com/civitai/civitai/blob/50edeced265cd63e99e488204032813a36a7e225/apps/auth/src/lib/server/oauth/redirect-uri.ts): source includes flexible loopback port matching; verify production behavior separately.
- [Civitai device authorization endpoint](https://github.com/civitai/civitai/blob/50edeced265cd63e99e488204032813a36a7e225/apps/auth/src/routes/api/auth/oauth/device/%2Bserver.ts): client, grant, and scope validation.
- [Official Civitai CLI OAuth implementation](https://github.com/civitai/cli/blob/main/internal/appapi/oauth.go): comparison for bundled identity and form/Origin handling; pin the revision actually used during implementation.
- [Production OIDC discovery](https://auth.civitai.com/.well-known/openid-configuration): verify issuer and endpoints; do not infer anonymous dynamic registration support from discovery alone.

Hoshimi is only an interaction and state-management reference. The required decisions, constraints, and file locations are recorded here so implementation does not depend on another workspace or prior conversation.
