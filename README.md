# CarbonGate: Carbon-Aware Quality Gates for Kubernetes GitOps

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.24+-blue.svg)](https://kubernetes.io/)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Go](https://img.shields.io/badge/Go-1.21+-00ADD8.svg)](https://golang.org/)

## Overview

CarbonGate is a framework for integrating carbon-awareness into GitOps workflows for Kubernetes deployments. It enables organizations to reduce deployment-associated carbon emissions by 23-31% while maintaining acceptable deployment velocity.

## Key Features

- **Real-time Carbon Monitoring**: Integrates with WattTime and ElectricityMap APIs
- **Intelligent Quality Gates**: Policy-based deployment decisions based on grid carbon intensity
- **GitOps Integration**: Native support for ArgoCD, Flux, and Tekton
- **Minimal Latency**: 28 seconds average for normal priority deployments
- **Full Observability**: Prometheus metrics and Grafana dashboards

## Quick Start

### Prerequisites

- Kubernetes 1.24+
- Helm 3.x
- WattTime or ElectricityMap API credentials

### Installation

```bash
# Add Helm repository
helm repo add carbongate https://carbongate.github.io/charts
helm repo update

# Install CarbonGate operator
helm install carbongate carbongate/carbongate-operator \
  --namespace carbongate-system \
  --create-namespace \
  --set carbonApi.provider=watttime \
  --set carbonApi.apiKeySecret=carbongate-api-credentials
```

### Create API Credentials Secret

```bash
kubectl create secret generic carbongate-api-credentials \
  --namespace carbongate-system \
  --from-literal=api-key=$WATTTIME_API_KEY \
  --from-literal=username=$WATTTIME_USERNAME
```

### Configure Carbon Policy

```yaml
apiVersion: carbongate.io/v1
kind: CarbonPolicy
metadata:
  name: default-policy
  namespace: carbongate-system
spec:
  thresholds:
    green: 150      # g CO2/kWh - proceed immediately
    yellow: 300     # g CO2/kWh - proceed with warning
    red: 450        # g CO2/kWh - defer or require approval
  
  actions:
    green: proceed
    yellow: proceed-with-warning
    red: defer-or-approve
  
  overrides:
    - priority: critical
      action: always-proceed
    - namespace: production-hotfix
      action: always-proceed
  
  deferral:
    maxWaitTime: 4h
    checkInterval: 15m
    forecastHorizon: 24h
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CarbonGate Architecture                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────┐     ┌──────────────┐     ┌─────────────────────────────────┐ │
│   │   Git    │────▶│   GitOps     │────▶│         CarbonGate              │ │
│   │  Repo    │     │  Controller  │     │  ┌─────────────────────────┐    │ │
│   └──────────┘     │  (ArgoCD/    │     │  │   Carbon Intensity      │◀───┼─┼── WattTime/
│                    │   Flux)      │     │  │      Fetcher            │    │ │   ElectricityMap
│                    └──────────────┘     │  └───────────┬─────────────┘    │ │
│                                         │              │                   │ │
│                                         │  ┌───────────▼─────────────┐    │ │
│                                         │  │   Carbon Estimator      │    │ │
│                                         │  └───────────┬─────────────┘    │ │
│                                         │              │                   │ │
│                                         │  ┌───────────▼─────────────┐    │ │
│                                         │  │    Quality Gate         │    │ │
│                                         │  │    Controller           │    │ │
│                                         │  └───────────┬─────────────┘    │ │
│                                         │              │                   │ │
│                                         │  ┌───────────▼─────────────┐    │ │
│                                         │  │  Deployment Scheduler   │    │ │
│                                         │  └───────────┬─────────────┘    │ │
│                                         └──────────────┼──────────────────┘ │
│                                                        │                     │
│                                                        ▼                     │
│                                         ┌─────────────────────────────────┐ │
│                                         │      Kubernetes Cluster         │ │
│                                         └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Carbon Estimation Model

CarbonGate estimates deployment carbon impact using:

```
C_deploy = E_compute × PUE × I_carbon × T_duration
```

### Default Power Coefficients

| Resource | Coefficient | Source |
|----------|-------------|--------|
| CPU (per core) | 10W active / 3W idle | Intel/AMD specifications |
| Memory (per GB) | 0.375W | DDR4/DDR5 specifications |
| Network (per Gbps) | 0.5W | Switch measurements |
| Storage I/O (per MB/s) | 0.01W | SSD specifications |

## Integrations

### ArgoCD

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: carbongate-presync
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: carbongate
        image: carbongate/gate:v1.0
        env:
        - name: CARBON_POLICY
          value: "default-policy"
      restartPolicy: Never
```

### Flux

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: carbongate-receiver
spec:
  type: generic
  secretRef:
    name: carbongate-webhook-token
  resources:
    - kind: Kustomization
      name: "*"
```

### Tekton

```yaml
apiVersion: tekton.dev/v1beta1
kind: Task
metadata:
  name: carbongate-check
spec:
  steps:
  - name: carbon-gate
    image: carbongate/gate:v1.0
    script: |
      carbongate check --policy=default-policy
```

## Metrics and Observability

### Prometheus Metrics

| Metric | Description |
|--------|-------------|
| `carbongate_deployments_total` | Total deployments processed |
| `carbongate_carbon_saved_grams` | Cumulative carbon saved |
| `carbongate_current_intensity` | Current grid carbon intensity |
| `carbongate_deferral_duration_seconds` | Time deployments spent deferred |

### Grafana Dashboard

Import the dashboard from `dashboards/carbongate.json` or use dashboard ID: `XXXXX`

## Project Structure

```
green-gitops/
├── README.md
├── requirements.txt
├── setup.py
├── src/
│   ├── __init__.py
│   ├── carbongate/
│   │   ├── __init__.py
│   │   ├── estimator.py        # Carbon estimation logic
│   │   ├── fetcher.py          # Carbon intensity API client
│   │   ├── gate.py             # Quality gate controller
│   │   ├── scheduler.py        # Deferral scheduler
│   │   └── policy.py           # Policy engine
│   ├── integrations/
│   │   ├── argocd.py
│   │   ├── flux.py
│   │   └── tekton.py
│   └── api/
│       ├── watttime.py
│       └── electricitymap.py
├── tests/
│   ├── test_estimator.py
│   ├── test_gate.py
│   └── test_integrations.py
├── helm/
│   └── carbongate/
├── dashboards/
│   └── carbongate.json
└── docs/
    ├── architecture.md
    ├── configuration.md
    └── troubleshooting.md
```

## Evaluation Results

### Carbon Reduction (6-month evaluation)

| Environment | Baseline | With CarbonGate | Reduction |
|-------------|----------|-----------------|-----------|
| US-East (AWS) | 2,847 kg CO₂ | 2,190 kg CO₂ | **23.1%** |
| EU-West (Azure) | 1,523 kg CO₂ | 1,089 kg CO₂ | **28.5%** |
| Asia-Pacific (GCP) | 2,156 kg CO₂ | 1,478 kg CO₂ | **31.4%** |

### Deployment Latency

| Priority | Mean Latency | P95 Latency |
|----------|--------------|-------------|
| Critical | 0s (bypass) | 0s |
| High | 8s | 45s |
| Normal | 28s | 4m |
| Low | 2h 15m | 3h 45m |

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/carbongate/carbongate
cd carbongate

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

### Running Locally

```bash
# Set API credentials
export WATTTIME_USERNAME=your_username
export WATTTIME_PASSWORD=your_password

# Run carbon gate check
python -m carbongate.gate check --deployment=my-app --region=us-east-1
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Citation

```bibtex
@article{kotak2024carbongate,
  title={Carbon-Aware GitOps: Implementing Energy-Efficient Quality Gates 
         in Kubernetes Delivery Workflows},
  author={Kotak, Bhavin},
  year={2024},
  doi={10.5281/zenodo.XXXXXXX}
}
```

## License

This project is licensed under the Apache License 2.0 - see [LICENSE](LICENSE) file.

## Author

**Bhavin Kotak**  
IBM Thomas J. Watson Research Center  
bhavin.kotak@ibm.com  
ORCID: [0009-0006-4793-7046](https://orcid.org/0009-0006-4793-7046)

## Acknowledgments

- [Green Software Foundation](https://greensoftware.foundation)
- [WattTime](https://www.watttime.org)
- [ElectricityMap](https://www.electricitymaps.com)
- [CNCF TAG Environmental Sustainability](https://github.com/cncf/tag-env-sustainability)
