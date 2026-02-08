"""
Tests for CarbonGate gate controller module.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from carbongate.gate import (
    CarbonGateController,
    CarbonPolicy,
    CarbonThresholds,
    DeferralConfig,
    GateDecision,
    GateResult,
    DeploymentPriority,
    evaluate_deployment,
)
from carbongate.estimator import DeploymentResources


class TestCarbonThresholds:
    """Tests for CarbonThresholds dataclass."""
    
    def test_default_values(self):
        """Test default threshold values."""
        thresholds = CarbonThresholds()
        
        assert thresholds.green == 150.0
        assert thresholds.yellow == 300.0
        assert thresholds.red == 450.0
    
    def test_custom_values(self):
        """Test custom threshold values."""
        thresholds = CarbonThresholds(
            green=100.0,
            yellow=200.0,
            red=400.0
        )
        
        assert thresholds.green == 100.0
        assert thresholds.yellow == 200.0
        assert thresholds.red == 400.0


class TestCarbonPolicy:
    """Tests for CarbonPolicy dataclass."""
    
    def test_default_policy(self):
        """Test default policy creation."""
        policy = CarbonPolicy.default()
        
        assert policy.name == "default-policy"
        assert policy.thresholds.green == 150.0
        assert DeploymentPriority.CRITICAL in policy.priority_overrides
    
    def test_from_dict(self):
        """Test policy creation from dictionary."""
        data = {
            "metadata": {"name": "test-policy"},
            "thresholds": {
                "green": 100,
                "yellow": 250,
                "red": 400
            },
            "deferral": {
                "maxWaitTime": "2h",
                "checkInterval": "10m",
            },
            "overrides": [
                {"priority": "critical", "action": "always-proceed"},
                {"namespace": "emergency", "action": "proceed"}
            ]
        }
        
        policy = CarbonPolicy.from_dict(data)
        
        assert policy.name == "test-policy"
        assert policy.thresholds.green == 100
        assert DeploymentPriority.CRITICAL in policy.priority_overrides
        assert "emergency" in policy.namespace_overrides


class TestCarbonGateController:
    """Tests for CarbonGateController class."""
    
    @pytest.fixture
    def controller(self):
        """Create a controller with default policy."""
        return CarbonGateController(policy=CarbonPolicy.default())
    
    @pytest.fixture
    def resources(self):
        """Create sample deployment resources."""
        return DeploymentResources(cpu_cores=4, memory_gb=8)
    
    def test_evaluate_green_zone(self, controller, resources):
        """Test evaluation in green zone."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=100,
            priority=DeploymentPriority.NORMAL
        )
        
        assert result.decision == GateDecision.PROCEED
        assert result.threshold_level == "green"
    
    def test_evaluate_yellow_zone(self, controller, resources):
        """Test evaluation in yellow zone."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=250,
            priority=DeploymentPriority.NORMAL
        )
        
        assert result.decision == GateDecision.PROCEED_WITH_WARNING
        assert result.threshold_level == "yellow"
    
    def test_evaluate_red_zone(self, controller, resources):
        """Test evaluation in red zone."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=500,
            priority=DeploymentPriority.NORMAL
        )
        
        assert result.decision == GateDecision.DEFER
        assert result.threshold_level == "red"
    
    def test_evaluate_critical_priority_override(self, controller, resources):
        """Test critical priority bypasses red zone."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=500,
            priority=DeploymentPriority.CRITICAL
        )
        
        assert result.decision == GateDecision.PROCEED
        assert "Priority override" in result.reason
    
    def test_evaluate_high_priority_override(self, controller, resources):
        """Test high priority in red zone."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=500,
            priority=DeploymentPriority.HIGH
        )
        
        assert result.decision == GateDecision.PROCEED_WITH_WARNING
        assert "Priority override" in result.reason
    
    def test_evaluate_namespace_override(self, controller, resources):
        """Test namespace override bypasses thresholds."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=500,
            priority=DeploymentPriority.NORMAL,
            namespace="production-hotfix"
        )
        
        assert result.decision == GateDecision.PROCEED
        assert "Namespace override" in result.reason
    
    def test_evaluate_with_forecast(self, controller, resources):
        """Test evaluation with intensity forecast."""
        now = datetime.now()
        forecast = [
            (now + timedelta(hours=1), 400),
            (now + timedelta(hours=2), 200),  # Optimal window
            (now + timedelta(hours=3), 350),
        ]
        
        result = controller.evaluate(
            resources=resources,
            current_intensity=500,
            priority=DeploymentPriority.NORMAL,
            intensity_forecast=forecast
        )
        
        assert result.decision == GateDecision.DEFER
        assert result.forecast_optimal_time is not None
        assert result.recommended_wait_minutes is not None
    
    def test_result_to_dict(self, controller, resources):
        """Test GateResult to_dict method."""
        result = controller.evaluate(
            resources=resources,
            current_intensity=100,
            priority=DeploymentPriority.NORMAL
        )
        
        d = result.to_dict()
        
        assert "decision" in d
        assert "carbon_estimate" in d
        assert "current_intensity" in d
        assert "threshold_level" in d
        assert "reason" in d


class TestConvenienceFunction:
    """Tests for convenience evaluation function."""
    
    def test_evaluate_deployment_green(self):
        """Test quick evaluation in green zone."""
        result = evaluate_deployment(
            cpu_cores=4,
            memory_gb=8,
            current_intensity=100,
            priority="normal"
        )
        
        assert result["decision"] == "proceed"
        assert result["threshold_level"] == "green"
    
    def test_evaluate_deployment_critical(self):
        """Test quick evaluation with critical priority."""
        result = evaluate_deployment(
            cpu_cores=4,
            memory_gb=8,
            current_intensity=500,
            priority="critical"
        )
        
        assert result["decision"] == "proceed"


class TestGateDecisionEnum:
    """Tests for GateDecision enum."""
    
    def test_decision_values(self):
        """Test all decision values."""
        assert GateDecision.PROCEED.value == "proceed"
        assert GateDecision.PROCEED_WITH_WARNING.value == "proceed-with-warning"
        assert GateDecision.DEFER.value == "defer"
        assert GateDecision.REQUIRE_APPROVAL.value == "require-approval"
        assert GateDecision.BLOCKED.value == "blocked"


class TestDeploymentPriorityEnum:
    """Tests for DeploymentPriority enum."""
    
    def test_priority_values(self):
        """Test all priority values."""
        assert DeploymentPriority.CRITICAL.value == "critical"
        assert DeploymentPriority.HIGH.value == "high"
        assert DeploymentPriority.NORMAL.value == "normal"
        assert DeploymentPriority.LOW.value == "low"
    
    def test_priority_from_string(self):
        """Test creating priority from string."""
        priority = DeploymentPriority("critical")
        assert priority == DeploymentPriority.CRITICAL
