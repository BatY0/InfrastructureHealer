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

        verified = False
        if re.search(r'<VERIFIED>', answer, re.IGNORECASE):
            verified = True
            answer = re.sub(r'<VERIFIED>', '', answer, flags=re.IGNORECASE)

        return {"type": "message", "thought": thought, "answer": answer.strip(), "verified_by_llm": verified}