# Contributing

## Branch naming

`type/scope-detail` — lowercase, hyphenated.

| Type | Use for |
|---|---|
| `feat/` | new capability |
| `fix/` | bug fix |
| `docs/` | docs only |
| `chore/` | deps, config, tooling |
| `bench/` | benchmark / measurement work |

Examples: `feat/frontend-tester`, `fix/fit-score`, `docs/doctrine`.

- One concern per branch.
- Branch off the branch that already holds the code you build on — not always `main`.
- `claude/*` branches are session-generated working branches; keep the pattern
  for automated sessions, use `type/scope-detail` for everything else.

## Commits

- Imperative subject, ≤72 chars: "Add the render gate", not "Added…".
- Body explains *why*, wrapped ~72 cols.
- One logical change per commit.

## Before pushing

```
python -m pytest tests/ -q     # backend
node --check <extracted-js>    # if you touched app/webtest.html
```

Heavy deps (cv2/mediapipe) are lazy — pure-math tests run without them.
