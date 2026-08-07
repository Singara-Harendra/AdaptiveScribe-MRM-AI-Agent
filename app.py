import streamlit as st
import json
import yaml
import os
import subprocess
import jinja2
import shutil
import re
import pandas as pd
from evaluate_kris import run_evaluation, get_suggested_opinion
from draft_narrative import draft_section, revise_draft_section, suggest_style_update

os.makedirs("artifacts", exist_ok=True)
os.makedirs("output", exist_ok=True)

try:
    with open("style_profile.json", "r") as f:
        STYLE_PROFILE = json.load(f)
except FileNotFoundError:
    STYLE_PROFILE = {}

CHAPTERS = {
    "Opinion": [],
    "Context": ["Model history and regulatory context", "Materiality"],
    "Annual Review Scope": [],
    "Glossary": [],
    "Executive Summary": [
        "WP1: General Portfolio Information",
        "WP2: Stability Analysis",
        "WP3: Performance Analysis",
        "WP4: Predictive Power",
        "WP5: Follow-up of recommendations"
    ],
    "Table of Recommendations": [
        "New Recommendations",
        "Follow-up of existing recommendations"
    ],
    "Working Paper 1": [
        "Metadata & Methodology",
        "Results & Opinion",
        "Portfolio Metrics & Appendices"
    ]
}

ALL_SECTIONS = []
for main, subs in CHAPTERS.items():
    if subs:
        for sub in subs: ALL_SECTIONS.append(f"{main} - {sub}")
    else: ALL_SECTIONS.append(main)

OPINION_CHOICES = [
    "No or minor deficiencies: Adequate",
    "Major deficiencies with mitigant: Acceptable",
    "Major deficiencies: need improvement",
    "Severe deficiencies: Rejected"
]

REC_COLUMNS = ["NFA ID", "REC NO.", "THEME", "FINDING", "RECOMMENDATION", "ADDRESSED TO", "CRITICALITY", "DUE DATE", "STATUS", "MRM OBSERVATIONS"]

def format_opinion_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r'(?i)\*?\*?Overall Assessment:\*?\*?', r'\\textbf{Overall Assessment:}\\\\[0.2cm]', text)
    text = re.sub(r'(?i)\*?\*?Conclusion:\*?\*?', r'\\vspace{0.4cm}\\noindent\\textbf{Conclusion:}\\\\[0.2cm]', text)
    return text

def escape_latex(text: str, is_opinion=False) -> str:
    if not text: return ""
    text = str(text)
    text = text.replace('\\', r'\textbackslash{}')
    special_chars = {
        '{': r'\{', '}': r'\}',
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_\allowbreak{}',
        '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'
    }
    for char, replacement in special_chars.items():
        text = text.replace(char, replacement)
    
    if is_opinion:
        text = format_opinion_text(text)
    else:
        text = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', text)
    
    if re.search(r'(?m)^[ \t]*[-*]\s', text):
        lines = text.split('\n')
        out_lines = []
        list_stack = 0
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('- ') or stripped.startswith('* '):
                indent = len(line) - len(stripped)
                level = 1 if indent < 3 else 2
                while list_stack < level:
                    out_lines.append(r'\begin{itemize}')
                    list_stack += 1
                while list_stack > level:
                    out_lines.append(r'\end{itemize}')
                    list_stack -= 1
                out_lines.append(r'\item ' + stripped[2:])
            else:
                if list_stack > 0 and line.strip() == "": continue
                while list_stack > 0:
                    out_lines.append(r'\end{itemize}')
                    list_stack -= 1
                out_lines.append(line)
        while list_stack > 0:
            out_lines.append(r'\end{itemize}')
            list_stack -= 1
        text = '\n'.join(out_lines)
    return text

def format_mrm_opinion(op_text):
    op_text = escape_latex(op_text)
    if ":" in op_text:
        parts = op_text.split(":", 1)
        return f"{parts[0]}: \\newline \\textbf{{{parts[1].strip()}}}"
    return f"\\textbf{{{op_text}}}"

def get_wp_rows(drafts_dict, key):
    data = drafts_dict.get(key, {})
    if not data: return []
    rows = data.get("rows", [])
    out = []
    for r in rows:
        out.append({
            "theme": escape_latex(r["theme"]),
            "opinion": format_mrm_opinion(r["opinion"]),
            "detail": escape_latex(r["detail"])
        })
    return out

def compile_pdf(drafts_dict):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader('.'),
        block_start_string='<BLOCK>', block_end_string='</BLOCK>',
        variable_start_string='<VAR>', variable_end_string='</VAR>',
        comment_start_string='<COMMENT>', comment_end_string='</COMMENT>',
        undefined=jinja2.StrictUndefined
    )
    
    op_data = drafts_dict.get("Opinion", {})
    final_opinion = op_data.get("opinion", "") if isinstance(op_data, dict) else ""
    
    wp1_metrics_raw = drafts_dict.get("Working Paper 1 - Portfolio Metrics & Appendices", {})
    
    def escape_dict_list(d_list):
        return [{k: escape_latex(str(v)) for k, v in row.items()} for row in d_list]
    
    template_vars = {
        "secOpinion": escape_latex(op_data.get("text", "") if isinstance(op_data, dict) else "", is_opinion=True),
        "secContextHistory": escape_latex(drafts_dict.get("Context - Model history and regulatory context", {}).get("text", "")),
        "secContextMateriality": escape_latex(drafts_dict.get("Context - Materiality", {}).get("text", "")),
        "secScope": escape_latex(drafts_dict.get("Annual Review Scope", {}).get("text", "")),
        "secGlossary": escape_latex(drafts_dict.get("Glossary", {}).get("text", "")),
        
        "wp1_rows": get_wp_rows(drafts_dict, "Executive Summary - WP1: General Portfolio Information"),
        "wp2_rows": get_wp_rows(drafts_dict, "Executive Summary - WP2: Stability Analysis"),
        "wp3_rows": get_wp_rows(drafts_dict, "Executive Summary - WP3: Performance Analysis"),
        "wp4_rows": get_wp_rows(drafts_dict, "Executive Summary - WP4: Predictive Power"),
        "wp5_rows": get_wp_rows(drafts_dict, "Executive Summary - WP5: Follow-up of recommendations"),
        
        "wp1_meta": drafts_dict.get("Working Paper 1 - Metadata & Methodology", {}),
        "wp1_res_op": format_mrm_opinion(drafts_dict.get("Working Paper 1 - Results & Opinion", {}).get("opinion", "")),
        "wp1_res_det": escape_latex(drafts_dict.get("Working Paper 1 - Results & Opinion", {}).get("detail", "")),
        
        "wp1_txt_kf": escape_latex(wp1_metrics_raw.get("text_key_fig", "")),
        "wp1_txt_def": escape_latex(wp1_metrics_raw.get("text_default", "")),
        "wp1_txt_app": escape_latex(wp1_metrics_raw.get("text_app", "")),
        "wp1_t8": escape_dict_list(wp1_metrics_raw.get("t8", [])),
        "wp1_t9": escape_dict_list(wp1_metrics_raw.get("t9", [])),
        "wp1_t10": escape_dict_list(wp1_metrics_raw.get("t10", [])),
        "wp1_t11": escape_dict_list(wp1_metrics_raw.get("t11", [])),
        
        "rec_new": escape_dict_list(drafts_dict.get("Table of Recommendations - New Recommendations", {}).get("rows", [])),
        "rec_ext": escape_dict_list(drafts_dict.get("Table of Recommendations - Follow-up of existing recommendations", {}).get("rows", [])),

        "opAdequate": r"$\boxtimes$" if final_opinion == "No or minor deficiencies: Adequate" else r"$\square$",
        "opAcceptable": r"$\boxtimes$" if final_opinion == "Major deficiencies with mitigant: Acceptable" else r"$\square$",
        "opImprovement": r"$\boxtimes$" if final_opinion == "Major deficiencies: need improvement" else r"$\square$",
        "opRejected": r"$\boxtimes$" if final_opinion == "Severe deficiencies: Rejected" else r"$\square$"
    }
    
    try:
        template = env.get_template('sg_irb_template_jinja.tex')
        rendered_tex = template.render(template_vars)
    except Exception as e:
        st.error(f"Template Rendering Error: {e}")
        return

    tex_path = os.path.join("artifacts", "generated_report.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(rendered_tex)
        
    try:
        for _ in range(2):
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory=artifacts", tex_path], check=True, capture_output=True, text=True)
            
        pdf_source = os.path.join("artifacts", "generated_report.pdf")
        pdf_dest = os.path.join("output", "MRM_Report.pdf")
        
        if os.path.exists(pdf_source):
            shutil.copy(pdf_source, pdf_dest)
            st.success(f"PDF Compiled Successfully! Saved to `{pdf_dest}`")
            with open(pdf_dest, "rb") as f:
                st.download_button("⬇️ Download Final PDF", f, file_name="MRM_Report.pdf", mime="application/pdf")
                
    except subprocess.CalledProcessError as e:
        st.error("❌ LaTeX Compilation Failed! Ensure 'sg_logo.png' is in the folder.")
        log_path = os.path.join("artifacts", "generated_report.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                st.text_area("LaTeX Log (Errors at end):", f.read()[-3000:], height=300)

def main():
    st.set_page_config(page_title="SG MRM Copilot", layout="wide")
    
    if "approved_sections" not in st.session_state: st.session_state.approved_sections = {}
    if "raw_kri" not in st.session_state: st.session_state.raw_kri = None
    if "raw_yaml" not in st.session_state: st.session_state.raw_yaml = None

    st.title("MRM Annual Review Copilot")

    with st.sidebar:
        st.header("1. Data Upload")
        kri_file = st.file_uploader("Upload KRI JSON", type=['json'])
        yaml_file = st.file_uploader("Upload Thresholds YAML", type=['yaml', 'yml'])
        
        if st.button("Load Data"):
            if kri_file and yaml_file:
                st.session_state.raw_kri = json.load(kri_file)
                st.session_state.raw_yaml = yaml.safe_load(yaml_file)
                st.success("Data Loaded!")
            else:
                st.warning("Please upload both files.")

        st.divider()
        st.header("2. Chapter Selection")
        selected_main = st.selectbox("Select Main Chapter:", list(CHAPTERS.keys()))
        subsections = CHAPTERS[selected_main]
        selected_sub = st.selectbox("Select Subsection:", subsections) if subsections else None
        draft_key = f"{selected_main} - {selected_sub}" if selected_sub else selected_main
            
        st.divider()
        st.header("Document Status")
        for sec in ALL_SECTIONS:
            icon = "✅" if sec in st.session_state.approved_sections else "❌"
            st.markdown(f"{icon} {sec}")

        st.divider()
        st.header("3. Final Generation")
        if st.button("Compile Final PDF"):
            with st.spinner("Compiling LaTeX to PDF..."):
                compile_pdf(st.session_state.approved_sections)

    st.header(f"Drafting: {draft_key}")
    
    is_wp_exec = "Executive Summary - WP" in draft_key
    is_opinion = draft_key == "Opinion"
    is_recs = "Table of Recommendations" in draft_key
    is_wp1_meta = draft_key == "Working Paper 1 - Metadata & Methodology"
    is_wp1_res = draft_key == "Working Paper 1 - Results & Opinion"
    is_wp1_met = draft_key == "Working Paper 1 - Portfolio Metrics & Appendices"
    
    # Pre-load temp variables if already approved
    is_approved = draft_key in st.session_state.approved_sections
    if is_approved and f"temp_{draft_key}" not in st.session_state:
        saved_data = st.session_state.approved_sections[draft_key]
        if "text" in saved_data:
            st.session_state[f"temp_{draft_key}"] = saved_data["text"]
            st.session_state[f"status_{draft_key}"] = "Loaded from Approved Data"
        if "detail" in saved_data:
            st.session_state[f"temp_{draft_key}"] = saved_data["detail"]
            st.session_state[f"status_{draft_key}"] = "Loaded from Approved Data"
        if "opinion" in saved_data:
            st.session_state[f"suggested_op_{draft_key}"] = saved_data["opinion"]
        if "rows" in saved_data and is_wp_exec:
            st.session_state[f"rows_{draft_key}"] = saved_data["rows"]

    # ---------------------------------------------------------
    # NON-AI SECTIONS (WP1 Metadata, Data Editors)
    # ---------------------------------------------------------
    if is_wp1_meta:
        st.subheader("General Portfolio Information - Metadata")
        saved = st.session_state.approved_sections.get(draft_key, {})
        
        bg_default = "According to the article 78 of the ECB guide to internal models which describes the content of the annual review, the following applies:\n\n(a) The validation process should assess the performance of the rating systems by means of qualitative and quantitative methods..."
        obj_default = "This working paper is devoted to providing an overall view of the ROE portfolio in terms of EAD, RWA, and defaults analyses."
        rev_default = "The procedure followed in this review consisted in analyzing the results provided by the model performance platform."
        con_default = "\\begin{itemize}\\item Abhisek KARMAKAR -- Model validation team\\end{itemize}"
        
        owner = st.text_input("Owner Name", saved.get("owner_raw", "Sejal AGARWAL"))
        owner_dept = st.text_input("Owner Dept", saved.get("owner_dept_raw", "GSCI/CEN/RISQ/MRM"))
        review1 = st.text_input("Reviewer 1 Name", saved.get("review1_raw", "Merick CRUCHON"))
        review1_dept = st.text_input("Reviewer 1 Dept", saved.get("review1_dept_raw", "RISQ/MRM"))
        review2 = st.text_input("Reviewer 2 Name", saved.get("review2_raw", "Pierre SANDANASSAMY"))
        review2_dept = st.text_input("Reviewer 2 Dept", saved.get("review2_dept_raw", "GSCI/CEN/RISQ/MRM"))
        objective = st.text_area("Table Objective", saved.get("objective_raw", "Provide a global description of the portfolio related to the defaults 2025 annual review exercise"))
        
        background = st.text_area("Background and rationale", saved.get("bg", bg_default), height=100)
        objectives_text = st.text_area("Objectives of the analysis", saved.get("obj_anal", obj_default), height=100)
        review_proc = st.text_area("Review procedure", saved.get("rev", rev_default), height=100)
        contacts = st.text_area("Key Contacts", saved.get("contacts_raw", con_default), height=100)
        
        if st.button("Approve & Lock WP1 Metadata"):
            st.session_state.approved_sections[draft_key] = {
                "owner": escape_latex(owner), "owner_raw": owner,
                "owner_dept": escape_latex(owner_dept), "owner_dept_raw": owner_dept,
                "review1": escape_latex(review1), "review1_raw": review1,
                "review1_dept": escape_latex(review1_dept), "review1_dept_raw": review1_dept,
                "review2": escape_latex(review2), "review2_raw": review2,
                "review2_dept": escape_latex(review2_dept), "review2_dept_raw": review2_dept,
                "objective": escape_latex(objective), "objective_raw": objective,
                "background": escape_latex(background), "bg": background,
                "objectives_text": escape_latex(objectives_text), "obj_anal": objectives_text,
                "review_proc": escape_latex(review_proc), "rev": review_proc,
                "contacts": contacts, "contacts_raw": contacts 
            }
            st.success("Metadata locked!")
        return 

    # ---------------------------------------------------------
    # KRI EVALUATION & DISPLAY
    # ---------------------------------------------------------
    relevant_metrics = STYLE_PROFILE.get(draft_key, {}).get("relevant_metrics", [])
    section_eval_summary = ""
    if st.session_state.raw_kri and st.session_state.raw_yaml:
        if relevant_metrics:
            section_eval_summary = run_evaluation(st.session_state.raw_kri, st.session_state.raw_yaml, filter_keys=relevant_metrics)
        else:
            section_eval_summary = "No quantitative KRIs required for this section. Rely entirely on Context."
            
        with st.expander(f"View Evaluated KRI Results for '{draft_key}'", expanded=False):
            st.text(section_eval_summary)

    # ---------------------------------------------------------
    # DATA EDITORS (WITH JSON UPLOAD)
    # ---------------------------------------------------------
    if is_recs:
        st.subheader("Manage Recommendations Data")
        upload_rec = st.file_uploader(f"Upload JSON to auto-fill table", type="json", key=f"up_rec_{draft_key}")
        if upload_rec is not None:
            try:
                st.session_state[f"df_{draft_key}"] = pd.DataFrame(json.load(upload_rec))
                st.success("JSON Loaded!")
            except Exception as e: st.error("Invalid JSON format.")
            
        if f"df_{draft_key}" not in st.session_state:
            saved = st.session_state.approved_sections.get(draft_key, {}).get("rows")
            if saved: st.session_state[f"df_{draft_key}"] = pd.DataFrame(saved)
            else: st.session_state[f"df_{draft_key}"] = pd.DataFrame(columns=REC_COLUMNS, data=[{c:"" for c in REC_COLUMNS}])
            
        st.session_state[f"df_{draft_key}"] = st.data_editor(st.session_state[f"df_{draft_key}"], num_rows="dynamic", use_container_width=True)

    if is_wp1_met:
        st.subheader("Manage WP1 Tables")
        saved_wp1 = st.session_state.approved_sections.get(draft_key, {})
        
        st.write("Table 8: Application Portfolio / Table 9: LRA Summary")
        up_t8 = st.file_uploader("Upload JSON for Table 8/9", type="json", key=f"up_t8_{draft_key}")
        if up_t8 is not None:
            try: st.session_state[f"df_t8_{draft_key}"] = pd.DataFrame(json.load(up_t8))
            except: pass
            
        if f"df_t8_{draft_key}" not in st.session_state:
            if "t8" in saved_wp1: st.session_state[f"df_t8_{draft_key}"] = pd.DataFrame(saved_wp1["t8"])
            else: st.session_state[f"df_t8_{draft_key}"] = pd.DataFrame(columns=["PERIOD", "RWEA", "EAD", "CUSTOMERS", "GRADES"], data=[{"PERIOD":"Dec-2023", "RWEA":"453M", "EAD":"950M", "CUSTOMERS":"17", "GRADES":"19"}])
        st.session_state[f"df_t8_{draft_key}"] = st.data_editor(st.session_state[f"df_t8_{draft_key}"], num_rows="dynamic", use_container_width=True)
        
        st.write("Table 10: Cohort Distribution")
        up_t10 = st.file_uploader("Upload JSON for Table 10", type="json", key=f"up_t10_{draft_key}")
        if up_t10 is not None:
            try: st.session_state[f"df_t10_{draft_key}"] = pd.DataFrame(json.load(up_t10))
            except: pass
            
        if f"df_t10_{draft_key}" not in st.session_state:
            if "t10" in saved_wp1: st.session_state[f"df_t10_{draft_key}"] = pd.DataFrame(saved_wp1["t10"])
            else: st.session_state[f"df_t10_{draft_key}"] = pd.DataFrame(columns=["Cohort", "CORI_IB", "CORI_Def", "GLBA_IB", "GLBA_Def", "GLFI_IB", "GLFI_Def", "Port_IB", "Port_Def"])
        st.session_state[f"df_t10_{draft_key}"] = st.data_editor(st.session_state[f"df_t10_{draft_key}"], num_rows="dynamic", use_container_width=True)
        
        st.write("Table 11: Rationale")
        up_t11 = st.file_uploader("Upload JSON for Table 11", type="json", key=f"up_t11_{draft_key}")
        if up_t11 is not None:
            try: st.session_state[f"df_t11_{draft_key}"] = pd.DataFrame(json.load(up_t11))
            except: pass
            
        if f"df_t11_{draft_key}" not in st.session_state:
            if "t11" in saved_wp1: st.session_state[f"df_t11_{draft_key}"] = pd.DataFrame(saved_wp1["t11"])
            else: st.session_state[f"df_t11_{draft_key}"] = pd.DataFrame(columns=["Reason", "Obligors", "Percent"])
        st.session_state[f"df_t11_{draft_key}"] = st.data_editor(st.session_state[f"df_t11_{draft_key}"], num_rows="dynamic", use_container_width=True)

    business_context = st.text_area("Business Context for AI Drafting:", height=100)
    
    # ---------------------------------------------------------
    # AI GENERATION
    # ---------------------------------------------------------
    if st.button(f"Generate Draft for {draft_key}"):
        if not st.session_state.raw_kri:
            st.warning("Please upload and load data first.")
        else:
            with st.spinner(f"AI is drafting content..."):
                if is_opinion:
                    business_context = f"The finalized MRM decision rating is: '{st.session_state.get('final_opinion', OPINION_CHOICES[0])}'. Structure the conclusion to align perfectly with this rating.\n\n{business_context}"
                
                draft, status_msg = draft_section(draft_key, section_eval_summary, business_context)
                suggested_opinion = get_suggested_opinion(st.session_state.raw_kri, st.session_state.raw_yaml, relevant_metrics)
                
                st.session_state[f"temp_{draft_key}"] = draft
                st.session_state[f"status_{draft_key}"] = status_msg
                st.session_state[f"suggested_op_{draft_key}"] = suggested_opinion

                if is_wp_exec:
                    default_theme = draft_key.split(": ")[1] if ": " in draft_key else draft_key
                    if "WP5" in draft_key:
                        recs = re.split(r'(?m)^[-*]\s+', draft)
                        clean_recs = [r.strip() for r in recs if r.strip()]
                        if clean_recs and len(clean_recs[0].split()) < 15 and ":" in clean_recs[0] and len(clean_recs) > 1:
                            clean_recs.pop(0)
                        if not clean_recs: clean_recs = [draft]
                        st.session_state[f"rows_{draft_key}"] = [{"theme": f"Recommendation {idx+1}", "opinion": suggested_opinion, "detail": r} for idx, r in enumerate(clean_recs)]
                    else:
                        st.session_state[f"rows_{draft_key}"] = [{"theme": default_theme, "opinion": suggested_opinion, "detail": draft}]

    # ---------------------------------------------------------
    # POST-GENERATION EDIT & LOCK
    # ---------------------------------------------------------
    temp_key = f"temp_{draft_key}"
    if temp_key in st.session_state or is_recs or is_wp1_met:
        
        if is_wp_exec and temp_key in st.session_state:
            st.markdown(f"**Status:** {st.session_state.get(f'status_{draft_key}', 'Ready')}")
            st.subheader("Edit Table Rows")
            rows = st.session_state.get(f"rows_{draft_key}", [{"theme": "", "opinion": OPINION_CHOICES[0], "detail": ""}])
            rows_to_delete = []
            for i, row in enumerate(rows):
                st.markdown(f"**Row {i+1}**")
                col_title, col_del = st.columns([11, 1])
                with col_del:
                    if st.button("🗑️", key=f"del_{draft_key}_{i}"): rows_to_delete.append(i)
                row["theme"] = st.text_input(f"Theme (Row {i+1})", value=row.get("theme",""), key=f"t_{draft_key}_{i}")
                row["opinion"] = st.selectbox(f"MRM Opinion (Row {i+1})", OPINION_CHOICES, index=OPINION_CHOICES.index(row.get("opinion", OPINION_CHOICES[0])) if row.get("opinion") in OPINION_CHOICES else 0, key=f"o_{draft_key}_{i}")
                row["detail"] = st.text_area(f"Detail (Row {i+1})", value=row.get("detail",""), height=150, key=f"d_{draft_key}_{i}")
                st.divider()
                
            if rows_to_delete:
                for idx in reversed(rows_to_delete): st.session_state[f"rows_{draft_key}"].pop(idx)
                st.rerun()

            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("➕ Add Row"):
                    st.session_state[f"rows_{draft_key}"].append({"theme": "", "opinion": OPINION_CHOICES[0], "detail": ""})
                    st.rerun()
            with col2:
                if st.button(f"Approve & Lock '{draft_key}' Table"):
                    st.session_state.approved_sections[draft_key] = {"rows": st.session_state[f"rows_{draft_key}"]}
                    st.success(f"'{draft_key}' locked!")

        elif is_recs:
            if temp_key in st.session_state:
                st.info("AI Drafted Text (Copy/Paste this into the table above):")
                st.text_area("AI Output", st.session_state[temp_key], height=150)
            if st.button(f"Approve & Lock '{draft_key}' Data"):
                st.session_state.approved_sections[draft_key] = {"rows": st.session_state[f"df_{draft_key}"].to_dict('records')}
                st.success(f"'{draft_key}' locked!")

        elif is_wp1_res:
            if temp_key in st.session_state:
                sug_op = st.session_state.get(f"suggested_op_{draft_key}", OPINION_CHOICES[0])
                op_val = st.selectbox("Confirm Final MRM Opinion Rating:", OPINION_CHOICES, index=OPINION_CHOICES.index(sug_op) if sug_op in OPINION_CHOICES else 0)
                draft_val = st.text_area("Review and Edit Detail Draft:", st.session_state[temp_key], height=200)
                if st.button("Approve & Lock WP1 Results"):
                    st.session_state.approved_sections[draft_key] = {"opinion": op_val, "detail": draft_val, "text": draft_val} 
                    st.success("WP1 Results locked!")

        elif is_wp1_met:
            saved_wp1 = st.session_state.approved_sections.get(draft_key, {})
            if temp_key in st.session_state:
                st.info("AI Drafted Narrative (Copy/Paste into the correct boxes below):")
                st.text_area("AI Output", st.session_state[temp_key], height=150)
            
            st.subheader("Edit Narrative Blocks")
            txt_kf = st.text_area("Portfolio key figures Narrative", saved_wp1.get("text_key_fig", ""), height=100)
            txt_def = st.text_area("Default analysis Narrative", saved_wp1.get("text_default", ""), height=100)
            txt_app = st.text_area("Appendices Rationale Narrative", saved_wp1.get("text_app", ""), height=100)
            
            if st.button("Approve & Lock WP1 Metrics & Data"):
                st.session_state.approved_sections[draft_key] = {
                    "text_key_fig": txt_kf,
                    "text_default": txt_def,
                    "text_app": txt_app,
                    "t8": st.session_state[f"df_t8_{draft_key}"].to_dict('records'),
                    "t9": st.session_state[f"df_t8_{draft_key}"].to_dict('records'), 
                    "t10": st.session_state[f"df_t10_{draft_key}"].to_dict('records'),
                    "t11": st.session_state[f"df_t11_{draft_key}"].to_dict('records')
                }
                st.success("WP1 Metrics Data locked!")

        elif temp_key in st.session_state:
            if is_opinion:
                sug_op = st.session_state.get(f"suggested_op_{draft_key}", OPINION_CHOICES[0])
                op_val = st.selectbox("Confirm Final MRM Opinion Rating:", OPINION_CHOICES, index=OPINION_CHOICES.index(sug_op) if sug_op in OPINION_CHOICES else 0)
                st.session_state.final_opinion = op_val
                
            draft_val = st.text_area("Review and Edit Draft:", st.session_state[temp_key], height=250)
            if st.button(f"Approve & Lock '{draft_key}'"):
                if is_opinion:
                    st.session_state.approved_sections[draft_key] = {"opinion": op_val, "text": draft_val}
                else:
                    st.session_state.approved_sections[draft_key] = {"text": draft_val}
                st.success(f"'{draft_key}' locked!")

        # ---------------------------------------------------------
        # AI FEEDBACK & PERMANENT STYLE UPDATER
        # ---------------------------------------------------------
        if temp_key in st.session_state and not is_wp1_meta:
            st.divider()
            st.subheader("AI Feedback & Style Updating")
            st.info("Not satisfied with the draft? Provide feedback to rewrite the text, or save the feedback as a permanent rule for future reports.")
            user_feedback = st.text_area("Feedback (e.g., 'Use bullet points', 'Include the missing metric 5.2%')", key=f"fb_{draft_key}")
            
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                if st.button("🔄 Regenerate Draft with Feedback"):
                    if not user_feedback:
                        st.warning("Provide feedback to regenerate.")
                    else:
                        with st.spinner("Revising draft..."):
                            if is_opinion:
                                business_context = f"The finalized MRM decision rating is: '{st.session_state.get('final_opinion', OPINION_CHOICES[0])}'.\n\n{business_context}"
                            
                            old_draft = st.session_state.get(temp_key, "")
                            new_draft, new_status = revise_draft_section(draft_key, section_eval_summary, business_context, old_draft, user_feedback)
                            
                            st.session_state[temp_key] = new_draft
                            st.session_state[f"status_{draft_key}"] = new_status
                            
                            if is_wp_exec:
                                sug_op = st.session_state.get(f"suggested_op_{draft_key}", OPINION_CHOICES[0])
                                default_theme = draft_key.split(": ")[1] if ": " in draft_key else draft_key
                                if "WP5" in draft_key:
                                    recs = re.split(r'(?m)^[-*]\s+', new_draft)
                                    clean_recs = [r.strip() for r in recs if r.strip()]
                                    if clean_recs and len(clean_recs[0].split()) < 15 and ":" in clean_recs[0] and len(clean_recs) > 1:
                                        clean_recs.pop(0)
                                    if not clean_recs: clean_recs = [new_draft]
                                    st.session_state[f"rows_{draft_key}"] = [{"theme": f"Recommendation {idx+1}", "opinion": sug_op, "detail": r} for idx, r in enumerate(clean_recs)]
                                else:
                                    st.session_state[f"rows_{draft_key}"] = [{"theme": default_theme, "opinion": sug_op, "detail": new_draft}]
                            st.rerun()

            with col_f2:
                if st.button("⚙️ Suggest Permanent Style Update"):
                    if not user_feedback:
                        st.warning("Provide feedback to generate a rule.")
                    else:
                        with st.spinner("Analyzing rules..."):
                            current_style = STYLE_PROFILE.get(draft_key, {"tone": "", "formatting_rules": [], "relevant_metrics": []})
                            proposed_json_str = suggest_style_update(draft_key, current_style, user_feedback)
                            st.session_state[f"proposed_style_{draft_key}"] = proposed_json_str
                            st.session_state[f"show_style_editor_{draft_key}"] = True

            if st.session_state.get(f"show_style_editor_{draft_key}"):
                st.markdown("#### Review Style Profile Update")
                col_b, col_a = st.columns(2)
                with col_b:
                    st.write("**Before (Current Rule):**")
                    st.json(STYLE_PROFILE.get(draft_key, {}))
                with col_a:
                    st.write("**After (Proposed Update):**")
                    edited_json_str = st.text_area("Edit proposed JSON before saving:", value=st.session_state[f"proposed_style_{draft_key}"], height=250)
                    
                if st.button("💾 Approve & Lock Style Profile"):
                    try:
                        updated_dict = json.loads(edited_json_str)
                        STYLE_PROFILE[draft_key] = updated_dict
                        with open("style_profile.json", "w") as f:
                            json.dump(STYLE_PROFILE, f, indent=2)
                        st.success("Style Profile updated successfully! Future generations will follow these rules.")
                        st.session_state[f"show_style_editor_{draft_key}"] = False
                    except json.JSONDecodeError as e:
                        st.error(f"Invalid JSON format. Please fix errors before saving: {e}")

if __name__ == "__main__":
    main()