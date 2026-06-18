# How to Run Experiment Suites in Virtuoso

This guide provides a step-by-step walkthrough for running large-scale experiment suites using Virtuoso's experiment framework. The framework uses YAML configuration files to define experiments and automates job submission to SLURM clusters.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Step 1: Configure Experiments](#step-1-configure-experiments)
- [Step 2: Generate Job Files](#step-2-generate-job-files)
- [Step 3: Validate and Submit](#step-3-validate-and-submit)
- [Step 4: Monitor Progress](#step-4-monitor-progress)
- [Step 5: Handle Failures](#step-5-handle-failures)
- [Configuration Examples](#configuration-examples)
- [Troubleshooting](#troubleshooting)

## Overview

The experiment framework consists of:

- **`clist.yaml`**: Central configuration file defining traces, configs, and experiment suites
- **`create_experiments.py`**: Generates SLURM job files from configurations
- **`safe_submit.py`**: Validates environment and submits jobs with throttling
- **`get_experiments_status.py`**: Monitors experiment progress
- **`create_rerun_experiments.py`**: Creates job files for failed/missing runs

## Prerequisites

- Virtuoso repository cloned with submodules
- Sniper simulator built (`simulator/sniper/run-sniper` exists)
- SLURM cluster environment
- Trace files available (downloaded via `simulator/sniper/download_traces.sh`)
- Python 3.8+

## Step 1: Configure Experiments

Create or edit `experiments/clist.yaml` to define your experiment suite.

### Basic Structure

```yaml
# Trace suites: collections of trace files
trace_suite:
  my_traces:
    tracelist_base_path: "vm_tlist/"
    tracelists:
      - victima.tlist

# Configs: simulation configurations
configs:
  configs_base_path: "../simulator/sniper/config/"
  baseline:
    name: "baseline"
    file: "virtuoso_configs/virtuoso_reservethp.cfg"
    description: "Baseline configuration"

# Experiment suites: combine traces + configs + instruction count
experiment_suites:
  my_experiment:
    description: "My first experiment"
    configs: [baseline]
    trace_suite: my_traces
    instruction_count: 5000000000
```

### Advanced Configuration

#### Parameter Sweeps

```yaml
configs:
  sweep_example:
    name: "frag_sweep"
    file: "virtuoso_configs/virtuoso_reservethp.cfg"
    sweeps:
      - identifier: ["frag"]
        option: ["--perf_model/reserve_thp_allocator/target_fragmentation="]
        values: [[0.0, 0.25, 0.5, 0.75, 1.0]]
    description: "Fragmentation sweep"
```

#### Config Extensions

```yaml
configs:
  extended_config:
    name: "custom"
    file: "virtuoso_configs/virtuoso_reservethp.cfg"
    extends:
      - "--perf_model/reserve_thp_allocator/target_fragmentation=0.1"
      - "--perf_model/core/frequency=3.0"
    description: "Custom configuration with overrides"
```

## Step 2: Generate Job Files

Run `create_experiments.py` to generate SLURM job files:

```bash
python3 experiments/create_experiments.py \
  --artifact-path /path/to/virtuoso \
  --yaml experiments/clist.yaml \
  --suite my_experiment \
  --suite-dir-name my_experiment \
  --force
```

**Parameters:**
- `--artifact-path`: Absolute path to Virtuoso root directory
- `--yaml`: Path to clist.yaml (default: experiments/clist.yaml)
- `--suite`: Name of experiment suite from clist.yaml
- `--suite-dir-name`: Directory name for experiment outputs
- `--force`: Overwrite existing experiment directory

**Output:**
- Creates `experiments/exp_my_experiment/` directory
- Generates `jobfile.sh` with SLURM sbatch commands
- Creates CSV files: `trace_list.csv`, `config_list.csv`, `job_list.csv`

## Step 3: Validate and Submit

Use `safe_submit.py` to validate and submit jobs:

```bash
# First, validate (dry run)
python3 experiments/safe_submit.py experiments/exp_my_experiment/jobfile.sh --dry-run

# Then submit with throttling
python3 experiments/safe_submit.py experiments/exp_my_experiment/jobfile.sh \
  --max-slurm-jobs 400 \
  --slurm-retry-delay 60 \
  --slurm-submit-delay 0.1
```

**Validation Checks:**
- Sniper build status and debug flags
- Trace file existence
- Config file availability
- Output directory sanity
- Disk space availability
- SLURM queue status

**Submission Options:**
- `--max-slurm-jobs`: Maximum concurrent jobs (default: 500)
- `--slurm-retry-delay`: Seconds to wait when queue full (default: 60)
- `--slurm-submit-delay`: Seconds between submissions (default: 0.1)
- `--force`: Submit despite validation warnings

## Step 4: Monitor Progress

Check experiment status using `get_experiments_status.py`:

```bash
python3 experiments/get_experiments_status.py \
  --exp-dir experiments/exp_my_experiment
```

**Status Categories:**
- `done`: All required files present (slurm.out, slurm.err, sim.stats)
- `running`: Some output files exist but not complete
- `error`: Python traceback in slurm.err
- `roi_error`: ROI-related errors
- `exception`: Internal simulator exceptions
- `pending`: No output files yet

**Output:**
- CSV files in `experiments/exp_my_experiment/status/`
- Summary of completion status by trace

## Step 5: Handle Failures

For failed or missing runs, create a rerun job file:

```bash
python3 experiments/create_rerun_experiments.py \
  --exp-dir experiments/exp_my_experiment \
  --status experiments/exp_my_experiment/status/error.csv \
  --jobfile experiments/exp_my_experiment/jobfile_rerun.sh
```

Then submit the rerun jobs:

```bash
python3 experiments/safe_submit.py experiments/exp_my_experiment/jobfile_rerun.sh
```

## Configuration Examples

### Complete clist.yaml Example

```yaml
trace_suite:
  benchmark_suite:
    tracelist_base_path: "vm_tlist/"
    tracelists:
      - victima.tlist
      - dpc3.tlist

configs:
  configs_base_path: "../simulator/sniper/config/"
  no_translation:
    name: "no_translation"
    file: "address_translation_schemes/no_translation.cfg"
    description: "No address translation"

  reservethp_variations:
    name: "reservethp"
    file: "virtuoso_configs/virtuoso_reservethp.cfg"
    sweeps:
      - identifier: ["frag"]
        option: ["--perf_model/reserve_thp_allocator/target_fragmentation="]
        values: [[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]]
    description: "ReserveTHP fragmentation sweep"

experiment_suites:
  fragmentation_study:
    description: "Study of fragmentation impact on virtual memory"
    configs: [no_translation, reservethp_variations]
    trace_suite: benchmark_suite
    instruction_count: 3000000000
```

### Trace List Format (.tlist)

Trace list files specify which traces to run:

```
# Base directory for traces
/home/user/traces/

# Format: name, relative_path, metadata...
bc, bc.sift, 0.5, 1.2
bfs, bfs.sift, 1.0, 0.8
cc, cc.sift, 0.3, 1.5
```

## Troubleshooting

### Common Issues

**Job files not generated:**
- Check clist.yaml syntax (YAML format)
- Verify trace files exist at specified paths
- Ensure config files are accessible

**Validation failures:**
- Rebuild Sniper if binary is outdated
- Check trace file permissions and paths
- Verify SLURM environment variables

**Jobs not submitting:**
- Check SLURM queue limits for your user
- Verify account and partition settings
- Check for conflicting job names

**Simulation errors:**
- Review slurm.err for error messages
- Check sim.out for simulator output
- Verify memory and time limits in job scripts

### Log Files

**Experiment logs:**
- `experiments/exp_*/create_experiments.log`: Job file generation
- `experiments/exp_*/submit.log`: Submission summary

**Per-job logs:**
- `results/*/slurm.out`: SLURM stdout
- `results/*/slurm.err`: SLURM stderr
- `results/*/sim.out`: Simulator output
- `results/*/sim.stats`: Performance statistics

### Performance Tips

- Use `--max-slurm-jobs` to avoid overwhelming the cluster
- Monitor queue status with `squeue -u $USER`
- Use `scancel` to cancel jobs if needed
- Archive completed experiments to save disk space

For more details, see the [experiments README](experiments/README.md).</content>
<parameter name="filePath">/media/pravesh/Storage/code/sims/artVirtuoso/docs/how_to_run_experiment_suites.md