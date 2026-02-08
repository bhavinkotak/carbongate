"""
CarbonGate: Carbon-Aware Quality Gates for Kubernetes GitOps

This module provides the core carbon estimation functionality for
calculating the carbon impact of Kubernetes deployments.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class PowerCoefficients:
    """Power consumption coefficients for resource types."""
    
    cpu_watts_per_core: float = 10.0  # Active power per CPU core
    cpu_idle_watts_per_core: float = 3.0  # Idle power per CPU core
    memory_watts_per_gb: float = 0.375  # Power per GB RAM
    network_watts_per_gbps: float = 0.5  # Power per Gbps network
    storage_watts_per_mbps: float = 0.01  # Power per MB/s storage I/O


@dataclass
class DeploymentResources:
    """Resource requirements for a Kubernetes deployment."""
    
    cpu_cores: float
    memory_gb: float
    replicas: int = 1
    network_gbps: float = 0.1
    storage_mbps: float = 10.0


@dataclass
class CarbonEstimate:
    """Carbon emission estimate for a deployment."""
    
    total_grams_co2: float
    energy_kwh: float
    power_watts: float
    duration_hours: float
    carbon_intensity_g_per_kwh: float
    pue: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_grams_co2": round(self.total_grams_co2, 2),
            "energy_kwh": round(self.energy_kwh, 4),
            "power_watts": round(self.power_watts, 2),
            "duration_hours": round(self.duration_hours, 4),
            "carbon_intensity_g_per_kwh": round(self.carbon_intensity_g_per_kwh, 2),
            "pue": self.pue
        }


class CarbonEstimator:
    """
    Estimates carbon emissions for Kubernetes deployments.
    
    Uses resource-based power estimation combined with grid carbon
    intensity to calculate deployment carbon footprint.
    
    Example:
        >>> estimator = CarbonEstimator(pue=1.4)
        >>> resources = DeploymentResources(cpu_cores=4, memory_gb=8)
        >>> estimate = estimator.estimate(
        ...     resources=resources,
        ...     duration_minutes=5,
        ...     carbon_intensity=300
        ... )
        >>> print(f"Carbon: {estimate.total_grams_co2:.2f}g CO2")
    """
    
    def __init__(
        self,
        pue: float = 1.4,
        coefficients: Optional[PowerCoefficients] = None
    ):
        """
        Initialize the carbon estimator.
        
        Args:
            pue: Power Usage Effectiveness of the data center (1.0-2.0)
            coefficients: Power consumption coefficients
        """
        self.pue = pue
        self.coefficients = coefficients or PowerCoefficients()
        
    def estimate_power(self, resources: DeploymentResources) -> float:
        """
        Estimate power consumption for given resources.
        
        Args:
            resources: Deployment resource requirements
            
        Returns:
            Estimated power consumption in watts
        """
        # CPU power (assuming active workload during deployment)
        cpu_power = (
            resources.cpu_cores * 
            self.coefficients.cpu_watts_per_core * 
            resources.replicas
        )
        
        # Memory power
        memory_power = (
            resources.memory_gb * 
            self.coefficients.memory_watts_per_gb * 
            resources.replicas
        )
        
        # Network power
        network_power = (
            resources.network_gbps * 
            self.coefficients.network_watts_per_gbps
        )
        
        # Storage power
        storage_power = (
            resources.storage_mbps * 
            self.coefficients.storage_watts_per_mbps
        )
        
        # Total compute power
        compute_power = cpu_power + memory_power + network_power + storage_power
        
        # Apply PUE to account for cooling, infrastructure overhead
        total_power = compute_power * self.pue
        
        logger.debug(
            f"Power estimate: CPU={cpu_power:.2f}W, Memory={memory_power:.2f}W, "
            f"Network={network_power:.2f}W, Storage={storage_power:.2f}W, "
            f"Total (with PUE)={total_power:.2f}W"
        )
        
        return total_power
    
    def estimate(
        self,
        resources: DeploymentResources,
        duration_minutes: float,
        carbon_intensity: float
    ) -> CarbonEstimate:
        """
        Estimate carbon emissions for a deployment.
        
        Args:
            resources: Deployment resource requirements
            duration_minutes: Expected deployment duration in minutes
            carbon_intensity: Grid carbon intensity in gCO2/kWh
            
        Returns:
            CarbonEstimate with detailed breakdown
        """
        # Calculate power
        power_watts = self.estimate_power(resources)
        
        # Convert to energy
        duration_hours = duration_minutes / 60.0
        power_kw = power_watts / 1000.0
        energy_kwh = power_kw * duration_hours
        
        # Calculate carbon
        total_grams_co2 = energy_kwh * carbon_intensity
        
        estimate = CarbonEstimate(
            total_grams_co2=total_grams_co2,
            energy_kwh=energy_kwh,
            power_watts=power_watts,
            duration_hours=duration_hours,
            carbon_intensity_g_per_kwh=carbon_intensity,
            pue=self.pue
        )
        
        logger.info(
            f"Carbon estimate: {total_grams_co2:.2f}g CO2 "
            f"({energy_kwh:.4f} kWh @ {carbon_intensity} gCO2/kWh)"
        )
        
        return estimate
    
    def estimate_from_pod_spec(
        self,
        pod_spec: Dict[str, Any],
        duration_minutes: float,
        carbon_intensity: float
    ) -> CarbonEstimate:
        """
        Estimate carbon from a Kubernetes pod specification.
        
        Args:
            pod_spec: Kubernetes pod specification dictionary
            duration_minutes: Expected deployment duration
            carbon_intensity: Grid carbon intensity in gCO2/kWh
            
        Returns:
            CarbonEstimate with detailed breakdown
        """
        # Parse resources from pod spec
        total_cpu = 0.0
        total_memory_gb = 0.0
        
        containers = pod_spec.get("containers", [])
        for container in containers:
            resources = container.get("resources", {}).get("requests", {})
            
            # Parse CPU (can be "100m" for millicores or "1" for cores)
            cpu_str = resources.get("cpu", "0")
            if cpu_str.endswith("m"):
                total_cpu += float(cpu_str[:-1]) / 1000.0
            else:
                total_cpu += float(cpu_str)
            
            # Parse memory (can be "1Gi", "1024Mi", etc.)
            memory_str = resources.get("memory", "0")
            total_memory_gb += self._parse_memory(memory_str)
        
        # Get replica count from deployment spec
        replicas = pod_spec.get("replicas", 1)
        
        resources = DeploymentResources(
            cpu_cores=total_cpu,
            memory_gb=total_memory_gb,
            replicas=replicas
        )
        
        return self.estimate(resources, duration_minutes, carbon_intensity)
    
    def _parse_memory(self, memory_str: str) -> float:
        """Parse memory string to GB."""
        memory_str = str(memory_str).strip()
        
        if memory_str.endswith("Gi"):
            return float(memory_str[:-2])
        elif memory_str.endswith("Mi"):
            return float(memory_str[:-2]) / 1024.0
        elif memory_str.endswith("Ki"):
            return float(memory_str[:-2]) / (1024.0 * 1024.0)
        elif memory_str.endswith("G"):
            return float(memory_str[:-1])
        elif memory_str.endswith("M"):
            return float(memory_str[:-1]) / 1024.0
        elif memory_str.endswith("K"):
            return float(memory_str[:-1]) / (1024.0 * 1024.0)
        else:
            # Assume bytes
            return float(memory_str) / (1024.0 ** 3)


# Convenience function for quick estimation
def estimate_deployment_carbon(
    cpu_cores: float,
    memory_gb: float,
    duration_minutes: float = 5.0,
    carbon_intensity: float = 300.0,
    pue: float = 1.4,
    replicas: int = 1
) -> float:
    """
    Quick estimation of deployment carbon emissions.
    
    Args:
        cpu_cores: CPU cores requested
        memory_gb: Memory in GB requested
        duration_minutes: Deployment duration in minutes
        carbon_intensity: Grid carbon intensity in gCO2/kWh
        pue: Power Usage Effectiveness
        replicas: Number of replicas
        
    Returns:
        Carbon emissions in grams CO2
    """
    estimator = CarbonEstimator(pue=pue)
    resources = DeploymentResources(
        cpu_cores=cpu_cores,
        memory_gb=memory_gb,
        replicas=replicas
    )
    estimate = estimator.estimate(resources, duration_minutes, carbon_intensity)
    return estimate.total_grams_co2


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    # Create estimator with default settings
    estimator = CarbonEstimator(pue=1.4)
    
    # Define deployment resources
    resources = DeploymentResources(
        cpu_cores=4,
        memory_gb=8,
        replicas=3
    )
    
    # Estimate carbon at different intensity levels
    for intensity in [100, 200, 300, 400, 500]:
        estimate = estimator.estimate(
            resources=resources,
            duration_minutes=5,
            carbon_intensity=intensity
        )
        print(f"At {intensity} gCO2/kWh: {estimate.total_grams_co2:.2f}g CO2")
