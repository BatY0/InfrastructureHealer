from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import chaos_injector
import subprocess

app = FastAPI(title="Infrastructure Healer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-import engine so startup is fast
from engine import GemmaDevOpsEngine
agent = GemmaDevOpsEngine()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    history: List[Message]
    terminal_history: str = ""

class ExecuteRequest(BaseModel):
    command: str

class ChaosInjectRequest(BaseModel):
    scenario: str # "oom" | "connection-leak" | "zombie" | "poisoned-update"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/scenarios")
def list_scenarios():
    """Return metadata for all 4 chaos scenarios."""
    return chaos_injector.get_scenarios()


@app.get("/api/status")
def get_status():
    """Live cluster status — poll this every 3 s from the frontend."""
    return chaos_injector.get_status()


@app.post("/api/chaos/inject")
async def chaos_inject(request: ChaosInjectRequest):
    try:
        result = chaos_injector.inject(request.scenario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Return the static briefing text so the student gets instant context
    # without waiting for a slow LLM generation.
    try:
        meta = chaos_injector.SCENARIOS[request.scenario]
        
        # We mimic the agent response dictionary structure so the frontend
        # can just render it normally as a chat message.
        result["briefing"] = {
            "type": "message",
            "thought": "",
            "answer": meta["briefing"]
        }
    except Exception:
        result["briefing"] = None

    return result


@app.post("/api/chaos/cleanup")
async def chaos_cleanup():
    try:
        result = chaos_injector.cleanup()
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        history = [m.model_dump() for m in request.history]
        scenario_context = None
        taught_commands = None
        status = chaos_injector.get_status()
        
        if status["active"] and status["scenario_key"]:
            key = status["scenario_key"]
            meta = chaos_injector.SCENARIOS[key]
            taught_commands = meta.get("taught_commands", [])
            
            pod_lines = "\n".join(
                f"  - {p['name']}: {p['status']} (restarts={p['restarts']})"
                for p in status["pods"]
            ) or "  (no pods visible yet)"
            scenario_context = (
                f"ACTIVE INCIDENT: {meta['name']}\n"
                f"Description: {meta['description']}\n"
                f"Learning objective: {meta['learning']}\n"
                f"Elapsed: {status['elapsed_seconds']}s\n"
                f"Pod statuses:\n{pod_lines}"
            )
            
        # Pass the terminal history AND taught commands to the engine
        response = agent.generate_response(
            chat_history=history, 
            terminal_history=request.terminal_history,
            scenario_context=scenario_context,
            taught_commands=taught_commands
        )
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/command/execute")
async def execute_command(request: ExecuteRequest):
    # Safety Check: Enforce kubectl and block dangerous shell characters
    cmd = request.command.strip()
    if not cmd.startswith("kubectl "):
        return {"output": "", "error": "Error: Only 'kubectl' commands are permitted in this sandbox.", "returncode": 1}
    
    dangerous_chars = ["|", ";", "&", ">", "<", "$"]
    if any(char in cmd for char in dangerous_chars):
        return {"output": "", "error": "Error: Shell piping and chaining are not permitted.", "returncode": 1}

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        # Log the executed command to the event stream
        chaos_injector.state.add_event(f"$ {request.command}")
        output = result.stdout or result.stderr
        if output:
            chaos_injector.state.add_event(output.strip())
        return {"output": result.stdout, "error": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Command timed out after 30s.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)