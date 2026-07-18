# nightly-audit runner SELF-TEST prompt

This file exists ONLY for `nightly_runner.py --selftest`. It is NOT a real
audit prompt and is never executed by a real `claude` session.

When the runner is invoked with `--selftest`, it drives the FULL spawn path
(single-instance lock, wake lock, fresh-code worktree refresh, broker snapshot,
preflight manifest, child spawn + heartbeat + transcript, hard timeout,
unconditional end marker, report copy-back, completion contract) using a tiny
echo-style child instead of `claude`. The child writes a minimal
structurally-valid report so the completion contract can be exercised
end-to-end without a real audit, a real broker call, or a real model turn.

Purpose: let the operator (or Fable) confirm, post-merge, that the runner
works on the audit host — wake lock acquires, git fetch + worktree refresh
succeed, the manifest and snapshot are produced, and the contract passes —
before trusting it with a real nightly run.
