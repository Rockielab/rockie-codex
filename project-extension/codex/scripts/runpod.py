#!/usr/bin/env python3
"""runpod.py — RunPod GPU provisioning CLI for rockie.

A thin wrapper over providers/runpod.py:RunPodProvider that speaks the
verbs rockie's autopilot needs: find cheap H100 spot pricing, bid, poll
until the pod is running, fetch SSH endpoint, stop, terminate.

Design principles:
  * **Default dry-run.** Any mutation (create, stop, terminate, resume)
    requires --yes or an interactive confirmation. Nothing charges your
    card unless you opt in.
  * **Cost transparency.** Before any provision, the CLI prints the
    current spot bid vs on-demand price for the chosen GPU and asks for
    confirmation.
  * **State in workflow.db.** Provisioned pods are recorded in the
    `gpu_pods` table so autopilot can reattach after a preemption.
  * **Pure-API provider; harness owns state.** All GraphQL lives in
    providers/runpod.py:RunPodProvider. This file owns the CLI, the SQL
    writes to gpu_pods, the budget.py charges, and the reconcile loop.
    Commit 7 lifts the reconcile loop into scripts/gpu.py — at that
    point this file becomes a thin shim that calls gpu.py with
    --providers runpod.

Subcommands:
  auth, list-gpus, price, create, list-pods, get-pod, stop, terminate,
  resume, cost, reconcile

Env:
  RUNPOD_API_KEY            required for every mutation/query
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
import time
from typing import Any

from providers.base import (
    AuthError,
    BidRejected,
    NoCapacity,
    OutOfStock,
    ProviderError,
    SpotSpec,
)
from providers.runpod import RunPodProvider

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "memory" / "workflow.db"


# ─── Provider error → exit code ────────────────────────────────────────────


def _handle(fn):
    """Decorator: translate provider exceptions into stable CLI exit codes.

    AuthError → 2 (config issue, fix the env)
    BidRejected/OutOfStock/NoCapacity → 3 (transient or capacity)
    ProviderError → 3 (any other adapter-raised error)
    Returns 0 if the wrapped fn completes; otherwise its int return.
    """

    def wrapped(args):
        try:
            return fn(args)
        except AuthError as e:
            print(f"auth: {e}", file=sys.stderr)
            return 2
        except (BidRejected, OutOfStock, NoCapacity) as e:
            print(f"capacity: {type(e).__name__}: {e}", file=sys.stderr)
            return 3
        except ProviderError as e:
            print(f"provider: {e}", file=sys.stderr)
            return 3

    return wrapped


# ─── SQLite — track provisioned pods ───────────────────────────────────────


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA trusted_schema=1")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpu_pods (
          id           TEXT PRIMARY KEY,
          provider     TEXT NOT NULL DEFAULT 'runpod',
          gpu_type     TEXT,
          gpu_count    INTEGER,
          bid_per_gpu  REAL,
          region       TEXT,
          status       TEXT,
          created_at   TEXT NOT NULL DEFAULT (datetime('now')),
          stopped_at   TEXT,
          ssh_endpoint TEXT,
          notes        TEXT
        );
        """
    )
    conn.commit()
    return conn


# ─── Commands ──────────────────────────────────────────────────────────────


@_handle
def cmd_auth(_args) -> int:
    me = RunPodProvider().auth() or {}
    if isinstance(me, dict) and me.get("id"):
        print(f"[auth] ok — user id {me.get('id')} / email {me.get('email','(hidden)')}")
    else:
        print("[auth] ok")
    return 0


@_handle
def cmd_list_gpus(args) -> int:
    rp = RunPodProvider()
    gpus = rp.list_gpus(grep=args.grep)
    print(f"{'gpuTypeId':40} {'display':20} mem(GB)")
    print("─" * 80)
    for g in gpus:
        print(f"{g.id:40} {g.name:20} {g.memory_gb if g.memory_gb is not None else '-':>7}")
    return 0


@_handle
def cmd_price(args) -> int:
    if args.secure:
        # --secure filters lowestPrice to SECURE-cloud datacenters. The
        # Protocol's price() doesn't carry that knob today; the resulting
        # numbers may be slightly higher than what runpod.py used to show
        # with --secure. (Create still honors --secure via SpotSpec.extras.)
        print("[note] --secure on `price` is currently a no-op; numbers reflect ALL clouds", file=sys.stderr)
    rp = RunPodProvider()
    pr = rp.price(args.gpu_type_id, args.gpu_count)
    print(f"{args.gpu_type_id}  (× {args.gpu_count})")
    print(f"  available counts:   {pr.stock} offer-row(s)")
    print(f"  spot bid (min):     ${pr.min_bid if pr.min_bid is not None else '?'}/h per GPU")
    print(f"  on-demand:          ${pr.on_demand if pr.on_demand is not None else '?'}/h per GPU")
    return 0


@_handle
def cmd_create(args) -> int:
    rp = RunPodProvider()

    # Pre-flight: show pricing + plan, ask for confirmation.
    pr = rp.price(args.gpu_type_id, args.gpu_count)
    bid = args.bid
    if bid is None:
        if pr.min_bid is None:
            print(
                f"--bid not set and no minimumBidPrice returned "
                f"(stock={pr.stock} offer-rows). GPU type may be out of "
                f"spot inventory. Try a different gpu-type-id or wait.",
                file=sys.stderr,
            )
            return 2
        bid = float(pr.min_bid)
        print(f"[bid] no --bid specified; defaulting to current minimum ${bid}/GPU-hr")
    if pr.min_bid is not None and bid < pr.min_bid:
        print(
            f"bid ${bid} is below minimum ${pr.min_bid} — would be rejected",
            file=sys.stderr,
        )
        return 2

    est = bid * args.gpu_count * args.hours
    print("provision plan:")
    print(f"  gpu:        {args.gpu_type_id} × {args.gpu_count}")
    print(f"  bid:        ${bid}/GPU-hr   (min ${pr.min_bid}, on-demand ${pr.on_demand})")
    print(f"  hours est:  {args.hours}")
    print(f"  total cap:  ${est:.2f}  (upper bound at bid if uninterrupted)")
    print(f"  stock:      {pr.stock} offer-row(s)")

    if not args.yes:
        print()
        print("dry-run (pass --yes to actually provision)")
        return 0

    spec = SpotSpec(
        gpu_type=args.gpu_type_id,
        gpu_count=args.gpu_count,
        volume_gb=args.volume_gb,
        disk_gb=args.disk_gb,
        bid=bid,
        image=args.image,
        name=args.name,
        env=dict(kv.split("=", 1) for kv in args.env),
        extras={
            "secure": args.secure,
            "min_vcpu": args.min_vcpu,
            "min_ram": args.min_ram,
        },
    )
    pod = rp.create_spot(spec, yes=True)
    if pod is None:
        # Should not happen with yes=True; defensive.
        print("create returned None unexpectedly", file=sys.stderr)
        return 3
    print(f"[created] pod_id={pod.id}")

    # Record in workflow.db so autopilot can track.
    conn = _db()
    conn.execute(
        "INSERT OR REPLACE INTO gpu_pods (id, provider, gpu_type, gpu_count, bid_per_gpu, status, notes) "
        "VALUES (?, 'runpod', ?, ?, ?, 'CREATED', ?)",
        (pod.id, args.gpu_type_id, args.gpu_count, bid, args.name),
    )
    conn.commit()

    # Charge the dollars budget — upper-bound at bid × count × hours.
    # The reconcile loop later corrects against actual spend.
    import subprocess as _sp

    estimated_cost = bid * args.gpu_count * args.hours
    try:
        _sp.run(
            [
                sys.executable,
                str(pathlib.Path(__file__).parent / "budget.py"),
                "add",
                "dollars",
                str(estimated_cost),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        pass

    if args.no_wait:
        return 0

    # Poll until SSH is up (or timeout).
    deadline = time.time() + args.wait_seconds
    while time.time() < deadline:
        try:
            cur = rp.get_pod(pod.id)
        except ProviderError as e:
            print(f"[wait] get_pod transient: {e}")
            time.sleep(5)
            continue
        if cur.ssh_endpoint:
            print(f"[running] {cur.ssh_endpoint}")
            conn.execute(
                "UPDATE gpu_pods SET status='RUNNING', ssh_endpoint=? WHERE id=?",
                (cur.ssh_endpoint, pod.id),
            )
            conn.commit()
            return 0
        print(f"[wait] status={cur.status} …")
        time.sleep(5)

    print(f"timed out waiting for RUNNING state after {args.wait_seconds}s", file=sys.stderr)
    return 3


@_handle
def cmd_list_pods(_args) -> int:
    rp = RunPodProvider()
    pods = rp.list_pods()
    if not pods:
        print("(no pods)")
        return 0
    print(f"{'pod_id':20} {'status':10}  ssh")
    print("─" * 80)
    for p in pods:
        print(f"{p.id:20} {p.status:10}  {p.ssh_endpoint or '-'}")
    return 0


@_handle
def cmd_get_pod(args) -> int:
    rp = RunPodProvider()
    p = rp.get_pod(args.pod_id)
    print(json.dumps({
        "id": p.id,
        "provider": p.provider,
        "status": p.status,
        "ssh_endpoint": p.ssh_endpoint,
        "gpu_type": p.gpu_type,
        "gpu_count": p.gpu_count,
    }, indent=2))
    return 0


@_handle
def cmd_stop(args) -> int:
    if not args.yes:
        print(f"dry-run: would stop pod {args.pod_id} (pass --yes to actually stop)")
        return 0
    RunPodProvider().stop(args.pod_id, yes=True)
    print(f"[stopped] {args.pod_id}")
    try:
        conn = _db()
        conn.execute(
            "UPDATE gpu_pods SET status='STOPPED', stopped_at=datetime('now') WHERE id=?",
            (args.pod_id,),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    return 0


@_handle
def cmd_terminate(args) -> int:
    """podTerminate — permanently delete a pod + its volume.

    Different from `stop`: stop pauses compute but keeps the volume
    (so you keep paying storage). terminate destroys everything. Use
    when a pod is EXITED and you don't intend to resume, or when a
    running pod should be fully torn down.
    """
    if not args.yes:
        print(f"dry-run: would TERMINATE (delete) pod {args.pod_id} — volume data LOST. Pass --yes to confirm.")
        return 0
    RunPodProvider().terminate(args.pod_id, yes=True)
    print(f"[terminated] {args.pod_id} — pod + volume deleted")
    try:
        conn = _db()
        conn.execute(
            "UPDATE gpu_pods SET status='TERMINATED', stopped_at=datetime('now') WHERE id=?",
            (args.pod_id,),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    return 0


@_handle
def cmd_reconcile(args) -> int:
    """Query live RunPod state, compute ACTUAL accrued spend per pod,
    and SET budget_usage.dollars to the truth.

    This is the mechanism behind budget enforcement. The dollars ceiling
    is meaningless without it — at create() time we only know the
    *estimated* upper-bound cost. If a pod runs 6h instead of 2h, or
    gets preempted at 30 min, the estimate diverges from reality.

    Called by:
      * hooks/budget-reconcile.sh on UserPromptSubmit (2-min TTL)
      * autopilot_loop.sh each iteration (continuous during autonomy)
      * `runpod.py reconcile` on-demand
      * `runpod.py cost` transparently before reporting

    Algorithm:
      For each pod our gpu_pods knows about:
        elapsed_hr = (now - created_at) / 3600
        if desiredStatus == RUNNING:  rate = costPerHr   # compute
        else:                         rate ≈ storage + 0.5 × compute
        accrued = elapsed_hr * rate                      # conservative
      gpu_pods.accrued_dollars = that value
      budget_usage[project:<p>:dollars] = SUM across project's pods.

    Conservative bias: charges full compute for RUNNING lifetime, and
    half compute for EXITED (since we don't know historical RUNNING-
    seconds after a preemption). Errs on the side of blocking sooner.
    """
    STORAGE_RATE_PER_GB_HR = 0.10 / 30 / 24  # ≈ $0.000139/GB/hr

    rp = RunPodProvider()
    state = rp.fetch_live_state()
    live_pods = {p["id"]: p for p in ((state.get("myself") or {}).get("pods") or [])}

    conn = _db()
    our_pods = conn.execute(
        "SELECT id, created_at, project, bid_per_gpu, gpu_count FROM gpu_pods"
    ).fetchall()

    updates = 0
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    for row in our_pods:
        pod_id = row["id"]
        live = live_pods.get(pod_id)
        if not live:
            # Pod was terminated or deleted on RunPod; freeze accrued.
            conn.execute(
                "UPDATE gpu_pods SET status='GONE', last_reconciled_at=datetime('now') "
                "WHERE id = ? AND status NOT IN ('TERMINATED','GONE')",
                (pod_id,),
            )
            continue

        created_s = (row["created_at"] or "").strip()
        try:
            created = datetime.fromisoformat(created_s.replace(" ", "T")).replace(
                tzinfo=timezone.utc
            )
        except Exception:
            if args.verbose:
                print(
                    f"[reconcile] skipping {pod_id}: bad created_at {created_s!r}",
                    file=sys.stderr,
                )
            continue

        elapsed_hr = max(0.0, (now - created).total_seconds() / 3600.0)
        status = live.get("desiredStatus") or "?"
        vol_gb = live.get("volumeInGb") or 0
        compute_rate = float(live.get("costPerHr") or 0)

        if status == "RUNNING":
            rate = compute_rate + STORAGE_RATE_PER_GB_HR * vol_gb
        else:
            rate = (compute_rate * 0.5) + STORAGE_RATE_PER_GB_HR * vol_gb

        accrued = round(elapsed_hr * rate, 4)

        conn.execute(
            "UPDATE gpu_pods SET accrued_dollars = ?, last_reconciled_at = datetime('now'), "
            "status = ? WHERE id = ?",
            (accrued, status, pod_id),
        )
        updates += 1

    # Rewrite project-scope dollars counter = SUM(accrued_dollars).
    totals = conn.execute(
        "SELECT project, SUM(accrued_dollars) AS total FROM gpu_pods GROUP BY project"
    ).fetchall()
    for t in totals:
        proj = t["project"] or _project_name()
        total = float(t["total"] or 0)
        bkey = f"project:{proj}:dollars"
        conn.execute(
            """
            INSERT INTO budget_usage (key, project, session_id, metric, value)
            VALUES (?, ?, NULL, 'dollars', ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')
            """,
            (bkey, proj, total, total),
        )

    conn.commit()

    state_dir = pathlib.Path(__file__).resolve().parent.parent / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "last_reconcile_ts").write_text(str(int(time.time())))

    if args.verbose or not args.quiet:
        print(f"[reconcile] updated {updates} pod row(s), refreshed dollars counter(s)")
        for t in totals:
            print(f"  {t['project']}: accrued ${float(t['total'] or 0):.4f}")
    return 0


def _project_name() -> str:
    """Best-effort: read project name from env or repo path."""
    import os as _os

    return _os.environ.get("ROCKIE_PROJECT") or pathlib.Path.cwd().name


@_handle
def cmd_cost(_args) -> int:
    """Current-hour spend snapshot + cumulative budget usage.

    Reconciles first so the numbers reflect current reality rather than
    create-time estimates. Reading cost without reconciliation would
    show accounting fiction.
    """

    class _ArgsStub:
        verbose = False
        quiet = True

    try:
        cmd_reconcile(_ArgsStub())
    except Exception:
        pass

    rp = RunPodProvider()
    state = rp.fetch_live_state()
    me = state.get("myself") or {}
    pods = me.get("pods") or []
    volumes = me.get("networkVolumes") or []

    print("── RunPod pods ──")
    if not pods:
        print("  (none)")
    running_cost_per_hr = 0.0
    idle_volume_gb = 0
    for p in pods:
        status = p.get("desiredStatus", "?")
        gb = p.get("volumeInGb", 0)
        rt = p.get("runtime") or {}
        up = rt.get("uptimeInSeconds")
        cph = p.get("costPerHr", 0) or 0
        marker = "▶" if status == "RUNNING" else ("×" if status in ("EXITED", "STOPPED") else "?")
        print(
            f"  {marker} {p['id']:20} {p.get('name',''):25} {status:8} vol={gb}GB cost={cph}/hr uptime={up}s"
        )
        if status == "RUNNING":
            running_cost_per_hr += float(cph)
        else:
            idle_volume_gb += int(gb)

    print("\n── RunPod network volumes ──")
    if not volumes:
        print("  (none)")
    vol_bytes = 0
    for v in volumes:
        print(f"  {v.get('id'):20} {v.get('name',''):20} {v.get('size')}GB in {v.get('dataCenterId','?')}")
        vol_bytes += int(v.get("size", 0) or 0)

    STORAGE_RATE = 0.10 / 30 / 24
    idle_hr_cost = (idle_volume_gb + vol_bytes) * STORAGE_RATE

    print("\n── current-hour cost estimate ──")
    print(f"  running compute:  ${running_cost_per_hr:.3f}/hr")
    print(
        f"  idle storage:     ${idle_hr_cost:.4f}/hr  ({idle_volume_gb + vol_bytes} GB idle)"
    )
    print(
        f"  TOTAL live rate:  ${running_cost_per_hr + idle_hr_cost:.3f}/hr "
        f"= ~${(running_cost_per_hr + idle_hr_cost)*24:.2f}/day"
    )
    print(f"  billing page:     {RunPodProvider.billing_url}")

    print("\n── budget counter (cumulative since install) ──")
    import subprocess as _sp

    _sp.run(
        [sys.executable, str(pathlib.Path(__file__).parent / "budget.py"), "status"],
        check=False,
    )
    return 0


@_handle
def cmd_resume(args) -> int:
    if not args.yes:
        print(f"dry-run: would resume pod {args.pod_id} (pass --yes)")
        return 0

    rp = RunPodProvider()

    # Decide spot vs on-demand + resolve the bid.
    # - --on-demand: provider.resume(bid=None) → podResume
    # - Otherwise: spot resume via podBidResume. If --bid is omitted,
    #   look up the pod's gpu_type from gpu_pods and default to current
    #   minimumBidPrice — never a bumped bid.
    if args.on_demand:
        rp.resume(args.pod_id, yes=True, bid=None)
        print(f"[resumed] {args.pod_id} (on-demand)")
        return 0

    bid = args.bid
    if bid is None:
        conn = _db()
        row = conn.execute(
            "SELECT gpu_type FROM gpu_pods WHERE id = ?", (args.pod_id,)
        ).fetchone()
        if row and row["gpu_type"]:
            try:
                pr = rp.price(row["gpu_type"], args.gpu_count)
                if pr.min_bid is not None:
                    bid = float(pr.min_bid)
                    print(f"[bid] resuming at current min ${bid}/GPU-hr for {row['gpu_type']}")
            except (OutOfStock, ProviderError):
                pass
        if bid is None:
            print(
                "--bid not set and couldn't resolve current min bid automatically. "
                "Pass --bid <min>/GPU-hr or --on-demand.",
                file=sys.stderr,
            )
            return 2

    rp.resume(args.pod_id, yes=True, bid=bid)
    print(f"[resumed] {args.pod_id} at ${bid}/GPU-hr")
    return 0


# ─── argparse ──────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("auth", help="Verify RUNPOD_API_KEY").set_defaults(func=cmd_auth)

    lp = sub.add_parser("list-gpus", help="List all GPU types")
    lp.add_argument("--grep", help="Filter by substring of id or display name")
    lp.set_defaults(func=cmd_list_gpus)

    pp = sub.add_parser("price", help="Spot + on-demand pricing for a GPU type")
    pp.add_argument("gpu_type_id", help='e.g. "NVIDIA H100 80GB HBM3"')
    pp.add_argument("--gpu-count", type=int, default=1)
    pp.add_argument("--secure", action="store_true", help="(currently no-op on price; honored on create)")
    pp.set_defaults(func=cmd_price)

    cp = sub.add_parser("create", help="Provision a spot Pod (dry-run unless --yes)")
    cp.add_argument("--gpu-type-id", required=True)
    cp.add_argument(
        "--bid",
        type=float,
        help="Spot bid $/GPU-hr. Default: current minimumBidPrice for this gpu type. "
        "Do NOT bump above min — provider-hop on preemption instead.",
    )
    cp.add_argument("--gpu-count", type=int, default=1)
    cp.add_argument("--hours", type=float, default=1.0, help="estimated runtime for cost display")
    cp.add_argument("--volume-gb", type=int, default=40)
    cp.add_argument("--disk-gb", type=int, default=40)
    cp.add_argument("--min-vcpu", type=int, default=4)
    cp.add_argument("--min-ram", type=int, default=16)
    cp.add_argument("--image", default="")
    cp.add_argument("--name", default="rockie-spot")
    cp.add_argument("--secure", action="store_true", help="Use SECURE-cloud datacenters only")
    cp.add_argument("--env", nargs="*", default=[], help="KEY=VALUE pairs (e.g. --env HF_TOKEN=abc)")
    cp.add_argument("--yes", action="store_true", help="Actually submit the mutation")
    cp.add_argument("--no-wait", action="store_true", help="Don't poll for RUNNING")
    cp.add_argument("--wait-seconds", type=int, default=300)
    cp.set_defaults(func=cmd_create)

    sub.add_parser("list-pods", help="List your pods").set_defaults(func=cmd_list_pods)

    gp = sub.add_parser("get-pod", help="Fetch one pod's detail")
    gp.add_argument("pod_id")
    gp.set_defaults(func=cmd_get_pod)

    sp = sub.add_parser("stop", help="Pause a pod (keeps volume; still pay storage). Dry-run unless --yes.")
    sp.add_argument("pod_id")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_stop)

    tp = sub.add_parser("terminate", help="DELETE a pod + its volume. Final. Dry-run unless --yes.")
    tp.add_argument("pod_id")
    tp.add_argument("--yes", action="store_true")
    tp.set_defaults(func=cmd_terminate)

    cp_cost = sub.add_parser("cost", help="Current-hour spend snapshot + cumulative budget usage")
    cp_cost.set_defaults(func=cmd_cost)

    rc = sub.add_parser(
        "reconcile",
        help="Query live state, recompute actual accrued cost per pod, rewrite budget.dollars",
    )
    rc.add_argument("--verbose", "-v", action="store_true")
    rc.add_argument("--quiet", "-q", action="store_true")
    rc.set_defaults(func=cmd_reconcile)

    rp_p = sub.add_parser("resume", help="Resume a stopped pod (spot, minimum bid by default)")
    rp_p.add_argument("pod_id")
    rp_p.add_argument("--gpu-count", type=int, default=1)
    rp_p.add_argument(
        "--bid",
        type=float,
        help="Spot bid $/GPU-hr. Default: current minimumBidPrice from RunPod. "
        "Bumping above min does NOT reduce preemption risk — hop providers instead.",
    )
    rp_p.add_argument(
        "--on-demand",
        action="store_true",
        help="Resume at on-demand pricing. Last-resort only (2× spot cost).",
    )
    rp_p.add_argument("--yes", action="store_true")
    rp_p.set_defaults(func=cmd_resume)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
