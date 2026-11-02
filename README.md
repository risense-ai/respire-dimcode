# respire

> Store on the inhale, recall on the exhale -- local encrypted memory for the Dim agent.

## Qoder build

The Qoder plugin is maintained separately at <https://github.com/risense-ai/respire-qoder> (with its release zip and install steps); this repo no longer bundles a copy.


`respire` is a standard Dim content plugin: it wires the [respire memory engine (CLI name rsrs)](https://www.npmjs.com/package/@rsrsai/cli) into the agent loop through command hooks -- a title-tier auto-recall every turn and a store triggered by the store prefix. Local-first, device-side encryption, cloud LWW sync; **no custom install script, installed the standard Dim marketplace way**.

## Data storage safety

1. **Works offline**: the memory store is local and a fresh configuration is offline mode -- no network, no registration, no login, and recall and writes keep working; writes made offline stay in the local queue and fill in through autosync after you log in.
2. **Only ciphertext goes to the cloud**: records are encrypted locally before upload and the server keeps encrypted records only; decryption, indexing and retrieval all happen on the device, the server needs no model and never holds an account's decryption key -- the cloud and its operators see ciphertext only.
3. **Enterprises can self-host the sync server**: `respire-server` supports private deployment (Docker Compose + Postgres) and can run entirely offline inside a corporate network. Point the sync endpoint at your own service and data never leaves the corporate network (see "Self-hosting" in respire-docs).

## Fully usable without a model (degradation is first class)

- **Registration, login, sync and recall never depend on an on-device model** -- installing the plugin is enough; without a model the engine automatically uses the lexical tier (equivalent to memlite with no embedding configured).
- BGE-M3 (~1.1GB) is a **purely optional enhancement**: run `rsrs model install && rsrs model activate m3` for better semantic recall. When the plugin detects it is missing it hints once in the session; with or without it nothing errors and nothing blocks.

## Install (standard Dim marketplace)

```bash
git clone https://github.com/risense-ai/respire-dimcode.git && cd respire-dimcode
python3 scripts/validate_plugin.py                     # self-check: structure/manifest/hooks/secret scan
dim plugin marketplace add .agents/plugins/marketplace.json
dim plugin install respire@risense
```

Upgrade (overwrite-install after pulling the source repo):

```bash
git pull
dim plugin marketplace upgrade risense     # refresh the registry source -- the marketplace installs a snapshot taken at registration, so without this it reinstalls the old version
dim plugin install respire@risense --overwrite
```

> If you need to keep your `hooks/respire.config.json`, copy it back from the old directory; deleting it falls back to the new defaults (old default values are not migrated automatically).

When the engine (rsrs CLI) is missing the plugin injects the install command into the session (`npm i -g @rsrsai/cli@latest`) so the agent can install it. **Takes effect in a new session.**

Install location: `~/.dimcode/v2/plugins/respire/` (CN distribution; Global uses `~/.dim/v2/plugins/` and source defaults to `~/.agents/plugins/` -- installation is a copy, so source changes require a reinstall).

Verify:

```bash
ls ~/.dimcode/v2/plugins/respire                 # .codex-plugin, hooks and skills all present
echo '{"prompt":"respire test"}' | python3 ~/.dimcode/v2/plugins/respire/hooks/respire.py UserPromptSubmit
```

Two things to know about Dim today (source verified): `dim` has **no** `plugin list` subcommand, and `dim hooks list` only lists project/user configuration, **not plugin hooks** -- an empty list does not mean hooks are not attached. Check the plugin itself in the TUI / Desktop plugin page, and treat a live new session as the only proof that it works.

## Role: installer plus manager plus normal hooks

The plugin does three things and then runs a lifecycle on its own:

1. **Installer while the engine is missing**: SessionStart hands the install command to the agent to run (`npm i -g @rsrsai/cli@latest` plus permission fallbacks and an `rsrs --version` check) and also states the next configuration steps (rsrs.rs registration / `rsrs register` / optional model) -- no manual work for the user;
2. **Normal hooks once it is ready**: it probes every turn, and once the engine is installed the rules, recall and explicit stores resume **within the same session**;
3. **A three-level manager switch** (see "Enable and disable" below).

## Enable and disable

| Level | How to turn it off | Scope |
| --- | --- | --- |
| Per turn | prompt prefix `/nomem` | that turn's recall only |
| Master switch | `"enabled": false` in `hooks/respire.config.json` | automatic rules/recall/store guidance goes silent; the installed placement guard stays active, and `hook.log` records `disabled` |
| Component level | toggle respire's **hook component** in the Dim plugin page (`skill`/`hook`/`mcp` are natively supported) | Dim unloads it directly |

## What happens after install

| Moment | Behaviour |
| --- | --- |
| `SessionStart` | Injects the memory-layer rules (when to recall, how to store, red lines), effective for the whole session and subagents; **one probe, three states** -- logged out adds registration guidance (rsrs.rs sign-up, `rsrs register` on the first device, `rsrs login --oauth --no-open` for an authorization link), an empty store (<10 records) adds first-day and import guidance, a missing semantic model adds the **optional** install note; silent in the normal case |
| `UserPromptSubmit` | Automatic `rsrs recall --titles`: **title-tier injection** -- only the score, 8-char short id and title, and the agent pulls the body on demand with `rsrs show <id>` (with the causal chain); **raw output, no filtering** by default, so the noise bound is the rsrs skip gate plus limit 5 plus the title tier |
| `prompt` starting with the store trigger or `remember:` | Writes directly with `rsrs remember … --importance important` and returns a receipt, **as a state machine**: `ok`/`warn` -> **written** (warn attaches the engine warning, e.g. an unresolved parent -- never a failure, never a resend), followed by a `show` read-back (verified / mismatch / unavailable labelled honestly); `pending` -> **not written**, restates candidates (with short ids) and engine-suggested actions (update > merge > attach > store in full; read candidate bodies with `show` before deciding); timeout/bad receipt -> **unknown**, where the receipt allows read-only verification only (`rsrs list`/`rsrs show`) and **forbids a resend** (duplicate-write risk; `ok`/`warn` without a valid id or with a malformed summary also map to unknown, neither failure nor success); the read-back is a **full verification** (id, title and complete body) worded honestly; remember/show/list share one hook time budget (`time.monotonic()` monotonic deadline, immune to clock changes; if the remaining budget is <=0 on entry, even remember is skipped and it goes straight to unknown). The receipt hard-requires the AI to extract a "subject + action + result" fact sentence and replace the provisional title with `retitle` |
| `Stop` (the AI finished) | **Store check**: `block+reason` continues for one turn and asks the model to store this turn's new **facts/decisions/agreements/lessons/pitfalls** one by one with `rsrs remember` (fact-sentence titles, decide on dedup first); plain chat with no new facts ends directly. **At most one nudge per real request**: the continuation turn's `stop_hook_active=true` allows, plus a per-session atomic one-shot latch (`O_EXCL` exclusive create, no TTL; a new prompt deletes and re-arms it; if the lock cannot be taken always allow, never block without it; sessions never interfere). **Suppression only accepts an attributable receipt**: this layer's successful write receipt for the same session after this turn's prompt (`ok`/`warn` plus id), stored in a **per-session state file** (`st_<sid>.json`, temp+rename atomic replace) -- cross-session reads are mutually invisible and parallel sessions never roll back each other's receipts; an engine-side whole-store timestamp cannot be attributed to a session and is no longer used for suppression (another session's write would wrongly suppress); `Stop` makes no engine query at all, so there is no list-failure continuation path either. Throttled by `store_nudge_every` (default 1 = every turn, N = every Nth, 0 = off) |
| `prompt` starting with `/nomem` | Skips recall for this turn |
| `prompt` carrying `$skill: name` | The prefix is stripped before recall -- the skill name collides lexically with skill memory |
| `skills/respire` | The on-demand playbook (recall/remember/show/forget/sync plus envelope parsing notes); **the skill is documentation only, every action is driven by the hooks** |

## First use: three things

1. **Register and log in** (works out of the box, no model needed): sign up at [rsrs.rs](https://rsrs.rs) then run `rsrs register` on this machine; day to day use `rsrs login` for browser authorization; autosync stays on, `rsrs sync` syncs manually and `rsrs status` shows state.
2. **Import existing memory and rules (one pass, the LLM extracts)**: open a new Dim session and paste the whole block below --

   > Import this machine's existing Dim rules and memory into respire: read one by one -- `~/AGENTS.md` (home-directory rules, if present), the `AGENTS.md` at the root of your usual projects, `~/.dimcode/v2/skills/*/SKILL.md`, `~/.dimcode/v2/hooks.json`, and the markdown under `~/.dimcode/v2/notes/` and `plan-drafts/`; extract reusable facts, agreements, lessons and red lines (exclude credentials, ID numbers, card numbers and private keys entirely; record only their location), deduplicate, then store them one by one with `rsrs remember` (`--importance important`, fact-sentence titles; on a dedup candidate decide first whether to attach or merge), and give me an inventory list when done.

   On an empty store, the first-day SessionStart injects the same lead.
3. **On-device model (optional enhancement)**: `rsrs model install && rsrs model activate m3` -- fully usable without it; install it only if you want better semantic recall.

## Tuning (optional)

`~/.dimcode/v2/plugins/respire/hooks/respire.config.json` (missing means all defaults; changes take effect in a new session; **never involves login or account settings**):

| Field | Default | Meaning |
| --- | --- | --- |
| `rsrs` | `""` | Engine path; empty = auto-detect (PATH -> `~/.local/bin` -> `~/.rsrs/bin`) |
| `recall_threshold` | `0.0` | Recall floor; **0 = off by default (raw rsrs output)**, a positive value enables filtering |
| `recall_limit` | `5` | Keep the first N hits |
| `min_prompt_chars` | `2` | 1 char is skipped, 2 chars triggers a query |
| `session_rules` | `true` | Whether to inject the SessionStart rules |
| `budget_chars` | `1500` | Total injection budget per turn (title lines are far shorter) |
| `enabled` | `true` | **Master switch**: false = everything silent |
| `store_nudge_every` | `1` | Stop store-check throttle: 1 = every turn, N = every Nth, 0 = off |
| `log` | `true` | `hooks/hook.log` trail (cleared above 256KB) |

Filtering policy: **no threshold by default** -- three layers already bound the noise: the rsrs skip gate, limit 5 and the title tier. History: every lowering of the threshold (0.56 -> 0.31) was a fix for genuinely relevant hits being blocked, and a missed recall costs far more than two extra title lines.

## Uninstall

`dim` has no `plugin uninstall` subcommand (source verified), so uninstalling means moving the directory, and **the target must be outside the plugins root** (a leftover directory with a manifest inside the root keeps being loaded as a plugin and the hooks run twice):

```bash
mv ~/.dimcode/v2/plugins/respire ~/.dimcode/v2/plugins-backup/respire.removed-$(date +%s)
```

## Design notes

- **fail-open for automatic guidance**: guidance errors remain silent and exit 0; identified PreToolUse memory writes deny on guard or parent-verification errors
- **Output**: guidance is plain text; PreToolUse refusals use static JSON deny and exit 0
- **Title-tier injection**: `recall --titles` returns id/score/title only and the body is pulled on demand with `show`; `superseded_by` is marked "superseded"
- **Respects the decide-then-store design**: writes never carry `--force`, and `pending` candidates are relayed verbatim for the model to decide
- **`${CLAUDE_PLUGIN_ROOT}` placeholder**: the Dim runtime substitutes the plugin install root, so it is portable across machines; commands use the `python3 || python` fallback and the `commandWindows` channel
- **In-package self-check**: `python3 scripts/validate_plugin.py` (structure/manifest/hooks shape/compilability/fail-open/secret scan), always run before distribution

## Known limits

- **Recall quality is the engine's ceiling**: across a vocabulary gap BGE-M3 can miss a real record -- the rules already require the model to retry with different wording (synonyms/hypernyms/English terms) when a hit does not fit
- **Cold-start window**: runtime cold start plus model load measured at 7s+, hence hook timeout 20s, recall 14s, probe 10s; on probe failure SessionStart injects a diagnostic section
- **PostCompact cannot re-inject** (the Dim protocol makes that event side-effect only): if the rules are lost after a long session is compacted, opening a new session restores them
- **Trail**: `hooks/hook.log` has one line per event (ts/ev/out/ms/d with a query summary) for per-line review

## Test

```bash
python3 scripts/validate_plugin.py   # package structure self-check
bash tests/test_hooks.sh             # read-only behaviour assertions (rules/recall/redaction/guidance), no store writes
bash tests/test_hooks.sh --store     # adds the write probe (writes the real store, checks the receipt, self-cleans with rsrs forget)
```

rsrs has no data-dir isolation (runtime singleton plus a global client.json), so write tests only run when explicitly enabled, and they write and forget immediately.

### PreToolUse write guard

Real shell redirections are removed before identifying the executable and subcommand; quoted text stays an argument. Every `remember --merge-ids` requires an explicit verified parent, including trivial merges because source importance can be inherited. Before `update --importance important`, the hook reads the target and verifies its existing non-empty parent; attach a root record before promoting it.

Before visible exec/Bash calls, the hook parses literal rsrs remember/update/attach arguments and every command in a sequence. It rejects force bypasses, important creation without a parent, explicit empty or invalid parents, and identified dynamic or wrapped memory writes. Use one explicit literal command when parsing is refused. Non-memory commands and read-only calls remain silent.

A non-empty parent must be an ID that an existing runner can verify with `rsrs --client-only show <id> --json`. Verification has a 16-second total budget inside the 20-second hook timeout; missing runners, errors, malformed receipts and timeouts deny the write and leave placement pending. No runtime is started and the hook never writes memory. Denials contain only static English guidance and exit 0, so the Python fallback cannot swallow them. Automatic guidance still honors the enabled switch; this placement guard remains active while the hook component is installed.

Host-visible `memory_remember`, `memory_update` and `memory_attach` MCP names, including `mcp__<server>__memory_*`, are denied because the hook cannot bind an arbitrary MCP server to the local target profile. Use an explicit rsrs command through the guarded shell instead. This is not a general shell sandbox: aliases, arbitrary external scripts, hidden API calls and tools that do not emit PreToolUse remain outside its visibility. A verified parent exists; the model must still read its full body and judge relevance before writing. Actual model termination and installation behavior require host verification.

## License

MIT

## GitHub Actions CI/CD

For PRs and main, Linux, Windows and macOS run the package self-check, the fully stubbed isolated behaviour/version tests and the release policy tests, then verify the source archive. The CI entry points are `python tests/test_ci.py` and `python -m unittest discover -s tests -p test_release.py -v`; the real-engine/write-probe sections of the legacy `test_hooks.sh` are not run. Tests use a temporary HOME, config, data, log and engine stub; ordinary input must recall successfully, a dead stub or bad JSON must fail the positive control, and a credential turn must make zero engine calls with no log leak.

It keeps the three-part version tag without a `v` and the original plugin root layout; the ZIP name stays `respire-version-YYYYMMDD.zip` with the date fixed to the source commit's UTC date so retries are stable. The ZIP comment is the exact commit SHA; the tag, manifest and hook VERSION (plus the existing marketplace version field) must agree. The old `scripts/package.sh` stays for the original local flow; the new Actions only archives committed files and never executes code from the tag.

Release/recovery: a normal new-version tag push triggers it; for an existing tag, use Actions -> release -> Run workflow, choose main and fill in the tag with the full expected_sha. The flow verifies the remote tag and its ancestry to main, never moves the tag and never passes off new main as old code. It only accepts existing assets with the same provenance and checksum, fills in what is missing and never overwrites a conflict; the Release provides both the ZIP and SHA256SUMS.

Defaults are contents:read with no persisted checkout credentials; only the separate controlled release job uses contents:write on GITHUB_TOKEN. No new secret/PAT/OAuth, no `pull_request_target`, and fork PRs cannot release. The same-version tag and recovery share a concurrency lock. The original plugin-zip artifact name, cleanup-receipt and cleanup policy/scripts are kept, and cleanup receipts wait for the check, package and release consumers to finish.

Three-platform stub tests are not acceptance of a real Dim host, GUI dispatch or the interpreter fallback after install; the old full suite and the author-declared baseline failures are still not independent proof of passing.

0.5.6 already has an official Release; this maintenance change does not re-release, move its tag or overwrite its assets.
