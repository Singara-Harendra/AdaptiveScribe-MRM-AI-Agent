import json
import yaml

def run_evaluation(kri_dict, yaml_dict, filter_keys=None):
    thresholds = yaml_dict.get("thresholds", {})
    results = kri_dict.get("results", {})
    evaluation_summary = []
    
    for metric, result_data in results.items():
        if filter_keys is not None and metric not in filter_keys:
            continue
        if metric not in thresholds:
            continue
            
        val = result_data.get("value")
        rule = thresholds[metric]
        green = rule.get("green_limit")
        amber = rule.get("amber_limit")
        red = rule.get("red_limit")
        
        if val is None:
            evaluation_summary.append(f"- {metric}: Data Missing.")
            continue
            
        condition = rule.get("condition")
        status = "UNKNOWN"
        
        if condition == "greater_than":
            if val >= green: status = "GREEN"
            elif val >= amber: status = "AMBER"
            else: status = "RED"
        elif condition == "less_than":
            if val <= green: status = "GREEN"
            elif val <= amber: status = "AMBER"
            else: status = "RED"
            
        evaluation_summary.append(f"- {metric}: Value={val} | Threshold={green} | Status={status}")
        
    return "\n".join(evaluation_summary)

def get_suggested_opinion(kri_dict, yaml_dict, filter_keys):
    thresholds = yaml_dict.get("thresholds", {})
    results = kri_dict.get("results", {})
    worst_status = "GREEN"
    
    if not filter_keys:
        return "No or minor deficiencies: Adequate"
        
    for metric, result_data in results.items():
        if metric not in filter_keys or metric not in thresholds:
            continue
            
        val = result_data.get("value")
        rule = thresholds[metric]
        green = rule.get("green_limit")
        amber = rule.get("amber_limit")
        
        if val is None:
            continue
            
        condition = rule.get("condition")
        status = "GREEN"
        
        if condition == "greater_than":
            if val < green and val >= amber: status = "AMBER"
            elif val < amber: status = "RED"
        elif condition == "less_than":
            if val > green and val <= amber: status = "AMBER"
            elif val > amber: status = "RED"
            
        if status == "RED":
            worst_status = "RED"
        elif status == "AMBER" and worst_status != "RED":
            worst_status = "AMBER"
            
    if worst_status == "RED":
        return "Major deficiencies: need improvement"
    elif worst_status == "AMBER":
        return "Major deficiencies with mitigant: Acceptable"
    else:
        return "No or minor deficiencies: Adequate"