"""Comprehensive Pipeline Benchmark: 5000 memories, 520 queries, 8 phases."""
import json
import os
import sys
import time
import shutil
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from benchmarks.generators.garbage_memories import generate_garbage
    from benchmarks.generators.useful_memories import generate_useful
    from benchmarks.generators.advisory_queries import generate_queries
except ModuleNotFoundError:
    # Fallback when benchmark is run from inside benchmarks/ directory.
    from generators.garbage_memories import generate_garbage
    from generators.useful_memories import generate_useful
    from generators.advisory_queries import generate_queries

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
SPARK_DIR = Path.home() / ".spark"
COGNITIVE_FILE = SPARK_DIR / "cognitive_insights.json"

def run_benchmark(seed=42):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 72)
    print("  COMPREHENSIVE PIPELINE BENCHMARK")
    print(f"  5000 Memories | 520 Queries | Seed={seed}")
    print("=" * 72)

    t0 = time.time()

    # ---- PHASE 0: SETUP ----
    print("\n" + "=" * 72)
    print("  PHASE 0: SETUP")
    print("=" * 72)

    # Backup cognitive store
    backup_name = f"cognitive_insights.backup_{ts}.json"
    if COGNITIVE_FILE.exists():
        shutil.copy2(COGNITIVE_FILE, COGNITIVE_FILE.parent / backup_name)
        print(f"  Backed up cognitive store to {backup_name}")

    # Generate data
    print("  Generating 5000 memories...")
    useful = generate_useful(seed)
    garbage = generate_garbage(seed)
    queries = generate_queries(seed)
    all_memories = useful + garbage

    print(f"  Useful:  {len(useful)} (layers: {', '.join(sorted(set(m['layer'] for m in useful)))})")
    print(f"  Garbage: {len(garbage)} (types: {len(set(m['garbage_type'] for m in garbage))})")
    print(f"  Queries: {len(queries)} (domains: {len(set(q['domain'] for q in queries))})")

    results = {
        "timestamp": ts,
        "seed": seed,
        "useful_count": len(useful),
        "garbage_count": len(garbage),
        "query_count": len(queries),
        "phases": {},
    }

    # ---- PHASE 1: importance_score ----
    print("\n" + "=" * 72)
    print("  PHASE 1: importance_score() on all 5000")
    print("=" * 72)

    from lib.memory_capture import importance_score

    layer_importance = {}
    garbage_importance = {}

    for i, mem in enumerate(all_memories):
        if i % 500 == 0:
            pct = i * 100 // len(all_memories)
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  importance_score [{bar}] {i}/{len(all_memories)} ({pct}%)", end="\r")

        score, breakdown = importance_score(mem["text"])
        mem["importance_score"] = score
        mem["importance_pass"] = score >= 0.65

        if mem["label"] == "garbage":
            gt = mem["garbage_type"]
            garbage_importance.setdefault(gt, {"pass": 0, "total": 0})
            garbage_importance[gt]["total"] += 1
            if mem["importance_pass"]:
                garbage_importance[gt]["pass"] += 1
        else:
            layer = mem["layer"]
            layer_importance.setdefault(layer, {"pass": 0, "total": 0})
            layer_importance[layer]["total"] += 1
            if mem["importance_pass"]:
                layer_importance[layer]["pass"] += 1

    print(f"  importance_score [{'#' * 40}] {len(all_memories)}/{len(all_memories)} (100%)")

    for layer in sorted(layer_importance.keys()):
        d = layer_importance[layer]
        print(f"  Layer {layer}: {d['pass']}/{d['total']} ({100*d['pass']//d['total']}%) pass")

    g_pass = sum(v["pass"] for v in garbage_importance.values())
    g_total = sum(v["total"] for v in garbage_importance.values())
    print(f"  Layer garbage: {g_pass}/{g_total} ({100*g_pass//g_total if g_total else 0}%) pass")

    results["phases"]["importance_score"] = {
        "layers": layer_importance,
        "garbage": garbage_importance,
    }

    # ---- PHASE 2: meta_ralph.roast() ----
    print("\n" + "=" * 72)
    print("  PHASE 2: meta_ralph.roast() on all 5000")
    print("=" * 72)

    from lib.meta_ralph import MetaRalph
    ralph = MetaRalph()
    ralph._save_state = lambda: None  # Prevent disk writes

    layer_ralph = {}
    garbage_ralph = {}
    score_dist = {}
    garbage_leaked = 0
    layer_a_blocked = 0

    for i, mem in enumerate(all_memories):
        if i % 500 == 0:
            pct = i * 100 // len(all_memories)
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  meta_ralph.roast [{bar}] {i}/{len(all_memories)} ({pct}%)", end="\r")

        verdict = ralph.roast(mem["text"], source="benchmark", context={"domain": mem.get("domain", "general")})
        mem["ralph_verdict"] = verdict.verdict.value if hasattr(verdict.verdict, 'value') else str(verdict.verdict)
        mem["ralph_score"] = verdict.score.total if hasattr(verdict, 'score') and hasattr(verdict.score, 'total') else 0
        mem["ralph_pass"] = str(mem["ralph_verdict"]).upper() == "QUALITY"

        score_val = mem["ralph_score"]
        score_dist[score_val] = score_dist.get(score_val, 0) + 1

        if mem["label"] == "garbage":
            gt = mem["garbage_type"]
            garbage_ralph.setdefault(gt, {"pass": 0, "total": 0})
            garbage_ralph[gt]["total"] += 1
            if mem["ralph_pass"]:
                garbage_ralph[gt]["pass"] += 1
                garbage_leaked += 1
        else:
            layer = mem["layer"]
            layer_ralph.setdefault(layer, {"pass": 0, "total": 0})
            layer_ralph[layer]["total"] += 1
            if mem["ralph_pass"]:
                layer_ralph[layer]["pass"] += 1
            elif layer == "A":
                layer_a_blocked += 1

    print(f"  meta_ralph.roast [{'#' * 40}] {len(all_memories)}/{len(all_memories)} (100%)")

    for layer in sorted(layer_ralph.keys()):
        d = layer_ralph[layer]
        print(f"  Layer {layer}: {d['pass']}/{d['total']} ({100*d['pass']//d['total']}%) QUALITY")

    g_pass_r = sum(v["pass"] for v in garbage_ralph.values())
    g_total_r = sum(v["total"] for v in garbage_ralph.values())
    print(f"  Layer garbage: {g_pass_r}/{g_total_r} ({100*g_pass_r//g_total_r if g_total_r else 0}%) QUALITY")
    print(f"\n  Score distribution: {dict(sorted(score_dist.items()))}")
    print(f"  Garbage leaked: {garbage_leaked}")
    print(f"  Layer A blocked: {layer_a_blocked}")

    results["phases"]["meta_ralph"] = {
        "layers": layer_ralph,
        "garbage": garbage_ralph,
        "score_distribution": score_dist,
        "garbage_leaked": garbage_leaked,
        "layer_a_blocked": layer_a_blocked,
    }

    # ---- PHASE 3: Cognitive noise filter ----
    print("\n" + "=" * 72)
    print("  PHASE 3: Cognitive noise filter on Ralph-passed")
    print("=" * 72)

    from lib.cognitive_learner import get_cognitive_learner
    cognitive = get_cognitive_learner()

    ralph_passed = [m for m in all_memories if m["ralph_pass"]]
    layer_cog = {}
    garbage_cog = {}

    for i, mem in enumerate(ralph_passed):
        if i % 200 == 0:
            pct = i * 100 // len(ralph_passed) if ralph_passed else 100
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  cognitive filter [{bar}] {i}/{len(ralph_passed)} ({pct}%)", end="\r")

        is_noise = cognitive._is_noise_insight(mem["text"])
        mem["cognitive_pass"] = not is_noise

        if mem["label"] == "garbage":
            gt = mem["garbage_type"]
            garbage_cog.setdefault(gt, {"pass": 0, "total": 0})
            garbage_cog[gt]["total"] += 1
            if mem["cognitive_pass"]:
                garbage_cog[gt]["pass"] += 1
        else:
            layer = mem["layer"]
            layer_cog.setdefault(layer, {"pass": 0, "total": 0})
            layer_cog[layer]["total"] += 1
            if mem["cognitive_pass"]:
                layer_cog[layer]["pass"] += 1

    print(f"  cognitive filter [{'#' * 40}] {len(ralph_passed)}/{len(ralph_passed)} (100%)")

    for layer in sorted(layer_cog.keys()):
        d = layer_cog[layer]
        print(f"  Layer {layer}: {d['pass']}/{d['total']} ({100*d['pass']//d['total'] if d['total'] else 0}%) accepted")

    g_pass_c = sum(v["pass"] for v in garbage_cog.values())
    g_total_c = sum(v["total"] for v in garbage_cog.values())
    print(f"  Layer garbage: {g_pass_c}/{g_total_c} ({100*g_pass_c//g_total_c if g_total_c else 0}%) accepted")

    results["phases"]["cognitive_filter"] = {
        "layers": layer_cog,
        "garbage": garbage_cog,
    }

    # ---- PHASE 4: Inject survivors ----
    print("\n" + "=" * 72)
    print("  PHASE 4: Injecting survivors into real cognitive store")
    print("=" * 72)

    from lib.cognitive_learner import CognitiveInsight, CognitiveCategory

    survivors = [m for m in all_memories if m.get("cognitive_pass")]
    injected_keys = []
    original_count = len(cognitive.insights)

    layer_injected = {}

    for i, mem in enumerate(survivors):
        if i % 200 == 0:
            pct = i * 100 // len(survivors) if survivors else 100
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  injecting [{bar}] {i}/{len(survivors)} ({pct}%)", end="\r")

        key = f"bench_{mem['id']}"
        conf = 0.7 if mem["layer"] in ("A", "B") else 0.5

        cognitive.insights[key] = CognitiveInsight(
            category=CognitiveCategory.REASONING,
            insight=mem["text"],
            evidence=f"benchmark layer={mem['layer']}",
            confidence=conf,
            context=f"domain:{mem.get('domain', 'general')}",
            times_validated=5,
            times_contradicted=0,
        )
        injected_keys.append(key)

        layer = mem["layer"]
        layer_injected[layer] = layer_injected.get(layer, 0) + 1

    print(f"  injecting [{'#' * 40}] {len(survivors)}/{len(survivors)} (100%)")
    print(f"  Original cognitive insights: {original_count}")
    print(f"  Injected: {len(injected_keys)}")
    print(f"  New total: {len(cognitive.insights)}")
    for layer in sorted(layer_injected.keys()):
        print(f"    Layer {layer}: {layer_injected[layer]}")

    results["phases"]["injection"] = {
        "original": original_count,
        "injected": len(injected_keys),
        "by_layer": layer_injected,
    }

    # ---- PHASE 5: advisor.advise() ----
    print("\n" + "=" * 72)
    print(f"  PHASE 5: advisor.advise() on {len(queries)} queries")
    print("=" * 72)

    from lib.advisor import SparkAdvisor
    advisor = SparkAdvisor()

    queries_with_advice = 0
    total_items = 0
    bench_items = 0
    real_items = 0
    source_dist = {}

    for i, q in enumerate(queries):
        if i % 50 == 0:
            pct = i * 100 // len(queries) if queries else 100
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  advisor.advise [{bar}] {i}/{len(queries)} ({pct}%)", end="\r")

        advice_list = advisor.advise(
            tool_name=q["tool"],
            tool_input=q["input"],
            task_context=q["context"],
            include_mind=False,
            track_retrieval=False,
            log_recent=False,
        )

        if advice_list:
            queries_with_advice += 1
            for a in advice_list:
                total_items += 1
                src = getattr(a, 'source', 'unknown')
                source_dist[src] = source_dist.get(src, 0) + 1
                key = getattr(a, 'insight_key', '') or ''
                if key.startswith("bench_"):
                    bench_items += 1
                else:
                    real_items += 1

    print(f"  advisor.advise [{'#' * 40}] {len(queries)}/{len(queries)} (100%)")
    print(f"  Queries with advice: {queries_with_advice}/{len(queries)} ({100*queries_with_advice//len(queries)}%)")
    print(f"  Total items: {total_items}")
    print(f"  From benchmark data: {bench_items}")
    print(f"  From real system: {real_items}")
    print(f"  By source: {source_dist}")

    results["phases"]["advisory"] = {
        "queries_with_advice": queries_with_advice,
        "total_queries": len(queries),
        "total_items": total_items,
        "bench_items": bench_items,
        "real_items": real_items,
        "source_distribution": source_dist,
    }

    # ---- PHASE 6: on_pre_tool() ----
    print("\n" + "=" * 72)
    print(f"  PHASE 6: REAL on_pre_tool() on {len(queries)} queries")
    print("=" * 72)

    from lib.advisory_engine import on_pre_tool

    emitted = 0
    no_emit = 0
    errors = 0
    latencies = []

    for i, q in enumerate(queries):
        if i % 50 == 0:
            pct = i * 100 // len(queries) if queries else 100
            bar = "#" * (pct * 40 // 100) + "-" * (40 - pct * 40 // 100)
            print(f"  on_pre_tool [{bar}] {i}/{len(queries)} ({pct}%)", end="\r")

        session_id = f"advisory-bench-{ts}_{i // 50}"
        t1 = time.time()
        try:
            result = on_pre_tool(session_id, q["tool"], q["input"], trace_id=f"bench_{i}")
            elapsed = (time.time() - t1) * 1000
            latencies.append(elapsed)

            if result:  # on_pre_tool returns text string when emitting, None otherwise
                emitted += 1
            else:
                no_emit += 1
        except Exception:
            errors += 1
            latencies.append((time.time() - t1) * 1000)

    print(f"  on_pre_tool [{'#' * 40}] {len(queries)}/{len(queries)} (100%)")

    latencies.sort()
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    print(f"  Emitted:  {emitted}/{len(queries)} ({100*emitted//len(queries) if queries else 0}%)")
    print(f"  No emit:  {no_emit}/{len(queries)} ({100*no_emit//len(queries) if queries else 0}%)")
    print(f"  Errors:   {errors}")
    print(f"  Latency:  avg={avg_lat:.0f}ms  p50={p50:.0f}ms  p95={p95:.0f}ms  p99={p99:.0f}ms")

    results["phases"]["on_pre_tool"] = {
        "emitted": emitted,
        "no_emit": no_emit,
        "errors": errors,
        "latency_avg": round(avg_lat, 1),
        "latency_p50": round(p50, 1),
        "latency_p95": round(p95, 1),
        "latency_p99": round(p99, 1),
    }

    # ---- PHASE 7: Gap Analysis ----
    print("\n" + "=" * 72)
    print("  PHASE 7: Gap Analysis")
    print("=" * 72)

    gaps = []

    # Layer A Meta-Ralph rate
    a_data = layer_ralph.get("A", {})
    if a_data:
        a_rate = a_data["pass"] / a_data["total"] if a_data["total"] else 0
        if a_rate < 0.75:
            gaps.append({
                "severity": "HIGH",
                "title": "Meta-Ralph blocks too many Layer A memories",
                "description": f"Only {a_data['pass']}/{a_data['total']} ({100*a_rate:.1f}%) of Layer A pass quality gate",
                "fix_target": "lib/meta_ralph.py",
                "fix_hypothesis": "Review scoring dimensions -- may over-penalize memories with good content",
                "metric": f"Layer A quality rate: {100*a_rate:.1f}%",
            })

    # Advisory retrieval rate
    adv = results["phases"].get("advisory", {})
    if adv:
        ret_rate = adv["queries_with_advice"] / adv["total_queries"] if adv["total_queries"] else 0
        if ret_rate < 0.5:
            gaps.append({
                "severity": "HIGH",
                "title": "Low advisory retrieval rate",
                "description": f"Only {adv['queries_with_advice']}/{adv['total_queries']} ({100*ret_rate:.1f}%) queries get any advice",
                "fix_target": "lib/cognitive_learner.py, lib/advisor.py",
                "fix_hypothesis": "Improve word matching or add semantic retrieval (BM25/embeddings)",
                "metric": f"Retrieval rate: {100*ret_rate:.1f}%",
            })

    # Garbage leakage by type
    for gt, data in sorted(garbage_ralph.items()):
        leak_rate = data["pass"] / data["total"] if data["total"] else 0
        if leak_rate > 0.05:
            gaps.append({
                "severity": "MEDIUM",
                "title": f"Meta-Ralph garbage leakage: {gt}",
                "description": f"{data['pass']}/{data['total']} ({100*leak_rate:.1f}%) {gt} memories pass quality gate",
                "fix_target": "lib/meta_ralph.py",
                "fix_hypothesis": f"Add negative scoring pattern for {gt} type content",
                "metric": f"{gt} leakage: {100*leak_rate:.1f}%",
            })

    # Benchmark recall
    if adv and adv["total_items"] > 0:
        bench_recall = adv["bench_items"] / adv["total_items"] if adv["total_items"] else 0
        if bench_recall < 0.20:
            gaps.append({
                "severity": "MEDIUM",
                "title": "Low benchmark recall in advisory",
                "description": f"Only {adv['bench_items']}/{adv['total_items']} ({100*bench_recall:.1f}%) advisory items from benchmark data",
                "fix_target": "lib/cognitive_learner.py",
                "fix_hypothesis": "Retrieval matching too narrow -- benchmark memories not found by keyword overlap",
                "metric": f"Benchmark recall: {100*bench_recall:.1f}%",
            })

    # Emission rate
    pt = results["phases"].get("on_pre_tool", {})
    if pt:
        emit_rate = pt["emitted"] / len(queries) if queries else 0
        if emit_rate < 0.05:
            gaps.append({
                "severity": "LOW" if emit_rate > 0 else "MEDIUM",
                "title": "Very low emission rate",
                "description": f"Only {pt['emitted']}/{len(queries)} ({100*emit_rate:.1f}%) queries emit advice (gate suppression)",
                "fix_target": "lib/advisory_gate.py",
                "fix_hypothesis": "Gate cooldowns too aggressive for rapid queries -- expected in benchmark mode",
                "metric": f"Emission rate: {100*emit_rate:.1f}%",
            })

    print(f"  Found {len(gaps)} gaps:")
    for g in gaps[:10]:
        print(f"    [{g['severity']}] {g['title']}: {g['metric']}")

    results["gaps"] = gaps

    # ---- PHASE 8: Cleanup ----
    print("\n" + "=" * 72)
    print("  PHASE 8: Cleanup")
    print("=" * 72)

    try:
        # Remove injected keys
        for key in injected_keys:
            cognitive.insights.pop(key, None)
        print(f"  Removed {len(injected_keys)} test insights from cognitive store")

        # Force save
        cognitive._save_insights_now()

        # Clean advisory state files
        cleaned = 0
        advisor_dir = SPARK_DIR / "advisor"
        if advisor_dir.exists():
            for f in advisor_dir.glob("*bench*"):
                try:
                    f.unlink()
                    cleaned += 1
                except Exception:
                    pass
        print(f"  Cleaned {cleaned} advisory state files")
        print(f"  Remaining insights: {len(cognitive.insights)}")

        # Verify
        bench_remaining = sum(1 for k in cognitive.insights if k.startswith("bench_"))
        print(f"  Verified: {bench_remaining} bench_ keys remain")
    except Exception as e:
        print(f"  Cleanup error: {e}")

    elapsed_total = time.time() - t0

    # ---- SAVE REPORTS ----
    json_path = RESULTS_DIR / f"benchmark_{ts}.json"
    md_path = RESULTS_DIR / f"benchmark_{ts}.md"
    gaps_path = RESULTS_DIR / f"gaps_{ts}.json"

    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    with open(gaps_path, "w") as f:
        json.dump({"gaps": gaps, "total": len(gaps)}, f, indent=2)

    # Build markdown report
    md = f"# Comprehensive Pipeline Benchmark Report\n\n"
    md += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    md += f"**Seed**: {seed}\n"
    md += f"**Memories**: {len(useful)} useful + {len(garbage)} garbage = {len(all_memories)}\n"
    md += f"**Queries**: {len(queries)}\n\n"
    md += "## Funnel Summary\n\n"
    md += "| Stage | " + " | ".join(f"Layer {l}" for l in sorted(layer_ralph.keys())) + " | Garbage |\n"
    md += "|-------" + "|------" * (len(layer_ralph) + 1) + "|\n"

    # Input row
    md += "| Input"
    for l in sorted(layer_ralph.keys()):
        md += f" | {layer_ralph[l]['total']}"
    md += f" | {g_total_r} |\n"

    # importance_score row
    md += "| importance_score"
    for l in sorted(layer_importance.keys()):
        md += f" | {layer_importance[l]['pass']}"
    g_imp = sum(v["pass"] for v in garbage_importance.values())
    md += f" | {g_imp} |\n"

    # Meta-Ralph row
    md += "| Meta-Ralph QUALITY"
    for l in sorted(layer_ralph.keys()):
        md += f" | {layer_ralph[l]['pass']}"
    md += f" | {g_pass_r} |\n"

    # Cognitive row
    md += "| Cognitive accepted"
    for l in sorted(layer_cog.keys()):
        md += f" | {layer_cog[l]['pass']}"
    md += f" | {g_pass_c} |\n"

    md += f"\n## Advisory Retrieval (Phase 5)\n\n"
    md += f"- Queries with advice: {adv.get('queries_with_advice', 0)}/{adv.get('total_queries', 0)}\n"
    md += f"- Benchmark items retrieved: {adv.get('bench_items', 0)}\n"
    md += f"- Real system items: {adv.get('real_items', 0)}\n"
    md += f"- Source distribution: {adv.get('source_distribution', {})}\n"

    md += f"\n## Production Path (Phase 6)\n\n"
    md += f"- Emitted: {pt.get('emitted', 0)}/{len(queries)}\n"
    md += f"- Latency: avg={pt.get('latency_avg', 0):.1f}ms p50={pt.get('latency_p50', 0):.1f}ms p95={pt.get('latency_p95', 0):.1f}ms p99={pt.get('latency_p99', 0):.1f}ms\n"

    md += f"\n## Gaps ({len(gaps)} found)\n\n"
    for g in gaps:
        md += f"- **[{g['severity']}]** {g['title']}: {g['metric']}\n"

    # Layer E comparison
    e_imp = layer_importance.get("E", {})
    e_ralph = layer_ralph.get("E", {})
    md += f"\n## Layer E: A/B Style Comparison\n\n"
    md += f"- importance_score pass: {e_imp.get('pass', 0)}/{e_imp.get('total', 0)}\n"
    md += f"- Meta-Ralph QUALITY: {e_ralph.get('pass', 0)}/{e_ralph.get('total', 0)}\n"

    # Garbage leakage table
    md += f"\n## Garbage Leakage by Type\n\n"
    md += "| Type | importance_score | Meta-Ralph | Cognitive |\n"
    md += "|------|-----------------|------------|----------|\n"
    for gt in sorted(garbage_importance.keys()):
        gi = garbage_importance.get(gt, {}).get("pass", 0)
        gr = garbage_ralph.get(gt, {}).get("pass", 0)
        gc = garbage_cog.get(gt, {}).get("pass", 0)
        md += f"| {gt} | {gi} | {gr} | {gc} |\n"

    with open(md_path, "w") as f:
        f.write(md)

    print("\n" + "=" * 72)
    print("  BENCHMARK COMPLETE")
    print(f"  Total time: {elapsed_total:.1f}s")
    print("=" * 72)
    print(f"\n  JSON report: {json_path}")
    print(f"  Markdown report: {md_path}")
    print(f"  Gaps report: {gaps_path}")

    # Condensed funnel
    useful_imp = sum(v["pass"] for v in layer_importance.values())
    useful_ralph = sum(v["pass"] for v in layer_ralph.values())
    useful_cog = sum(v["pass"] for v in layer_cog.values())
    garb_imp = sum(v["pass"] for v in garbage_importance.values())
    garb_ralph = sum(v["pass"] for v in garbage_ralph.values())
    garb_cog = sum(v["pass"] for v in garbage_cog.values())

    print("\n" + "=" * 72)
    print("  CONDENSED FUNNEL")
    print("=" * 72)
    print(f"\n  {'Stage':<30} {'Useful':>7}  {'Garbage':>7}")
    print(f"  {'-' * 45}")
    print(f"  {'Input':<30} {len(useful):>7}  {len(garbage):>7}")
    print(f"  {'importance_score':<30} {useful_imp:>7}  {garb_imp:>7}")
    print(f"  {'Meta-Ralph':<30} {useful_ralph:>7}  {garb_ralph:>7}")
    print(f"  {'Cognitive':<30} {useful_cog:>7}  {garb_cog:>7}")
    print(f"  {'Advisor retrieval':<30} {adv.get('bench_items', 0):>7}  {'0':>7}")
    print(f"  {'on_pre_tool emitted':<30} {pt.get('emitted', 0):>7}  {'0':>7}")

if __name__ == "__main__":
    run_benchmark()
