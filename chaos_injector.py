"""
chaos_injector.py
-----------------
Manages the four "Pillars of Failure" by deploying real workloads into
the Kubernetes cluster via kubectl.

Each scenario tracks its own state so the frontend can poll /api/status
for live metrics.
"""

import subprocess
import tempfile
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Scenario YAML manifests
# ---------------------------------------------------------------------------

OOM_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: memory-hog
  namespace: default
  labels:
    scenario: oom
    app: infrastructure-healer
spec:
  containers:
  - name: memory-hog
    image: python:3.9-slim
    command: ["python", "-c"]
    args:
    - |
      import time
      data = []
      print("Starting memory allocation...")
      while True:
          data.append(' ' * 10**7)  # ~10 MB per iteration
          print(f"Allocated {len(data) * 10} MB")
          time.sleep(0.3)
    resources:
      requests:
        memory: "50Mi"
      limits:
        memory: "100Mi"
  restartPolicy: Never
"""

CONNECTION_LEAK_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: connection-leaker
  namespace: default
  labels:
    scenario: connection-leak
    app: infrastructure-healer
spec:
  containers:
  - name: connection-leaker
    image: python:3.9-slim
    command: ["python", "-c"]
    args:
    - |
      import socket, time, threading
      sockets = []
      def leak():
          while True:
              try:
                  s = socket.socket()
                  s.connect(("8.8.8.8", 80))
                  sockets.append(s)
                  print(f"Open connections: {len(sockets)}")
              except:
                  pass
              time.sleep(0.1)
      threading.Thread(target=leak, daemon=True).start()
      time.sleep(3600)
    resources:
      requests:
        memory: "32Mi"
      limits:
        memory: "256Mi"
  restartPolicy: Never
"""

ZOMBIE_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: zombie-factory
  namespace: default
  labels:
    scenario: zombie
    app: infrastructure-healer
spec:
  containers:
  - name: zombie-factory
    image: python:3.9-slim
    command: ["python", "-c"]
    args:
    - |
      import os, time
      print("Spawning zombie processes...")
      while True:
          pid = os.fork()
          if pid == 0:
              os._exit(0)   # child exits immediately → becomes zombie
          print(f"Zombie PIDs accumulated...")
          time.sleep(0.5)
    resources:
      requests:
        memory: "32Mi"
      limits:
        memory: "128Mi"
  restartPolicy: Never
"""

POISONED_UPDATE_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: poisoned-app
  namespace: default
  labels:
    scenario: poisoned-update
    app: infrastructure-healer
spec:
  replicas: 3
  selector:
    matchLabels:
      app: poisoned-app
  template:
    metadata:
      labels:
        app: poisoned-app
    spec:
      containers:
      - name: poisoned-app
        image: nginx:latest
        env:
        - name: DATABASE_URL
          value: "postgres://user:password@nonexistent-db:5432/prod"
        - name: APP_ENV
          value: "PRODUCTON"  # Intentional typo → app reads wrong env
        - name: SECRET_KEY
          value: ""            # Missing secret → app crash on startup
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080         # Wrong port → probe always fails
          initialDelaySeconds: 5
          periodSeconds: 3
        resources:
          requests:
            memory: "32Mi"
          limits:
            memory: "64Mi"
"""

# ---------------------------------------------------------------------------
# State tracker
# ---------------------------------------------------------------------------

SCENARIOS = {
    "oom": {
        "name": "The OOM",
        "description": "A pod exceeds its memory limits, entering CrashLoopBackOff.",
        "icon": "💥",
        "difficulty": "Beginner",
        "learning": "Resource limits, requests, and horizontal scaling.",
        "yaml": OOM_YAML,
        "pod_names": ["memory-hog"],
        "kind": "pod",
        "briefing": "Hey junior. Looks like an OOM (Out of Memory) incident just triggered. I'm seeing a pod called `memory-hog` that might be crashing because it's eating up too much RAM. You take point on this. What's your first move?"
    },
    "connection-leak": {
        "name": "The Connection Leak",
        "description": "Unclosed sockets exhaust the connection pool, causing 503 errors.",
        "icon": "🕳️",
        "difficulty": "Intermediate",
        "learning": "Monitoring service health and connection pool management.",
        "yaml": CONNECTION_LEAK_YAML,
        "pod_names": ["connection-leaker"],
        "kind": "pod",
        "briefing": "Hi there. I just noticed a connection leak scenario starting up. We have a pod named `connection-leaker` that might be leaving sockets open and eating up all the available connections. It's your turn to debug. How do you want to handle this?"
    },
    "zombie": {
        "name": "The Zombie Apocalypse",
        "description": "Defunct processes fill the PID table, starving the scheduler.",
        "icon": "🧟",
        "difficulty": "Intermediate",
        "learning": "OS-level troubleshooting and process signals (SIGKILL/SIGTERM).",
        "yaml": ZOMBIE_YAML,
        "pod_names": ["zombie-factory"],
        "kind": "pod",
        "briefing": "Uh oh, a zombie apocalypse scenario just fired off. There's a pod called `zombie-factory` that's probably spawning a bunch of defunct processes and filling up the PID table. We need to investigate this before it starves the whole node. Show me what you've got."
    },
    "poisoned-update": {
        "name": "The Poisoned Update",
        "description": "A mis-configured deployment is stuck with 0/3 pods ready.",
        "icon": "☠️",
        "difficulty": "Advanced",
        "learning": "Mastering rollbacks and declarative infrastructure recovery.",
        "yaml": POISONED_UPDATE_YAML,
        "pod_names": ["poisoned-app"],
        "kind": "deployment",
        "briefing": "Hey! We've got a 'poisoned update' situation. A deployment just went out with some bad configs — maybe a typo or missing secret — and it looks like the pods are failing to become ready. How should we start debugging this rollout?"
    },
}


@dataclass
class ScenarioState:
    active: bool = False
    scenario_key: Optional[str] = None
    start_time: Optional[float] = None
    events: list = field(default_factory=list)

    def reset(self):
        self.active = False
        self.scenario_key = None
        self.start_time = None
        self.events = []

    def elapsed_seconds(self) -> int:
        if self.start_time is None:
            return 0
        return int(time.time() - self.start_time)

    def add_event(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.events.append(f"[{ts}] {msg}")
        if len(self.events) > 100:
            self.events = self.events[-100:]


# Singleton state — shared across the FastAPI app
state = ScenarioState()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_scenarios():
    """Return metadata for all 4 scenarios (for the frontend scenario picker)."""
    return [
        {
            "key": key,
            "name": meta["name"],
            "description": meta["description"],
            "icon": meta["icon"],
            "difficulty": meta["difficulty"],
            "learning": meta["learning"],
        }
        for key, meta in SCENARIOS.items()
    ]


def inject(scenario_key: str):
    """Deploy the chaos workload for the given scenario into the cluster."""
    if scenario_key not in SCENARIOS:
        raise ValueError(f"Unknown scenario: '{scenario_key}'. Valid: {list(SCENARIOS.keys())}")

    if state.active:
        raise RuntimeError(f"Scenario '{state.scenario_key}' is already active. Clean up first.")

    meta = SCENARIOS[scenario_key]
    state.add_event(f"🚨 Injecting scenario: {meta['name']}")

    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.yaml') as f:
        f.write(meta["yaml"])
        temp_path = f.name

    try:
        # Step 1: Force delete any existing resource so we have a clean slate.
        # We wait for deletion to complete to avoid immutability race conditions on apply.
        for pod_name in meta["pod_names"]:
            subprocess.run(
                ["kubectl", "delete", meta["kind"], pod_name, "--ignore-not-found=true"],
                capture_output=True, text=True
            )

        # Step 2: Apply the fresh manifest
        result = subprocess.run(
            ["kubectl", "apply", "-f", temp_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"kubectl apply failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        state.active = True
        state.scenario_key = scenario_key
        state.start_time = time.time()
        state.add_event(f"✅ Workload deployed → {', '.join(meta['pod_names'])}")
        if result.stdout.strip():
            state.add_event(result.stdout.strip())
        return {"status": "injected", "scenario": meta["name"], "output": result.stdout}
    finally:
        os.unlink(temp_path)


def cleanup():
    """Remove all chaos workloads from the cluster."""
    if not state.active or state.scenario_key is None:
        raise RuntimeError("No active scenario to clean up.")

    meta = SCENARIOS[state.scenario_key]
    state.add_event(f"🔧 Healing cluster — removing {meta['name']} workloads...")

    errors = []
    for pod_name in meta["pod_names"]:
        result = subprocess.run(
            ["kubectl", "delete", meta["kind"], pod_name, "--ignore-not-found=true"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            errors.append(result.stderr)
        else:
            state.add_event(f"🗑️  Deleted {meta['kind']}/{pod_name}")

    if errors:
        raise RuntimeError(f"Partial cleanup errors:\n" + "\n".join(errors))

    state.add_event("✅ Cluster healed. All chaos workloads removed.")
    scenario_name = meta["name"]
    state.reset()
    return {"status": "cleaned", "scenario": scenario_name}


def get_status():
    """
    Return current cluster state: scenario info, elapsed time, recent events,
    and live pod metrics fetched from kubectl.
    """
    pods = _get_pod_statuses()

    return {
        "active": state.active,
        "scenario_key": state.scenario_key,
        "scenario_name": SCENARIOS[state.scenario_key]["name"] if state.scenario_key else None,
        "elapsed_seconds": state.elapsed_seconds(),
        "events": state.events[-30:],  # last 30 events for the log panel
        "pods": pods,
    }


def _get_pod_statuses():
    """Fetch pod statuses from kubectl for the healer's labelled pods."""
    try:
        result = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", "default",
                "-l", "app=infrastructure-healer",
                "--no-headers",
                "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,READY:.status.containerStatuses[0].ready"
            ],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        pods = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                pods.append({
                    "name": parts[0],
                    "status": parts[1],
                    "restarts": parts[2] if len(parts) > 2 else "0",
                    "ready": parts[3] if len(parts) > 3 else "false",
                })
        return pods
    except Exception:
        return []
