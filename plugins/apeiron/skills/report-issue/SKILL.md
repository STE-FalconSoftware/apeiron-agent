---
name: report-issue
disable-model-invocation: true
description: File an Apeiron bug report with the team, from the running editor
allowed-tools: Bash(ngine doctor:*), Bash(ngine where:*)
---

Report a problem with Apeiron to the Apeiron team. First gather, without changing anything: the
output of `ngine where` and `ngine doctor`, the `report` field of the `editor.version` op, the last
errors in `editor.context`, and the exact ops and arguments that led to the problem.

Draft a one-line title and a body (what I did, what I expected, what happened, plus what you
gathered) and SHOW IT TO ME. Ask two questions: may I send it, and may the newest crash report go
with it (only if there was a crash)? When I say yes, call `editor.report_issue {kind, title, body,
include_crash}` — `include_crash: true` only if I agreed to share crash data. It is filed under my
Apeiron account (never on GitHub), the editor log is attached, and the reply carries a `report_id`
(or `pending`: then read `account.status`'s `last_report`).

If the editor is not signed in, the op is refused: tell me to use Account > Sign in in the editor,
then send again. List separately anything you could NOT collect and why.
