"""
CarbonGate: Carbon-Aware Quality Gates for Kubernetes GitOps

This module provides the quality gate controller for making
deployment decisions based on carbon intensity policies.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime, timedelta

from .estimator import CarbonEstimator, DeploymentResources, CarbonEstimate

logger = logging.getLogger(__name__)


class GateDecision(Enum):
    """Possible decisions from the carbon gate."""
    PROCEED = "proceed"
    PROCEED_WITH_WARNING = "proceed-with-warning"
    DEFER = "defer"
    REQUIRE_APPROVAL = "require-approval"
    BLOCKED = "blocked"


class DeploymentPriority(Enum):
    """Deployment priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class CarbonThresholds:
    """Carbon intensity thresholds for gate decisions."""
    green: float = 150.0  # g CO2/kWh
    yellow: float = 300.0
    red: float = 450.0


@dataclass
class DeferralConfig:
    """Configuration for deployment deferral."""
    max_wait_hours: float = 4.0
    check_interval_minutes: float = 15.0
    forecast_horizon_hours: float = 24.0


@dataclass
class CarbonPolicy:
    """Carbon gate policy configuration."""
    name: str
    thresholds: CarbonThresholds
    deferral: DeferralConfig
    priority_overrides: Dict[DeploymentPriority, GateDecision]
    namespace_overrides: Dict[str, GateDecision]
    
    @classmethod
    def default(cls) -> "CarbonPolicy":
        """Create a default carbon policy."""
        return cls(
            name="default-policy",
            thresholds=CarbonThresholds(),
            deferral=DeferralConfig(),
            priority_overrides={
                DeploymentPriority.CRITICAL: GateDecision.PROCEED,
                DeploymentPriority.HIGH: GateDecision.PROCEED_WITH_WARNING,
            },
            namespace_overrides={
                "production-hotfix": GateDecision.PROCEED,
                "emergency": GateDecision.PROCEED,
            }
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CarbonPolicy":
        """Create policy from dictionary (e.g., from YAML config)."""
        thresholds = CarbonThresholds(
            green=data.get("thresholds", {}).get("green", 150),
            yellow=data.get("thresholds", {}).get("yellow", 300),
            red=data.get("thresholds", {}).get("red", 450),
        )
        
        deferral = DeferralConfig(
            max_wait_hours=data.get("deferral", {}).get("maxWaitTime", "4h").rstrip("h"),
            check_interval_minutes=data.get("deferral", {}).get("checkInterval", "15m").rstrip("m"),
            forecast_horizon_hours=data.get("deferral", {}).get("forecastHorizon", "24h").rstrip("h"),
        )
        
        priority_overrides = {}
        for override in data.get("overrides", []):
            if "priority" in override:
                priority = DeploymentPriority(override["priority"])
                action = cls._parse_action(override["action"])
                priority_overrides[priority] = action
        
        namespace_overrides = {}
        for override in data.get("overrides", []):
            if "namespace" in override:
                namespace = override["namespace"]
                action = cls._parse_action(override["action"])
                namespace_overrides[namespace] = action
        
        return cls(
            name=data.get("metadata", {}).get("name", "custom-policy"),
            thresholds=thresholds,
            deferral=deferral,
            priority_overrides=priority_overrides,
            namespace_overrides=namespace_overrides,
        )
    
    @staticmethod
    def _parse_action(action_str: str) -> GateDecision:
        """Parse action string to GateDecision."""
        action_map = {
            "proceed": GateDecision.PROCEED,
            "always-proceed": GateDecision.PROCEED,
            "proceed-with-warning": GateDecision.PROCEED_WITH_WARNING,
            "defer": GateDecision.DEFER,
            "defer-or-approve": GateDecision.DEFER,
            "require-approval": GateDecision.REQUIRE_APPROVAL,
            "block": GateDecision.BLOCKED,
        }
        return action_map.get(action_str.lower(), GateDecision.DEFER)


@dataclass
class GateResult:
    """Result of a carbon gate evaluation."""
    decision: GateDecision
    carbon_estimate: CarbonEstimate
    current_intensity: float
    threshold_level: str  # "green", "yellow", or "red"
    reason: str
    recommended_wait_minutes: Optional[float] = None
    forecast_optimal_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "decision": self.decision.value,
            "carbon_estimate": self.carbon_estimate.to_dict(),
            "current_intensity": self.current_intensity,
            "threshold_level": self.threshold_level,
            "reason": self.reason,
            "recommended_wait_minutes": self.recommended_wait_minutes,
            "forecast_optimal_time": (
                self.forecast_optimal_time.isoformat() 
                if self.forecast_optimal_time else None
            ),
        }


class CarbonGateController:
    """
    Controller for making deployment decisions based on carbon intensity.
    
    Evaluates deployment requests against configured carbon policies
    and makes proceed/defer decisions.
    
    Example:
        >>> controller = CarbonGateController(policy=CarbonPolicy.default())
        >>> result = controller.evaluate(
        ...     resources=DeploymentResources(cpu_cores=4, memory_gb=8),
        ...     current_intensity=350,
        ...     priority=DeploymentPriority.NORMAL
        ... )
        >>> print(f"Decision: {result.decision.value}")
    """
    
    def __init__(
        self,
        policy: CarbonPolicy,
        estimator: Optional[CarbonEstimator] = None
    ):
        """
        Initialize the gate controller.
        
        Args:
            policy: Carbon policy configuration
            estimator: Carbon estimator instance (creates default if None)
        """
        self.policy = policy
        self.estimator = estimator or CarbonEstimator()
        
    def evaluate(
        self,
        resources: DeploymentResources,
        current_intensity: float,
        priority: DeploymentPriority = DeploymentPriority.NORMAL,
        namespace: Optional[str] = None,
        duration_minutes: float = 5.0,
        intensity_forecast: Optional[List[tuple]] = None
    ) -> GateResult:
        """
        Evaluate a deployment request against the carbon policy.
        
        Args:
            resources: Deployment resource requirements
            current_intensity: Current grid carbon intensity (gCO2/kWh)
            priority: Deployment priority level
            namespace: Kubernetes namespace (for override matching)
            duration_minutes: Expected deployment duration
            intensity_forecast: Optional list of (datetime, intensity) tuples
            
        Returns:
            GateResult with decision and details
        """
        # Calculate carbon estimate
        estimate = self.estimator.estimate(
            resources=resources,
            duration_minutes=duration_minutes,
            carbon_intensity=current_intensity
        )
        
        # Check for priority override
        if priority in self.policy.priority_overrides:
            override_decision = self.policy.priority_overrides[priority]
            return GateResult(
                decision=override_decision,
                carbon_estimate=estimate,
                current_intensity=current_intensity,
                threshold_level=self._get_threshold_level(current_intensity),
                reason=f"Priority override: {priority.value} -> {override_decision.value}"
            )
        
        # Check for namespace override
        if namespace and namespace in self.policy.namespace_overrides:
            override_decision = self.policy.namespace_overrides[namespace]
            return GateResult(
                decision=override_decision,
                carbon_estimate=estimate,
                current_intensity=current_intensity,
                threshold_level=self._get_threshold_level(current_intensity),
                reason=f"Namespace override: {namespace} -> {override_decision.value}"
            )
        
        # Evaluate against thresholds
        thresholds = self.policy.thresholds
        
        if current_intensity <= thresholds.green:
            return GateResult(
                decision=GateDecision.PROCEED,
                carbon_estimate=estimate,
                current_intensity=current_intensity,
                threshold_level="green",
                reason=f"Carbon intensity ({current_intensity} gCO2/kWh) is below green threshold ({thresholds.green})"
            )
        
        elif current_intensity <= thresholds.yellow:
            return GateResult(
                decision=GateDecision.PROCEED_WITH_WARNING,
                carbon_estimate=estimate,
                current_intensity=current_intensity,
                threshold_level="yellow",
                reason=f"Carbon intensity ({current_intensity} gCO2/kWh) is in yellow zone. Consider deferring non-urgent deployments."
            )
        
        else:  # Red zone
            # Calculate recommended wait time from forecast
            wait_minutes = None
            optimal_time = None
            
            if intensity_forecast:
                optimal = self._find_optimal_window(intensity_forecast)
                if optimal:
                    optimal_time, optimal_intensity = optimal
                    wait_minutes = (optimal_time - datetime.now()).total_seconds() / 60
                    
                    # Cap at max wait time
                    max_wait = self.policy.deferral.max_wait_hours * 60
                    if wait_minutes > max_wait:
                        wait_minutes = None
                        optimal_time = None
            
            return GateResult(
                decision=GateDecision.DEFER,
                carbon_estimate=estimate,
                current_intensity=current_intensity,
                threshold_level="red",
                reason=f"Carbon intensity ({current_intensity} gCO2/kWh) exceeds red threshold ({thresholds.red}). Deferring deployment.",
                recommended_wait_minutes=wait_minutes,
                forecast_optimal_time=optimal_time
            )
    
    def _get_threshold_level(self, intensity: float) -> str:
        """Get the threshold level for an intensity value."""
        if intensity <= self.policy.thresholds.green:
            return "green"
        elif intensity <= self.policy.thresholds.yellow:
            return "yellow"
        else:
            return "red"
    
    def _find_optimal_window(
        self,
        forecast: List[tuple]
    ) -> Optional[tuple]:
        """
        Find the optimal deployment window from forecast.
        
        Args:
            forecast: List of (datetime, intensity) tuples
            
        Returns:
            Tuple of (optimal_time, intensity) or None
        """
        if not forecast:
            return None
        
        # Find minimum intensity in forecast
        min_intensity = float('inf')
        optimal_time = None
        
        for time, intensity in forecast:
            if intensity < min_intensity:
                min_intensity = intensity
                optimal_time = time
        
        # Only recommend if significantly better
        if optimal_time and min_intensity < self.policy.thresholds.yellow:
            return (optimal_time, min_intensity)
        
        return None


def evaluate_deployment(
    cpu_cores: float,
    memory_gb: float,
    current_intensity: float,
    priority: str = "normal",
    policy: Optional[CarbonPolicy] = None
) -> Dict[str, Any]:
    """
    Convenience function to evaluate a deployment.
    
    Args:
        cpu_cores: CPU cores requested
        memory_gb: Memory in GB requested
        current_intensity: Current grid carbon intensity
        priority: Deployment priority ("critical", "high", "normal", "low")
        policy: Carbon policy (uses default if None)
        
    Returns:
        Dictionary with gate decision and details
    """
    controller = CarbonGateController(policy=policy or CarbonPolicy.default())
    resources = DeploymentResources(cpu_cores=cpu_cores, memory_gb=memory_gb)
    priority_enum = DeploymentPriority(priority.lower())
    
    result = controller.evaluate(
        resources=resources,
        current_intensity=current_intensity,
        priority=priority_enum
    )
    
    return result.to_dict()


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Create controller with default policy
    policy = CarbonPolicy.default()
    controller = CarbonGateController(policy=policy)
    
    # Define deployment resources
    resources = DeploymentResources(cpu_cores=4, memory_gb=8, replicas=3)
    
    # Test at different intensity levels
    print("\n=== Carbon Gate Evaluation ===\n")
    
    for intensity in [100, 200, 350, 500]:
        result = controller.evaluate(
            resources=resources,
            current_intensity=intensity,
            priority=DeploymentPriority.NORMAL
        )
        print(f"Intensity: {intensity} gCO2/kWh")
        print(f"  Decision: {result.decision.value}")
        print(f"  Level: {result.threshold_level}")
        print(f"  Carbon: {result.carbon_estimate.total_grams_co2:.2f}g CO2")
        print(f"  Reason: {result.reason}")
        print()
    
    # Test critical priority override
    print("\n=== Priority Override Test ===\n")
    result = controller.evaluate(
        resources=resources,
        current_intensity=500,
        priority=DeploymentPriority.CRITICAL
    )
    print(f"Critical priority at 500 gCO2/kWh:")
    print(f"  Decision: {result.decision.value}")
    print(f"  Reason: {result.reason}")
