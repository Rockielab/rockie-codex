-- Migration 003: scope gpu_pods to a project so reconcile can sum per
-- project into budget_usage[project:<p>:dollars].
--
-- gpu.py reconcile GROUPs BY project to upsert one budget_usage row per
-- project. Without this
-- column the reconcile SELECT crashes with "no such column: project".
--
-- NULL is allowed; reconcile resolves NULL to the current project name
-- (ROCKIE_PROJECT env or repo dir basename).

ALTER TABLE gpu_pods ADD COLUMN project TEXT;
