"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for who, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{who}: {p}" for p in _report_problems(rep, graded, spec)]
    # Same (item, seed) multiset as the baseline: no dropped, duplicated or cherry-picked rows.
    pk, bk = _keys(pr), _keys(base)
    if pk != bk:
        missing, extra = bk - pk, pk - bk
        problems.append(f"(item, seed) rows differ from baseline: {sum(missing.values())} missing "
                        f"{_fmt(missing)}, {sum(extra.values())} extra {_fmt(extra)}")
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"manifest seeds {pm.get('seeds')} != baseline seeds {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} != baseline items {bm.get('items')}")
    # Slice tags are derived from labels; they must not move between runs on the same eval set.
    ps, bs = _slices(pr), _slices(base)
    moved = sorted(i for i in ps.keys() & bs.keys() if ps[i] != bs[i])
    if moved:
        problems.append(f"slice tags differ from baseline for {', '.join(moved[:5])}"
                        f"{' ...' if len(moved) > 5 else ''} (e.g. {moved[0]}: {sorted(ps[moved[0]])} vs {sorted(bs[moved[0]])})")
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _keys(rep: dict) -> Counter:
    return Counter((str(r.get("item_id")), r.get("seed")) for r in rep.get("rows") or [])


def _fmt(c: Counter, n: int = 4) -> str:
    keys = [f"{i}@{s}" + (f"x{k}" if k > 1 else "") for (i, s), k in sorted(c.items(), key=str)]
    return "[" + ", ".join(keys[:n]) + (" ..." if len(keys) > n else "") + "]"


def _slices(rep: dict) -> dict[str, frozenset]:
    out: dict[str, set] = {}
    for r in rep.get("rows") or []:
        out.setdefault(str(r.get("item_id")), set()).add(frozenset(r.get("slices") or []))
    # an item whose rows disagree with each other is itself a relabelling
    return {i: (next(iter(v)) if len(v) == 1 else frozenset({"<inconsistent>"})) for i, v in out.items()}


def _bad_number(v: Any) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(rep: dict, graded: list[str], spec: dict) -> list[str]:
    problems: list[str] = []
    rows = rep.get("rows") or []
    man = rep.get("manifest") or {}
    if not rows:
        return ["report has no rows"]
    for k, v in (rep.get("metrics") or {}).items():
        if _bad_number(v):
            problems.append(f"metric {k} is {v}")
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows != {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    dup = sorted((k for k, c in _keys(rep).items() if c > 1), key=str)
    if dup:
        problems.append(f"{len(dup)} duplicated (item, seed) row(s), e.g. {dup[0][0]}@{dup[0][1]}")
    seeds = set(man.get("seeds") or [])
    off = sorted({r.get("seed") for r in rows} - seeds, key=str)
    if off:
        problems.append(f"rows with seeds {off} not in manifest seeds")
    if rep.get("evaluator_failures"):
        problems.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    nulls: Counter = Counter()
    for r in rows:
        for m in graded:
            v = r.get(m)
            if v is None or _bad_number(v) or not isinstance(v, (bool, int, float)):
                nulls[m] += 1
    problems += [f"{c} row(s) with no value for graded metric {m} (crashed / dropped grader)"
                 for m, c in sorted(nulls.items())]
    # Reported metrics must be what the rows say (no hand-edited aggregate).
    if not nulls:
        ids = [m for m in graded if all(m in r for r in rows)]
        try:
            again = aggregate([{**r, "cost": float(r.get("cost") or 0.0)} for r in rows], ids,
                              k_values=spec.get("pass_k", []))
        except Exception as exc:                      # noqa: BLE001 -- an unreadable report is untrusted
            problems.append(f"cannot recompute metrics from rows: {exc}")
            again = {}
        for k, v in (rep.get("metrics") or {}).items():
            w = again.get(k)
            if isinstance(v, (int, float)) and isinstance(w, (int, float)) and not _bad_number(v) \
                    and abs(float(v) - float(w)) > 1e-6:
                problems.append(f"metric {k}={v} but rows give {w} (aggregate edited)")
    return problems


_LOOSER = {"max": lambda new, old: new > old, "min": lambda new, old: new < old,
           "max_increase": lambda new, old: new > old}


def _threshold_looser(where: str, new: dict, old: dict) -> list[str]:
    out = []
    for key, looser in _LOOSER.items():
        if key in old:
            if key not in new:
                out.append(f"{where}: threshold {key} removed (was {old[key]})")
            elif looser(float(new[key]), float(old[key])):
                out.append(f"{where}: {key} {old[key]} -> {new[key]} is looser")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop dropped")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold may only get stricter. A new eval-set version
    starts a new baseline, so the ratchet does not apply across versions."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems: list[str] = []
    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for old in base_spec.get("metrics") or []:
        mid = old["id"]
        new = new_m.get(mid)
        if new is None:
            problems.append(f"RATCHET metric {mid} removed from spec")
            continue
        if old.get("blocking") and not new.get("blocking"):
            problems.append(f"RATCHET metric {mid} no longer blocking")
        if old.get("kind") == "safety" and new.get("kind") != "safety":
            problems.append(f"RATCHET metric {mid} kind safety -> {new.get('kind')}")
        problems += [f"RATCHET {p}" for p in _threshold_looser(f"metric {mid}", new.get("threshold") or {},
                                                                 old.get("threshold") or {})]
    key = lambda s: (s.get("name"), s.get("metric"))
    new_s = {key(s): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        new = new_s.get(key(old))
        where = f"slice {old.get('name')}/{old.get('metric')}"
        if new is None:
            problems.append(f"RATCHET {where} removed from spec")
            continue
        if old.get("blocking") and not new.get("blocking"):
            problems.append(f"RATCHET {where} no longer blocking")
        problems += [f"RATCHET {p}" for p in _threshold_looser(where, new, old)]
    for k in ("seeds", "eval_set", "labels", "adversarial_pack"):
        if base_spec.get(k) != spec.get(k):
            problems.append(f"RATCHET {k} changed {base_spec.get(k)} -> {spec.get(k)} on the same eval-set version")
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    for k in ("rng", "method", "confidence"):
        if ob.get(k) != nb.get(k):
            problems.append(f"RATCHET bootstrap {k} changed {ob.get(k)} -> {nb.get(k)} (picking the CI)")
    if int(nb.get("n_resamples", 1000)) < int(ob.get("n_resamples", 1000)):
        problems.append("RATCHET bootstrap n_resamples lowered")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "slice empty in PR"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = "ok" if verdict == "ok" else ("BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<40} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
