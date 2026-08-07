# overlay/ — additive NEW files dropped into the reused engines (plan 01 §3.1, Tier A)

Brand-new files (that do not exist upstream) are stored here under `overlay/<engine>/<same-rel-path>`
and copied into the engine tree by `setup.sh`. Because the file is new, upstream `git pull` can never
conflict with it. Example (lands in P3/P6):

    overlay/vigil/services/decepticon_ingestion.py   →  vigil/services/decepticon_ingestion.py
    overlay/vigil/mcp/redblue-decepticon-driver.json →  jq-merged into vigil/mcp-config.json

For **edits to existing** upstream files, use `patches/` (Tier B), not this dir. Empty in P0.
