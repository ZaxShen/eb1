"""
eb1 pipeline — Analyzer architecture.

Step flow (default: segment → validate → evaluate):
  segment  — Analyzer LLM: segments chat session + classifies topics in one pass [MongoDB write]
  validate — deterministic graders (G0.3–G0.9, G1.2, G1.4) check segmentation quality [read-only]
  evaluate — quality metrics (topic distribution, confidence, label sources) [read-only]

Standalone (not part of default pipeline — will move to independent pipeline):
  signal   — extract TP/FP signals from PROD matchings → matching_signals [MongoDB write]

MongoDB is only written to during segment (and signal when run explicitly).

Run all steps:
    uv run python -m pipeline

Run a single step:
    uv run python -m pipeline --step signal
    uv run python -m pipeline --step segment
    uv run python -m pipeline --step validate
    uv run python -m pipeline --step evaluate

Options:
    --limit N              Process only the first N users (segment step only)
    --relabel              Clear classification fields on unreviewed segments and re-run the Analyzer
    --benchmark NAME       Run benchmark: all models write to sms_chat_segments_{NAME}
    --benchmark-eval [NAME] Evaluate benchmark against ground truth (NAME or 'all')
    --rerun-user USER_ID   Re-segment a single user by ObjectId (use with --benchmark)
    --classify-templates   Classify PROD message templates against taxonomy (one-time setup)
    --offline-quality      Run offline quality layer: embed → HDBSCAN → cluster object
                           (NOT part of the regular pipeline — run periodically)
    --collection COL       Target a specific collection (use with --offline-quality)

Configuration:
    pipeline/config/analyzer.toml + pipeline/config/clustering.toml
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()  # inject .env into os.environ (API keys, DB URIs)

from config.settings import settings
from db.client import close_client, get_db, get_input_db
from db.pg import close_pool, get_pool
from db.repositories.pipeline_config import PipelineConfigRepository
from db.repositories.segments import SegmentRepository
from db.repositories.signals import SignalRepository
from db.repositories.taxonomy import TaxonomyRepository
from db.repositories.templates import TemplateMappingRepository
from pipeline.config.loader import (
    init_taxonomy,
    init_template_taxonomy,
    load_analyzer_config,
    load_benchmark_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

_ALL_STEPS = ["segment", "validate", "evaluate"]


# ── Step runners ──────────────────────────────────────────────────────────────


def _run_signal(db, cfg, input_db=None, **_):
    from pipeline.sampling.signal_extractor import run_signal_extraction
    return run_signal_extraction(input_db=input_db if input_db is not None else db, output_db=db, cfg=cfg)


def _run_segment(
    db, cfg, limit, input_db=None, base_url=None, user_ids=None,
    segment_repo=None, signal_repo=None, taxonomy_repo=None,
    template_repo=None, config_id=None, remap_repo=None, **_,
):
    from db.repositories.pipeline_logs import PipelineLogRepository
    from pipeline.segmentation.segmenter import run_segmenter
    pool = get_pool()
    return run_segmenter(
        input_db=input_db if input_db is not None else db,
        output_db=db, cfg=cfg, limit=limit,
        base_url=base_url if base_url is not None else cfg.base_url,
        user_ids=user_ids,
        segment_repo=segment_repo or SegmentRepository(pool),
        signal_repo=signal_repo or SignalRepository(pool),
        taxonomy_repo=taxonomy_repo or TaxonomyRepository(pool),
        template_repo=template_repo or TemplateMappingRepository(pool),
        config_id=config_id,
        remap_repo=remap_repo or PipelineLogRepository(pool),
    )


def _run_validate(db, cfg, input_db=None, segment_repo=None, **_):
    from pipeline.graders.segmentation_graders import run_all_graders
    repo = segment_repo or SegmentRepository(get_pool())
    results = run_all_graders(
        segment_repo=repo,
        input_db=input_db if input_db is not None else db,
        cfg=cfg,
    )
    all_passed = all(r.passed for r in results)
    return {
        "graders_run": len(results),
        "all_passed": all_passed,
        **{r.grader_id: "PASS" if r.passed else "FAIL" for r in results},
    }


def _run_evaluate(db, cfg, segment_repo=None, **_):
    from pipeline.evaluation.evaluator import run_evaluation
    repo = segment_repo or SegmentRepository(get_pool())
    metrics = run_evaluation(repo, cfg)
    return metrics


_STEP_FNS = {
    "signal":   _run_signal,
    "segment":  _run_segment,
    "validate": _run_validate,
    "evaluate": _run_evaluate,
}


# ── Benchmark write adapter ──────────────────────────────────────────────────


class _BenchmarkWriteAdapter:
    """Wraps BenchmarkSegmentRepository to enrich segments with run identity on insert.

    Passed as `segment_repo` to the segmenter in benchmark mode so writes go to
    eb1_benchmark_raw instead of sms_chat_segments.
    """

    def __init__(self, benchmark_repo, metadata: dict):
        self._repo = benchmark_repo
        self._metadata = metadata

    def insert_many(self, segments: list[dict]) -> int:
        rows = [{**seg, **self._metadata} for seg in segments]
        return self._repo.insert_many(rows)

    def exists_for_user(self, user_id: str) -> bool:
        return False  # benchmark always processes all users

    def find_by_user(self, user_id: str, **kwargs) -> list[dict]:
        return []  # no incremental mode in benchmark

    def find_reviewed_for_user(self, user_id: str) -> list[dict]:
        return []

    def latest_segment_for_user(self, user_id: str):
        return None  # no incremental mode in benchmark

    def delete_unreviewed_for_user(self, user_id: str) -> int:
        return 0

    def delete_unreviewed_all(self) -> int:
        return 0

    def delete_by_ids(self, ids: list[int]) -> int:
        return 0


# ── Main ──────────────────────────────────────────────────────────────────────


def _log_connection_mode() -> None:
    if settings.mongodb_input_uri:
        log.info(
            "Connection mode: Input=PROD (db=%s)  Output=Local (db=%s)",
            settings.mongodb_input_db_name or settings.mongodb_db_name,
            settings.mongodb_db_name,
        )
    else:
        log.info(
            "Connection mode: Input=Local  Output=Local (db=%s)",
            settings.mongodb_db_name,
        )


def run_pipeline(step: str, limit: int | None, relabel: bool = False) -> None:
    if not settings.postgres_dsn:
        log.error("POSTGRES_DSN is required. Set it in .env or environment.")
        sys.exit(1)

    cfg = load_analyzer_config()
    effective_limit = limit or (cfg.user_limit if cfg.user_limit > 0 else None)

    _log_connection_mode()
    input_db = get_input_db()
    # MongoDB output DB — only needed for _ensure_taxonomy_entry (legacy)
    try:
        db = get_db()
    except Exception:
        db = None
        log.warning("MongoDB output DB not available — taxonomy upserts will be skipped.")

    # PostgreSQL repositories
    pool = get_pool()
    taxonomy_repo = TaxonomyRepository(pool)
    segment_repo = SegmentRepository(pool)
    signal_repo = SignalRepository(pool)
    template_repo = TemplateMappingRepository(pool)
    pipeline_config_repo = PipelineConfigRepository(pool)

    init_taxonomy(taxonomy_repo)
    init_template_taxonomy(taxonomy_repo)

    config_id = pipeline_config_repo.get_or_create(
        model=cfg.model,
        user_prompt=cfg.prompt_version,
        bot_prompt=cfg.bot_prompt_version,
        temperature=cfg.temperature,
    )
    log.info(
        "Pipeline config_id=%d (model=%s, prompt=%s)",
        config_id, cfg.model, cfg.prompt_version,
    )

    if relabel or cfg.relabel:
        log.info("━━━ RELABEL MODE — re-running Analyzer on existing segments ━━━")
        cleared = segment_repo.clear_classification_fields()
        log.info("Cleared classification fields on %d unreviewed segments.", cleared)
        steps = ["segment", "evaluate"]
    elif step == "all":
        steps = _ALL_STEPS
    else:
        steps = [step]

    for s in steps:
        log.info("━━━ Step: %s ━━━", s)
        result = _STEP_FNS[s](
            db=db, input_db=input_db, cfg=cfg,
            limit=effective_limit,
            segment_repo=segment_repo,
            signal_repo=signal_repo,
            taxonomy_repo=taxonomy_repo,
            template_repo=template_repo,
            config_id=config_id,
        )
        if result:
            for k, v in result.items():
                log.info("  %s = %s", k, v)


def run_benchmark(
    name: str,
    rerun_user: str | None = None,
    cluster: bool = False,
    group_id_override: str | None = None,
) -> None:
    """Run the Analyzer with each benchmark config sequentially.

    All models write to a single shared collection
    ``sms_chat_segments_{name}``.  Each segment carries
    ``analyzerMeta.runId`` and ``analyzerMeta.model`` to identify
    which model produced it.

    pure_llm is derived from the model name prefix "pure_llm_" (e.g. "pure_llm_openai/gpt-5.4").
    The prefix is stripped before passing the model name to the LLM API.

    Args:
        name: Benchmark prefix — all runs write to
              ``sms_chat_segments_{name}`` in the output DB.
        rerun_user: When set, delete and re-segment only this user (ObjectId
                    string) across all benchmark runs instead of processing
                    all users.
        cluster: When True, run HDBSCAN after each LLM run (CLI --cluster
                 OR benchmark.toml ``cluster = true``).
    """
    from bson import ObjectId

    bench_cfg = load_benchmark_config()
    if not bench_cfg.runs:
        log.error("No benchmark runs. Add [[run]] entries to benchmark.toml.")
        return

    # CLI --group-id overrides toml; default to bench-YYYY-MM-DD
    if group_id_override:
        bench_cfg.group_id = group_id_override
    elif not bench_cfg.group_id:
        bench_cfg.group_id = f"bench-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        log.info("No group_id specified — using %s", bench_cfg.group_id)

    # CLI --cluster flag OR benchmark.toml cluster = true
    do_cluster = cluster or bench_cfg.cluster

    # Parse rerun_user ObjectId upfront so we fail fast on bad input
    rerun_uid = None
    if rerun_user:
        try:
            rerun_uid = ObjectId(rerun_user)
        except Exception:
            log.error("Invalid ObjectId: %s", rerun_user)
            return

    cfg = load_analyzer_config()

    # Single shared collection for all benchmark models
    collection = f"sms_chat_segments_{name}"

    if rerun_uid:
        log.info(
            "━━━ BENCHMARK RERUN — user=%s, %d run(s), collection=%s, cluster=%s ━━━",
            rerun_uid, len(bench_cfg.runs), collection, do_cluster,
        )
    else:
        log.info(
            "━━━ BENCHMARK MODE — %d run(s), collection=%s, user_sample=%.0f%%, cluster=%s ━━━",
            len(bench_cfg.runs), collection,
            bench_cfg.user_sample * 100, do_cluster,
        )

    # One-time setup — DB connections, taxonomy
    _log_connection_mode()
    input_db = get_input_db()
    # MongoDB output DB — only needed for _ensure_taxonomy_entry (legacy)
    try:
        db = get_db()
    except Exception:
        db = None
        log.warning("MongoDB output DB not available — taxonomy upserts will be skipped.")

    pool = get_pool()
    segment_repo = SegmentRepository(pool)
    signal_repo = SignalRepository(pool)
    template_repo = TemplateMappingRepository(pool)
    pipeline_config_repo = PipelineConfigRepository(pool)

    # Benchmark taxonomy: UNION ALL reads from prod + benchmark tables.
    # Writes from _ensure_taxonomy_entry go to benchmark tables only.
    from db.repositories.benchmark_taxonomy import BenchmarkTaxonomyRepository
    benchmark_taxonomy_repo = BenchmarkTaxonomyRepository(pool)
    init_taxonomy(benchmark_taxonomy_repo)
    init_template_taxonomy(benchmark_taxonomy_repo)

    from db.repositories.benchmark import BenchmarkSegmentRepository
    from db.repositories.benchmark_groups import BenchmarkGroupRepository
    from db.repositories.benchmark_runs import BenchmarkRunRepository
    from db.repositories.pipeline_logs import BenchmarkPipelineLogRepository
    benchmark_repo = BenchmarkSegmentRepository(pool)
    group_repo = BenchmarkGroupRepository(pool)
    run_repo = BenchmarkRunRepository(pool)
    benchmark_remap_repo = BenchmarkPipelineLogRepository(pool)

    group_id = group_repo.get_or_create(
        name=bench_cfg.group_id,
        type=getattr(bench_cfg, "type", "") or "",
        objective=getattr(bench_cfg, "objective", "") or "",
    )
    log.info("Benchmark group_id=%d (name=%s)", group_id, bench_cfg.group_id)

    # Benchmark uses reviewed users from sms_chat_segments (true_topic & true_sub_topic IS NOT NULL)
    all_reviewed_user_ids = segment_repo.distinct_reviewed_user_ids()
    if not all_reviewed_user_ids:
        log.error("No reviewed users found in sms_chat_segments. Cannot run benchmark.")
        return

    sample_rate = max(0.0, min(1.0, bench_cfg.user_sample))
    if sample_rate < 1.0:
        import random
        k = max(1, int(len(all_reviewed_user_ids) * sample_rate))
        benchmark_user_ids = sorted(random.sample(all_reviewed_user_ids, k))
    else:
        benchmark_user_ids = all_reviewed_user_ids
    log.info(
        "Benchmark: %d/%d reviewed users (sample=%.0f%%).",
        len(benchmark_user_ids), len(all_reviewed_user_ids), sample_rate * 100,
    )

    now = datetime.now(timezone.utc)

    for i, run in enumerate(bench_cfg.runs, 1):
        log.info(
            "━━━ Benchmark run %d/%d: %s (model=%s, user_prompt=%s, bot_prompt=%s) ━━━",
            i, len(bench_cfg.runs), bench_cfg.group_id,
            run.model, run.user_prompt, run.bot_prompt,
        )

        # Override config for this run
        is_pure_llm = run.model.startswith("pure_llm_")
        cfg.model = run.model.removeprefix("pure_llm_") if is_pure_llm else run.model
        cfg.prompt_version = run.user_prompt
        cfg.bot_prompt_version = run.bot_prompt
        cfg.temperature = run.temperature
        cfg.benchmark_mode = True
        cfg.run_id = bench_cfg.group_id
        cfg.col_output_chat_segment = collection
        cfg.pure_llm = is_pure_llm
        log.info("  group=%s, model=%s, pure_llm=%s", bench_cfg.group_id, cfg.model, is_pure_llm)
        if cfg.pure_llm:
            log.info("  pure_llm mode — all messages sent through V3 prompt (no preprocessing)")

        config_id = pipeline_config_repo.get_or_create(
            model=run.model,
            user_prompt=run.user_prompt,
            bot_prompt=run.bot_prompt,
            temperature=run.temperature,
        )
        log.info("  config_id=%d", config_id)

        # Create (or reset) a pending run entry — scores are filled by --benchmark-eval
        benchmark_run_id = run_repo.upsert({
            "group_id": group_id,
            "config_id": config_id,
            "summary": run.summary or None,
            "run_at": now,
            "total_gt_segments": 0,
            "total_model_segments": 0,
            "matched_count": 0,
            "match_rate": 0.0,
            "avg_iou": 0.0,
            "topic_accuracy": 0.0,
            "subtopic_accuracy": 0.0,
            "segment_count_ratio": 0.0,
            "ue_gt_segments": 0,
            "ue_matched_count": 0,
            "ue_match_rate": 0.0,
            "ue_topic_accuracy": 0.0,
            "ue_subtopic_accuracy": 0.0,
            "confidence_calibration": None,
            "rank": None,
        })
        log.info("  benchmark_run_id=%d", benchmark_run_id)

        # Set run context so taxonomy + remap writes carry provenance
        benchmark_taxonomy_repo.set_run_context(group_id, benchmark_run_id)
        benchmark_remap_repo.set_run_context(group_id, benchmark_run_id)

        # Delete previous raw segments for this run before inserting fresh
        benchmark_repo.delete_by_run(benchmark_run_id)

        # Adapter enriches segments with run identity and writes to eb1_benchmark_raw
        write_adapter = _BenchmarkWriteAdapter(benchmark_repo, {
            "benchmark_run_id": benchmark_run_id,
        })

        from pipeline.segmentation.segmenter import get_llm_stats, reset_llm_stats
        reset_llm_stats()
        import time as _time
        _run_start = _time.perf_counter()

        if rerun_uid:
            # Delete previous benchmark segments for this user+run+model
            deleted = benchmark_repo.delete_by_run_and_user(
                benchmark_run_id, str(rerun_uid),
            )
            log.info(
                "  deleted %d unreviewed benchmark segments for user %s run %s",
                deleted, rerun_uid, bench_cfg.group_id,
            )

            result = _STEP_FNS["segment"](
                db=db, input_db=input_db, cfg=cfg,
                limit=None,
                base_url=run.base_url,
                user_ids=[str(rerun_uid)],
                segment_repo=write_adapter,
                signal_repo=signal_repo,
                taxonomy_repo=benchmark_taxonomy_repo,
                template_repo=template_repo,
                config_id=config_id,
                remap_repo=benchmark_remap_repo,
            )
        else:
            result = _STEP_FNS["segment"](
                db=db, input_db=input_db, cfg=cfg,
                limit=None,
                base_url=run.base_url,
                user_ids=benchmark_user_ids,
                segment_repo=write_adapter,
                signal_repo=signal_repo,
                taxonomy_repo=benchmark_taxonomy_repo,
                template_repo=template_repo,
                config_id=config_id,
                remap_repo=benchmark_remap_repo,
            )

        _run_elapsed = _time.perf_counter() - _run_start
        llm_stats = get_llm_stats()
        log.info(
            "  duration=%.1fs, llm_calls=%d, avg_latency=%.0fms",
            _run_elapsed, llm_stats["llm_call_count"],
            llm_stats["avg_llm_latency_ms"],
        )

        # Update run entry with duration and latency
        run_repo.update_timing(
            benchmark_run_id,
            duration_seconds=round(_run_elapsed, 1),
            avg_llm_latency_ms=llm_stats["avg_llm_latency_ms"],
        )

        if result:
            for k, v in result.items():
                log.info("  %s = %s", k, v)

        # Validation is skipped in benchmark mode — use --benchmark-eval for quality assessment
        log.info("  validate = skipped (benchmark mode — use --benchmark-eval)")

        # Run HDBSCAN clustering — isolated by benchmark_run_id,
        # user-engaged segments only, writes back to eb1_benchmark_raw
        if do_cluster:
            from pipeline.config.loader import load_clustering_config
            from pipeline.quality.offline import run_offline_quality

            class _BenchmarkClusterAdapter:
                """Scopes clustering reads/writes to one benchmark run."""

                def __init__(self, repo, run_id: int):
                    self._repo = repo
                    self._run_id = run_id

                def find_with_summary(self):
                    return self._repo.find_with_summary_by_run(
                        self._run_id, user_engaged_only=True,
                    )

                def bulk_update_clusters(self, updates):
                    return self._repo.bulk_update_clusters(updates)

            ccfg = load_clustering_config()
            log.info(
                "  ━━━ Clustering: run_id=%d (user-engaged) ━━━",
                benchmark_run_id,
            )
            cluster_adapter = _BenchmarkClusterAdapter(
                benchmark_repo, benchmark_run_id,
            )
            cluster_result = run_offline_quality(
                cluster_adapter, ccfg, cfg,
                user_engaged_only=False,  # adapter already filters
            )
            if cluster_result:
                for k, v in cluster_result.items():
                    log.info("    %s = %s", k, v)

        log.info("━━━ Benchmark run %s complete ━━━", bench_cfg.group_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the analysis pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        choices=_ALL_STEPS + ["signal", "all"],
        default="all",
        help="Pipeline step to run (default: all — excludes signal, which must be run explicitly)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N users (segment step only)",
    )
    parser.add_argument(
        "--relabel",
        action="store_true",
        help="Clear AI classification fields on unreviewed segments and re-run the Analyzer (segment→evaluate)",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        metavar="NAME",
        default=None,
        help="Run benchmark: all models → sms_chat_segments_{NAME}",
    )
    parser.add_argument(
        "--benchmark-eval",
        type=str,
        nargs="?",
        const="all",
        default=None,
        metavar="NAME",
        help="Evaluate benchmark collections against ground truth. "
             "NAME = benchmark prefix (e.g. 'test1'), 'all' = evaluate all benchmarks.",
    )
    parser.add_argument(
        "--rerun-user",
        type=str,
        metavar="USER_ID",
        default=None,
        help="Re-segment a single user by ObjectId (use with --benchmark)",
    )
    parser.add_argument(
        "--offline-quality",
        action="store_true",
        help="Run offline quality layer: embed summaries → HDBSCAN → write cluster object",
    )
    parser.add_argument(
        "--collection",
        type=str,
        metavar="COL",
        default=None,
        help="Target a specific collection (use with --offline-quality)",
    )
    parser.add_argument(
        "--group-id",
        type=str,
        metavar="GROUP_ID",
        default=None,
        help="Benchmark group name. Defaults to 'bench-YYYY-MM-DD' if not specified. "
             "Overrides group_id in benchmark.toml.",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Run HDBSCAN after each benchmark LLM run (use with --benchmark)",
    )
    parser.add_argument(
        "--classify-templates",
        action="store_true",
        help="Classify PROD message templates with topic/subTopic from taxonomy",
    )
    args = parser.parse_args()

    try:
        if args.classify_templates:
            from pipeline.templates.classifier import run_template_classifier
            cfg = load_analyzer_config()
            input_db = get_input_db()
            pool = get_pool()
            taxonomy_repo = TaxonomyRepository(pool)
            template_repo = TemplateMappingRepository(pool)
            init_taxonomy(taxonomy_repo)
            init_template_taxonomy(taxonomy_repo)
            log.info("━━━ Template Classification ━━━")
            result = run_template_classifier(
                input_db=input_db, cfg=cfg,
                template_repo=template_repo,
                taxonomy_repo=taxonomy_repo,
            )
            if result:
                for k, v in result.items():
                    log.info("  %s = %s", k, v)
        elif args.offline_quality:
            from pipeline.config.loader import load_clustering_config
            from pipeline.quality.offline import run_offline_quality
            ccfg = load_clustering_config()
            acfg = load_analyzer_config()
            if args.collection:
                acfg.col_output_chat_segment = args.collection
            pool = get_pool()
            taxonomy_repo = TaxonomyRepository(pool)
            init_taxonomy(taxonomy_repo)
            init_template_taxonomy(taxonomy_repo)
            segment_repo = SegmentRepository(pool)
            log.info("━━━ Offline Quality Layer → %s ━━━", acfg.col_output_chat_segment)
            result = run_offline_quality(segment_repo, ccfg, acfg)
            if result:
                for k, v in result.items():
                    log.info("  %s = %s", k, v)
        elif args.benchmark_eval is not None:
            from db.repositories.benchmark import BenchmarkSegmentRepository
            from db.repositories.benchmark_groups import BenchmarkGroupRepository
            from db.repositories.benchmark_matches import BenchmarkMatchRepository
            from db.repositories.benchmark_runs import BenchmarkRunRepository
            from pipeline.evaluation.benchmark_eval import run_benchmark_eval
            pool = get_pool()
            segment_repo = SegmentRepository(pool)
            benchmark_repo = BenchmarkSegmentRepository(pool)
            match_repo = BenchmarkMatchRepository(pool)
            run_repo = BenchmarkRunRepository(pool)
            group_repo = BenchmarkGroupRepository(pool)
            eval_group_id = args.group_id  # None = evaluate all groups
            log.info("━━━ Benchmark Evaluation ━━━")
            result = run_benchmark_eval(
                segment_repo=segment_repo,
                benchmark_repo=benchmark_repo,
                match_repo=match_repo,
                run_repo=run_repo,
                group_repo=group_repo,
                name=args.benchmark_eval,
                group_id=eval_group_id,
            )
            if not result:
                log.error("Benchmark evaluation produced no results.")
        elif args.benchmark:
            run_benchmark(
                name=args.benchmark,
                rerun_user=args.rerun_user,
                cluster=args.cluster,
                group_id_override=args.group_id,
            )
        else:
            run_pipeline(step=args.step, limit=args.limit, relabel=args.relabel)
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    finally:
        close_client()
        close_pool()
