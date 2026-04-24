import re
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "gemma4:e2b"


class GemmaDevOpsEngine:
    def __init__(self):
        self.base_system_prompt = (
            "You are a junior developer pairing with a senior engineer (the user) "
            "to debug a broken Kubernetes cluster. You are eager to learn and rely on the senior for direction. "
            "Use a casual, human voice (e.g. 'Hey, it looks like...', 'Got it, should we try...'). "
            "Do NOT act like a robotic AI assistant. "
            "RULES:\n"
            "1. Always use <think>...</think> FIRST to analyze the logs privately before talking to the user.\n"
            "2. DO NOT automatically propose a command unless the user asks you to or suggests an action. Let the user drive the investigation.\n"
            "3. If the user tells you to do something (e.g., 'check the pods', 'look at the logs'), propose the exact command by wrapping it like this: <command>kubectl get pods</command>\n"
            "4. Only propose ONE command at a time — you need the senior's approval before running it.\n"
            "5. Keep your responses short and conversational. Don't write essays.\n"
            "6. After a command is executed, look at the output, summarize what you see, and ask the user what they want to do next."
        )

    def generate_response(self, chat_history, scenario_context: str = None):
        """
        chat_history: list of dicts with {'role': 'user'|'assistant', 'content': '...'}
        scenario_context: optional string injected from the active chaos scenario
        """
        system_prompt = self.base_system_prompt
        if scenario_context:
            system_prompt += f"\n\nCURRENT CLUSTER STATE:\n{scenario_context}"

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
        """
        Strips all known thinking/reasoning tag variants from the visible answer.
        Gemma models may use any of: <think>, <|think|>, <thinking>, etc.
        The thought is extracted separately and only shown in the UI's collapsible panel.
        """
        THINK_PATTERNS = [
            r'<think>(.*?)</think>',
            r'<\|think\|>(.*?)</\|think\|>',
            r'<thinking>(.*?)</thinking>',
            r'<\|thinking\|>(.*?)</\|thinking\|>',
            # unclosed variants (model stops mid-thought)
            r'<think>(.*?)$',
            r'<\|think\|>(.*?)$',
        ]

        thought = ""
        answer = text.strip()

        for pattern in THINK_PATTERNS:
            m = re.search(pattern, answer, re.DOTALL | re.IGNORECASE)
            if m:
                thought = m.group(1).strip()
                # Remove ALL occurrences of any think block from the answer
                break

        # Strip every think block variant from the visible text
        for pattern in THINK_PATTERNS:
            answer = re.sub(pattern, '', answer, flags=re.DOTALL | re.IGNORECASE)

        answer = answer.strip()

        # Extract <command>...</command>
        command_match = re.search(r'<command>(.*?)</command>', answer, re.DOTALL)
        if command_match:
            command = command_match.group(1).strip()
            answer = re.sub(r'<command>.*?</command>', '', answer, flags=re.DOTALL).strip()
            return {
                "type": "action_required",
                "command": command,
                "thought": thought,
                "answer": answer,
            }

        return {"type": "message", "thought": thought, "answer": answer}