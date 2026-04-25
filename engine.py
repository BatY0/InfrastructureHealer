import re
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "gemma4:e2b"


class GemmaDevOpsEngine:
    def __init__(self):
        self.base_system_prompt = (
            "You are the 'Game Guide' and Senior Mentor in a Kubernetes Training Simulator. "
            "The player is learning how to fix broken infrastructure. "
            "They have a terminal on their screen where they run commands, and a chat window to talk to you. "
            "RULES:\n"
            "1. Be encouraging, fun, and educational. Treat this like a puzzle game.\n"
            "2. DO NOT give them the exact command right away. Give them hints (e.g., 'What command lists our pods?').\n"
            "3. If they are stuck, explain the CONCEPTS (like what an OOM is) rather than just fixing it.\n"
            "4. You will be provided with their 'RECENT TERMINAL ACTIVITY'. Use this to praise them or correct them.\n"
            "5. Keep responses short and punchy. No massive walls of text.\n"
            "6. Always use <think>...</think> FIRST to analyze privately before talking to the player.\n"
            "7. CRITICAL HARDWARE LIMITATION: The sandbox terminal is non-interactive. The player CANNOT use 'vi', 'nano', or 'kubectl edit'. "
            "If they need to change resources, guide them to use CLI arguments like: `kubectl set resources deployment <name> --limits=memory=500Mi`\n"
            "8. VICTORY CHECK: Look closely at the 'CURRENT LEVEL STATE' provided below. If the player's pods are all showing as 'Running' with 1/1 READY, "
            "THE PLAYER HAS WON. Congratulate them enthusiastically, tell them why their fix worked, and instruct them to click the 'Finish Level' button. DO NOT ask them any more questions.\n"
            "9. If the player says they solved it, but the 'CURRENT LEVEL STATE' shows the pods are still Crashing or Pending, gently tell them the cluster is still showing errors and they need to keep investigating."
        )

    def generate_response(self, chat_history, terminal_history: str = "", scenario_context: str = None):
        system_prompt = self.base_system_prompt

        if scenario_context:
            system_prompt += f"\n\n--- CURRENT LEVEL STATE ---\n{scenario_context}"
            
        if terminal_history:
            system_prompt += f"\n\n--- PLAYER'S RECENT TERMINAL ACTIVITY ---\n{terminal_history}"
        else:
            system_prompt += "\n\n--- PLAYER'S RECENT TERMINAL ACTIVITY ---\n(None yet)"

        messages = [{"role": "system", "content": system_prompt}] + chat_history

        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
        }

        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Could not connect to Ollama at {OLLAMA_URL}. "
                "Make sure Ollama is running (`ollama serve`)."
            )
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(
                f"Ollama returned an error: {e.response.status_code} – {e.response.text}"
            )

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

        return {"type": "message", "thought": thought, "answer": answer.strip()}