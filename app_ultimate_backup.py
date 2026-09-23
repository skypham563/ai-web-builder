import os
import openai
import streamlit as st
import streamlit.components.v1 as components
import base64
import sqlite3
import datetime
import io
import zipfile
import re
import json
from duckduckgo_search import DDGS
import requests

# --- Pro IDE Plugin Attempt ---
try:
    from streamlit_ace import st_ace
    HAS_ACE = True
except ImportError:
    HAS_ACE = False

# --- Web Scraper Plugin Attempt ---
try:
    from bs4 import BeautifulSoup
    HAS_SCRAPER = True
except ImportError:
    HAS_SCRAPER = False

# --- Configuration ---
LOCAL_API_BASE = "http://localhost:11434/v1"
LOCAL_API_KEY = "local-server"
NETLIFY_ACCESS_TOKEN = "YOUR_NETLIFY_PERSONAL_ACCESS_TOKEN" # Add your Netlify PAT here
GITHUB_ACCESS_TOKEN = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"   # Add your GitHub PAT here

# --- Theme Engine Definitions ---
THEME_PRESETS = {
    "Default (None)": "",
    "Apple Minimalist": "Use extreme minimalism. White and very light gray backgrounds (bg-gray-50), subtle borders, soft rounded corners (rounded-2xl or 3xl), and very soft shadows (shadow-sm). Typography should be clean sans-serif (tracking-tight). Use frosted glass effects (backdrop-blur) for navbars.",
    "Cyberpunk 2077": "Use a dark mode aesthetic (bg-gray-900 or black). Accents must be bright neon pink, cyan, and yellow. Use sharp, square corners (rounded-none). Add thick borders to buttons with glowing hover effects. Typography should be monospace.",
    "Neo-Brutalist": "High contrast and brutalist. Backgrounds in harsh white or bright bold colors (yellow, pink). ALL UI elements (cards, buttons) MUST have thick black borders (border-4 border-black) and hard black shadows (shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]). Typography must be huge, bold, and black.",
    "Web3 Glassmorphism": "Use dark gradient backgrounds. UI cards must be semi-transparent (bg-white/10) with strong background blur (backdrop-blur-md), subtle white borders (border border-white/20), and white text. Everything should feel floating and futuristic."
}

# --- Database Setup (JSON Storage) ---
def init_db():
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_project(name, pages_dict, project_id=None):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    code_json = json.dumps(pages_dict)
    if project_id:
        c.execute('UPDATE projects SET name=?, code=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (name, code_json, project_id))
    else:
        c.execute('INSERT INTO projects (name, code) VALUES (?, ?)', (name, code_json))
        project_id = c.lastrowid
    conn.commit()
    conn.close()
    return project_id

def load_project(project_id):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('SELECT name, code FROM projects WHERE id=?', (project_id,))
    row = c.fetchone()
    conn.close()
    if row:
        try:
            pages = json.loads(row[1])
        except json.JSONDecodeError:
            pages = {"index.html": row[1]}
        return row[0], pages
    return None, None

def get_all_projects():
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('SELECT id, name, updated_at FROM projects ORDER BY updated_at DESC')
    rows = c.fetchall()
    conn.close()
    return rows

init_db()

# --- Utility Functions ---
def parse_multi_file_response(response_text: str) -> dict:
    """Parses the AI's delimited output into a dictionary of files."""
    files = {}
    parts = re.split(r'===FILE:\s*(.+?)===', response_text)
    
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            filename = parts[i].strip()
            content = parts[i+1].strip()
            if content.startswith("```html"): content = content[7:]
            if content.endswith("```"): content = content[:-3]
            files[filename] = content.strip()
    else:
        content = response_text.strip()
        if content.startswith("```html"): content = content[7:]
        if content.endswith("```"): content = content[:-3]
        files["index.html"] = content.strip()
        
    return files

def generate_zip_file(pages_dict: dict) -> bytes:
    """Bundles multiple pages into an in-memory ZIP file."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for filename, html_code in pages_dict.items():
            zip_file.writestr(filename, html_code)
    return zip_buffer.getvalue()

def deploy_to_netlify(zip_bytes: bytes) -> str:
    """Deploys the in-memory ZIP file to Netlify using their REST API."""
    if not NETLIFY_ACCESS_TOKEN or NETLIFY_ACCESS_TOKEN == "YOUR_NETLIFY_PERSONAL_ACCESS_TOKEN":
        return "Error: Netlify Access Token is missing. Please add it to the top of your app.py file."

    url = "https://api.netlify.com/api/v1/sites"
    headers = {
        "Content-Type": "application/zip",
        "Authorization": f"Bearer {NETLIFY_ACCESS_TOKEN}"
    }

    try:
        response = requests.post(url, headers=headers, data=zip_bytes)
        response.raise_for_status() 
        site_data = response.json()
        deploy_url = site_data.get("url")
        
        if deploy_url:
             return f"Success! Site deployed to: {deploy_url}"
        else:
             return "Deployment succeeded, but couldn't find the URL in the response."

    except requests.exceptions.RequestException as e:
         return f"Deployment failed: {e}"

def push_to_github(repo_name: str, pages_dict: dict) -> str:
    """Creates a new GitHub repo and pushes the multi-page dictionary to it."""
    if not GITHUB_ACCESS_TOKEN or GITHUB_ACCESS_TOKEN == "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
        return "Error: GitHub Access Token is missing. Please add it to the top of your app.py file."
    
    headers = {
        "Authorization": f"token {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Step 1: Create the repository
    repo_data = {
        "name": repo_name,
        "description": "Multi-page website generated by AI Web Builder",
        "private": False,
        "auto_init": True # Initializes with a README so we have a master/main branch
    }
    
    try:
        repo_resp = requests.post("https://api.github.com/user/repos", headers=headers, json=repo_data)
        if repo_resp.status_code not in (200, 201):
            return f"Failed to create repo: {repo_resp.json().get('message', 'Unknown error')}"
            
        full_repo_name = repo_resp.json()["full_name"]
        repo_url = repo_resp.json()["html_url"]
        
        # Step 2: Upload the files
        for filename, content in pages_dict.items():
            file_url = f"https://api.github.com/repos/{full_repo_name}/contents/{filename}"
            # GitHub API requires file content to be Base64 encoded
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            file_data = {
                "message": f"🤖 Auto-generated {filename} via AI Builder",
                "content": encoded_content
            }
            
            requests.put(file_url, headers=headers, json=file_data)
            
        return f"Success! Pushed to GitHub: {repo_url}"
        
    except Exception as e:
        return f"GitHub API Error: {e}"

# --- Agent Functions ---
def scrape_website_data(url: str) -> str:
    """Agent Step: Visits a URL and extracts structural data for cloning."""
    if not HAS_SCRAPER:
        return "ERROR: Missing scraping libraries."
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.title.string if soup.title else "Unknown Site"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2', 'h3']) if h.get_text(strip=True)][:15]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:20]
        
        analysis = f"TARGET CLONE URL: {url}\n"
        analysis += f"PAGE TITLE: {title}\n"
        analysis += f"KEY STRUCTURE (Headings): {', '.join(headings)}\n"
        analysis += f"NAVIGATION LINKS (Actions): {', '.join(links)}\n"
        analysis += "\nINSTRUCTION TO CODER: Analyze the structure above. Replicate the layout, navigation, and section flow of this exact website. Adapt the aesthetic to fit the user's specific request."
        
        return analysis
    except Exception as e:
        return f"Failed to scrape URL. Error: {e}"

def enhance_user_prompt(prompt: str, model_name: str = "qwen2.5-coder", temp: float = 0.7) -> str:
    system_instruction = """
    You are an expert Web Design Prompt Engineer.
    The user will provide a short, simple idea for a website.
    Your task is to expand this into a highly detailed, comprehensive prompt for an AI coder.
    If it makes sense, suggest multiple pages (e.g., Home, About, Contact).
    Include specifics about modern UI/UX, typography, and sections.
    DO NOT write code. ONLY return the descriptive prompt. Keep it under 2 paragraphs.
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"Enhance this website idea: {prompt}"}
            ],
            temperature=temp,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return prompt

def research_topic(prompt: str) -> str:
    try:
        results = DDGS().text(prompt, max_results=3)
        if not results: return "No recent news found."
        
        compiled_research = "Here is the latest information from the web:\n"
        for r in results:
            compiled_research += f"- {r.get('title', 'No Title')}: {r.get('body', 'No description')}\n"
        return compiled_research
    except Exception as e:
        return "Search skipped or failed."

def generate_website_code(prompt: str, context: str = "", image_bytes: bytes = None, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7) -> dict:
    system_instruction = f"""
    You are an expert web developer. The user will describe a website.
    You must determine if it requires multiple pages (e.g., Home, About, Contact) or just one.
    Generate the complete HTML code for ALL necessary pages.
    Wire up the navigation menus to link correctly to each other (e.g., href="index.html", href="about.html").
    
    *** CRITICAL: MULTI-FILE OUTPUT FORMAT ***
    You MUST separate each page using this exact delimiter:
    ===FILE: filename.html===
    
    *** MANDATORY DESIGN PREFERENCES ***
    {custom_style}
    
    CRITICAL - Ensure the code is styled with Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
    CRITICAL - Include FontAwesome for icons: <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    
    *** AI IMAGE GENERATION MANDATE ***
    Do NOT use generic placeholder images. You MUST use the Pollinations AI image generator for ALL images.
    Format: https://image.pollinations.ai/prompt/[highly_detailed_description]?width=[width]&height=[height]&nologo=true
    *********************************************
    Return ONLY the raw files separated by the delimiter.
    """

    messages = [{"role": "system", "content": system_instruction}]
    user_content = []
    if context: user_content.append({"type": "text", "text": f"Background Context:\n{context}\n\n"})
    user_content.append({"type": "text", "text": f"User Request: {prompt}"})

    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

    messages.append({"role": "user", "content": user_content})

    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name, messages=messages, temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return {"error.txt": f"Error generating code: {e}"}

def critique_code(prompt: str, generated_pages: dict, custom_style: str = "", model_name: str = "qwen2.5-coder") -> str:
    pages_str = "\n".join([f"===FILE: {name}===\n{code}" for name, code in generated_pages.items()])
    system_instruction = f"""
    You are a Senior Web Design Reviewer. Review the provided multi-page HTML codebase.
    Compare it against the user's request and check for broken navigation links.
    Identify 2-3 areas for improvement. Keep your critique concise.
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Request: {prompt}\n\nGenerated Code:\n{pages_str}"}
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Critique failed: {e}"

def improve_code(prompt: str, generated_pages: dict, critique: str, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7) -> dict:
    pages_str = "\n".join([f"===FILE: {name}===\n{code}" for name, code in generated_pages.items()])
    system_instruction = f"""
    You are an Expert Web Developer. You will be given a user's request, the initial multi-page code, and a critique.
    Rewrite and fix the pages to address ALL points in the critique.
    
    *** CRITICAL: MULTI-FILE OUTPUT FORMAT ***
    You MUST separate each page using this exact delimiter:
    ===FILE: filename.html===
    
    *** MANDATORY DESIGN PREFERENCES ***
    {custom_style}
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Request: {prompt}\n\nInitial Code:\n{pages_str}\n\nCritique:\n{critique}"}
            ],
            temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return generated_pages 

def edit_website_code(prompt: str, current_pages: dict, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7) -> dict:
    pages_str = "\n".join([f"===FILE: {name}===\n{code}" for name, code in current_pages.items()])
    system_instruction = f"""
    You are an Expert Web Developer. Modify the existing codebase to apply the user's requested changes.
    
    *** CRITICAL: MULTI-FILE OUTPUT FORMAT ***
    You MUST separate each page using this exact delimiter:
    ===FILE: filename.html===
    
    *** MANDATORY DESIGN PREFERENCES ***
    {custom_style}
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Edit Request: {prompt}\n\nCurrent Code:\n{pages_str}"}
            ],
            temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return {"error.txt": f"Error editing code: {e}"}

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="AI Web Builder")

if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "current_pages" not in st.session_state: st.session_state.current_pages = {}
if "current_project_id" not in st.session_state: st.session_state.current_project_id = None
if "current_project_name" not in st.session_state: st.session_state.current_project_name = "Untitled Project"

with st.sidebar:
    st.title("📁 Project Manager")
    project_name_input = st.text_input("Project Name", value=st.session_state.current_project_name)
    
    if st.button("💾 Save Project", use_container_width=True):
        if st.session_state.current_pages:
            st.session_state.current_project_name = project_name_input
            pid = save_project(st.session_state.current_project_name, st.session_state.current_pages, st.session_state.current_project_id)
            st.session_state.current_project_id = pid
            st.success("Project Saved!")
        else:
            st.warning("No code to save yet!")
            
    if st.button("✨ New Blank Project", use_container_width=True):
        st.session_state.current_pages = {}
        st.session_state.chat_history = []
        st.session_state.current_project_id = None
        st.session_state.current_project_name = "Untitled Project"
        st.rerun()

    st.divider()
    saved_projects = get_all_projects()
    if saved_projects:
        project_options = {f"{p[1]} (ID: {p[0]})": p[0] for p in saved_projects}
        selected_project_str = st.selectbox("Load Project", list(project_options.keys()))
        
        if st.button("📂 Load Selected", use_container_width=True):
            proj_id = project_options[selected_project_str]
            p_name, p_dict = load_project(proj_id)
            if p_dict:
                st.session_state.current_project_name = p_name
                st.session_state.current_pages = p_dict
                st.session_state.current_project_id = proj_id
                st.session_state.chat_history = [{"role": "assistant", "content": f"Loaded project: {p_name}"}]
                st.rerun()

    st.divider()
    st.title("⚙️ Pro Settings")
    
    selected_model = st.selectbox("🧠 AI Brain (Model)", ["qwen2.5-coder", "llama3", "llama3.2-vision", "phi3"])
    ai_temperature = st.slider("🎨 AI Creativity", 0.0, 1.0, 0.7, 0.1)
    
    selected_theme = st.selectbox("🎨 Theme Engine", list(THEME_PRESETS.keys()))
    custom_design = st.text_area("🖌️ Extra Design Rules", placeholder="e.g., Make buttons huge...")
    
    design_rules = f"{THEME_PRESETS[selected_theme]}\n{custom_design}".strip()

st.title("🤖 Local Autonomous Web Builder")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Agent Chat")
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]): st.markdown(message["content"])

    uploaded_image = st.file_uploader("🎨 Upload sketch (Optional)", type=["png", "jpg", "jpeg"])
    image_bytes = uploaded_image.read() if uploaded_image else None
    
    clone_url = st.text_input("🕷️ Website Cloner (Paste URL to clone)", placeholder="https://example.com")

    action_mode = "Create New Website"
    if st.session_state.current_pages:
        action_mode = st.radio("Action:", ["Create New Website", "Edit Current Website"], horizontal=True)

    auto_enhance = st.toggle("✨ Auto-Enhance Prompt (AI Prompt Engineer)")
    user_prompt = st.chat_input("Describe the website...")
    
    if user_prompt:
        st.session_state.chat_history.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"): st.markdown(user_prompt)

        with st.chat_message("assistant"):
            active_prompt = user_prompt
            
            if auto_enhance:
                st.write("✨ **Prompt Engineer:** Supercharging your prompt...")
                active_prompt = enhance_user_prompt(user_prompt, selected_model, ai_temperature)
                st.info(f"**Enhanced:**\n{active_prompt}")
                st.session_state.chat_history.append({"role": "assistant", "content": f"✨ **Enhanced Prompt:**\n{active_prompt}"})

            with st.status("Agents working...", expanded=True) as status:
                
                scraped_context = ""
                if clone_url:
                    if HAS_SCRAPER:
                        st.write(f"🕷️ **Scraper Agent:** Analyzing layout of {clone_url}...")
                        scraped_context = scrape_website_data(clone_url)
                        st.write("✅ URL Successfully Ingested!")
                    else:
                        st.error("Missing libraries for Website Cloner! Run `pip install requests beautifulsoup4`")

                if action_mode == "Edit Current Website":
                    st.write("🛠️ **Editor Agent:** Modifying files...")
                    final_pages = edit_website_code(active_prompt, st.session_state.current_pages, design_rules, selected_model, ai_temperature)
                
                else:
                    if image_bytes:
                        st.write("👁️ **Vision Agent:** Analyzing image...")
                        draft_pages = generate_website_code(active_prompt, image_bytes=image_bytes, custom_style=design_rules, model_name="llama3.2-vision", temp=ai_temperature)
                    else:
                        if scraped_context:
                            combined_context = scraped_context
                        else:
                            st.write("🔍 **Researcher:** Checking web...")
                            combined_context = research_topic(active_prompt)
                            
                        st.write("💻 **Coder Agent:** Writing pages...")
                        draft_pages = generate_website_code(active_prompt, context=combined_context, custom_style=design_rules, model_name=selected_model, temp=ai_temperature)

                    if "error.txt" not in draft_pages:
                        st.write("🧐 **Reviewer Agent:** Critiquing code...")
                        critique = critique_code(active_prompt, draft_pages, design_rules, selected_model)
                        st.write("✨ **Refiner Agent:** Polishing...")
                        final_pages = improve_code(active_prompt, draft_pages, critique, design_rules, selected_model, ai_temperature)
                    else:
                        final_pages = draft_pages
                
                status.update(label="✅ Operations Complete!", state="complete", expanded=False)
            
            if "error.txt" not in final_pages:
                st.markdown("Here is your multi-page website!")
                st.session_state.chat_history.append({"role": "assistant", "content": "Updated successfully!"})
                st.session_state.current_pages = final_pages
                st.rerun()
            else:
                st.error(final_pages["error.txt"])

with col2:
    st.subheader("Workspace")
    
    if st.session_state.current_pages:
        
        tab1, tab2 = st.tabs(["👁️ Live Preview", "💻 Code Editor"])
        
        with tab1:
            zip_bytes = generate_zip_file(st.session_state.current_pages)
            
            # --- Workspace Toolbar (ZIP, Netlify, GitHub) ---
            col_dl, col_deploy, col_git = st.columns(3)
            
            with col_dl:
                st.download_button(
                    label="📦 Download ZIP",
                    data=zip_bytes,
                    file_name=f"{st.session_state.current_project_name.replace(' ', '_').lower()}_site.zip",
                    mime="application/zip",
                    use_container_width=True,
                    type="primary"
                )
                
            with col_deploy:
                if st.button("🚀 Deploy Netlify", use_container_width=True, type="secondary"):
                    with st.spinner("Deploying..."):
                         deploy_result = deploy_to_netlify(zip_bytes)
                         if "Success" in deploy_result:
                             st.success("Deployed!")
                             url = deploy_result.split("Site deployed to: ")[1]
                             st.markdown(f"**[View Live Site]({url})**")
                         else:
                             st.error(deploy_result)
                             
            with col_git:
                if st.button("🐙 Push to GitHub", use_container_width=True, type="secondary"):
                    with st.spinner("Creating Repository..."):
                         # Sanitize the project name so it's a valid GitHub repo name
                         safe_repo_name = re.sub(r'[^a-zA-Z0-9-]', '-', st.session_state.current_project_name).strip('-').lower()
                         if not safe_repo_name or safe_repo_name == "untitled-project": 
                             safe_repo_name = "ai-generated-site"
                             
                         git_result = push_to_github(safe_repo_name, st.session_state.current_pages)
                         
                         if "Success" in git_result:
                             st.success("Pushed!")
                             url = git_result.split("GitHub: ")[1]
                             st.markdown(f"**[View Repository]({url})**")
                         else:
                             st.error(git_result)
            
            st.divider()
            
            selected_page = st.selectbox("📄 Active Page (Select file to preview)", list(st.session_state.current_pages.keys()), key="preview_select")
            components.html(st.session_state.current_pages[selected_page], height=800, scrolling=True)
            
        with tab2:
            edit_page = st.selectbox("📄 Active Page (Select file to edit)", list(st.session_state.current_pages.keys()), key="edit_select")
            st.caption(f"Editing: {edit_page}")
            
            if HAS_ACE:
                manual_code = st_ace(
                    value=st.session_state.current_pages[edit_page],
                    language='html',
                    theme='monokai',
                    key=f"editor_{edit_page}",
                    height=720,
                    font_size=14,
                    tab_size=4,
                    wrap=True,
                    show_gutter=True,
                    auto_update=False
                )
            else:
                st.warning("⚠️ Unlock the Pro IDE! Run `pip install streamlit-ace` in your terminal.")
                manual_code = st.text_area("Raw HTML Code", value=st.session_state.current_pages[edit_page], height=720, label_visibility="collapsed")
            
            if st.button("🔄 Apply Changes", use_container_width=True, type="primary"):
                st.session_state.current_pages[edit_page] = manual_code
                st.rerun()
    else:
        tab1, tab2 = st.tabs(["👁️ Live Preview", "💻 Code Editor"])
        with tab1: st.info("Preview will appear here.")
        with tab2: st.info("Code editor will appear here.")