"""
CarbonGate CLI - Command Line Interface for carbon-aware deployment decisions.

Usage:
    carbongate estimate --cpu=4 --memory=8 --intensity=300
    carbongate check --manifest=deployment.yaml --region=us-east-1
"""

import click
import json
import sys
from typing import Optional

from .estimator import CarbonEstimator, DeploymentResources, estimate_deployment_carbon
from .gate import (
    CarbonGateController,
    CarbonPolicy,
    DeploymentPriority,
    GateDecision,
    evaluate_deployment,
)


@click.group()
@click.version_option(version="1.0.0", prog_name="carbongate")
def main():
    """CarbonGate - Carbon-Aware Quality Gates for Kubernetes GitOps.
    
    Estimate carbon impact of deployments and make intelligent
    scheduling decisions based on grid carbon intensity.
    """
    pass


@main.command()
@click.option("--cpu", type=float, required=True, help="CPU cores requested")
@click.option("--memory", type=float, required=True, help="Memory in GB requested")
@click.option("--intensity", type=float, required=True, help="Grid carbon intensity (gCO2/kWh)")
@click.option("--duration", type=float, default=5.0, help="Deployment duration in minutes")
@click.option("--pue", type=float, default=1.4, help="Power Usage Effectiveness")
@click.option("--replicas", type=int, default=1, help="Number of pod replicas")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def estimate(
    cpu: float,
    memory: float,
    intensity: float,
    duration: float,
    pue: float,
    replicas: int,
    json_output: bool
):
    """Estimate carbon emissions for a deployment.
    
    Example:
        carbongate estimate --cpu=4 --memory=8 --intensity=300
    """
    estimator = CarbonEstimator(pue=pue)
    resources = DeploymentResources(
        cpu_cores=cpu,
        memory_gb=memory,
        replicas=replicas
    )
    
    result = estimator.estimate(
        resources=resources,
        duration_minutes=duration,
        carbon_intensity=intensity
    )
    
    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"Carbon Estimate: {result.total_grams_co2:.2f}g CO2")
        click.echo(f"  Energy: {result.energy_kwh:.4f} kWh")
        click.echo(f"  Power: {result.power_watts:.2f}W")
        click.echo(f"  Duration: {result.duration_hours:.4f}h")
        click.echo(f"  Intensity: {result.carbon_intensity_g_per_kwh:.0f} gCO2/kWh")
        click.echo(f"  PUE: {result.pue}")


@main.command()
@click.option("--cpu", type=float, required=True, help="CPU cores requested")
@click.option("--memory", type=float, required=True, help="Memory in GB requested")
@click.option("--intensity", type=float, required=True, help="Current grid carbon intensity (gCO2/kWh)")
@click.option("--priority", type=click.Choice(["critical", "high", "normal", "low"]), default="normal", help="Deployment priority")
@click.option("--threshold-green", type=float, default=150, help="Green threshold (gCO2/kWh)")
@click.option("--threshold-yellow", type=float, default=300, help="Yellow threshold (gCO2/kWh)")
@click.option("--threshold-red", type=float, default=450, help="Red threshold (gCO2/kWh)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def check(
    cpu: float,
    memory: float,
    intensity: float,
    priority: str,
    threshold_green: float,
    threshold_yellow: float,
    threshold_red: float,
    json_output: bool
):
    """Check if deployment should proceed based on carbon policy.
    
    Exit codes:
        0 - Proceed (green/yellow zone or priority override)
        1 - Blocked (red zone, should defer)
    
    Example:
        carbongate check --cpu=4 --memory=8 --intensity=500 --priority=normal
    """
    from .gate import CarbonThresholds
    
    policy = CarbonPolicy.default()
    policy.thresholds = CarbonThresholds(
        green=threshold_green,
        yellow=threshold_yellow,
        red=threshold_red
    )
    
    controller = CarbonGateController(policy=policy)
    resources = DeploymentResources(cpu_cores=cpu, memory_gb=memory)
    priority_enum = DeploymentPriority(priority)
    
    result = controller.evaluate(
        resources=resources,
        current_intensity=intensity,
        priority=priority_enum
    )
    
    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        # Determine status indicator
        if result.decision == GateDecision.PROCEED:
            status = "✅ PROCEED"
        elif result.decision == GateDecision.PROCEED_WITH_WARNING:
            status = "⚠️  PROCEED WITH WARNING"
        elif result.decision == GateDecision.DEFER:
            status = "❌ DEFER"
        else:
            status = f"🚫 {result.decision.value.upper()}"
        
        click.echo(f"Decision: {status}")
        click.echo(f"  Carbon: {result.carbon_estimate.total_grams_co2:.2f}g CO2")
        click.echo(f"  Intensity: {result.current_intensity} gCO2/kWh")
        click.echo(f"  Level: {result.threshold_level}")
        click.echo(f"  Reason: {result.reason}")
        
        if result.recommended_wait_minutes:
            click.echo(f"  Wait: {result.recommended_wait_minutes:.0f} minutes")
        if result.forecast_optimal_time:
            click.echo(f"  Optimal: {result.forecast_optimal_time}")
    
    # Exit with error code if deferred/blocked
    if result.decision in [GateDecision.DEFER, GateDecision.BLOCKED, GateDecision.REQUIRE_APPROVAL]:
        sys.exit(1)


@main.command()
def version():
    """Show version information."""
    click.echo("CarbonGate v1.0.0")
    click.echo("Carbon-Aware Quality Gates for Kubernetes GitOps")
    click.echo("")
    click.echo("Author: Bhavin Kotak <bhavin.kotak@ibm.com>")
    click.echo("Repository: https://github.com/bhavinkotak/carbongate")


if __name__ == "__main__":
    main()
