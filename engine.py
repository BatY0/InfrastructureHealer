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
            "2. DO NOT give them the exact command right away. Give them hints.\n"
            "3. If they are stuck, explain the CONCEPTS rather than just fixing it.\n"
            "4. You will be provided with their 'RECENT TERMINAL ACTIVITY'. Use this to praise them or correct them.\n"
            "5. Keep responses short and punchy. No massive walls of text.\n"
            "6. Always use <think>...</think> FIRST to analyze privately before talking to the player.\n"
            "7. CRITICAL HARDWARE LIMITATION: The sandbox terminal is non-interactive. The player CANNOT use 'vi', 'nano', or 'kubectl edit'.\n"
        )

    def generate_response(self, chat_history, terminal_history: str = "", scenario_context: str = None, taught_commands: list = None, victory_condition: str = None):
        system_prompt = self.base_system_prompt

        if taught_commands:
            system_prompt += (
                f"\n\n--- LEARNING OBJECTIVE ---\n"
                f"The user MUST learn and use these specific commands to beat this level: {', '.join(taught_commands)}.\n"
                f"If they ask for help, guide them to use EXACTLY these commands. Do not suggest alternative solutions or concepts until they have mastered these."
            )
            
        if victory_condition:
            system_prompt += (
                f"\n\n--- VICTORY CONDITION ---\n"
                f"To win this level, the following must happen: {victory_condition}\n"
                f"CRITICAL RULE: If the user has met this condition, your ONLY job is to congratulate them enthusiastically and explicitly tell them to click the 'Finish Level' button. DO NOT introduce new concepts. DO NOT ask them any more follow-up questions. The level is OVER."
            )

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
        except Exception as e:
            raise RuntimeError(f"Ollama error: {e}")

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