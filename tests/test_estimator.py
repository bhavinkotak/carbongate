"""
Tests for CarbonGate estimator module.
"""

import pytest
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from carbongate.estimator import (
    CarbonEstimator,
    DeploymentResources,
    PowerCoefficients,
    estimate_deployment_carbon,
)


class TestPowerCoefficients:
    """Tests for PowerCoefficients dataclass."""
    
    def test_default_values(self):
        """Test default power coefficients."""
        coeffs = PowerCoefficients()
        
        assert coeffs.cpu_watts_per_core == 10.0
        assert coeffs.cpu_idle_watts_per_core == 3.0
        assert coeffs.memory_watts_per_gb == 0.375
        assert coeffs.network_watts_per_gbps == 0.5
        assert coeffs.storage_watts_per_mbps == 0.01
    
    def test_custom_values(self):
        """Test custom power coefficients."""
        coeffs = PowerCoefficients(
            cpu_watts_per_core=15.0,
            memory_watts_per_gb=0.5
        )
        
        assert coeffs.cpu_watts_per_core == 15.0
        assert coeffs.memory_watts_per_gb == 0.5


class TestDeploymentResources:
    """Tests for DeploymentResources dataclass."""
    
    def test_default_values(self):
        """Test default deployment resources."""
        resources = DeploymentResources(cpu_cores=4, memory_gb=8)
        
        assert resources.cpu_cores == 4
        assert resources.memory_gb == 8
        assert resources.replicas == 1
        assert resources.network_gbps == 0.1
        assert resources.storage_mbps == 10.0
    
    def test_custom_replicas(self):
        """Test custom replica count."""
        resources = DeploymentResources(
            cpu_cores=2,
            memory_gb=4,
            replicas=3
        )
        
        assert resources.replicas == 3


class TestCarbonEstimator:
    """Tests for CarbonEstimator class."""
    
    @pytest.fixture
    def estimator(self):
        """Create a default estimator."""
        return CarbonEstimator(pue=1.4)
    
    @pytest.fixture
    def resources(self):
        """Create sample deployment resources."""
        return DeploymentResources(
            cpu_cores=4,
            memory_gb=8,
            replicas=1
        )
    
    def test_estimate_power_basic(self, estimator, resources):
        """Test basic power estimation."""
        power = estimator.estimate_power(resources)
        
        # CPU: 4 cores * 10W = 40W
        # Memory: 8GB * 0.375W = 3W
        # Network: 0.1 Gbps * 0.5W = 0.05W
        # Storage: 10 MB/s * 0.01W = 0.1W
        # Total compute: ~43.15W
        # With PUE 1.4: ~60.4W
        
        assert 55 < power < 65  # Allow some tolerance
    
    def test_estimate_power_with_replicas(self, estimator):
        """Test power estimation with multiple replicas."""
        resources = DeploymentResources(
            cpu_cores=2,
            memory_gb=4,
            replicas=3
        )
        
        power = estimator.estimate_power(resources)
        
        # CPU and memory scale with replicas
        # Network and storage don't scale
        assert power > 0
    
    def test_estimate_carbon_green_intensity(self, estimator, resources):
        """Test carbon estimation at green intensity."""
        estimate = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=100  # Green
        )
        
        assert estimate.total_grams_co2 > 0
        assert estimate.carbon_intensity_g_per_kwh == 100
        assert estimate.pue == 1.4
    
    def test_estimate_carbon_red_intensity(self, estimator, resources):
        """Test carbon estimation at red intensity."""
        green_estimate = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=100
        )
        
        red_estimate = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=500
        )
        
        # Red should be 5x the carbon of green
        ratio = red_estimate.total_grams_co2 / green_estimate.total_grams_co2
        assert 4.9 < ratio < 5.1
    
    def test_estimate_duration_scaling(self, estimator, resources):
        """Test that carbon scales linearly with duration."""
        short = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=300
        )
        
        long = estimator.estimate(
            resources=resources,
            duration_minutes=10,
            carbon_intensity=300
        )
        
        # Double duration should double carbon
        ratio = long.total_grams_co2 / short.total_grams_co2
        assert 1.9 < ratio < 2.1
    
    def test_estimate_to_dict(self, estimator, resources):
        """Test CarbonEstimate to_dict method."""
        estimate = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=300
        )
        
        d = estimate.to_dict()
        
        assert "total_grams_co2" in d
        assert "energy_kwh" in d
        assert "power_watts" in d
        assert "duration_hours" in d
        assert "carbon_intensity_g_per_kwh" in d
        assert "pue" in d
    
    def test_estimate_from_pod_spec_cores(self, estimator):
        """Test estimation from pod spec with CPU cores."""
        pod_spec = {
            "containers": [
                {
                    "name": "app",
                    "resources": {
                        "requests": {
                            "cpu": "2",
                            "memory": "4Gi"
                        }
                    }
                }
            ]
        }
        
        estimate = estimator.estimate_from_pod_spec(
            pod_spec=pod_spec,
            duration_minutes=5,
            carbon_intensity=300
        )
        
        assert estimate.total_grams_co2 > 0
    
    def test_estimate_from_pod_spec_millicores(self, estimator):
        """Test estimation from pod spec with millicores."""
        pod_spec = {
            "containers": [
                {
                    "name": "app",
                    "resources": {
                        "requests": {
                            "cpu": "500m",
                            "memory": "1024Mi"
                        }
                    }
                }
            ]
        }
        
        estimate = estimator.estimate_from_pod_spec(
            pod_spec=pod_spec,
            duration_minutes=5,
            carbon_intensity=300
        )
        
        assert estimate.total_grams_co2 > 0
    
    def test_estimate_from_pod_spec_multiple_containers(self, estimator):
        """Test estimation from pod spec with multiple containers."""
        pod_spec = {
            "containers": [
                {
                    "name": "app",
                    "resources": {
                        "requests": {
                            "cpu": "1",
                            "memory": "2Gi"
                        }
                    }
                },
                {
                    "name": "sidecar",
                    "resources": {
                        "requests": {
                            "cpu": "100m",
                            "memory": "256Mi"
                        }
                    }
                }
            ]
        }
        
        estimate = estimator.estimate_from_pod_spec(
            pod_spec=pod_spec,
            duration_minutes=5,
            carbon_intensity=300
        )
        
        assert estimate.total_grams_co2 > 0


class TestConvenienceFunction:
    """Tests for convenience estimation function."""
    
    def test_estimate_deployment_carbon(self):
        """Test quick estimation function."""
        carbon = estimate_deployment_carbon(
            cpu_cores=4,
            memory_gb=8,
            duration_minutes=5,
            carbon_intensity=300,
            pue=1.4
        )
        
        assert carbon > 0
        assert isinstance(carbon, float)
    
    def test_estimate_deployment_carbon_with_replicas(self):
        """Test quick estimation with replicas."""
        single = estimate_deployment_carbon(
            cpu_cores=2,
            memory_gb=4,
            replicas=1
        )
        
        triple = estimate_deployment_carbon(
            cpu_cores=2,
            memory_gb=4,
            replicas=3
        )
        
        # Replicas scale CPU and memory power
        assert triple > single
