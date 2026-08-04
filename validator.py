import re

def extract_numbers(text):
    raw_numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)
    return {float(n) for n in raw_numbers}

def validate_draft(draft_text, allowed_numbers, required_keywords):
    errors = []
    found_numbers = extract_numbers(draft_text)
    rogue_numbers = []
    
    for num in found_numbers:
        if not any(abs(num - safe_num) < 0.0001 for safe_num in allowed_numbers):
            rogue_numbers.append(num)
            
    if rogue_numbers:
        errors.append(f"HALLUCINATION DETECTED: Unauthorized numbers {rogue_numbers}.")
        
    if errors:
        return False, " | ".join(errors)
        
    return True, "Passed validation."
