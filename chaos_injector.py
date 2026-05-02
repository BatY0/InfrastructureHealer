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
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Scenario YAML manifests
# ---------------------------------------------------------------------------

#
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
    imagePullPolicy: IfNotPresent
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
    image: python:alpine
    imagePullPolicy: IfNotPresent
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
        image: python:alpine
        imagePullPolicy: IfNotPresent
        command: ["python", "-c"]
        args:
        - |
          import time
          data = []
          print("Starting memory allocation...")
          # Simulate an app that needs ~500MB of RAM to start up
          for i in range(50):
              data.append(' ' * 10**7)  # ~10 MB per iteration
              print(f"Allocated {(i+1) * 10} MB")
              time.sleep(0.3)
          print("Memory stabilized at 500MB. Application running smoothly.")
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
  strategy:
    type: Recreate
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
        imagePullPolicy: IfNotPresent
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
POISONED_UPDATE_HEALTHY_YAML = """
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
        image: nginx:alpine
        imagePullPolicy: IfNotPresent
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
    image: python:alpine
    imagePullPolicy: IfNotPresent
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
    image: python:alpine
    imagePullPolicy: IfNotPresent
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
        "tutorial_text": "Welcome to your first incident response drill. A basic service is running, and your job is to confirm the platform view is healthy before we move to harder outages.\n\nFocus on two questions: what workloads exist right now, and what machines are hosting them. Your mentor can coach you step by step if you get stuck.",
        "yaml": HELLO_CLUSTER_YAML,
        "pod_names": ["hello-world"],
        "kind": "pod",
        "briefing": "Welcome to your first day on call. We have a newly deployed web pod and need a quick health and placement check before declaring the environment stable. Inspect the cluster state and identify where the pod is running.",
        "victory_condition": "The user successfully runs the commands and identifies the node name or verifies the pod is running.",
        "victory_message": "Great job! You just learned how to explore the cluster. `get nodes` shows you the physical machines, and `get pods` shows you the applications running on them. Always start here!"
    },
    "silent-crash": {
        "order": 2,
        "name": "Level 2: The Silent Crash",
        "description": "A pod is failing to start. Time to investigate why.",
        "icon": "🔍",
        "difficulty": "Beginner",
        "learning": "Describing pods and reading logs.",
        "taught_commands": ["kubectl describe pod <name>", "kubectl logs <name>"],
        "tutorial_text": "A newly shipped service keeps restarting and users cannot access it. This level teaches evidence-driven debugging: inspect runtime signals, then trace the root cause from system behavior to application failure.\n\nYour objective is to collect enough proof to explain why the crash is happening, not to patch code.",
        "yaml": SILENT_CRASH_YAML,
        "pod_names": ["crashing-app"],
        "kind": "pod",
        "briefing": "Production alert: the new Python workload is in a restart loop. Investigate the failing pod and extract the real error behind the restarts.",
        "victory_condition": "The user successfully reads the logs and identifies that the error is about missing database credentials. (Note: The pod cannot be fixed in this level, finding the error IS the win).",
        "victory_message": "Excellent! You used `kubectl logs` to discover the missing database credentials. Reading logs is always step one when an application crashes."
    },
    "oom": {
        "order": 3,
        "name": "Level 3: The OOM",
        "description": "A deployment exceeds its memory limits.",
        "icon": "💥",
        "difficulty": "Intermediate",
        "learning": "Resource limits, requests, and updating deployments.",
        "taught_commands": ["kubectl set resources deployment <name> --limits=memory=..."],
        "tutorial_text": "Traffic increased and one deployment is repeatedly dying under memory pressure. Kubernetes is protecting the node by terminating containers that exceed limits, but that also takes your service down.\n\nDiagnose the resource mismatch and apply a safer runtime configuration so the app can stay alive.",
        "yaml": OOM_YAML,
        "pod_names": ["memory-hog"],
        "kind": "deployment",
        "briefing": "We have an active OOM incident. The `memory-hog` deployment starts, consumes memory aggressively, and gets killed before it can serve reliably. Investigate the failure pattern and guide the cluster toward a stable memory envelope.",
        "victory_condition": "The user successfully increases the memory limits and the pod status in the cluster state shows as 'Running' with 1/1 READY.",
        "victory_message": "Perfect! You identified the OOMKilled error and increased the memory limits in the deployment. The pod now has enough breathing room to process the data without crashing."
    },
    "poisoned-update": {
        "order": 4,
        "name": "Level 4: The Poisoned Update",
        "description": "A mis-configured deployment is stuck.",
        "icon": "☠️",
        "difficulty": "Advanced",
        "learning": "Rollbacks and deployment history.",
        "taught_commands": ["kubectl rollout history deployment <name>", "kubectl rollout undo deployment <name>"],
        "tutorial_text": "A fresh rollout introduced a bad configuration and the service is now unhealthy. In real incidents, restoring availability is often more important than hunting every typo during the outage.\n\nYour mission is to recover service quickly using deployment revision history and controlled rollback.",
        "yaml": POISONED_UPDATE_HEALTHY_YAML,
        "pod_names": ["poisoned-app"],
        "kind": "deployment",
        "briefing": "The latest release poisoned runtime health and pods are failing readiness checks. We need rapid recovery with minimal user impact. Inspect rollout state, revert to the last known good revision, and confirm replicas are healthy again.",
        "victory_condition": "The user successfully rolls back the deployment and the pods show as 'Running' with 1/1 READY.",
        "victory_message": "Crisis averted! You used `kubectl rollout undo` to instantly revert the bad code deployment. The traffic is flowing again while the developers fix their code."
    },
    "zombie": {
        "order": 5,
        "name": "Level 5: The Zombie Apocalypse",
        "description": "Defunct processes fill the PID table.",
        "icon": "🧟",
        "difficulty": "Advanced",
        "learning": "OS-level troubleshooting and process signals.",
        "taught_commands": ["kubectl exec <pod> -- ps aux", "kubectl delete pod <name>"],
        "tutorial_text": "Not all outages come from app logic; some come from process lifecycle failures. Here, a workload is leaking defunct processes and exhausting the node's PID space, which can cascade into wider instability.\n\nInvestigate inside the container, confirm the zombie pattern, and take the safest containment action.",
        "yaml": ZOMBIE_YAML,
        "pod_names": ["zombie-factory"],
        "kind": "pod",
        "briefing": "Kernel-level stress event detected. The `zombie-factory` pod is generating defunct child processes that never get reaped, steadily consuming PID capacity. Validate what is happening from inside the workload and execute containment before the node degrades further.",
        "victory_condition": "The user deletes the pod to clear the zombie processes.",
        "victory_message": "Ghost busted! You successfully tracked down and terminated the pod containing the zombie processes. The cluster's CPU is safe once more."
    },
    "connection-leak": {
        "order": 6,
        "name": "Level 6: The Connection Leak",
        "description": "Unclosed sockets exhaust the pool.",
        "icon": "🕳️",
        "difficulty": "Expert",
        "learning": "Network troubleshooting.",
        "taught_commands": ["kubectl exec <pod> -- netstat -an", "kubectl delete pod <name>"],
        "tutorial_text": "This incident simulates a slow-burn networking failure. The app keeps opening sockets and never releasing them, so connection tables and file descriptors gradually fill up until requests fail.\n\nTrace the leak from inside the workload and decide on a mitigation that restores service quickly.",
        "yaml": CONNECTION_LEAK_YAML,
        "pod_names": ["connection-leaker"],
        "kind": "pod",
        "briefing": "Network reliability alert: the `connection-leaker` workload is accumulating open sockets and pushing the system toward exhaustion. Gather concrete evidence of the leak and apply immediate remediation to protect cluster health.",
        "victory_condition": "The user investigates the connections and figures out the pod is leaking sockets, then deletes the pod.",
        "victory_message": "Masterful troubleshooting! You used `netstat` inside the container to prove the connection leak, and then nuked the pod to recycle the connections."
    },
}

@dataclass
class ScenarioState:
    active: bool = False
    scenario_key: Optional[str] = None
    start_time: Optional[float] = None
    events: list = field(default_factory=list)
    llm_verified: bool = False

    def reset(self):
        self.active = False
        self.scenario_key = None
        self.start_time = None
        self.events = []
        self.llm_verified = False

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
            "victory_message": meta.get("victory_message")
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
        # Clean slate: Nuke ANY existing infrastructure-healer apps to prevent ghost pods
        subprocess.run(
            ["kubectl", "delete", "deployment,pod", "-l", "app=infrastructure-healer", "--ignore-not-found=true"],
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

        # For poisoned-update: apply a second "bad" manifest on top to create rollout history
        if scenario_key == "poisoned-update":
            state.add_event("⏳ Simulating bad deployment rollout...")
            time.sleep(2)  # Let revision 1 settle
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.yaml') as f2:
                f2.write(POISONED_UPDATE_YAML)
                bad_path = f2.name
            try:
                bad_result = subprocess.run(
                    ["kubectl", "apply", "-f", bad_path],
                    capture_output=True, text=True
                )
                if bad_result.returncode != 0:
                    raise RuntimeError(f"Bad deployment apply failed:\n{bad_result.stderr}")
                state.add_event("💀 Bad config deployed — pods are now failing readiness probes!")
            finally:
                os.unlink(bad_path)

        return {"status": "injected", "scenario": meta["name"], "output": result.stdout}
    finally:
        os.unlink(temp_path)

def cleanup():
    if not state.active or state.scenario_key is None:
        raise RuntimeError("No active scenario to clean up.")

    meta = SCENARIOS[state.scenario_key]
    state.add_event(f"🔧 Validating and cleaning up {meta['name']}...")

    errors = []
    # Clean up ALL workloads with the healer label
    result = subprocess.run(
        ["kubectl", "delete", "deployment,pod", "-l", "app=infrastructure-healer", "--ignore-not-found=true"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        errors.append(result.stderr)
    else:
        state.add_event(f"🗑️  Cleaned up all scenario workloads")

    if errors:
        raise RuntimeError(f"Partial cleanup errors:\n" + "\n".join(errors))

    scenario_name = meta["name"]
    state.reset()
    return {"status": "cleaned", "scenario": scenario_name}

def check_victory(scenario_key: str, state: ScenarioState, pods: list) -> bool:
    if not state.active:
        return False
        
    if scenario_key == "hello-cluster":
        has_pods = any(re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s+\$\s+kubectl\s+get\s+(pods?|po)\b", e) for e in state.events)
        has_nodes = any(re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s+\$\s+kubectl\s+get\s+(nodes?|no)\b", e) for e in state.events)
        return has_pods and has_nodes and state.llm_verified

    if scenario_key == "silent-crash":
        has_logs = any(re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s+\$\s+kubectl\s+logs\s+.*crashing-app", e) for e in state.events)
        has_desc = any(re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s+\$\s+kubectl\s+describe\s+(pod|po|pods)\s+.*crashing-app", e) for e in state.events)
        return has_logs and has_desc and state.llm_verified

    if scenario_key == "oom":
        has_set = any("set resources" in e for e in state.events)
        for p in pods:
            if p["name"].startswith("memory-hog") and p["status"] == "Running" and p["ready"] == "true" and has_set:
                return True
        return False

    if scenario_key == "poisoned-update":
        has_undo = any("rollout undo" in e for e in state.events)
        running_ready = sum(1 for p in pods if p["name"].startswith("poisoned-app") and p["status"] == "Running" and p["ready"] == "true")
        return has_undo and running_ready >= 3

    if scenario_key == "zombie" or scenario_key == "connection-leak":
        meta = SCENARIOS[scenario_key]
        for name in meta["pod_names"]:
            if any(p["name"].startswith(name) for p in pods):
                return False
        if state.elapsed_seconds() > 3:
            return True

    return False

def get_status():
    pods = _get_pod_statuses()
    is_victorious = False
    if state.active and state.scenario_key:
        is_victorious = check_victory(state.scenario_key, state, pods)
        
    return {
        "active": state.active,
        "scenario_key": state.scenario_key,
        "scenario_name": SCENARIOS[state.scenario_key]["name"] if state.scenario_key else None,
        "elapsed_seconds": state.elapsed_seconds(),
        "events": state.events[-30:],
        "pods": pods,
        "victory": is_victorious,
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