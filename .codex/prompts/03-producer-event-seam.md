# mboxer neutral producer event seam

You are working in the `mboxer` repo.

Goal: add a small internal abstraction seam for future producer events, without connecting to uScientDB and without changing core behavior unnecessarily.

Important framing:

`mboxer` is the producer/tool. uScientDB may eventually receive append-only evidence, but it does not exist here yet. This task should make future integration easier while keeping `mboxer` independent.

Constraints:

- Do not add network calls.
- Do not add uScientDB package names unless purely conceptual in docs/comments and clearly marked future-facing.
- Do not invent a final event schema that pretends to be uScientDB’s API.
- Keep it local, testable, and boring.
- Prefer a neutral module name like `events`, `activity`, `audit`, or `producer`.
- Events should be append-oriented descriptions of local operations, not mutable state.
- Do not include sensitive raw body content by default.
- Watch for instruction-surface changes and report them explicitly.

Tasks:

1. Inspect existing places where operational evidence already exists:
   - ingest runs
   - classifications
   - category review/approval/rejection
   - security findings
   - exports/manifests
2. Propose the smallest neutral internal event abstraction.
3. Implement only if the seam is clearly useful and does not require broad rewrites.
4. Add tests.
5. Document how a future adapter could consume these events.

Preferred shape:

- A simple dataclass or typed structure for local producer events.
- Stable event names for operations like ingest completed, classification completed, security scan completed, export completed, category reviewed.
- JSON-serializable payloads.
- No external delivery.
- Clear boundaries around what is evidence vs derived/exported content.

Output:

- What you inspected.
- What seam you added and why.
- Files changed.
- Tests run.
- Why this does not couple `mboxer` to uScientDB.
- Later abstraction/refactor opportunities discovered, without implementing them.
- Instruction-surface changes.
