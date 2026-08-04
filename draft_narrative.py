import requests
import json

try:
    with open("style_profile.json", "r") as f:
        STYLE_PROFILE = json.load(f)
except FileNotFoundError:
    STYLE_PROFILE = {}

def call_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "phi3",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0, 
            "num_predict": 800, 
            "num_ctx": 1024     
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=90)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"Error contacting Ollama: {str(e)}"

def build_prompt(section_name, eval_summary, business_context):
    style = STYLE_PROFILE.get(section_name, {})
    tone = style.get("tone", "Formal and objective.")
    rules = " ".join(style.get("formatting_rules", []))
    
    safe_eval = str(eval_summary)[:1000]
    safe_context = str(business_context)[:600]

    prompt = f"""<|user|>
You are a strict data-to-text transcriber for Societe Generale. Your ONLY job is to convert the provided FACTS into formal paragraphs for the '{section_name}' section.

CRITICAL RULES:
1. You must ONLY use the exact numbers, dates, and metrics provided in the FACTS and BUSINESS CONTEXT.
2. If a specific metric, total volume, or date is missing, you must construct your sentences to completely ignore it. You cannot invent data to fill in gaps.
3. Tone: {tone}
4. Format: {rules}
5. Do not write the section title.

EXAMPLE OF CORRECT BEHAVIOR:
Facts provided: "5 defaults observed."
Bad Output (Do Not Do This): "Out of an aggregate volume of XX loans, 5 defaulted in the year 202X."
Good Output: "The portfolio observed 5 defaults during the period."

FACTS:
{safe_eval}

BUSINESS CONTEXT:
{safe_context}

Write the narrative now.
<|end|>
<|assistant|>"""
    return prompt

def draft_section(section_name, eval_summary, business_context):
    prompt_1 = build_prompt(section_name, eval_summary, business_context)
    draft_1 = call_ollama(prompt_1)
    
    status_msg = "Draft Generated."
    if "XX" in draft_1 or "202X" in draft_1:
        status_msg = "⚠️ WARNING: AI hallucinated a placeholder (XX). Please review and edit manually."
        
    return draft_1, status_msg