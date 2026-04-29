import re
import json
import os
import threading
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "model_settings.json")

DEFAULT_SETTINGS = {
    "selected_model": "gemma4:e2b",
    "model_options": [
        {
            "id": "gemma4:e2b",
            "label": "Fast (Gemma 4 E2B)",
            "approx_hardware": "Approx: 8-12 GB RAM for smooth local use; CPU-only works but slower.",
            "notes": "Best for low-resource laptops and live demos."
        },
        {
            "id": "gemma4:e4b",
            "label": "Balanced (Gemma 4 E4B)",
            "approx_hardware": "Approx: 16+ GB RAM, or 8+ GB VRAM for responsive chat.",
            "notes": "Stronger multi-step coaching while keeping acceptable latency."
        },
        {
            "id": "gemma4:4b",
            "label": "Quality (Gemma 4 4B-class)",
            "approx_hardware": "Approx: 24+ GB RAM, or 12+ GB VRAM recommended.",
            "notes": "Better reasoning consistency; use if your machine can handle it."
        }
    ]
}


class GemmaDevOpsEngine:
    def __init__(self):
        self._settings_lock = threading.Lock()
        self.settings = self._load_settings()
        self.current_model = self.settings.get("selected_model", "gemma4:e2b")
        self.base_system_prompt = (
            "You are the 'Game Guide' and Senior Mentor in a Kubernetes Training Simulator. "
            "The player is learning how to fix broken infrastructure. "
            "They have a terminal on their screen where they run commands, and a chat window to talk to you. "
            "RULES:\n"
            "1. Be encouraging, fun, and educational. Treat this like a puzzle game.\n"
            "2. Use a METHODOLOGY-FIRST coaching style. Always start with an incident workflow: Observe -> Hypothesize -> Test -> Verify. Teach the process, not just the command.\n"
            "3. Use a STRICT PROGRESSIVE HINT ladder before revealing any exact command:\n"
            "   - Level 1 hint: Goal framing only (what signal they should inspect).\n"
            "   - Level 2 hint: Tactical direction (which kubectl area to explore, still no exact command).\n"
            "   - Level 3 hint: Partial command scaffold with placeholders only.\n"
            "   - Level 4 hint: Exact command ONLY as a last resort after multiple failed attempts.\n"
            "4. If the player says 'I don't know' once, do NOT immediately reveal exact commands. Give Level 2 or Level 3 guidance first. Reveal exact commands only if they remain stuck after repeated attempts.\n"
            "5. You will be provided with their 'RECENT TERMINAL ACTIVITY'. Use this to praise them or correct them.\n"
            "6. Keep responses short and punchy. No massive walls of text.\n"
            "7. Always use <think>...</think> FIRST to analyze privately before talking to the player.\n"
            "8. CRITICAL HARDWARE LIMITATION: The sandbox terminal is non-interactive. The player CANNOT use 'vi', 'nano', 'kubectl edit', or any command with -it flag. For kubectl exec, always use: kubectl exec <pod> -- <command> (NO -it flag).\n"
        )

    def _load_settings(self):
        if not os.path.exists(SETTINGS_FILE):
            self._save_settings(DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid settings format")
            if "selected_model" not in data or not data["selected_model"]:
                data["selected_model"] = DEFAULT_SETTINGS["selected_model"]
            if "model_options" not in data or not isinstance(data["model_options"], list) or not data["model_options"]:
                data["model_options"] = DEFAULT_SETTINGS["model_options"]
            return data
        except Exception:
            self._save_settings(DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)

    def _save_settings(self, data):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_settings(self):
        with self._settings_lock:
            return {
                "selected_model": self.current_model,
                "model_options": self.settings.get("model_options", [])
            }

    def set_model(self, model_id: str):
        model_id = (model_id or "").strip()
        if not model_id:
            raise ValueError("Model id cannot be empty.")
        with self._settings_lock:
            self.current_model = model_id
            self.settings["selected_model"] = model_id
            self._save_settings(self.settings)

    def _is_model_installed(self, model_id: str, installed_models: list) -> bool:
        if not model_id:
            return False
        normalized = {m.strip() for m in installed_models if isinstance(m, str)}
        if model_id in normalized:
            return True
        if ":" not in model_id and f"{model_id}:latest" in normalized:
            return True
        if model_id.endswith(":latest") and model_id.split(":")[0] in normalized:
            return True
        return False

    def get_ollama_status(self):
        status = {
            "running": False,
            "api_compatible": False,
            "installed_models": [],
            "selected_model": self.current_model,
            "selected_model_installed": False,
            "error": None,
        }
        try:
            resp = requests.get(OLLAMA_TAGS_URL, timeout=5)
            status["running"] = True
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", []) if isinstance(data, dict) else []
                installed = []
                for model in models:
                    if isinstance(model, dict):
                        model_name = model.get("name") or model.get("model")
                        if model_name:
                            installed.append(model_name)
                status["installed_models"] = installed
                status["api_compatible"] = True
                status["selected_model_installed"] = self._is_model_installed(self.current_model, installed)
                return status
            if resp.status_code == 404:
                status["error"] = "A service is running on port 11434, but /api/tags was not found. Make sure this is Ollama."
                return status
            status["error"] = f"Ollama check failed with HTTP {resp.status_code}."
            return status
        except Exception as e:
            status["error"] = f"Ollama is unreachable on localhost:11434 ({e})."
            return status

    def generate_response(self, chat_history, terminal_history: str = "", scenario_context: str = None, taught_commands: list = None, victory_condition: str = None, is_victory_review: bool = False):
        system_prompt = self.base_system_prompt

        if taught_commands:
            system_prompt += (
                f"\n\n--- LEARNING OBJECTIVE ---\n"
                f"The user MUST learn and use these specific commands to beat this level: {', '.join(taught_commands)}.\n"
                f"Guide them toward these commands through the progressive methodology-first hint ladder. "
                f"Do NOT reveal the full exact command early. Prioritize reasoning prompts, debugging heuristics, and partial scaffolds before explicit syntax."
            )
            
        if is_victory_review:
            system_prompt += (
                f"\n\n--- VICTORY ACHIEVED ---\n"
                f"The user has just solved the scenario! Review their terminal history above. "
            )
            if victory_condition:
                system_prompt += f"Context: The true goal of this level was: {victory_condition} "
            
            system_prompt += (
                f"Explain concisely what the core error in the infrastructure was, and how the commands they ran helped identify or fix it."
            )
        elif victory_condition:
            system_prompt += (
                f"\n\n--- LEVEL BOUNDARY ---\n"
                f"The ultimate goal of this level is: {victory_condition}\n"
                f"ABSOLUTE RULES:\n"
                f"1. You are a MENTOR ONLY. The backend system, not you, controls when the level ends.\n"
                f"2. NEVER say things like 'You did it!', 'Let's wrap this up', 'Awesome job finishing!', 'Level complete', or any phrase that implies the level is over.\n"
                f"3. If the student has successfully met the goal (including answering any questions required by the goal) AND they have successfully run the required commands in the terminal, you MUST include the exact tag <VERIFIED> anywhere in your response. DO NOT output this tag if they haven't run the commands yet. This tag tells the backend to run the official verification check.\n"
                f"4. Continue mentoring naturally if they have questions."
            )

        if scenario_context:
            system_prompt += f"\n\n--- CURRENT LEVEL STATE ---\n{scenario_context}"
            
        if terminal_history:
            system_prompt += f"\n\n--- PLAYER'S RECENT TERMINAL ACTIVITY ---\n{terminal_history}"
        else:
            system_prompt += "\n\n--- PLAYER'S RECENT TERMINAL ACTIVITY ---\n(None yet)"

        messages = [{"role": "system", "content": system_prompt}] + chat_history

        payload = {
            "model": self.current_model,
            "messages": messages,
            "stream": False,
        }

        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        except Exception as e:
            raise RuntimeError(
                "Cannot reach Ollama at localhost:11434. Start Ollama first, then retry. "
                f"Underlying error: {e}"
            )

        if resp.status_code >= 400:
            response_error = ""
            try:
                body = resp.json()
                if isinstance(body, dict):
                    response_error = body.get("error", "")
            except Exception:
                response_error = (resp.text or "").strip()

            status = self.get_ollama_status()
            if resp.status_code == 404:
                if not status["api_compatible"]:
                    raise RuntimeError(
                        "Connected to localhost:11434, but this does not look like a compatible Ollama API "
                        "for /api/chat. Ensure Ollama is running and up to date."
                    )
                raise RuntimeError("Ollama endpoint /api/chat returned 404. Please verify your Ollama installation.")

            if (("not found" in response_error.lower()) and ("model" in response_error.lower())) or (not status["selected_model_installed"]):
                raise RuntimeError(
                    f"Selected model '{self.current_model}' is not installed in Ollama. "
                    f"Run: ollama pull {self.current_model}"
                )

            raise RuntimeError(f"Ollama request failed (HTTP {resp.status_code}): {response_error or 'Unknown error'}")

        data = resp.json()
        response_text = data["message"]["content"]
        return self.parse_response(response_text)

    def parse_response(self, text: str) -> dict:
        THINK_PATTERNS = [
            r'<think>(.*?)</think>', r'<\|think\|>(.*?)</\|think\|>', r'<thinking>(.*?)</thinking>',
            r'<\|thinking\|>(.*?)</\|thinking\|>', r'<think>(.*?)$', r'<\|think\|>(.*?)$',
        ]

        thought = ""
        answer = text.strip()

        for pattern in THINK_PATTERNS:
            m = re.search(pattern, answer, re.DOTALL | re.IGNORECASE)
            if m:
                thought = m.group(1).strip()
                break

        for pattern in THINK_PATTERNS:
            answer = re.sub(pattern, '', answer, flags=re.DOTALL | re.IGNORECASE)

        verified = False
        if re.search(r'<VERIFIED>', answer, re.IGNORECASE):
            verified = True
            answer = re.sub(r'<VERIFIED>', '', answer, flags=re.IGNORECASE)

        return {"type": "message", "thought": thought, "answer": answer.strip(), "verified_by_llm": verified}