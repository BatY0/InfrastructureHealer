# KubeQuest: AI Infrastructure Simulator (Gemma 4)

KubeQuest is an incident-response training simulator that teaches practical Kubernetes debugging through guided chaos scenarios.  
Learners investigate real failure patterns in a sandbox cluster while an AI mentor (Gemma 4) provides progressive hints instead of instant answers.

## Why This Project

Many learners can run commands but struggle with operational reasoning under pressure.  
KubeQuest trains a repeatable debugging method:

- Observe system state
- Form a hypothesis
- Test with terminal evidence
- Verify service recovery

This focuses on practical digital reliability skills for students, junior DevOps engineers, and bootcamp cohorts.

## Impact Narrative

KubeQuest improves infrastructure learning outcomes by turning abstract Kubernetes concepts into realistic incident drills.  
Learners practice diagnosing failures from live evidence, applying remediation safely, and validating recovery in a guided loop.

Target outcomes:

- Faster incident triage confidence for early-career engineers
- Better root-cause identification through evidence-based debugging
- Stronger operational readiness for education and workforce training programs

## Gemma 4 Usage

- Mentor engine runs via Ollama using `gemma4:e2b` (`engine.py`).
- The model drives scenario coaching, contextual guidance from terminal history, and victory-review explanations.
- Prompting enforces methodology-first hints with escalating guidance rather than immediate command reveal.

## Core Features

- 6 guided infrastructure incidents (from beginner to expert)
- Real terminal command execution with safety guardrails (`kubectl` only)
- Live pod dashboard and scenario state tracking
- Progressive level unlocks and star-based scoring
- AI mentor chat integrated with cluster context and terminal activity

## Scenario Catalog

1. Hello, Cluster - environment discovery basics
2. Silent Crash - restart loop and log-driven diagnosis
3. OOM - memory limits and runtime stabilization
4. Poisoned Update - rollout rollback and recovery
5. Zombie Apocalypse - OS-level process failure containment
6. Connection Leak - socket exhaustion investigation

## Architecture

- **Backend:** FastAPI (`main.py`), scenario engine (`chaos_injector.py`), mentor engine (`engine.py`)
- **Frontend:** React + TypeScript + Vite (`frontend/`)
- **Model Runtime:** Ollama local API (`http://localhost:11434/api/chat`)
- **Sandbox Infra:** Kubernetes (local k3d cluster recommended)

## Model Settings

- Users can switch mentor models directly from the frontend.
- The backend persists model choice in `model_settings.json`.
- Each preset includes approximate hardware guidance to help users choose a model that matches their machine.
- Advanced users can enter any custom Ollama model id from the UI.

## Quick Start

### 1) Prerequisites

- Python 3.10+
- Node.js 20+
- Docker
- `kubectl`
- `k3d` (recommended for local sandbox)
- Ollama with Gemma 4 model

### 2) Start a local cluster

```bash
python sandbox.py create
```

### 3) Start backend

From project root:

```bash
pip install fastapi uvicorn requests pydantic docker
uvicorn main:app --reload
```

Backend runs on `http://127.0.0.1:8000`.

### 4) Start frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

### 5) Pull and run Gemma 4 in Ollama

```bash
ollama pull gemma4:e2b
```

Ensure Ollama is running before opening mentor chat.

## API Endpoints (Backend)

- `GET /api/scenarios` - scenario metadata
- `GET /api/status` - live scenario and pod status
- `POST /api/chaos/inject` - start selected scenario
- `POST /api/chaos/cleanup` - end/reset current scenario
- `POST /api/chat` - mentor response generation
- `POST /api/command/execute` - safe terminal execution

## Safety and Scope

- Terminal endpoint blocks non-`kubectl` commands and shell chaining symbols.
- This is a training simulator, not a production incident automation tool.
- Designed for local, sandboxed use.

## Known Limitations

- Scenario verification rules are heuristic and can be expanded.
- Model quality depends on local hardware and Ollama runtime responsiveness.

### Model Capability Tradeoffs

- Current default is `gemma4:e2b`, which is lightweight and responsive for local coaching loops.
- Smaller models can be less consistent at multi-step mentoring (for example: weaker hypothesis tracking across long chats).
- A larger Gemma 4 variant (such as a 4B-class model, if available in your runtime) can improve coaching depth, hint quality, and reasoning stability.
- Larger models usually require more VRAM/RAM and may increase latency, so the best choice depends on your hardware and classroom/demo constraints.

### Recommended Model Presets

- **Fast (lower-resource laptops):** `gemma4:e2b`  
  Best for smooth UX and quick hint turnaround when hardware is limited.
- **Balanced (most demos):** nearest available mid-size Gemma 4 variant in your Ollama setup  
  Better reasoning consistency while keeping latency acceptable for live mentoring.
- **Quality (strong hardware):** largest stable Gemma 4 variant your machine can run  
  Best for deeper coaching and more reliable multi-turn methodology guidance.

Tip: keep one fallback profile ready (`Fast`) before live judging sessions in case of resource pressure.


## License

Prototype project for educational and hackathon use.
