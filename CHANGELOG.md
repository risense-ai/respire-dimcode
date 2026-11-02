# Changelog

## 0.5.16 — 2026-11-02

- Remove all non-ASCII (CJK) text from hooks, tests, scripts, docs and manifests. Behaviour is
  unchanged: patterns that must match Chinese user input or existing Chinese data now use
  `\u` escapes (`STORE_PREFIX` triggers, `SECRET_RE`/redaction keywords, sentence separators in
  `extract_title`, the credential-guard test fixtures).

## 0.5.15 — 2026-11-01 · prompts reduced to a pure-English memory discipline

- **`RULES` and `SKILL.md` became pure English and keep only the memory discipline**: recall first (the round's first tool call), recall before fixing on an error, the causal chain with `chain --depth 3`, dedup order update->merge->attach->create, titles as subject+action+result, the trust boundary, no secrets, honest failure reporting; CLI parsing tutorials, account/sync guidance, data-safety marketing and operation checklists were removed.
- **SessionStart extra hint sections removed**: `LOGIN_NUDGE`, `EMPTY_NUDGE`, `NO_MODEL`, `PROBE_FAIL` plus `check_model()` and their fake backdoors are gone; `probe_status()` is now a diagnostic trail only and appends no hint.
- **`NO_RSRS` trimmed**: only the engine install and registration steps remain; the recovery-code and `--super` prohibitions were not relaxed.
- Test assertions updated: `test_hooks.sh` and `test_ci.py` now match the new English first line and drop assertions for the removed hint sections.

## 0.5.14 — 2026-11-01 · round six final: remove disk-receipt suppression

- **`turn_stored` is always False (review 6 final)**: across events (UserPromptSubmit and Stop are two separate processes) there is no reliable disk identity for the current request -- every unlink/write/lock failure-recovery window was disproved round by round (4, 5 and 6, including the reviewer-named "permissions restored before Stop after a failed delete" and "a delete outside the lock recreated by an in-flight writer"). Per the review recommendation the suppression optimisation was **removed**: de-dup goes back to latch semantics (created with O_EXCL at nudge time, deleted by the next real prompt). The receipt is still returned honestly to the model and the state file remains a diagnostic trail. **Also review #3**: deleted the stale `test_common_write_failure_poisons_old_receipt`, which a later same-name test method shadowed so it never ran.

## 0.5.13 — 2026-11-01 · round five residual fix (unlink as the invalidation primitive)

- **Delete-first receipt invalidation (review 5 residual)**: `mark_prompt` deletes this session's state file before any write -- unlink needs no disk space, so even when all three writes fail the old receipt is physically deleted and the current request's Stop cannot suppress from it (without waiting for the next mark_prompt); if the unlink itself fails because the directory is unwritable, Stop's latch_claim fails the same way and allows. Tests follow the reviewer's order: an old successful receipt -> mark_prompt called while all three writes fail -> write capability returns but mark_prompt is not called and POISON is not hand-written -> Stop does not suppress (the state-file assertion confirms deletion) -> normal registration recovers.

## 0.5.12 — 2026-11-01 · round five review fix (safe degradation when the marker writes fail together)

- **POISON invalidation token (review 5)**: `mark_prompt` no longer ignores a write failure -- if either the gen marker or the state write fails it immediately writes the `+inf` invalidation token through the same blind-write path; `turn_stored` returns False for POISON or any finite old receipt, keeping the suppression optimisation off (bias to nudging, never suppress from an old disk receipt). The first mark_prompt after recovery rewrites the marker and restores it. Full-flow tests: old receipt -> both writes fail -> degraded -> no suppression; normal registration recovers; POISON alone switches it off.

## 0.5.11 — 2026-11-01 · round four review fix (safe invalidation on registration failure + lock ownership)

- **Safe invalidation when registration fails (review #1)**: a new gen marker file `st_<sid>.gen` (blind temp+rename write, no read-modify-write, no lock, immune to contention) is the truth about "the current request"; `mark_prompt` writes the marker before updating the state file; `turn_stored` requires prompt_ts == marker == store_req_ts -- when a new request fails to register (lock window exceeded / write failure) the marker has already advanced, so **the old receipt is invalid immediately and never wrongly suppresses** (test: an old request was stored -> holding the lock makes registration fail -> release -> no suppression; the recovery path suppresses again after normal registration).
- **Lock ownership (review #2)**: mtime age preemption removed; the lock content is a unique token and `_release_lock` deletes only a token-matching lock -- it never preempts a live lock and never deletes a later holder's lock (test: a second process gives up past the window while the holder is alive; a token mismatch deletes nothing). Giving up past the wait window is safe (combined with the gen marker).
- Tests: CI 39/39 (+2: registration-failure invalidation and recovery, lock ownership; the isolation suite adapted to the gen-marker truth chain).

## 0.5.10 — 2026-11-01 · round three review fix (same-session request isolation + strict envelope)

- **Receipt bound to the request generation (review #1)**: `mark_prompt` returns a gen, `do_store` captures it on entry, `mark_store(session, gen)` records `store_req_ts`, and `turn_stored` requires `store_req_ts == prompt_ts` -- a late-completing old request in the same session never suppresses a new one (two-way barrier test).
- **Same-session RMW transaction lock (review #1)**: `_map_lock` is an O_EXCL lockfile (mtime>5s staleness fallback, give up past the wait window) that serialises read-modify-write inside it, so a stale snapshot write-back can never roll back a new prompt (mutual-exclusion test).
- **Strict ID type and whitelist (review #2)**: `summary.id` must be a native string (the JSON number 12345678 is no longer `str()`-coerced); the whitelist tightens to a UUID or 16+ hex chars (`a-------` is rejected) -> unknown.
- **Read-back three-way id plus native types (review #2)**: verified requires summary.id and entry.id to both be strings and === the target id, and title/content to be native strings (the number 42 never matches "42") -- a wrong entry.id, a missing field or a non-string body is always mismatch with Saved retained.

### Changed

- Tests: CI 37/37 (+2 test blocks: request generation / RMW lock, strict envelope numeric id / hyphen string / wrong entry.id / numeric body).

## 0.5.9 — 2026-11-01 · review round 2 (PR #6 review round 2)

### Fixed

- **Per-session state files kill the cross-process RMW rollback (round two main item)**: the shared `turn_map.json` is gone -- it read the whole table, changed its own session and wrote everything back with temp+rename and no cross-process lock; the reproducible interleaving "B reads a stale snapshot -> A's new request updates prompt_ts and re-arms -> B writes everything back" rolled A back to the old values, so A's Stop mistook the old write for a write this turn and skipped the store check (the reverse interleaving lost a new receipt and caused a redundant nudge). One successful rename guarantees a complete write, not a transaction. It is now a per-session `st_<sidkey>.json` (temp+rename atomic replace), so none of B's writes can structurally touch A's entry; an old store receipt is invalid after a new prompt (prompt_ts>store_ts -> no suppression). The `_SCRIPT_DIR` definition accidentally deleted in the 0.5.8 refactor is restored (previously, with no `RESPITE_TURN_STATE` in production, the prompt hook raised NameError -> fail-open and the whole recall chain was dead).
- **Readback bad-details type guard (round two #2)**: a `show` read-back whose `details` is not a dict (array/string etc.) is no longer `.get()`-ed directly -- an AttributeError would tear down the whole written receipt (losing Saved); it is reported as **unavailable**, keeping the written fact and pointing to read-only verification.
- **Shared monotonic deadline (round two #3)**: the `do_store` budget uses the `time.monotonic()` clock (immune to clock changes); the `remember` timeout is `min(STORE_T, remaining budget)`, so a tight budget no longer waits the full 18s window; if the remaining budget is <=0 on entry even `remember` is skipped and it returns unknown directly (no resend).

### Changed

- Version 0.5.8 -> 0.5.9 (hook `VERSION`, `.codex-plugin/plugin.json`, and a `version` added to the `.claude-plugin/marketplace.json` entry); `.gitignore` gains the `st_*.json`/`st_*.json.*.tmp` runtime artifacts.
- Tests: CI 35/35 (+6 round-two counterexamples: B's write-back does not roll back A's new prompt state, A's new receipt is not erased by B's update, an old store does not suppress after A's new prompt (seeded-time assertion, independent of real clock granularity), bad show details (array/string) keep Saved plus unavailable, a tight budget caps the remember timeout (with an elapsed upper bound), an exhausted entry budget makes zero engine calls; the hang stub now detaches stdio/CWD first -- after a Windows .cmd shell timeout kill, a grandchild holding the pipe/CWD breaks both the timeout and cleanup, taking the suite from 75s to 17s); bash stays 75/0 (existing Stop/lock/suppression behaviour untouched).

## 0.5.8 — 2026-11-01 · maintainer review fix (PR #6 review)

### Fixed

- **One-shot completion latch rework (review #1)**: the single-session `.store_turn` state became a **per-session lock file** (`O_CREAT|O_EXCL` atomic -- of concurrent Stop calls only one takes the lock; no TTL, still held after 25 hours, only a new real prompt deletes and re-arms it; an A->B->A interleaving does not lose the lock); when the lock cannot be taken (unwritable state dir etc.) always allow -- never block without it. prompt_ts/store_ts live in a best-effort per-session map (temp+rename atomic replace, pruned by count only); a map failure only loses the optimisation.
- **A malformed list result is no longer treated as success (review #2)**: `details` not an array, or non-empty without a parseable timestamp -> treated as a failed query (a new entry is not attributed to this write).
- **Shared hook budget (review #3)**: remember/read-back/read-only verification share one deadline (`RESPITE_HOOK_BUDGET_S`, default 20s, with 2.5s output headroom); after a slow bad receipt the remainder is too small and it goes straight to unknown with no extra list.
- **Receipt/read-back hardening (review #4)**: `ok`/`warn` without a valid id (hex/uuid whitelist check), a malformed summary (type-guarded, no exception) or an unknown status all map to **unknown** (no resend); the read-back became a **full verification**: the returned id must equal the written id, the title must match and the complete body must match to be called verified, otherwise mismatch/unavailable is labelled honestly.
- **Attributable suppression receipts (review #1 acceptance completion)**: removed "an engine-wide newest write later than the prompt suppresses" (unattributable to a session; B's write would wrongly suppress A); `Stop` makes no engine query at all, so there is no list-failure continuation path either; `/nomem` still counts as a new request (mark moved earlier) and only skips recall, not the re-arm.

### Changed

- Tests: CI 29/29 (+ review-required counterexamples: an A->B->A interleaving does not lose the lock, the lock is not released without a new prompt, missing/garbage id or a bad summary -> unknown, a skip receipt is not a failure, a wrong id or tail tampering -> mismatch, a slow bad receipt plus a tight budget -> zero extra calls, a bad-schema list is not attributed); bash 75/0 (Stop scenarios follow the new contract: engine writes no longer suppress plus the single-nudge count, a bad envelope/dead process still nudges, an unwritable state dir allows, a 25-hour lock is still held, a new request and /nomem re-arm; `RESPITE_TURN_STATE` uses a Windows-native visible path); `.gitignore` gains the `.latch_*`/`turn_map.json` runtime artifacts.

## 0.5.7 — audit fix: write-result state machine, Stop fail-open, request-level suppression receipt (DM-01~DM-04)

### Fixed

- **DM-02 write-result state machine**: the explicit-store receipt no longer accepts only `status=ok` -- `warn` with a valid id means **written with warnings**, reported honestly with the error summary, never misreported as "not accepted" and never prompting a resend (the old implementation treated committed data as a failure and invited duplicate writes); a timeout/bad receipt maps to **unknown**, where the receipt requires "verify read-only with `rsrs list`/`rsrs show`, never resend", and an instant bad receipt triggers an automatic `list` cross-check reporting a possible write.
- **DM-01 Stop fail-open**: when the `list` store query fails, times out, returns a bad envelope or hits a dead process, allow directly instead of blocking -- a memory-layer fault must not block the end of the main task.
- **DM-03 request-level suppression receipt**: the global "any write in the last 10 minutes" suppression is gone (it suppressed across turns by mistake); it is now `.store_turn` -- only a successful write receipt for the same session after this turn's prompt, or an engine-side write, suppresses. A pending receipt keeps the candidate short ids and the full set of engine-suggested actions (update > merge > attach > store, 7.2); after ok/warn a `show` read-back verifies the write (R11).
- **DM-04 one-shot latch**: when the host sends no `stop_hook_active`, the same request still blocks at most once; a new prompt re-arms it.

### Changed

- Tests: the CI stub whitelist upgraded to an ordered call sequence (remember -> show read-back chain) and the spy supports warn/pending/silent/hang/show_mismatch; 8 contract tests added and the old wrong expectations flipped (failed -> block used to be treated as correct). The bash suite moved to a portable python engine stub (.cmd wrapper) and Windows pseudo-failures were fixed, from a baseline 54/7 to 71/0 (--store 74/0). `RESPITE_TEST_FAST`/`RESPITE_TURN_STATE` test backdoors; README behaviour table updated; `.gitignore` gains `.store_turn`.

## 0.5.6 — suspected-credential blocking plus unified install/registration wording

- Added an input-side suspected-credential scan (`contains_secret`): when a prompt matches a private-key block, high-risk tokens such as sk-, ghp_, github_pat_, xox, Bearer, or an assignment of `password|passphrase|private key|passwd|api key|token|secret`, that prompt is neither recalled nor stored and a `SECRET_SKIP` note is injected -- completing the same defence as the codex/pi/dsh side (previously the rules only said "do not store credentials" with no machine gate).
- Install and registration wording aligned with the CLI: `npm i -g rsrs-cli@latest` (the official new-user entry; `@rsrsai/cli` still works); registration is a direct local `rsrs register` with no website step (in NO_RSRS / LOGIN_NUDGE / PROBE_FAIL; the old "sign up at rsrs.rs first" was outdated).
- Tests 48 -> 50: two checks for "a suspected credential is not recalled / not stored"; the install and registration assertions follow the new wording.

## 0.5.5 — three data-storage-safety notes (injected with the install guidance)

- README gained a "Data storage safety" section: (1) works offline (local store; recall and writes work without network, registration or login, and offline writes queue up for sync); (2) only ciphertext goes to the cloud (encrypted locally before upload, the server holds no decryption key); (3) enterprises can self-host the sync server (respire-server, Docker Compose + Postgres on an internal network, data never leaves the corporate network).
- Hook-side placement: the three notes went into `NO_RSRS` (engine missing, injected at install time), **not into `RULES`** -- the per-session rules do not repeat the sales pitch, it is only stated at install/missing-engine time.
- SKILL.md gained a "Data safety (user-facing)" section (say it plainly when asked); the manifest `description` and `interface.longDescription` follow suit (visible on the plugin page before install).

## 0.5.4 — Stop throttle now asks the engine (agent-side stores allow as well)

- Stop's "already stored within 10 minutes" originally scanned only this layer's hook.log store events, which only the hook-side explicit-store path writes -- a direct `rsrs remember` by the agent was invisible, so in practice the event count was always 0, the branch never fired and every turn nudged (the Qoder side fixed the same defect in 0.6.3).
- Added `engine_last_store()`: `rsrs list --limit 3 --json` takes the max of `updated_at`/`created_at` and compares it with 600s, leaving `stored_recent_skip src=engine` on a hit; a 6s timeout or any exception always allows and nudges as usual, and the log fast path is kept.
- Tests 45 -> 48: a recent engine store does not nudge / a stale one still nudges / the trail records src=engine; the throttle assertions use the stale/fresh engine stubs instead of depending on a real store.
- Released with this version: the `respire-qoder/` subdirectory was removed; the Qoder build is maintained only in the separate repo risense-ai/respire-qoder, and README/CHANGELOG now point there.

## 0.5.3 — prompts in English plus marketplace metadata and icon

- SKILL.md, the injected hook rules and the store/pending/recall receipts all became English; Chinese prefixes such as the store trigger remain supported.
- The Dim manifest `defaultPrompt` and `shortDescription` became English; test assertions follow the English text and no longer depend on a locale or a real store.
- `interface.logo` points at the new `assets/logo.png` (512x512, shown in the Dim plugin list); top-level `author`/`homepage`/`repository`/`license`/`keywords` and an English `interface.longDescription` were added.
- CI: `.github/workflows/release.yml` -- a tag push (`*.*.*`) packages and publishes a Release (sharing `scripts/package.sh`); main/PR pushes run the self-check; `workflow_dispatch` produces an artifact dry run.
- The package manifest includes `assets/`.

## 0.5.0 — store after finishing (the Stop hook)

- Lifecycle completed: the user speaks -> recall is injected (UserPromptSubmit); **the AI finishes -> the store check is injected** (Stop) --
  `block+reason` continues for one turn and asks for this turn's new facts/decisions/agreements/lessons/pitfalls one by one with `rsrs remember`
- Loop guard: the continuation turn's `stop_hook_active=true` allows; measurement showed plain-text injection is invisible at Stop, so block+reason is required
- Throttle `store_nudge_every` (every turn by default, tunable to N or 0); no nudge when something was stored within 10 minutes
- Test logs and throttle state are isolated through `RESPITE_LOG`/`RESPITE_NUDGE_STATE`; 47 assertions

## 0.4.0 — installer and manager

- **Role narrowed**: the plugin is an installer plus a manager plus normal hooks -- while the engine is missing it hands the install command and the next configuration steps to the agent to run (probing live every turn, usable as soon as installed); once ready it runs the normal hooks.
- **Master switch** `enabled` (false = everything silent, `hook.log` records disabled); three management levels: `/nomem` per turn / `enabled` master / the Dim plugin page hook component toggle.
- PROBE_FAIL gained the "brand-new machine not yet registered" branch; NO_RSRS became the install command plus configuration guidance.
- The three-step upgrade must include `marketplace upgrade` (install uses the registration snapshot).

## 0.3.0 — standard Dim plugin form

- Distribution moved to the standard Dim plugin marketplace: `dim plugin marketplace add .agents/plugins/marketplace.json` plus `dim plugin install respire@risense`; **the custom install.sh / uninstall.sh were removed**.
- Package structure aligned with the spec: `.codex-plugin/plugin.json` (interface gained developerName/category/capabilities/websiteURL/defaultPrompt), hooks under `hooks/hooks.json`, commands with the `python3 || python` fallback chain and `commandWindows`.
- Added `scripts/validate_plugin.py` (structure/manifest/hooks shape/compilability/fail-open/secret scan).
- **Degradation is first class**: registration, login, sync and lexical recall never depend on an on-device model; BGE-M3 is a purely optional enhancement (`rsrs model install && rsrs model activate m3`).
- Threshold off by default (raw rsrs output); the `$skill:` identification prefix is stripped; hook.log trail; cold-start timeout window.

## 0.2.x — first version (manual install script era)

- memlite -> respire(rsrs) engine swap, title-tier recall, decide-then-store, three-state session guidance.
