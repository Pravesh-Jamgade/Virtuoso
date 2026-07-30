#!/usr/bin/env python3
"""
Parallel Job Scheduler & Simulation Monitor

Schedules and executes batch jobs in parallel based on a specified CPU worker limit.
Logs status transitions (START, COMPLETE, ABORTED, FAILED) along with wall-clock
execution time and simulation metrics (parsed from sim.out if available).

Usage:
    python3 job_scheduler.py -j jobs.sh -c 4
    python3 job_scheduler.py --jobs-file jobs.txt --cpus 8 --log-file scheduler.log
"""

import os
import sys
import time
import signal
import argparse
import subprocess
import threading
from queue import Queue, Empty
from datetime import datetime
from typing import List, Dict, Optional, Tuple


# ANSI Styling
class Style:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

    @classmethod
    def disable(cls):
        cls.GREEN = ''
        cls.YELLOW = ''
        cls.RED = ''
        cls.CYAN = ''
        cls.BLUE = ''
        cls.MAGENTA = ''
        cls.BOLD = ''
        cls.DIM = ''
        cls.RESET = ''


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or SS.s string."""
    if seconds < 0:
        return "00:00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d} ({seconds:.1f}s)"


def extract_output_dir(command: str) -> Optional[str]:
    """Extract output directory (-d <dir>) from job command."""
    parts = command.split()
    for i, p in enumerate(parts):
        if p == "-d" and i + 1 < len(parts):
            return parts[i + 1]
        elif p.startswith("-d="):
            return p.split("=", 1)[1]
    return None


def parse_sim_metrics(output_dir: str, workspace_root: str = "") -> Dict[str, str]:
    """Parse Sniper sim.out metrics if available."""
    metrics = {}
    if not output_dir:
        return metrics

    # Resolve output directory on host
    host_dir = output_dir
    if host_dir.startswith("/app/"):
        rel_path = host_dir[5:]
        host_dir = os.path.join(workspace_root or os.getcwd(), rel_path)

    sim_out = os.path.join(host_dir, "sim.out")
    if not os.path.exists(sim_out):
        return metrics

    try:
        with open(sim_out, "r") as f:
            for line in f:
                line_str = line.strip()
                if "Time (ns)" in line_str or "Time (ms)" in line_str:
                    metrics["sim_time"] = line_str
                elif "Instructions" in line_str and "Instructions" not in metrics:
                    metrics["instructions"] = line_str
                elif "IPC" in line_str and "IPC" not in metrics:
                    metrics["ipc"] = line_str
    except Exception:
        pass

    return metrics


class JobTask:

    def __init__(self, job_id: int, command: str):
        self.job_id = job_id
        self.status = "PENDING"  # PENDING, START, COMPLETE, ABORTED, FAILED
        self.start_timestamp: Optional[str] = None
        self.start_time: Optional[float] = None
        self.end_timestamp: Optional[str] = None
        self.end_time: Optional[float] = None
        self.elapsed_sec: float = 0.0
        self.exit_code: Optional[int] = None
        self.process: Optional[subprocess.Popen] = None
        self.output_dir = extract_output_dir(command)

        # Detect docker command and generate unique container name
        cmd_stripped = command.strip()
        if "docker run" in cmd_stripped:
            self.container_name = f"virtu_job_{job_id}_{int(time.time())}_{os.getpid()}"
            self.command = cmd_stripped.replace("docker run", f"docker run --name {self.container_name}", 1)
        else:
            self.container_name = None
            self.command = cmd_stripped

    def summary(self) -> str:
        cmd_short = self.command if len(self.command) <= 80 else self.command[:77] + "..."
        return f"Job #{self.job_id} [{cmd_short}]"


class JobScheduler:

    def __init__(self, jobs: List[str], cpus: int, log_file_path: str, workspace_root: str = ""):
        self.cpus = cpus
        self.log_file_path = log_file_path
        self.workspace_root = workspace_root
        self.job_queue: Queue = Queue()
        self.tasks: List[JobTask] = []
        self.active_processes: List[Tuple[JobTask, subprocess.Popen]] = []
        self.lock = threading.Lock()
        self.abort_event = threading.Event()

        self.completed_count = 0
        self.failed_count = 0
        self.aborted_count = 0

        # Enqueue jobs
        for i, cmd in enumerate(jobs, start=1):
            task = JobTask(i, cmd)
            self.tasks.append(task)
            self.job_queue.put(task)

        # Open log file
        log_dir = os.path.dirname(os.path.abspath(log_file_path))
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        self.log_file = open(log_file_path, "a")

    def _log(self, status: str, color_style: str, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plain_line = f"[{status:<8}] [{timestamp}] {msg}"
        color_line = f"{color_style}[{status:<8}]{Style.RESET} {Style.DIM}[{timestamp}]{Style.RESET} {msg}"

        with self.lock:
            # Print to stdout
            print(color_line, flush=True)
            # Write plain text to log file
            self.log_file.write(plain_line + "\n")
            self.log_file.flush()

    def _worker(self):
        while not self.abort_event.is_set():
            try:
                task: JobTask = self.job_queue.get(timeout=0.5)
            except Empty:
                break

            if self.abort_event.is_set():
                task.status = "ABORTED"
                self.aborted_count += 1
                self.job_queue.task_done()
                break

            # Mark START
            task.status = "START"
            task.start_time = time.time()
            task.start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log("START", Style.CYAN, f"{task.summary()}")

            try:
                proc = subprocess.Popen(task.command, shell=True, preexec_fn=os.setsid)
                task.process = proc

                with self.lock:
                    self.active_processes.append((task, proc))

                # Wait for process to complete
                exit_code = proc.wait()
                task.exit_code = exit_code

                with self.lock:
                    self.active_processes = [(t, p) for t, p in self.active_processes if t != task]

                task.end_time = time.time()
                task.end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                task.elapsed_sec = task.end_time - task.start_time
                dur_str = format_duration(task.elapsed_sec)

                if self.abort_event.is_set():
                    task.status = "ABORTED"
                    self.aborted_count += 1
                    self._log("ABORTED", Style.YELLOW, f"Job #{task.job_id} Aborted after {dur_str}")
                elif exit_code == 0:
                    task.status = "COMPLETE"
                    self.completed_count += 1

                    # Check for simulation metrics
                    metrics = parse_sim_metrics(task.output_dir, self.workspace_root)
                    extra_info = ""
                    if metrics:
                        extra_parts = [v for v in metrics.values()]
                        extra_info = f" | {', '.join(extra_parts)}"

                    self._log("COMPLETE", Style.GREEN, f"Job #{task.job_id} Finished in {dur_str}{extra_info}")
                else:
                    task.status = "FAILED"
                    self.failed_count += 1
                    self._log("FAILED", Style.RED, f"Job #{task.job_id} Failed with exit code {exit_code} (Elapsed: {dur_str})")

            except Exception as e:
                task.end_time = time.time()
                task.elapsed_sec = task.end_time - (task.start_time or time.time())
                dur_str = format_duration(task.elapsed_sec)
                task.status = "FAILED"
                self.failed_count += 1
                self._log("FAILED", Style.RED, f"Job #{task.job_id} Exception: {e} (Elapsed: {dur_str})")

            self.job_queue.task_done()

    def run(self):
        total_jobs = len(self.tasks)
        start_wall_time = time.time()

        self._log("INFO", Style.BLUE, f"Starting Job Scheduler with {self.cpus} CPU workers for {total_jobs} job(s)")
        self._log("INFO", Style.BLUE, f"Log File: {self.log_file_path}")

        # Signal handlers for graceful SIGINT / SIGTERM shutdown
        def handle_signal(sig, frame):
            if not self.abort_event.is_set():
                self.abort_event.set()
                self._log("ABORTING", Style.YELLOW, "Received cancellation signal (Ctrl+C). Terminating running jobs...")

                # Send SIGTERM to all active process groups and kill docker containers
                with self.lock:
                    for task, proc in self.active_processes:
                        task.status = "ABORTED"
                        if getattr(task, 'container_name', None):
                            try:
                                subprocess.Popen(f"docker kill {task.container_name}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            except Exception:
                                pass
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except Exception:
                            try:
                                proc.terminate()
                            except Exception:
                                pass

                # Short grace period for graceful termination
                time.sleep(0.5)

                # Force kill any remaining processes in the group and containers
                with self.lock:
                    for task, proc in self.active_processes:
                        if getattr(task, 'container_name', None):
                            try:
                                subprocess.Popen(f"docker rm -f {task.container_name}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            except Exception:
                                pass
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # Spawn worker threads
        workers: List[threading.Thread] = []
        num_workers = min(self.cpus, total_jobs)
        for _ in range(num_workers):
            t = threading.Thread(target=self._worker)
            t.daemon = True
            t.start()
            workers.append(t)

        # Wait for workers to finish
        for t in workers:
            t.join()

        total_elapsed = time.time() - start_wall_time
        summary_msg = (
            f"Scheduler Finished in {format_duration(total_elapsed)} | "
            f"Total: {total_jobs}, "
            f"Completed: {self.completed_count}, "
            f"Failed: {self.failed_count}, "
            f"Aborted: {self.aborted_count}"
        )

        if self.failed_count == 0 and self.aborted_count == 0:
            self._log("SUMMARY", Style.GREEN, summary_msg)
        else:
            self._log("SUMMARY", Style.YELLOW, summary_msg)

        self.log_file.close()


def main():
    parser = argparse.ArgumentParser(
        description="Parallel Job Scheduler & Simulation Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 job_scheduler.py -j jobs.sh -c 4
  python3 job_scheduler.py --jobs-file jobs.txt --cpus 8 --log-file scheduler.log
        """,
    )
    parser.add_argument(
        "--jobs-file", "-j",
        type=str,
        required=True,
        help="Input file containing job commands (one per line)",
    )
    parser.add_argument(
        "--cpus", "-c",
        type=int,
        default=os.cpu_count() or 4,
        help=f"Number of parallel CPU slots / workers (default: {os.cpu_count() or 4})",
    )
    parser.add_argument(
        "--log-file", "-l",
        type=str,
        default="scheduler.log",
        help="Path to output log file (default: scheduler.log)",
    )
    parser.add_argument(
        "--workspace-root", "-w",
        type=str,
        default=os.getcwd(),
        help="Host workspace root path",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colored output in terminal",
    )

    args = parser.parse_args()

    if args.no_color:
        Style.disable()

    jobs_file = os.path.abspath(args.jobs_file)
    if not os.path.exists(jobs_file):
        print(f"Error: Jobs file not found: {jobs_file}", file=sys.stderr)
        sys.exit(1)

    # Read jobs file ignoring empty lines and comments
    jobs: List[str] = []
    with open(jobs_file, "r") as f:
        for line in f:
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                jobs.append(line_str)

    if not jobs:
        print(f"Error: No valid job commands found in {jobs_file}", file=sys.stderr)
        sys.exit(1)

    scheduler = JobScheduler(
        jobs=jobs,
        cpus=args.cpus,
        log_file_path=os.path.abspath(args.log_file),
        workspace_root=os.path.abspath(args.workspace_root),
    )
    scheduler.run()


if __name__ == "__main__":
    main()
