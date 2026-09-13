# Contributing

## Branches & naming

`main` is the single source of truth. Branch **from `main`**, one concern per branch,
PR back into `main`, delete after merge.

The branch-name taxonomy (`type/scope-detail`) and the full workflow live in one place —
**[`docs/BRANCHING_SOP.md`](docs/BRANCHING_SOP.md)**. Read it before creating a branch.
(Not repeated here, to keep one source.)

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
