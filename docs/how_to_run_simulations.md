# How to Run Simulations on Virtuoso

Virtuoso is a simulation framework for virtual memory research that integrates multiple simulators (Sniper for CPU, Ramulator2 for DRAM) with MimicOS, a lightweight userspace OS kernel for memory management simulation.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Basic Setup](#basic-setup)
- [Running Basic Simulations](#running-basic-simulations)
- [Running Experiment Suites](#running-experiment-suites)
- [Ramulator2 Integration](#ramulator2-integration)
- [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)

## Overview

Virtuoso supports two main simulation modes:

1. **Sniper-based simulations**: Event-driven CPU simulation with MimicOS handling virtual memory operations
2. **Ramulator2-based simulations**: Cycle-accurate DRAM timing with MimicOS for page table management

## Prerequisites

- Linux environment with SLURM (for cluster jobs)
- CMake 3.14+, C++17 compiler (g++ 9+ or clang 10+)
- Python 3.8+
- Intel SDE (for Ramulator2 pintool integration)
- Git with submodules

## Basic Setup

### 1. Clone Repository

```bash
git clone --recursive https://github.com/CMU-SAFARI/Virtuoso.git
cd Virtuoso
```

### 2. Install Dependencies

```bash
cd simulator/sniper/
sh install_dependencies.sh
# Reload environment or create conda environment
conda create -n virtuoso python=3.10
conda activate virtuoso
```

### 3. Build Sniper

```bash
cd simulator/sniper
make distclean
make -j
```

### 4. Download Traces

```bash
cd simulator/sniper/
sh download_traces.sh
```

## Running Basic Simulations

### Sniper Example Run

```bash
cd simulator/sniper/
sh run_example.sh
```

This runs a basic simulation using Sniper with default configurations.

### Custom Sniper Run

```bash
cd simulator/sniper/
./run-sniper --traces=traces_victima/bc.sift -c config/virtuoso_configs/virtuoso_reservethp.cfg -d output_dir
```

## Running Experiment Suites

Virtuoso provides a comprehensive experiment framework for running large-scale studies.

### 1. Configure Experiments

Edit `experiments/clist.yaml` to define:

- **Trace suites**: Collections of trace files
- **Configs**: Simulation configurations
- **Experiment suites**: Combinations of traces and configs

Example `clist.yaml`:

```yaml
trace_suite:
  victima:
    tracelist_base_path: "vm_tlist/"
    tracelists:
      - victima.tlist

configs:
  configs_base_path: "../simulator/sniper/config/"
  reservethp:
    name: "reservethp-frag0.1"
    file: "virtuoso_configs/virtuoso_reservethp.cfg"
    extends:
      - "--perf_model/reserve_thp_allocator/target_fragmentation=0.1"

experiment_suites:
  my-suite:
    configs: [reservethp]
    trace_suite: victima
    instruction_count: 5000000000
```

### 2. Generate Job Files

```bash
cd experiments/
python3 create_experiments.py --suite my-suite
```

This creates `experiments/exp_my-suite/jobfile.sh` with SLURM submission commands.

### 3. Submit Jobs

```bash
python3 safe_submit.py exp_my-suite/jobfile.sh --max-slurm-jobs 400
```

The `safe_submit.py` script validates the environment and submits jobs with throttling.

### 4. Monitor Progress

```bash
python3 get_experiments_status.py --exp-dir exp_my-suite
```

This generates CSV reports on completed, running, failed, and pending simulations.

### 5. Rerun Failed Jobs

```bash
python3 create_rerun_experiments.py --exp-dir exp_my-suite --jobfile exp_my-suite/jobfile_rerun.sh
python3 safe_submit.py exp_my-suite/jobfile_rerun.sh
```

## Ramulator2 Integration

For cycle-accurate DRAM simulations, Virtuoso integrates Ramulator2 with MimicOS.

### Setup

1. Apply the integration patch:
```bash
bash patches/apply_ramulator2_mimicos.sh
```

2. Build Ramulator2:
```bash
cd simulator/ramulator2
mkdir -p build && cd build
cmake ..
make -j
```

3. Build SDE pintool:
```bash
cd simulator/ramulator2/pintool
make SDE_BUILD_KIT=/path/to/sde-kit
```

4. Build MimicOS:
```bash
cd simulator/ramulator2/mimicos
make SNIPER_INCLUDE=$PWD/../../sniper/include
```

### Running Ramulator2 Simulations

#### Basic Run
```bash
cd simulator/ramulator2
./build/ramulator2 --config example_config.yaml --tlb-config test_tlb_config.yaml --mimicos-config mimicos/configs/default.ini
```

#### With SDE Pintool (Full IPC)
```bash
# Terminal 1: Start MimicOS
cd simulator/ramulator2/mimicos
./mimicos --config configs/default.ini --ipc-mode pipe --pipe-path /tmp/mimicos_pipe

# Terminal 2: Run with pintool
cd simulator/ramulator2
/path/to/sde -t ./pintool/obj-intel64/mimicos_bridge.so --pipe-path /tmp/mimicos_pipe -- ./build/ramulator2 --config example_config.yaml
```

#### Using Wrapper Script
```bash
cd simulator/ramulator2
python3 mimicos/run_mimicos_wrapper.py --ramulator-config example_config.yaml --mimicos-config mimicos/configs/default.ini --trace example_inst.trace
```

## Monitoring and Troubleshooting

### Common Issues

- **Missing traces**: Ensure traces are downloaded and paths are correct
- **Build failures**: Check compiler versions and dependencies
- **SLURM errors**: Verify queue limits and resource requests
- **IPC issues**: For Ramulator2, ensure named pipes are set up correctly

### Validation Checks

The `safe_submit.py` script performs comprehensive validation:
- Sniper build status
- Trace file existence
- Config file availability
- Disk space
- SLURM queue status

### Log Files

Simulation outputs are in:
- `sim.out`: Main simulation log
- `sim.stats`: Performance statistics
- `sim.stats.sqlite3`: Detailed metrics database
- `slurm.out`/`slurm.err`: SLURM job logs

For more details, see:
- [Ramulator2 Integration Guide](ramulator2_mimicos.md)
- [Experiment Framework](experiments/README.md)</content>
<parameter name="filePath">/media/pravesh/Storage/code/sims/artVirtuoso/docs/how_to_run_simulations.md