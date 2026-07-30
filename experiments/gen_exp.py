import os
import argparse
import sys
from typing import List, Tuple, Dict, Any

def load_yaml(yaml_path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        print("Error: PyYAML not installed. Install via 'pip install pyyaml'.", file=sys.stderr)
        sys.exit(1)

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        seen = set()
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key: {key}",
                    key_node.start_mark,
                )
            seen.add(key)
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.construct_mapping = construct_mapping  # type: ignore

    try:
        with open(yaml_path, "r") as f:
            data = yaml.load(f, Loader=UniqueKeyLoader)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping/dict")
        return data
    except FileNotFoundError:
        print(f"Error: YAML file not found: {yaml_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading YAML '{yaml_path}': {e}", file=sys.stderr)
        sys.exit(1)


def parse_tlist(tlist_path: str) -> Tuple[str, List[Tuple[str, str, str, str]]]:
    """Parse a .tlist file.
    Line 1: base directory on host containing trace files.
    Line 2+: comma-separated entries (tracename, filename, l2tlb_mpki, norm_ptw_lat).
    Returns (trace_dir_host, rows).
    """
    rows: List[Tuple[str, str, str, str]] = []
    trace_dir = ""
    try:
        with open(tlist_path, "r") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not lines:
            return trace_dir, rows
        trace_dir = lines[0]
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                tracename = parts[0]
                filename = parts[1]
                l2tlb_mpki = parts[2] if len(parts) > 2 else "0"
                norm_ptw_lat = parts[3] if len(parts) > 3 else "0"
                rows.append((tracename, filename, l2tlb_mpki, norm_ptw_lat))
            else:
                print(f"Warning: Skipping malformed tlist entry: {line}", file=sys.stderr)
    except FileNotFoundError:
        print(f"Error: tlist file not found: {tlist_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error reading tlist '{tlist_path}': {e}", file=sys.stderr)
    return trace_dir, rows


def resolve_traces(
    yaml_data: Dict[str, Any],
    yaml_dir: str,
    trace_suite_name: str,
) -> Tuple[str, List[Tuple[str, str, str, str]]]:
    trace_suites = yaml_data.get("trace_suite", {})
    ts = trace_suites.get(trace_suite_name)
    if not ts:
        print(f"Error: Trace suite '{trace_suite_name}' not defined in YAML.", file=sys.stderr)
        available = list(trace_suites.keys())
        if available:
            print(f"Available trace suites: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    base_rel = ts.get("tracelist_base_path", ".")
    tracelists = ts.get("tracelists", [])
    if not tracelists:
        print(f"Error: Trace suite '{trace_suite_name}' missing tracelists.", file=sys.stderr)
        sys.exit(1)

    trace_list_dir = os.path.normpath(os.path.join(yaml_dir, base_rel))
    all_traces: List[Tuple[str, str, str, str]] = []
    common_trace_dir = ""

    for tl in tracelists:
        tl_path = os.path.join(trace_list_dir, tl)
        host_dir, rows = parse_tlist(tl_path)
        if host_dir and not common_trace_dir:
            common_trace_dir = host_dir
        all_traces.extend(rows)

    return common_trace_dir, all_traces


def resolve_configs(
    yaml_data: Dict[str, Any],
    suite_config_keys: List[str],
    yaml_dir: str,
    workspace_root: str,
) -> List[Tuple[str, str, str]]:
    """Resolve configs from YAML into (variant_name, container_cfg_path, extra_flags) tuples.
    Cartesian product sweeps are expanded into distinct variants.
    """
    from itertools import product

    configs_root = yaml_data.get("configs", {})
    base_path_rel = configs_root.get("configs_base_path")
    if not base_path_rel:
        print("Error: 'configs_base_path' missing in YAML.", file=sys.stderr)
        sys.exit(1)

    # Base directory for configs on host
    configs_base_dir_host = os.path.normpath(os.path.join(yaml_dir, base_path_rel))

    resolved: List[Tuple[str, str, str]] = []

    for cfg_key in suite_config_keys:
        cfg_entry = configs_root.get(cfg_key)
        if not cfg_entry:
            print(f"Error: Config key '{cfg_key}' not defined in YAML.", file=sys.stderr)
            sys.exit(1)

        base_name = cfg_entry.get("name", cfg_key)
        cfg_file = cfg_entry.get("file")
        if not cfg_file:
            print(f"Error: Config '{cfg_key}' missing 'file' attribute.", file=sys.stderr)
            sys.exit(1)

        # Host path and container path (/app/...)
        full_cfg_path_host = os.path.normpath(os.path.join(configs_base_dir_host, cfg_file))
        rel_to_workspace = os.path.relpath(full_cfg_path_host, workspace_root)
        container_cfg_path = f"/app/{rel_to_workspace}"

        # Parse 'extends' options
        base_extra_flags = ""
        extends = cfg_entry.get("extends", [])
        for ext in extends:
            if isinstance(ext, str):
                base_extra_flags += f" -g {ext}"
            elif isinstance(ext, list) and len(ext) == 2:
                _, opt = ext
                base_extra_flags += f" -g {opt}"

        # Parse 'sweeps' options
        sweeps = cfg_entry.get("sweeps", [])
        if sweeps:
            dims: List[List[List[Tuple[str, str, Any]]]] = []
            for sw in sweeps:
                sid = sw.get("identifier")
                opt = sw.get("option")
                vals = sw.get("values")
                if not sid or not opt or not isinstance(vals, list) or not vals:
                    print(f"Error: Malformed sweep in config '{cfg_key}'.", file=sys.stderr)
                    sys.exit(1)

                if isinstance(sid, str) and isinstance(opt, str):
                    dim_groups: List[List[Tuple[str, str, Any]]] = []
                    for v in vals:
                        dim_groups.append([(sid, opt, v)])
                    dims.append(dim_groups)
                elif isinstance(sid, list) and isinstance(opt, list):
                    lengths = [len(vl) for vl in vals]
                    num_entries = lengths[0]
                    dim_groups: List[List[Tuple[str, str, Any]]] = []
                    for i in range(num_entries):
                        group: List[Tuple[str, str, Any]] = []
                        for j in range(len(sid)):
                            group.append((sid[j], opt[j], vals[j][i]))
                        dim_groups.append(group)
                    dims.append(dim_groups)

            for combo in product(*dims):
                assignments: List[Tuple[str, str, Any]] = [t for group in combo for t in group]
                name_suffix_parts = []
                extra_flags = base_extra_flags
                for sid_i, opt_i, val_i in assignments:
                    str_val = str(val_i).lower() if isinstance(val_i, bool) else str(val_i)
                    name_suffix_parts.append(f"-{sid_i}{str_val}")
                    extra_flags += f" -g {opt_i}{str_val}"

                variant_name = base_name + "".join(name_suffix_parts)
                resolved.append((variant_name, container_cfg_path, extra_flags))
        else:
            resolved.append((base_name, container_cfg_path, base_extra_flags))

    return resolved


def sanitize_dirname(name: str) -> str:
    name = name.replace(",", "-").replace(" ", "-")
    for char in [':', ';', '|', '\\', '/', '*', '?', '"', '<', '>', '!']:
        name = name.replace(char, '-')
    while '--' in name:
        name = name.replace('--', '-')
    return name


def generate_jobs(
    workspace_root: str,
    image_name: str,
    results_base_dir: str,
    suite_name: str,
    instruction_count: int,
    configs: List[Tuple[str, str, str]],
    trace_dir_host: str,
    traces: List[Tuple[str, str, str, str]],
) -> List[str]:
    jobs: List[str] = []

    for cfg_name, container_cfg_path, extra_flags in configs:
        for tracename, filename, _, _ in traces:
            safe_cfg = sanitize_dirname(cfg_name)
            safe_trace = sanitize_dirname(tracename)
            output_dir = f"{results_base_dir}/{suite_name}/{safe_cfg}_{safe_trace}"

            docker_cmd = (
                f'docker run --rm '
                f'-v "{workspace_root}":/app '
                f'--mount type=bind,src="{trace_dir_host}",target=/app/traces/ '
                f'"{image_name}" '
                f'/app/simulator/sniper/run-sniper '
                f'-s stop-by-icount:{instruction_count} '
                f'--genstats --power '
                f'-d {output_dir} '
                f'-c {container_cfg_path}{extra_flags} '
                f'--traces=/app/traces/{filename}'
            )
            jobs.append(docker_cmd)

    return jobs


def main():
    parser = argparse.ArgumentParser(
        description="Generate Docker execution job commands from an experiment YAML configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example Usage:
  python3 gen_exp.py --yaml experiments/starnet.yaml --suite perfect_translation
  python3 gen_exp.py --yaml experiments/clist.yaml --suite perfect_translation -o jobs.sh
        """,
    )
    parser.add_argument("--yaml", "-y", type=str, default="experiments/starnet.yaml", help="Path to experiment YAML file")
    parser.add_argument("--suite", "-s", type=str, nargs="+", required=True, help="Experiment suite name(s) from YAML")
    parser.add_argument("--workspace-root", "-w", type=str, default=None, help="Host path to workspace root (default: auto-detected)")
    parser.add_argument("--image", "-i", type=str, default="virtu:latest", help="Docker image name (default: virtu:latest)")
    parser.add_argument("--results-base", "-r", type=str, default="/app/results", help="Base directory inside container for output results")
    parser.add_argument("--icount-override", type=int, default=None, help="Override instruction count from YAML")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file to save jobs list (optional)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only output job commands without informational messages")

    args = parser.parse_args()

    yaml_path = os.path.abspath(args.yaml)
    yaml_dir = os.path.dirname(yaml_path)

    # Autodetect workspace root (parent directory of 'experiments' or current directory)
    if args.workspace_root:
        workspace_root = os.path.abspath(args.workspace_root)
    else:
        # If yaml is inside an 'experiments' dir, workspace root is its parent
        if os.path.basename(yaml_dir) == "experiments":
            workspace_root = os.path.dirname(yaml_dir)
        else:
            workspace_root = os.path.abspath(os.path.join(yaml_dir, ".."))

    data = load_yaml(yaml_path)
    suites_data = data.get("experiment_suites", {})

    all_jobs: List[str] = []

    for suite_name in args.suite:
        if suite_name not in suites_data:
            print(f"Error: Experiment suite '{suite_name}' not found in YAML.", file=sys.stderr)
            available = list(suites_data.keys())
            if available:
                print(f"Available suites: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)

        suite = suites_data[suite_name]
        cfg_keys = suite.get("configs", [])
        trace_suite_name = suite.get("trace_suite")

        icount = args.icount_override or int(suite.get("instruction_count", 300000000))

        configs = resolve_configs(data, cfg_keys, yaml_dir, workspace_root)
        trace_dir_host, traces = resolve_traces(data, yaml_dir, trace_suite_name)

        jobs = generate_jobs(
            workspace_root=workspace_root,
            image_name=args.image,
            results_base_dir=args.results_base,
            suite_name=suite_name,
            instruction_count=icount,
            configs=configs,
            trace_dir_host=trace_dir_host,
            traces=traces,
        )
        all_jobs.extend(jobs)

    # Output jobs separated by newline
    jobs_output = "\n".join(all_jobs)

    if args.output:
        with open(args.output, "w") as f:
            f.write(jobs_output + "\n")
        if not args.quiet:
            print(f"Generated {len(all_jobs)} jobs written to {args.output}", file=sys.stderr)

    # Print to stdout
    print(jobs_output)


if __name__ == "__main__":
    main()
