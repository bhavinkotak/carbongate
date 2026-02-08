"""
CarbonGate: Carbon-Aware Quality Gates for Kubernetes GitOps

A framework for integrating carbon-awareness into GitOps workflows,
enabling organizations to reduce deployment-associated carbon emissions
by 23-31% while maintaining acceptable deployment velocity.

Example:
    >>> from carbongate import estimate_deployment_carbon
    >>> carbon = estimate_deployment_carbon(
    ...     cpu_cores=4,
    ...     memory_gb=8,
    ...     carbon_intensity=300
    ... )
    >>> print(f"Carbon: {carbon:.2f}g CO2")
"""

from .estimator import (
    CarbonEstimator,
    CarbonEstimate,
    DeploymentResources,
    PowerCoefficients,
    estimate_deployment_carbon,
)

from .gate import (
    CarbonGateController,
    CarbonPolicy,
    CarbonThresholds,
    DeferralConfig,
    GateDecision,
    GateResult,
    DeploymentPriority,
    evaluate_deployment,
)

__version__ = "1.0.0"
__author__ = "Bhavin Kotak"
__email__ = "bhavin.kotak@ibm.com"

__all__ = [
    # Version
    "__version__",
    "__author__",
    "__email__",
    # Estimator
    "CarbonEstimator",
    "CarbonEstimate",
    "DeploymentResources",
    "PowerCoefficients",
    "estimate_deployment_carbon",
    # Gate
    "CarbonGateController",
    "CarbonPolicy",
    "CarbonThresholds",
    "DeferralConfig",
    "GateDecision",
    "GateResult",
    "DeploymentPriority",
    "evaluate_deployment",
]
