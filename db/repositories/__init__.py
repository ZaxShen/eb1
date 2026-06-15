"""Repository layer — PostgreSQL access for pipeline tables."""

from db.repositories.benchmark import BenchmarkSegmentRepository
from db.repositories.benchmark_groups import BenchmarkGroupRepository
from db.repositories.benchmark_matches import BenchmarkMatchRepository
from db.repositories.benchmark_runs import BenchmarkRunRepository
from db.repositories.pipeline_config import PipelineConfigRepository
from db.repositories.segments import SegmentRepository
from db.repositories.signals import SignalRepository
from db.repositories.taxonomy import TaxonomyRepository
from db.repositories.templates import TemplateMappingRepository

__all__ = [
    "BenchmarkGroupRepository",
    "BenchmarkMatchRepository",
    "BenchmarkRunRepository",
    "BenchmarkSegmentRepository",
    "PipelineConfigRepository",
    "SegmentRepository",
    "SignalRepository",
    "TaxonomyRepository",
    "TemplateMappingRepository",
]
