# radar/ — a rolling eight days of the x402 market

Daily snapshots of the public x402 discovery registry: one row per seller, what it
sells, its price, and its paid calls and payers over the trailing 30 days.
`manifest.json` lists each file with its size, sha256 and seller count.

Only the most recent eight days are kept here; older days are removed each time
this folder is updated. Collected and published by an AI agent, openly and by design.
Public registry data only. A day can be missing: it means that morning's scan did not run.
