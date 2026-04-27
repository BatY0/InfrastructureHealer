"""
chaos_injector.py
-----------------
Manages the scenarios for KubeQuest.
Each scenario tracks its own state so the frontend can poll /api/status
for live metrics.
"""

import subprocess
import tempfile
import os
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Scenario YAML manifests
# ---------------------------------------------------------------------------

# NEW: LEVEL 1
HELLO_CLUSTER_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: hello-world
  namespace: default
  labels:
    scenario: hello-cluster
    app: infrastructure-healer
spec:
  containers:
  - name: hello-world
    image: nginx:alpine
    resources:
      requests:
        memory: "16Mi"
      limits:
        memory: "32Mi"
"""

# NEW: LEVEL 2
SILENT_CRASH_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: crashing-app
  namespace: default
  labels:
    scenario: silent-crash
    app: infrastructure-healer
spec:
  containers:
  - name: crashing-app
    image: python:3.9-slim
    command: ["python", "-c"]
    args:
    - |
      import time
      print("Initializing application...")
      time.sleep(2)
      print("Connecting to database...")
      time.sleep(1)
      raise Exception("FATAL: Database credentials missing or invalid!")
    resources:
      requests:
        memory: "16Mi"
      limits:
        memory: "32Mi"
"""

OOM_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memory-hog
  namespace: default
  labels:
    scenario: oom
    app: infrastructure-healer
spec:
  replicas: 1
  selector:
    matchLabels:
      app: infrastructure-healer
      scenario: oom
  template:
    metadata:
      labels:
        app: infrastructure-healer
        scenario: oom
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
          for i in range(15):
              data.append(' ' * 10**7)  # ~10 MB per iteration
              print(f"Allocated {(i+1) * 10} MB")
              time.sleep(0.3)
          print("Memory stabilized at 150MB. Application running smoothly.")
          while True:
              time.sleep(60)
        resources:
          requests:
            memory: "50Mi"
          limits:
            memory: "100Mi"
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
      app: infrastructure-healer
      scenario: poisoned-update
  template:
    metadata:
      labels:
        app: infrastructure-healer
        scenario: poisoned-update
    spec:
      containers:
      - name: poisoned-app
        image: nginx:latest
        env:
        - name: DATABASE_URL
          value: "postgres://user:password@nonexistent-db:5432/prod"
        - name: APP_ENV
          value: "PRODUCTON"  # Intentional typo
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080         # Wrong port
          initialDelaySeconds: 5
          periodSeconds: 3
        resources:
          requests:
            memory: "32Mi"
          limits:
            memory: "64Mi"
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
              os._exit(0)
          print(f"Zombie PIDs accumulated...")
          time.sleep(0.5)
    resources:
      requests:
        memory: "32Mi"
      limits:
        memory: "128Mi"
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


# ---------------------------------------------------------------------------
# State tracker & Curriculum Metadata
# ---------------------------------------------------------------------------

SCENARIOS = {
    "hello-cluster": {
        "order": 1,
        "name": "Level 1: Hello, Cluster!",
        "description": "Learn the basics of navigating the cluster.",
        "icon": "👋",
        "difficulty": "Beginner",
        "learning": "Listing resources with kubectl.",
        "taught_commands": ["kubectl get pods", "kubectl get nodes"],
        "tutorial_text": "Welcome to KubeQuest! Before fixing broken infrastructure, you must learn to see it.\n\nRun `kubectl get pods` to list all running applications, and `kubectl get nodes` to see the servers powering them. Verify the pod is running, then click 'Finish Level'.",
        "yaml": HELLO_CLUSTER_YAML,
        "pod_names": ["hello-world"],
        "kind": "pod",
        "briefing": "Welcome to your first day! Let's start easy. I just spun up a basic web server. Can you run some commands to check on it and tell me what node it is running on?",
        "victory_condition": "The user successfully runs the commands and tells you the node name or acknowledges the pod is running."
    },
    "silent-crash": {
        "order": 2,
        "name": "Level 2: The Silent Crash",
        "description": "A pod is failing to start. Time to investigate why.",
        "icon": "🔍",
        "difficulty": "Beginner",
        "learning": "Describing pods and reading logs.",
        "taught_commands": ["kubectl describe pod <name>", "kubectl logs <name>"],
        "tutorial_text": "Not all apps start perfectly. When a pod crashes, it enters 'CrashLoopBackOff'.\n\nUse `kubectl describe pod <name>` to see cluster events, and `kubectl logs <name>` to read the actual application error output.",
        "yaml": SILENT_CRASH_YAML,
        "pod_names": ["crashing-app"],
        "kind": "pod",
        "briefing": "Hey there. I tried to deploy a new python app, but it keeps crashing and restarting. Can you grab the logs and tell me what the error message says?",
        "victory_condition": "The user successfully reads the logs and tells you the error is about missing database credentials. (Note: The pod cannot be fixed in this level, finding the error IS the win)."
    },
    "oom": {
        "order": 3,
        "name": "Level 3: The OOM",
        "description": "A deployment exceeds its memory limits.",
        "icon": "💥",
        "difficulty": "Intermediate",
        "learning": "Resource limits, requests, and updating deployments.",
        "taught_commands": ["kubectl set resources deployment <name> --limits=memory=..."],
        "tutorial_text": "Containers are strictly limited in how much memory they can use. If they exceed this, Kubernetes kills them with an 'OOMKilled' (Out Of Memory) error.\n\nYou'll need to increase the limits using `kubectl set resources`.",
        "yaml": OOM_YAML,
        "pod_names": ["memory-hog"],
        "kind": "deployment",
        "briefing": "Looks like an OOM (Out of Memory) incident just triggered. The `memory-hog` deployment is eating up too much RAM. How should we fix this?",
        "victory_condition": "The user successfully increases the memory limits and the pod status in the cluster state shows as 'Running' with 1/1 READY."
    },
    "poisoned-update": {
        "order": 4,
        "name": "Level 4: The Poisoned Update",
        "description": "A mis-configured deployment is stuck.",
        "icon": "☠️",
        "difficulty": "Advanced",
        "learning": "Rollbacks and deployment history.",
        "taught_commands": ["kubectl rollout history deployment <name>", "kubectl rollout undo deployment <name>"],
        "tutorial_text": "Someone pushed a bad config! The pods are failing their readiness probes.\n\nInstead of finding the typo, the fastest way to restore service is to roll back to the previous known-good state using `kubectl rollout undo`.",
        "yaml": POISONED_UPDATE_YAML,
        "pod_names": ["poisoned-app"],
        "kind": "deployment",
        "briefing": "We've got a 'poisoned update' situation. A deployment just went out with bad configs. How should we restore the service quickly?",
        "victory_condition": "The user successfully rolls back the deployment and the pods show as 'Running' with 1/1 READY."
    },
    "zombie": {
        "order": 5,
        "name": "Level 5: The Zombie Apocalypse",
        "description": "Defunct processes fill the PID table.",
        "icon": "🧟",
        "difficulty": "Advanced",
        "learning": "OS-level troubleshooting and process signals.",
        "taught_commands": ["kubectl exec -it <pod> -- ps aux", "kubectl delete pod <name>"],
        "tutorial_text": "Sometimes the problem isn't Kubernetes, but the OS itself. A pod is spawning zombie processes, starving the node of PIDs.\n\nYou might need to execute into the pod to see what's happening, or just kill the pod entirely.",
        "yaml": ZOMBIE_YAML,
        "pod_names": ["zombie-factory"],
        "kind": "pod",
        "briefing": "Uh oh, a zombie apocalypse scenario just fired off. There's a pod called `zombie-factory` that's filling up the PID table. Show me what you've got.",
        "victory_condition": "The user deletes the pod to clear the zombie processes."
    },
    "connection-leak": {
        "order": 6,
        "name": "Level 6: The Connection Leak",
        "description": "Unclosed sockets exhaust the pool.",
        "icon": "🕳️",
        "difficulty": "Expert",
        "learning": "Network troubleshooting.",
        "taught_commands": ["kubectl exec -it <pod> -- netstat -an"],
        "tutorial_text": "An application is opening network sockets but never closing them, eventually bringing down the network stack.\n\nInvestigate the open connections.",
        "yaml": CONNECTION_LEAK_YAML,
        "pod_names": ["connection-leaker"],
        "kind": "pod",
        "briefing": "I just noticed a connection leak. The `connection-leaker` pod is leaving sockets open. It's your turn to debug. How do you want to handle this?",
        "victory_condition": "The user investigates the connections and figures out the pod is leaking sockets, then deletes the pod."
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

# Singleton state
state = ScenarioState()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_scenarios():
    """Return metadata for all scenarios, sorted by order."""
    scenarios_list = [
        {
            "key": key,
            "order": meta["order"],
            "name": meta["name"],
            "description": meta["description"],
            "icon": meta["icon"],
            "difficulty": meta["difficulty"],
            "learning": meta["learning"],
            "taught_commands": meta["taught_commands"],
            "tutorial_text": meta["tutorial_text"],
        }
        for key, meta in SCENARIOS.items()
    ]
    # Sort by order so the UI displays them Level 1 -> Level 6
    return sorted(scenarios_list, key=lambda x: x["order"])

def inject(scenario_key: str):
    if scenario_key not in SCENARIOS:
        raise ValueError(f"Unknown scenario: '{scenario_key}'.")

    if state.active:
        raise RuntimeError(f"Scenario '{state.scenario_key}' is already active. Clean up first.")

    meta = SCENARIOS[scenario_key]
    state.add_event(f"🚨 Starting {meta['name']}...")

    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.yaml') as f:
        f.write(meta["yaml"])
        temp_path = f.name

    try:
        # Clean slate
        for pod_name in meta["pod_names"]:
            subprocess.run(
                ["kubectl", "delete", meta["kind"], pod_name, "--ignore-not-found=true"],
                capture_output=True, text=True
            )

        # Apply fresh manifest
        result = subprocess.run(
            ["kubectl", "apply", "-f", temp_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed:\n{result.stderr}")
            
        state.active = True
        state.scenario_key = scenario_key
        state.start_time = time.time()
        state.add_event(f"✅ Level initialized. Environment ready.")
        
        return {"status": "injected", "scenario": meta["name"], "output": result.stdout}
    finally:
        os.unlink(temp_path)

def cleanup():
    if not state.active or state.scenario_key is None:
        raise RuntimeError("No active scenario to clean up.")

    meta = SCENARIOS[state.scenario_key]
    state.add_event(f"🔧 Validating and cleaning up {meta['name']}...")

    errors = []
    for pod_name in meta["pod_names"]:
        result = subprocess.run(
            ["kubectl", "delete", meta["kind"], pod_name, "--ignore-not-found=true"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            errors.append(result.stderr)
        else:
            state.add_event(f"🗑️  Cleaned up {meta['kind']}/{pod_name}")

    if errors:
        raise RuntimeError(f"Partial cleanup errors:\n" + "\n".join(errors))

    scenario_name = meta["name"]
    state.reset()
    return {"status": "cleaned", "scenario": scenario_name}

def get_status():
    pods = _get_pod_statuses()
    return {
        "active": state.active,
        "scenario_key": state.scenario_key,
        "scenario_name": SCENARIOS[state.scenario_key]["name"] if state.scenario_key else None,
        "elapsed_seconds": state.elapsed_seconds(),
        "events": state.events[-30:],
        "pods": pods,
    }

def _get_pod_statuses():
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