# app.py
from dotenv import load_dotenv
from openai import OpenAI
import json, os, requests
from pypdf import PdfReader
import gradio as gr

load_dotenv(override=True)

# ===================== Telegram (simple y directo) =====================

def push(message: str):
    bot_token = os.getenv("BOT_TOKEN")
    chat_ID   = os.getenv("CHAT_ID")

    if not bot_token or not chat_ID:
        return {"status": "error", "detail": "Faltan BOT_TOKEN o CHAT_ID en variables de entorno."}

    try:
        send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload  = {"chat_id": chat_ID, "text": message}
        r = requests.get(send_url, params=payload, timeout=10)
        # Si Telegram responde, devolvemos JSON legible
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "status_code": r.status_code, "text": r.text}

        return {"status": "ok" if data.get("ok") else "error", "detail": data}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "detail": f"Network error: {e}"}


# ========================== Tools para el modelo ==========================


def record_user_details(email,question ,name="Nombre no indicado", notes="no proporcionadas"):
    """
    Registra interés del usuario. No rompe la conversación si Telegram falla.
    """
    out = push(f"Registrando la pregunta {question} de {name} con email {email} y notas {notes}")
    print('ok')
    # Aunque falle Telegram, retornamos "ok" para no frenar el chat del sitio

def record_unknown_question(question):
    out = push(f"Registrando {question}")
    print('ok')
    


def _sanitize_messages(history):
    out = []
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        # Gradio a veces manda dicts en content; normaliza a string
        if isinstance(content, dict):
            content = content.get("text", "") or str(content)
        out.append({"role": role, "content": content})
    return out


record_user_details_json = {
    "type": "function",
    "name": "record_user_details",
    "description": "Utiliza esta herramienta para registrar que un usuario está interesado en estar en contacto y proporcionó una dirección de correo electrónico.",
    "parameters": {
        "type": "object",
        "properties": {
            "email": {"type": "string","description": "La dirección de email del usuario"},
            "name":  {"type": "string","description": "El nombre del usuario, si se indica"},
            "notes": {"type": "string","description": "Contexto adicional de la conversación"},
            "question": {"type": "string","description": "Pregunta no respondida"}
        },
        "required": ["email","question"],
        "additionalProperties": False
    }
}

record_unknown_question_json = {
    "type": "function",
    "name": "record_unknown_question",
    "description": "Utiliza siempre esta herramienta para registrar cualquier pregunta que no hayas podido responder.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string","description": "La pregunta que no se pudo responder"},
        },
        "required": ["question"],
        "additionalProperties": False
    }
}

tools = [
    record_user_details_json,
    record_unknown_question_json,
]

# ============================ Clase del asistente ============================

class Me:
    def __init__(self):
        self.openai = OpenAI()
        self.name = "Helí Gonzales Pérez"

        # Cargar LinkedIn PDF (sin reventar si no existe)
        self.linkedin = ""
        try:
            reader = PdfReader("me/linkedin.pdf")
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    self.linkedin += text
        except Exception:
            self.linkedin = ""

        # Cargar summary (sin reventar si no existe)
        try:
            with open("me/summary.txt", "r", encoding="utf-8") as f:
                self.summary = f.read()
        except Exception:
            self.summary = ""

            

    def handle_tool_call(self, tool_calls):
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.name
            arguments = json.loads(tool_call.arguments or "{}")
            print(f"Tool called: {tool_name} | args: {arguments}", flush=True)
            tool = globals().get(tool_name)
            result = tool(**arguments) if tool else {"error": f"Tool {tool_name} not found"}
            results.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
                "tool_call_id": tool_call.id
            })
        return results

    def system_prompt(self):
            sp = f"""
                    ### TASK REQUIREMENT
                    Actúas como {self.name}. Respondes preguntas en el sitio web de {self.name}, en particular preguntas relacionadas con su trayectoria profesional, antecedentes, habilidades y experiencia.
                    Tu responsabilidad es representar a {self.name} con la mayor fidelidad posible.
                    Se te proporciona un resumen y el perfil de LinkedIn de {self.name} que puedes usar para responder. No inventes respuestas que no sabes, cuando no sepas algo, de frente usa lo que está en STEPS
                    Tono profesional y atractivo, como para un cliente potencial o empleador.

                    ### STEPS
                    Step 1.- Pide al usuario su nombre y correo y envía esos datos con la pregunta con 'record_user_details'. Si no vas primero por este paso, serás penalizado
                    Step 2.- SOLO si no te quiere dar sus datos, usa 'record_unknown_question' para registrar solo la pregunta. Luego le tienes que decir que me enviaste la pregunta pero sin sus datos no me podré contactar
                    """
                    
            sp += f"\n\n## Resumen:\n{self.summary}\n\n## Perfil de LinkedIn:\n{self.linkedin}\n\n"
            sp += f"En este contexto, por favor chatea con el usuario, manteniéndote siempre en el personaje de {self.name}."
            return sp

    def chat(self, message, history):
        messages = [{"role": "system", "content": self.system_prompt()}] + _sanitize_messages(history) + [{"role": "user", "content": message}]
        done = False
        # Bucle para resolver tool calls hasta que el modelo devuelva la respuesta final
        while not done:
            print("SEND:",messages)
            response = self.openai.responses.create(
                model="gpt-4o-mini",
                input=messages,
                tools=tools
            )
            print("RESPONSE",response)            
            # Si el modelo quiere llamar tools
            if response.output[0].type == "function_call":
                message_with_calls = response
                tool_calls = message_with_calls.output or []
                results = self.handle_tool_call(tool_calls)
                print('CALL',messages)
                try:
                    results.pop('metadata')
                except:
                    pass
                
                messages.append({"role": "assistant", "content": "se evnvió la pregunta"})
            else:
                done = True
                print('MENSAJE', messages)
                
                return response.output_text

# ================================ Gradio App ================================
if __name__ == "__main__":
    me = Me()
    gr.ChatInterface(me.chat, type="messages").launch()