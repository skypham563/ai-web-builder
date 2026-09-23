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
import requests
import hashlib
from duckduckgo_search import DDGS

# --- Voice-to-Code Plugin Attempt ---
try:
    from streamlit_mic_recorder import speech_to_text
    HAS_VOICE = True
except ImportError:
    HAS_VOICE = False

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
NETLIFY_ACCESS_TOKEN = "YOUR_NETLIFY_PERSONAL_ACCESS_TOKEN" 
GITHUB_ACCESS_TOKEN = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"   

# --- Theme Engine Definitions ---
THEME_PRESETS = {
    "Default (None)": "",
    "Apple Minimalist": "Use extreme minimalism. White and very light gray backgrounds (bg-gray-50), subtle borders, soft rounded corners (rounded-2xl or 3xl), and very soft shadows (shadow-sm). Typography should be clean sans-serif (tracking-tight). Use frosted glass effects (backdrop-blur) for navbars.",
    "Cyberpunk 2077": "Use a dark mode aesthetic (bg-gray-900 or black). Accents must be bright neon pink, cyan, and yellow. Use sharp, square corners (rounded-none). Add thick borders to buttons with glowing hover effects. Typography should be monospace.",
    "Neo-Brutalist": "High contrast and brutalist. Backgrounds in harsh white or bright bold colors (yellow, pink). ALL UI elements (cards, buttons) MUST have thick black borders (border-4 border-black) and hard black shadows (shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]). Typography must be huge, bold, and black.",
    "Web3 Glassmorphism": "Use dark gradient backgrounds. UI cards must be semi-transparent (bg-white/10) with strong background blur (backdrop-blur-md), subtle white borders (border border-white/20), and white text. Everything should feel floating and futuristic."
}

# --- Database Setup & Auth (SQLite) ---
def init_db():
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    
    query1 = "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)"
    c.execute(query1)
    
    query2 = "CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT NOT NULL, code TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))"
    c.execute(query2)
    
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, hash_password(password)))
        conn.commit()
        return True, "Registration successful! You can now log in."
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    finally:
        conn.close()

def authenticate_user(username, password):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    
    if result and result[1] == hash_password(password):
        return result[0] 
    return None

def save_project(name, pages_dict, assets_dict, chat_history, user_id, project_id=None):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    
    encoded_assets = {}
    for k, v in assets_dict.items():
        encoded_assets[k] = base64.b64encode(v).decode('utf-8')
        
    payload = {"pages": pages_dict, "assets": encoded_assets, "chat_history": chat_history}
    code_json = json.dumps(payload)
    
    if project_id:
        c.execute('UPDATE projects SET name=?, code=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?', (name, code_json, project_id, user_id))
    else:
        c.execute('INSERT INTO projects (user_id, name, code) VALUES (?, ?, ?)', (user_id, name, code_json))
        project_id = c.lastrowid
    conn.commit()
    conn.close()
    return project_id

def load_project(project_id, user_id):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('SELECT name, code FROM projects WHERE id=? AND user_id=?', (project_id, user_id))
    row = c.fetchone()
    conn.close()
    if row:
        try:
            data = json.loads(row[1])
            if isinstance(data, dict) and "pages" in data:
                pages = data.get("pages", {})
                chat_history = data.get("chat_history", [])
                assets = {}
                for k, v in data.get("assets", {}).items():
                    assets[k] = base64.b64decode(v)
            else:
                pages = data 
                assets = {}
                chat_history = []
        except json.JSONDecodeError:
            pages = {"index.html": row[1]}
            assets = {}
            chat_history = []
        return row[0], pages, assets, chat_history
    return None, None, None, None

def get_all_projects(user_id):
    conn = sqlite3.connect('projects.db')
    c = conn.cursor()
    c.execute('SELECT id, name, updated_at FROM projects WHERE user_id=? ORDER BY updated_at DESC', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

init_db()

# --- Utility Functions ---
def parse_multi_file_response(response_text: str) -> dict:
    files = {}
    parts = re.split(r'===FILE:\s*(.+?)===', response_text)
    
    html_marker = chr(96) + chr(96) + chr(96) + "html"
    end_marker = chr(96) + chr(96) + chr(96)
    
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            filename = parts[i].strip()
            content = parts[i+1].strip()
            if content.startswith(html_marker): 
                content = content[7:]
            if content.endswith(end_marker): 
                content = content[:-3]
            files[filename] = content.strip()
    else:
        content = response_text.strip()
        if content.startswith(html_marker): 
            content = content[7:]
        if content.endswith(end_marker): 
            content = content[:-3]
        files["index.html"] = content.strip()
        
    return files

def inject_assets_for_preview(html_str: str, assets_dict: dict) -> str:
    for filename, file_bytes in assets_dict.items():
        ext = filename.split('.')[-1].lower()
        mime = "application/octet-stream"
        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']:
            mime = "image/" + ext
        if ext == 'svg': 
            mime = "image/svg+xml"
        
        b64_str = base64.b64encode(file_bytes).decode('utf-8')
        data_uri = "data:" + mime + ";base64," + b64_str
        
        html_str = html_str.replace('src="' + filename + '"', 'src="' + data_uri + '"')
        html_str = html_str.replace("src='" + filename + "'", "src='" + data_uri + "'")
        html_str = html_str.replace('src="./' + filename + '"', 'src="' + data_uri + '"')
        html_str = html_str.replace('url("' + filename + '")', 'url("' + data_uri + '")')
        html_str = html_str.replace("url('" + filename + "')", "url('" + data_uri + "')")
    return html_str

def generate_zip_file(pages_dict: dict, assets_dict: dict) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for filename, html_code in pages_dict.items():
            zip_file.writestr(filename, html_code)
        for filename, file_bytes in assets_dict.items():
            zip_file.writestr(filename, file_bytes)
    return zip_buffer.getvalue()

def deploy_to_netlify(zip_bytes: bytes) -> str:
    if not NETLIFY_ACCESS_TOKEN or NETLIFY_ACCESS_TOKEN == "YOUR_NETLIFY_PERSONAL_ACCESS_TOKEN":
        return "Error: Netlify Access Token is missing."

    url = "https://api.netlify.com/api/v1/sites"
    headers = {
        "Content-Type": "application/zip",
        "Authorization": "Bearer " + NETLIFY_ACCESS_TOKEN
    }
    try:
        response = requests.post(url, headers=headers, data=zip_bytes)
        response.raise_for_status() 
        site_data = response.json()
        deploy_url = site_data.get("url")
        if deploy_url:
             return "Success! Site deployed to: " + deploy_url
        else:
             return "Deployment succeeded, but couldn't find URL."
    except requests.exceptions.RequestException as e:
         return "Deployment failed: " + str(e)

def push_to_github(repo_name: str, pages_dict: dict, assets_dict: dict) -> str:
    if not GITHUB_ACCESS_TOKEN or GITHUB_ACCESS_TOKEN == "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
        return "Error: GitHub Access Token is missing."
    
    headers = {
        "Authorization": "token " + GITHUB_ACCESS_TOKEN,
        "Accept": "application/vnd.github.v3+json"
    }
    repo_data = {
        "name": repo_name,
        "description": "Multi-page website generated by AI Web Builder",
        "private": False,
        "auto_init": True 
    }
    try:
        repo_resp = requests.post("https://api.github.com/user/repos", headers=headers, json=repo_data)
        if repo_resp.status_code not in (200, 201):
            return "Failed to create repo."
            
        full_repo_name = repo_resp.json()["full_name"]
        repo_url = repo_resp.json()["html_url"]
        
        for filename, content in pages_dict.items():
            file_url = "https://api.github.com/repos/" + full_repo_name + "/contents/" + filename
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            file_data = {
                "message": "Auto-generated " + filename,
                "content": encoded_content
            }
            requests.put(file_url, headers=headers, json=file_data)
            
        for filename, file_bytes in assets_dict.items():
            file_url = "https://api.github.com/repos/" + full_repo_name + "/contents/" + filename
            encoded_content = base64.b64encode(file_bytes).decode('utf-8')
            file_data = {
                "message": "Uploaded asset " + filename,
                "content": encoded_content
            }
            requests.put(file_url, headers=headers, json=file_data)
            
        return "Success! Pushed to GitHub: " + repo_url
    except Exception as e:
        return "GitHub API Error: " + str(e)

# --- Agent Functions ---
def scrape_website_data(url: str) -> str:
    if not HAS_SCRAPER:
        return "ERROR: Missing scraping libraries."
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.title.string if soup.title else "Unknown Site"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2', 'h3']) if h.get_text(strip=True)][:15]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:20]
        
        analysis = "TARGET CLONE URL: " + url + " | "
        analysis += "PAGE TITLE: " + title + " | "
        analysis += "KEY STRUCTURE (Headings): " + ", ".join(headings) + " | "
        analysis += "NAVIGATION LINKS: " + ", ".join(links) + " | "
        analysis += "INSTRUCTION: Replicate the layout, navigation, and section flow of this exact website."
        return analysis
    except Exception as e:
        return "Failed to scrape URL."

def enhance_user_prompt(prompt: str, model_name: str = "qwen2.5-coder", temp: float = 0.7) -> str:
    system_instruction = "You are an expert Web Design Prompt Engineer. Expand the user's idea into a detailed prompt. DO NOT write code."
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "Enhance this website idea: " + prompt}
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
        compiled_research = "Here is the latest information from the web: "
        for r in results:
            compiled_research += r.get('title', 'No Title') + ": " + r.get('body', 'No description') + " | "
        return compiled_research
    except Exception as e:
        return "Search skipped or failed."

def generate_website_code(prompt: str, context: str = "", image_bytes: bytes = None, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7, available_assets: list = []) -> dict:
    asset_instruction = ""
    if available_assets:
        files_str = ", ".join(available_assets)
        asset_instruction = "USER UPLOADED ASSETS: You have access to these local files: " + files_str + ". Use these exact filenames in the img src attribute."

    system_instruction = "You are an expert web developer. Generate multi-page HTML code if needed. "
    system_instruction += "Separate each page using this exact delimiter: ===FILE: filename.html=== "
    system_instruction += "MANDATORY DESIGN PREFERENCES: " + custom_style + " "
    system_instruction += 'CRITICAL - Tailwind CSS via CDN:  '
    system_instruction += 'CRITICAL - FontAwesome:  '
    system_instruction += asset_instruction + " "
    system_instruction += "For all other placeholder images, use: https://image.pollinations.ai/prompt/[description]?width=[w]&height=[h]&nologo=true "
    system_instruction += "Return ONLY raw files separated by the delimiter."
    
    messages = [{"role": "system", "content": system_instruction}]
    user_content = []
    
    if context: 
        user_content.append({"type": "text", "text": "Background Context: " + context})
        
    user_content.append({"type": "text", "text": "User Request: " + prompt})
    
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        img_url = "data:image/jpeg;base64," + base64_image
        user_content.append({"type": "image_url", "image_url": {"url": img_url}})
        
    messages.append({"role": "user", "content": user_content})

    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name, messages=messages, temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return {"error.txt": "Error generating code."}

def critique_code(prompt: str, generated_pages: dict, custom_style: str = "", model_name: str = "qwen2.5-coder") -> str:
    pages_list = []
    for name, code in generated_pages.items():
        pages_list.append("===FILE: " + name + "===\n" + code)
    pages_str = "\n".join(pages_list)
    
    system_instruction = "You are a Senior Web Reviewer. Identify 2-3 areas for improvement."
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "User Request: " + prompt + " Generated Code: " + pages_str}
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content
    except Exception as e:
        return "Critique failed."

def improve_code(prompt: str, generated_pages: dict, critique: str, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7) -> dict:
    pages_list = []
    for name, code in generated_pages.items():
        pages_list.append("===FILE: " + name + "===\n" + code)
    pages_str = "\n".join(pages_list)
    
    system_instruction = "Rewrite pages to address critique. Use format: ===FILE: filename.html=== " + custom_style
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "User Request: " + prompt + " Initial Code: " + pages_str + " Critique: " + critique}
            ],
            temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return generated_pages 

def audit_seo_accessibility(generated_pages: dict, model_name: str = "qwen2.5-coder", temp: float = 0.5) -> dict:
    pages_list = []
    for name, code in generated_pages.items():
        pages_list.append("===FILE: " + name + "===\n" + code)
    pages_str = "\n".join(pages_list)
    
    system_instruction = "You are an Expert SEO and Accessibility (a11y) Auditor. "
    system_instruction += "Review the provided HTML and automatically fix/inject: "
    system_instruction += "1. Missing SEO meta tags (title, description). "
    system_instruction += "2. Accessibility features (aria-labels, alt text). "
    system_instruction += "3. Ensure HTML lang attribute is set. "
    system_instruction += "CRITICAL: You MUST separate each page using this delimiter: ===FILE: filename.html=== "
    system_instruction += "Return ONLY the raw fixed files. Do not explain changes."
    
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "Please audit and fix this code for SEO and Accessibility: " + pages_str}
            ],
            temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return generated_pages

def edit_website_code(prompt: str, current_pages: dict, custom_style: str = "", model_name: str = "qwen2.5-coder", temp: float = 0.7, available_assets: list = []) -> dict:
    pages_list = []
    for name, code in current_pages.items():
        pages_list.append("===FILE: " + name + "===\n" + code)
    pages_str = "\n".join(pages_list)
    
    asset_instruction = ""
    if available_assets:
        files_str = ", ".join(available_assets)
        asset_instruction = "USER UPLOADED ASSETS: You have access to these local files: " + files_str + ". Use these exact filenames in the img src attribute."

    system_instruction = "Modify existing codebase based on edits. Use format: ===FILE: filename.html=== " + custom_style + " " + asset_instruction
    
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "User Edit Request: " + prompt + " Current Code: " + pages_str}
            ],
            temperature=temp, max_tokens=6000
        )
        return parse_multi_file_response(response.choices[0].message.content)
    except Exception as e:
        return {"error.txt": "Error editing code."}

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="AI Web Builder")

if "user_id" not in st.session_state: st.session_state.user_id = None
if "username" not in st.session_state: st.session_state.username = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "current_pages" not in st.session_state: st.session_state.current_pages = {}
if "assets" not in st.session_state: st.session_state.assets = {}
if "current_project_id" not in st.session_state: st.session_state.current_project_id = None
if "current_project_name" not in st.session_state: st.session_state.current_project_name = "Untitled Project"

# --- Authentication Screen ---
if st.session_state.user_id is None:
    st.title("Welcome to the Ultimate AI Website Builder")
    tab_login, tab_register = st.tabs(["Log In", "Register"])
    
    with tab_login:
        with st.form("login_form"):
            login_username = st.text_input("Username")
            login_password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In")
            if submitted:
                user_id = authenticate_user(login_username, login_password)
                if user_id:
                    st.session_state.user_id = user_id
                    st.session_state.username = login_username
                    st.success("Welcome back, " + login_username + "!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
                    
    with tab_register:
        with st.form("register_form"):
            reg_username = st.text_input("Choose a Username")
            reg_password = st.text_input("Choose a Password", type="password")
            reg_password_confirm = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Register")
            if submitted:
                if reg_password != reg_password_confirm:
                    st.error("Passwords do not match.")
                elif not reg_username or not reg_password:
                    st.error("Please fill in all fields.")
                else:
                    success, msg = register_user(reg_username, reg_password)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
    st.stop()

# --- Main Application ---
with st.sidebar:
    st.title("👋 Welcome, " + st.session_state.username)
    if st.button("Log Out"):
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.current_pages = {}
        st.session_state.assets = {}
        st.session_state.chat_history = []
        st.session_state.current_project_id = None
        st.rerun()
        
    st.divider()
    st.title("📁 Project Manager")
    project_name_input = st.text_input("Project Name", value=st.session_state.current_project_name)
    
    if st.button("💾 Save Project", use_container_width=True):
        if st.session_state.current_pages:
            st.session_state.current_project_name = project_name_input
            pid = save_project(
                st.session_state.current_project_name, 
                st.session_state.current_pages, 
                st.session_state.assets, 
                st.session_state.chat_history, 
                st.session_state.user_id, 
                st.session_state.current_project_id
            )
            st.session_state.current_project_id = pid
            st.success("Project Saved (with Chat History)!")
        else:
            st.warning("No code to save yet!")
            
    if st.button("✨ New Blank Project", use_container_width=True):
        st.session_state.current_pages = {}
        st.session_state.assets = {}
        st.session_state.chat_history = []
        st.session_state.current_project_id = None
        st.session_state.current_project_name = "Untitled Project"
        st.rerun()

    st.divider()
    saved_projects = get_all_projects(st.session_state.user_id)
    if saved_projects:
        project_options = {}
        for p in saved_projects:
            option_name = p[1] + " (ID: " + str(p[0]) + ")"
            project_options[option_name] = p[0]
            
        selected_project_str = st.selectbox("Load Project", list(project_options.keys()))
        
        if st.button("📂 Load Selected", use_container_width=True):
            proj_id = project_options[selected_project_str]
            p_name, p_dict, p_assets, p_chat = load_project(proj_id, st.session_state.user_id)
            if p_dict:
                st.session_state.current_project_name = p_name
                st.session_state.current_pages = p_dict
                st.session_state.assets = p_assets or {}
                st.session_state.current_project_id = proj_id
                
                if p_chat:
                    st.session_state.chat_history = p_chat
                else:
                    st.session_state.chat_history = [{"role": "assistant", "content": "Loaded project: " + p_name}]
                    
                st.rerun()

    st.divider()
    st.title("🖼️ Media Asset Manager")
    uploaded_media = st.file_uploader("Upload your images/logos", accept_multiple_files=True, type=['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'])
    if uploaded_media:
        for m in uploaded_media:
            st.session_state.assets[m.name] = m.read()
        st.success("Uploaded " + str(len(uploaded_media)) + " files!")
        
    if st.session_state.assets:
        st.write("**Available Assets for AI:**")
        for asset_name in st.session_state.assets.keys():
            st.caption("✅ " + asset_name)
        if st.button("Clear Assets"):
            st.session_state.assets = {}
            st.rerun()

    st.divider()
    st.title("⚙️ Pro Settings")
    selected_model = st.selectbox("🧠 AI Brain (Model)", ["qwen2.5-coder", "llama3", "llama3.2-vision", "phi3"])
    ai_temperature = st.slider("🎨 AI Creativity", 0.0, 1.0, 0.7, 0.1)
    selected_theme = st.selectbox("🎨 Theme Engine", list(THEME_PRESETS.keys()))
    custom_design = st.text_area("🖌️ Extra Design Rules", placeholder="e.g., Make buttons huge...")
    design_rules = THEME_PRESETS[selected_theme] + " " + custom_design

st.title("🤖 Local Autonomous Web Builder")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Agent Chat")
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]): st.markdown(message["content"])

    uploaded_image = st.file_uploader("🎨 Upload UI sketch to clone (Vision)", type=["png", "jpg", "jpeg"])
    image_bytes = uploaded_image.read() if uploaded_image else None
    
    clone_url = st.text_input("🕷️ Website Cloner (Paste URL to clone)", placeholder="https://example.com")

    action_mode = "Create New Website"
    if st.session_state.current_pages:
        action_mode = st.radio("Action:", ["Create New Website", "Edit Current Website"], horizontal=True)

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        auto_enhance = st.toggle("✨ Auto-Enhance Prompt", value=True)
    with col_t2:
        run_auditor = st.toggle("🕵️ SEO & a11y Auditor", value=True)

    voice_input = None
    if HAS_VOICE:
        st.write("🎙️ **Voice Command:** (Click to speak)")
        voice_input = speech_to_text(language='en', use_container_width=True, just_once=True, key='STT')
    else:
        st.caption("🎙️ Voice commands disabled. Run `pip install streamlit-mic-recorder`.")

    text_input = st.chat_input("Or type your request here...")
    
    user_request = voice_input or text_input
    
    if user_request:
        st.session_state.chat_history.append({"role": "user", "content": user_request})
        with st.chat_message("user"): st.markdown(user_request)

        with st.chat_message("assistant"):
            active_prompt = user_request
            if auto_enhance:
                st.write("✨ **Prompt Engineer:** Supercharging your prompt...")
                active_prompt = enhance_user_prompt(user_request, selected_model, ai_temperature)
                st.info("**Enhanced:**\n" + active_prompt)
                st.session_state.chat_history.append({"role": "assistant", "content": "✨ **Enhanced Prompt:**\n" + active_prompt})

            with st.status("Agents working...", expanded=True) as status:
                scraped_context = ""
                asset_names = list(st.session_state.assets.keys())
                
                if clone_url:
                    if HAS_SCRAPER:
                        st.write("🕷️ **Scraper Agent:** Analyzing layout of " + clone_url + "...")
                        scraped_context = scrape_website_data(clone_url)
                        st.write("✅ URL Successfully Ingested!")
                    else:
                        st.error("Missing libraries for Website Cloner!")

                if action_mode == "Edit Current Website":
                    st.write("🛠️ **Editor Agent:** Modifying files...")
                    final_pages = edit_website_code(active_prompt, st.session_state.current_pages, design_rules, selected_model, ai_temperature, asset_names)
                else:
                    if image_bytes:
                        st.write("👁️ **Vision Agent:** Analyzing image...")
                        draft_pages = generate_website_code(active_prompt, image_bytes=image_bytes, custom_style=design_rules, model_name="llama3.2-vision", temp=ai_temperature, available_assets=asset_names)
                    else:
                        if scraped_context:
                            combined_context = scraped_context
                        else:
                            st.write("🔍 **Researcher:** Checking web...")
                            combined_context = research_topic(active_prompt)
                            
                        st.write("💻 **Coder Agent:** Writing pages...")
                        draft_pages = generate_website_code(active_prompt, context=combined_context, custom_style=design_rules, model_name=selected_model, temp=ai_temperature, available_assets=asset_names)

                    if "error.txt" not in draft_pages:
                        st.write("🧐 **Reviewer Agent:** Critiquing code...")
                        critique = critique_code(active_prompt, draft_pages, design_rules, selected_model)
                        st.write("✨ **Refiner Agent:** Polishing...")
                        final_pages = improve_code(active_prompt, draft_pages, critique, design_rules, selected_model, ai_temperature)
                    else:
                        final_pages = draft_pages
                
                if "error.txt" not in final_pages and run_auditor:
                    st.write("🕵️ **Auditor Agent:** Scanning for SEO and Accessibility...")
                    final_pages = audit_seo_accessibility(final_pages, selected_model, ai_temperature)
                    st.write("✅ **Auditor Agent:** Optimizations injected!")

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
            zip_bytes = generate_zip_file(st.session_state.current_pages, st.session_state.assets)
            col_dl, col_deploy, col_git = st.columns(3)
            
            with col_dl:
                st.download_button(
                    label="📦 Download ZIP",
                    data=zip_bytes,
                    file_name=st.session_state.current_project_name.replace(' ', '_').lower() + "_site.zip",
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
                             st.markdown("**[View Live Site](" + url + ")**")
                         else:
                             st.error(deploy_result)
            with col_git:
                if st.button("🐙 Push to GitHub", use_container_width=True, type="secondary"):
                    with st.spinner("Creating Repository..."):
                         safe_repo_name = re.sub(r'[^a-zA-Z0-9-]', '-', st.session_state.current_project_name).strip('-').lower()
                         if not safe_repo_name or safe_repo_name == "untitled-project": 
                             safe_repo_name = "ai-generated-site"
                         git_result = push_to_github(safe_repo_name, st.session_state.current_pages, st.session_state.assets)
                         if "Success" in git_result:
                             st.success("Pushed!")
                             url = git_result.split("GitHub: ")[1]
                             st.markdown("**[View Repository](" + url + ")**")
                         else:
                             st.error(git_result)
            
            st.divider()
            selected_page = st.selectbox("📄 Active Page (Select file to preview)", list(st.session_state.current_pages.keys()), key="preview_select")
            
            preview_html = inject_assets_for_preview(st.session_state.current_pages[selected_page], st.session_state.assets)
            components.html(preview_html, height=800, scrolling=True)
            
        with tab2:
            edit_page = st.selectbox("📄 Active Page (Select file to edit)", list(st.session_state.current_pages.keys()), key="edit_select")
            st.caption("Editing: " + edit_page)
            
            if HAS_ACE:
                manual_code = st_ace(
                    value=st.session_state.current_pages[edit_page],
                    language='html',
                    theme='monokai',
                    key="editor_" + edit_page,
                    height=720,
                    font_size=14,
                    tab_size=4,
                    wrap=True,
                    show_gutter=True,
                    auto_update=False
                )
            else:
                st.warning("⚠️ Unlock the Pro IDE! Run `pip install streamlit-ace`.")
                manual_code = st.text_area("Raw HTML Code", value=st.session_state.current_pages[edit_page], height=720, label_visibility="collapsed")
            
            if st.button("🔄 Apply Changes", use_container_width=True, type="primary"):
                st.session_state.current_pages[edit_page] = manual_code
                st.rerun()
    else:
        tab1, tab2 = st.tabs(["👁️ Live Preview", "💻 Code Editor"])
        with tab1: st.info("Preview will appear here.")
        with tab2: st.info("Code editor will appear here.")

st.sidebar.divider()
st.sidebar.title("☁️ Cloud API Settings")
cloud_provider = st.sidebar.selectbox("AI Provider", ["Local (Ollama)", "OpenAI", "Anthropic", "DeepSeek"])

api_key_input = ""
if cloud_provider != "Local (Ollama)":
    api_key_input = st.sidebar.text_input(f"Enter your {cloud_provider} API Key", type="password", value=st.secrets.get(f"{cloud_provider.upper()}_KEY", ""))
