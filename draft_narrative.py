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
2. CONFLICT RESOLUTION: If the numbers in the BUSINESS CONTEXT contradict the FACTS, you must assume the BUSINESS CONTEXT is the absolute truth and ignore the conflicting Fact.
3. If a specific metric, total volume, or date is missing, construct your sentences to completely ignore it. You cannot invent data to fill in gaps.
4. Tone: {tone}
5. Format: {rules}
6. Do not write the section title.

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

def revise_draft_section(section_name, eval_summary, business_context, previous_draft, user_feedback):
    """Takes the previous draft and applies the user's natural language feedback."""
    style = STYLE_PROFILE.get(section_name, {})
    tone = style.get("tone", "Formal and objective.")
    rules = " ".join(style.get("formatting_rules", []))
    
    safe_eval = str(eval_summary)[:1000]
    safe_context = str(business_context)[:600]
    
    prompt = f"""<|user|>
You are a strict data-to-text transcriber for Societe Generale revising a draft for the '{section_name}' section.

CRITICAL RULES:
1. You must ONLY use the exact numbers, dates, and metrics provided in the FACTS, BUSINESS CONTEXT, and USER FEEDBACK.
2. CONFLICT RESOLUTION: If the numbers in the BUSINESS CONTEXT or FEEDBACK contradict the FACTS, you must assume the BUSINESS CONTEXT/FEEDBACK is the absolute truth.
3. If a metric is missing, ignore it. Do not invent data.
4. Tone: {tone}
5. Format: {rules}

FACTS:
{safe_eval}

BUSINESS CONTEXT:
{safe_context}

PREVIOUS DRAFT:
{previous_draft}

USER FEEDBACK FOR REVISION:
{user_feedback}

Apply the user's feedback strictly to the previous draft and rewrite the text. Do not write introductory conversational text.
<|end|>
<|assistant|>"""
    
    new_draft = call_ollama(prompt)
    status_msg = "Draft Revised with Feedback."
    if "XX" in new_draft or "202X" in new_draft:
        status_msg = "⚠️ WARNING: AI hallucinated a placeholder (XX). Please review and edit manually."
        
    return new_draft, status_msg

def suggest_style_update(section_name, current_style_dict, user_feedback):
    """Uses LLM to convert natural language feedback into an updated JSON style profile dict."""
    prompt = f"""<|user|>
You are an expert JSON configuration generator. Update this specific section of a style profile based on the user's feedback.

Current JSON for "{section_name}":
{json.dumps(current_style_dict, indent=2)}

USER FEEDBACK / DESIRED CHANGE:
{user_feedback}

CRITICAL RULES:
1. SCHEMA LOCKDOWN: Your output MUST contain exactly three keys: "tone" (string), "formatting_rules" (array of strings), and "relevant_metrics" (array of strings). NEVER invent new keys (like "sections", "text", or "examples").
2. METRICS: "relevant_metrics" MUST contain ONLY short, exact variable names based on the feedback. NEVER write definitions or explanations. Add or remove metrics as requested.
3. FORMATTING: "formatting_rules" MUST be instructions for the AI writer, NOT the actual text of the report. If the user asks for paragraphs, add the rule "Write in paragraphs." Do NOT write the actual paragraphs, placeholders, or templates.
4. PRESERVATION: Keep existing formatting rules and metrics unless the user's feedback explicitly asks to change or remove them.
5. Return ONLY valid JSON. Do not include markdown tags like ```json.

Generate the updated JSON now.
<|end|>
<|assistant|>"""
    response = call_ollama(prompt)
    
    # Cleanup to ensure it's raw JSON
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    elif response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
        
    return response.strip()