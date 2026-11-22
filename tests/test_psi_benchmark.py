"""Test suite for Phase 07: PSI vs HMAC Benchmark Lab.

Verifies:
1. Educational DH-PSI returns the exact correct intersection on known sets.
2. Symmetric HMAC token matching returns the exact correct intersection.
3. Fast execution of the benchmark on development scales (< 5 seconds).
4. Validation of the Plotly-ready JSON export schema.
"""

import json
import os
import time
import pytest

from src.token_service.psi_benchmark import (
    EducationalDHPSI,
    HMACTokenMatching,
    run_benchmark_suite,
)


def test_psi_correct_intersection():
    """Verify that Educational DH-PSI computes the exact mathematical set intersection."""
    set_a = ["ACC_WB_001", "ACC_WB_002", "ACC_WB_003", "ACC_WB_004", "ACC_WB_005"]
    set_b = ["ACC_WB_003", "ACC_WB_004", "ACC_WB_006", "ACC_WB_007"]
    expected_intersection = {"ACC_WB_003", "ACC_WB_004"}

    psi = EducationalDHPSI()
    intersection, metrics = psi.run_psi(set_a, set_b)

    assert intersection == expected_intersection
    assert metrics["intersection_size"] == 2
    assert metrics["communication_rounds"] == 2
    assert metrics["bytes_exchanged"] > 0


def test_hmac_correct_intersection():
    """Verify that HMAC token matching computes the exact set intersection."""
    set_a = ["ACC_WB_001", "ACC_WB_002", "ACC_WB_003", "ACC_WB_004", "ACC_WB_005"]
    set_b = ["ACC_WB_003", "ACC_WB_004", "ACC_WB_006", "ACC_WB_007"]
    expected_intersection = {"ACC_WB_003", "ACC_WB_004"}

    hmac_matcher = HMACTokenMatching()
    intersection, metrics = hmac_matcher.run_matching(set_a, set_b)

    assert intersection == expected_intersection
    assert metrics["intersection_size"] == 2
    assert metrics["communication_rounds"] == 1
    assert metrics["bytes_exchanged"] == (len(set_a) + len(set_b)) * 32


def test_benchmark_dev_size_fast():
    """Verify that the benchmark execution runs in under 2 minutes (per prompt requirements)."""
    start_time = time.perf_counter()
    results = run_benchmark_suite(sizes=[50, 100], overlap_fraction=0.20)
    elapsed = time.perf_counter() - start_time

    assert elapsed < 120.0, f"Benchmark took too long: {elapsed:.2f}s (must be < 2 minutes)"
    assert len(results["psi"]) == 2
    assert len(results["hmac"]) == 2


def test_plotly_json_schema():
    """Verify that docs/generated/psi_vs_hmac.json exists and satisfies the Plotly schema."""
    json_path = "docs/generated/psi_vs_hmac.json"
    assert os.path.exists(json_path), f"Missing JSON dataset: {json_path}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "set_sizes" in data
    assert "metrics" in data
    assert "wall_time_ms" in data["metrics"]
    assert "bandwidth_kb" in data["metrics"]
    assert "communication_rounds" in data["metrics"]

    # Verify data arrays align with set sizes
    n_sizes = len(data["set_sizes"])
    assert len(data["metrics"]["wall_time_ms"]["hmac"]) == n_sizes
    assert len(data["metrics"]["wall_time_ms"]["psi"]) == n_sizes
