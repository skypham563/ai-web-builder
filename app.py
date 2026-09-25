import streamlit as st
import sqlite3
import re
from openai import OpenAI

# 1. Database Setup (Creates users.db automatically)
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, credits INTEGER)''')
    # Secretly create the admin account by default for testing
    c.execute("INSERT OR IGNORE INTO users (username, password, credits) VALUES (?, ?, ?)", 
              ("skypham563@gmail.com", "admin123", 9999))
    conn.commit()
    conn.close()

init_db()

# Database Helper Functions
def get_user_credits(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE username=?", (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_credits(username, amount):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE username=?", (amount, username))
    conn.commit()
    conn.close()

def authenticate(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    result = c.fetchone()
    conn.close()
    return result is not None

def register_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, credits) VALUES (?, ?, 5)")
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

# 2. Session State Initialization
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
if "generated_html" not in st.session_state:
    st.session_state.generated_html = ""

# 3. Sidebar (Auth, Credits, and Admin Panel)
with st.sidebar:
    st.title("⚙️ Account Settings")
    
    if not st.session_state.logged_in:
        tab1, tab2 = st.tabs(["Login", "Register"])
        with tab1:
            log_user = st.text_input("Email", key="log_user")
            log_pass = st.text_input("Password", type="password", key="log_pass")
            if st.button("Login"):
                if authenticate(log_user, log_pass):
                    st.session_state.logged_in = True
                    st.session_state.username = log_user
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        with tab2:
            reg_user = st.text_input("New Email", key="reg_user")
            reg_pass = st.text_input("New Password", type="password", key="reg_pass")
            if st.button("Register"):
                if register_user(reg_user, reg_pass):
                    st.success("Registered! 5 Free credits added. Please log in.")
                else:
                    st.error("Email already exists.")
    else:
        st.success(f"Logged in as: {st.session_state.username}")
        st.metric("Available Credits", get_user_credits(st.session_state.username))
        st.markdown("[☕ Buy More Credits (Ko-fi)](https://ko-fi.com/)")
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.rerun()
            
        # Secret Admin Panel (Only visible to you)
        if st.session_state.username == "skypham563@gmail.com":
            st.divider()
            st.warning("👑 Admin Fulfillment Dashboard")
            add_user = st.text_input("User Email to Credit")
            add_amount = st.number_input("Credits to Add", value=5)
            if st.button("Grant Credits"):
                update_credits(add_user, add_amount)
                st.success(f"Added {add_amount} credits to {add_user}!")

# 4. Main App Interface
st.title("🚀 Ultimate AI Website Builder")

if not st.session_state.logged_in:
    st.info("👈 Please register or log in using the sidebar to start building!")
else:
    api_key = st.text_input("Enter your OpenAI API Key:", type="password")
    
    # Show the generated website preview
    if st.session_state.generated_html:
        st.components.v1.html(st.session_state.generated_html, height=500, scrolling=True)
        st.download_button("💾 Download your website (index.html)", 
                           st.session_state.generated_html, 
                           "index.html", "text/html")
        st.divider()
    
    # Iterative Chat Memory
    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
            
    # Chat Input Trigger
    if prompt := st.chat_input("Describe the website you want to build..."):
        if get_user_credits(st.session_state.username) <= 0:
            st.error("You are out of credits! Please purchase more using the link in the sidebar.")
        elif not api_key:
            st.warning("Please enter your OpenAI API key above.")
        else:
            update_credits(st.session_state.username, -1) # Deduct 1 credit
            
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
                
            with st.chat_message("assistant"):
                with st.spinner("Writing code..."):
                    try:
                        client = OpenAI(api_key=api_key)
                        system_prompt = "You are an expert web developer. Output ONLY raw HTML, CSS, and JS inside a single ```html block. Do not include markdown or explanations."
                        
                        # Send the full history to AI for iterative updates
                        messages = [{"role": "system", "content": system_prompt}] + st.session_state.messages
                        
                        response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=messages
                        )
                        raw_output = response.choices[0].message.content
                        st.write("Website generated successfully! Credits remaining: " + str(get_user_credits(st.session_state.username)))
                        
                        st.session_state.messages.append({"role": "assistant", "content": raw_output})
                        
                        html_match = re.search(r"```html\n(.*?)```", raw_output, re.DOTALL)
                        if html_match:
                            st.session_state.generated_html = html_match.group(1)
                        else:
                            st.session_state.generated_html = raw_output
                            
                        st.rerun()
                    except Exception as e:
                        st.error(f"API Error: {e}")
