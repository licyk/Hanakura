# Enable Default Civitai Browser Sign-In with UserRead

Prepared: 2026-10-21.

Status: implementation plan only. This document does not change runtime behavior. It revises the scope and default-client decisions in `plan.md` in light of the user's real-machine test results.

## 1. Objective

Make a fresh, local Hanakura installation support this flow without requiring the user to register an OAuth application or enter a client ID:

1. Open Settings and click **Sign in with Civitai**.
2. Sign in and authorize on Civitai's website.
3. Return to Hanakura with the account connected.
4. Use the resulting OAuth credential for supported model downloads.

Use the bundled Civitai ComfyNodes public client with `scope=1` (`UserRead`). Retain custom OAuth clients, explicit scope settings, manual API tokens, browser binding, PKCE, credential ownership, and cancellation behavior.

This change enables local browser authorization. It does not enable device authorization for the bundled client or guarantee that every restricted model can be downloaded.

## 2. Evidence and its limits

The user reported the following results after running the temporary local test launcher supplied in this conversation:

| Test | Reported result | Interpretation |
| --- | --- | --- |
| ComfyNodes client with `scope=5` | `invalid_scope`, with `Invalid scope: Requested scope is invalid` | The requested combination was rejected in this test |
| Same test with `scope=1` | Login succeeded | Browser authorization and the return flow work with UserRead |
| Model download after login | Download succeeded | The tested download path worked with this configuration |

These are user-reported live results, not an independently repeated test by the implementation agent. The model identifier, whether it required authentication, and whether another credential overrode OAuth were not supplied. Do not invent those details or describe the result as exhaustive authenticated-download verification.

The evidence supports enabling the tested browser sign-in configuration. It does not establish that the token has `ModelsRead`, that all model endpoints accept it, or that Civitai guarantees this behavior indefinitely. Refresh, restart recovery, revocation, and the production credential-store path still need live acceptance checks.

The earlier requirement to obtain `UserRead | ModelsRead` before accepting any login is superseded for this bundled sign-in path. Keep the distinction between a successful account connection, the permissions actually granted, and the outcome of a particular API request.

## 3. Configuration decisions

### 3.1 New installations

In `hanakura/core/settings/models.py`:

- Change `DEFAULT_OAUTH_SCOPE` from `5` to `1`.
- Replace the comment claiming that scope 5 is the universal minimum for browsing and downloading with a description of UserRead as the sign-in baseline.
- Keep `oauth_scope` as a configurable positive integer.
- Keep `oauth_client_id=None`, `oauth_enabled=True`, and the existing authorization-service URL.
- Update the client-ID comment to describe the enabled bundled client rather than a future verified candidate.

Both bundled and custom clients continue to use the effective `config.oauth_scope`. A new custom-client configuration therefore also defaults to 1; users needing additional permissions must request them explicitly.

### 3.2 Existing installations

Changing a model default does not replace a value already saved in `settings.toml`.

- Preserve existing explicit values, including `oauth_scope=5`.
- Preserve environment overrides and host-pinned settings.
- Do not silently rewrite a custom client's requested permissions.
- Do not automatically retry `invalid_scope` with reduced permissions.
- Do not clear or relabel existing credentials merely because the default changed.
- Continue using the client ID and issuer recorded with a credential for refresh and revocation.

Document the opt-in update for an installation that wants the bundled scope-1 flow:

```bash
hanakura config set auth.civitai.oauth_scope 1
```

For a separate data directory, use the same directory for both configuration and startup:

```bash
hanakura --data-dir /path/to/data config set auth.civitai.oauth_scope 1
hanakura webui --data-dir /path/to/data
```

`HANAKURA_AUTH__CIVITAI__OAUTH_SCOPE` overrides the saved value. A host-pinned scope must be changed by the host application. Documentation must explain why changing the file may have no effect in either case.

An explicit custom client ID remains authoritative. Users returning to the bundled client must deliberately clear that setting and any corresponding override. Do not automatically reinterpret a custom ID as a bundled profile, even when the strings match: callback selection follows the profile source.

The old value 5 may have been serialized from a previous default or deliberately chosen. This plan does not attempt to guess which; it uses an explicit migration instruction instead of a destructive automatic migration.

## 4. Enable the bundled browser client

In `hanakura/core/auth/clients.py`:

- Enable the existing ComfyNodes profile by setting `verified=True`.
- Keep client ID `2d61872c-9aa9-4dbc-93c3-899c222842c1`.
- Keep its actual application name, `Civitai ComfyNodes`; do not relabel it as Hanakura.
- Keep `flows=frozenset({"browser"})` and `callback_path="/civitai/callback"`.
- Point its evidence description to this document's reported results and limitations.
- Replace comments and module documentation that require scope 5 before a profile can be enabled.

For this profile, `verified` means that the selected browser authorization configuration has user-reported live evidence. It must not be documented as proof of every permission, grant, download, or token lifecycle operation. Retain the existing field rather than introducing an unrelated profile-state redesign.

Keep resolution precedence unchanged:

1. Disabled OAuth prevents new authorizations.
2. An explicit custom client wins.
3. Otherwise, choose the enabled bundled profile.
4. Reject a bundled profile for an incompatible issuer.
5. Deployment checks determine whether its browser callback is available.

Keep all current callback restrictions: root-owning local deployment, loopback binding, the registered callback path, browser-binding cookies, PKCE S256, single-use transactions, and callback query redaction. The successful temporary launcher must no longer be needed for normal startup.

## 5. Keep permission checks and correct error descriptions

`CivitaiAuthService._commit()` already compares the granted scope with the transaction's requested scope. Retain that behavior:

- Requested 1, granted 1: accept.
- Requested 1, granted a valid superset such as 5: accept and retain the actual grant.
- Requested 5, granted 1: reject.
- Missing or unparseable granted scope: reject a new connection rather than assume authorization.

In `hanakura/core/auth/service.py`, replace the hardcoded error suffix about reading models and the account with wording about the requested permissions. Continue reporting `insufficient_scope` and discarding an unusable newly issued pair.

Review the English and Chinese UI messages for the same assumption. Do not describe a scope-1 credential as having ModelsRead, and do not present a connected account as a guarantee of access to every model.

Keep the existing refresh protocol and compatibility behavior in this focused change. Do not synthesize scope 5, rewrite stored grants to the new default, or silently switch to another account or manual token after an OAuth failure. A redesign of missing-scope handling during refresh is outside this plan.

## 6. API, Web UI, CLI, and downloads

### API and Web UI

- A fresh compatible local server should report a configured bundled client and the browser flow.
- The normal Settings screen should offer sign-in without asking for a client ID.
- Retain the displayed consent-application identity and advanced custom-client configuration.
- Keep manual API-token entry and method selection available.
- Keep the current root callback, session tracking, cancellation, and device-page fixes.
- Remove obsolete messages claiming that no bundled client has been verified. Retain an accurate `no_client` fallback for an empty or entirely unverified profile set.
- In remote, mounted, or prefixed deployments that cannot satisfy the bundled callback rules, explain the unsupported deployment and available alternatives. Do not redirect a remote user's browser to an unrelated localhost.

### CLI and device flow

- Default `hanakura auth connect` must not attempt the ComfyNodes device grant.
- Explain that the bundled client supports browser sign-in through the local Web UI.
- Keep device authorization for explicitly configured clients that support it.
- Do not enable Link Desktop or the Civitai CLI as additional bundled identities based on this test; neither was tested by the user in this browser flow.

### Downloads

Retain the existing credential entry point, bearer header handling, redirect protection, and downloader. The real-machine result does not require a downloader rewrite.

Keep existing 401 handling and do not add silent credential fallback, permission escalation, or automatic switching to manual mode. If a particular request is refused, report its failure without claiming that the user never signed in.

## 7. Regression coverage

Update fixtures deliberately. Do not replace every occurrence of 5 with 1: several tests must continue to exercise explicit broader scopes and insufficient grants.

| Area | Required coverage |
| --- | --- |
| Settings | Fresh configuration defaults to 1; saved 5 stays 5; environment and host overrides remain effective |
| Default client | The production bundled profile resolves to ComfyNodes, browser-only, root callback, effective scope 1 |
| Fallback profiles | Explicit empty and unverified-only profile sets still report `no_client` |
| Precedence | Custom IDs, explicit custom scope 5, disabled OAuth, and incompatible issuers retain their behavior |
| Authorization request | Default request carries scope 1, correct client ID, root redirect, state, and PKCE S256 |
| Grant validation | Requested 1 accepts 1 and a valid superset; requested 5 rejects 1; missing or malformed scope is rejected |
| Stored credentials | The actual grant, issuing client, and issuer survive persistence; defaults do not rewrite an existing pair |
| API | Default local status and callback work with the production profile and mocked provider; unsupported deployments remain unavailable |
| Browser binding | Both callbacks retain cross-tab binding protection; root callback is unavailable to inappropriate clients or deployments |
| CLI | The default client produces a browser-flow guidance error rather than a misleading missing-client error; custom device-flow tests remain valid |
| UI | Default local sign-in is available; advanced client settings are not required; unsupported deployment and insufficient-scope messages remain accurate |
| Download authentication | Existing mocked download tests verify the OAuth bearer is attached to Civitai requests and removed on redirects to storage |

Primary test files are `tests/core/test_auth.py`, the applicable settings tests, `tests/api/test_api.py`, `tests/api/test_mount.py`, `tests/cli/test_cli.py`, and `hanakura/webui/src/components/CivitaiAuthPanel.test.ts`.

Make tests that need an unavailable default explicitly inject an empty profile set. Make scope-5 refusal tests explicitly request 5. Keep tests offline and use the existing fake provider and clock.

## 8. Documentation and generated types

Update:

- `README.md` and `README_zh-CN.md`: normal local browser sign-in, bundled application identity, scope-1 default, upgrade instructions, and deployment limitations.
- `AGENTS.md`: effective client selection, the revised scope policy, evidence provenance, and remaining live verification gaps.
- `plan.md`: mark the old scope-5 gate as superseded by `plan1.md`; update current status without erasing the original investigation and failed probes.
- `hanakura/webui/src/api/schema.d.ts`: regenerate after the settings default changes; the schema's documented default is part of the change.
- English and Chinese translations, only where their existing text becomes inaccurate.

Distinguish user-reported test results, automated checks, and any subsequent independently observed live results. Do not describe a registered or approved Hanakura application: the reused identity remains ComfyNodes.

## 9. Implementation order and automated validation

1. Change the settings default, profile activation, and stale core comments.
2. Correct service, UI, and CLI messages where needed.
3. Adjust the focused fixtures and regression coverage.
4. Update documentation and regenerate API types under Pydantic v2.
5. Run the focused authentication tests, then the full repository check.
6. Review the final diff and record which live acceptance checks remain pending.

Use the repository's supported Python environment and Bun tooling:

```bash
python scripts/dev.py typegen
python scripts/dev.py check
git diff --check
```

`typegen-check` compares the regenerated schema with the Git index. Once reviewed, the generated schema must be staged before that consistency check can pass for an intentional schema change. Staging is not a commit or push. Keep any pre-existing staged or unrelated work intact.

Retain Pydantic v1 compatibility and run the applicable compatibility checks in an available isolated environment. Report any compatibility environment that was unavailable rather than treating it as verified. Avoid dependency upgrades or unrelated formatting changes.

## 10. Real-machine acceptance

Use a normal application startup with the built Web UI, not a launcher that overrides profiles in memory.

| Check | Expected result |
| --- | --- |
| Fresh local data directory, no client ID | Settings offers browser sign-in |
| Browser authorization | Civitai accepts scope 1 and returns through `/civitai/callback` |
| Account status | Hanakura reports the connected account and effective OAuth authentication |
| Download requiring authentication | The selected file downloads using OAuth, with no manual-token environment override; verify the published checksum where available |
| Restart | The stored account and credential remain usable |
| Access-token expiry | A later authorized request refreshes the credential and persists the rotated pair |
| Disconnect | Local OAuth credentials are cleared; the method does not silently change to another credential |
| Provider revocation | Test independently if possible; a successful revoke HTTP response alone is not proof of revocation |
| Existing settings containing scope 5 | The value is preserved; explicitly setting 1 enables the tested flow |
| Unsupported deployment | The interface explains why the bundled browser callback cannot be used |

Record the date, deployment type, actual requested/granted scopes, and the public identifier of the tested model when available. Never record access tokens, refresh tokens, authorization codes, state values, device secrets, or complete authorization/callback URLs.

The already reported login and download successes should be retained as evidence. Do not mark the other checks complete until they have actually been performed.

## 11. Completion criteria and scope boundaries

The code change is ready when a fresh compatible local deployment selects the bundled browser client with scope 1, preserves explicit configuration and credential ownership, passes the required automated checks, and documents the upgrade path and remaining live limitations.

Report implementation completion separately from complete real-machine token-lifecycle validation. Full live acceptance requires the pending checks above, especially an authenticated-only download with confirmed credential source, restart recovery, and refresh.

Do not add a hosted relay, browser-cookie extraction, password collection, new default device clients, wider permissions, or a downloader redesign. Do not register an OAuth application as part of this plan.

Creating this plan does not authorize implementation, commits, pushes, a version bump, or publication. Perform those only when subsequently requested.
