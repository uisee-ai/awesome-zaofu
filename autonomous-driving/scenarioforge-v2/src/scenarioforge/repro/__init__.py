from .comparison import compare_runs, compare_trajectory_series, publish_comparison_report
from .contracts import (
    ComparisonReport,
    ContinuousComparison,
    CounterfactualResult,
    CounterfactualSpec,
    ImmutableRunReference,
    ReproductionOutcome,
    SeedContract,
    SeedField,
    ToleranceProfile,
)
from .counterfactual import apply_counterfactual, assess_counterfactual
from .runner import ReproducibilityRunner
from .matrix import P0RealMatrixRunner
from .regression import (
    P0MatrixSpec,
    PairedRegressionReport,
    PolicyRunSample,
    RegressionCase,
    RegressionContractError,
    RegressionMatrixReport,
    RegressionThresholds,
    bind_regression_policy,
    build_regression_case,
    compare_policy_pair,
    compare_regression_matrix,
    regression_contract,
)
from .seed import resolve_seeded_instance

__all__ = [
    "ComparisonReport",
    "ContinuousComparison",
    "CounterfactualResult",
    "CounterfactualSpec",
    "ImmutableRunReference",
    "P0MatrixSpec",
    "P0RealMatrixRunner",
    "PairedRegressionReport",
    "PolicyRunSample",
    "ReproducibilityRunner",
    "ReproductionOutcome",
    "RegressionCase",
    "RegressionContractError",
    "RegressionMatrixReport",
    "RegressionThresholds",
    "SeedContract",
    "SeedField",
    "ToleranceProfile",
    "apply_counterfactual",
    "assess_counterfactual",
    "bind_regression_policy",
    "build_regression_case",
    "compare_runs",
    "compare_policy_pair",
    "compare_regression_matrix",
    "compare_trajectory_series",
    "publish_comparison_report",
    "regression_contract",
    "resolve_seeded_instance",
]
