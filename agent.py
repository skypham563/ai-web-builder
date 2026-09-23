import streamlit as st
import openai

# --- Configuration ---
LOCAL_API_BASE = "http://localhost:11434/v1" 
LOCAL_API_KEY = "local-server" 
LOCAL_MODEL_NAME = "llama3" 

# --- Agent Functions ---
def generate_website_code(prompt: str) -> str:
    system_instruction = """
    You are an expert web developer. The user will describe a website they want.
    Your task is to generate the complete HTML code for that website.
    The code MUST be contained entirely within a single HTML file.
    Include all necessary CSS within a <style> tag in the <head>.
    Include all necessary JavaScript within a <script> tag at the end of the <body>.
    Make the design modern, responsive, and visually appealing.
    Return ONLY the raw HTML code, starting with <!DOCTYPE html>. Do not include markdown formatting or explanations.
    """
    
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000 
        )
        
        generated_code = response.choices[0].message.content
        if generated_code.startswith("```html"):
            generated_code = generated_code[7:]
        if generated_code.endswith("```"):
            generated_code = generated_code[:-3]
            
        return generated_code.strip()
    except Exception as e:
        return f"Error: {e}"

def critique_code(prompt: str, generated_code: str) -> str:
    system_instruction = """
    You are a Senior Web Design Reviewer. Review the provided HTML/CSS/JS code.
    Compare it against the user's original request.
    Identify 2-3 areas for improvement (e.g., missing features, poor color contrast, bad layout, lack of responsiveness).
    Keep your critique concise and actionable. Do NOT write code, just provide the critique.
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Request: {prompt}\n\nGenerated Code:\n{generated_code}"}
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Critique failed: {e}"

def improve_code(prompt: str, generated_code: str, critique: str) -> str:
    system_instruction = """
    You are an Expert Web Developer. You will be given a user's request, the initial HTML code, and a Senior Reviewer's critique.
    Your job is to rewrite and fix the HTML code to address ALL the points in the critique.
    Return ONLY the raw HTML code, starting with <!DOCTYPE html>. Do not include markdown formatting or explanations.
    """
    try:
        client = openai.OpenAI(base_url=LOCAL_API_BASE, api_key=LOCAL_API_KEY)
        response = client.chat.completions.create(
            model=LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Request: {prompt}\n\nInitial Code:\n{generated_code}\n\nCritique:\n{critique}"}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        improved_code = response.choices[0].message.content
        if improved_code.startswith("```html"):
            improved_code = improved_code[7:]
        if improved_code.endswith("```"):
            improved_code = improved_code[:-3]
        return improved_code.strip()
    except Exception as e:
        return generated_code 

# --- Streamlit UI Setup ---
st.set_page_config(page_title="Manus AI Clone", layout="wide", initial_sidebar_state="collapsed")

# Session state to remember the generated code between screen refreshes
if "current_html" not in st.session_state:
    st.session_state.current_html = ""

st.title("🤖 Local Autonomous Web Builder")

# Create a two-column layout (Chat on left, Preview on right)
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Agent Chat")
    user_prompt = st.chat_input("Describe the website you want to build...")
    
    if user_prompt:
        st.write(f"**You:** {user_prompt}")
        
        # This creates a cool loading dropdown box for the AI's internal thoughts
        with st.status("Agent is working...", expanded=True) as status:
            st.write("🧑‍💻 **Coder Agent:** Generating initial HTML layout...")
            draft_code = generate_website_code(user_prompt)
            
            st.write("🧐 **Reviewer Agent:** Analyzing code for flaws...")
            critique = critique_code(user_prompt, draft_code)
            st.info(f"**Reviewer Notes:** {critique}")
            
            st.write("🛠️ **Refiner Agent:** Fixing code based on review...")
            final_code = improve_code(user_prompt, draft_code, critique)
            
            st.session_state.current_html = final_code
            status.update(label="Website Built Successfully!", state="complete", expanded=False)

with col2:
    st.subheader("Live Preview")
    
    if st.session_state.current_html:
        # Render the HTML directly inside the Streamlit app!
        st.components.v1.html(st.session_state.current_html, height=800, scrolling=True)
        
        # Add a dropdown to look at the raw code
        with st.expander("View Source Code"):
            st.code(st.session_state.current_html, language="html")
    else:
        st.info("Your website preview will appear here once the agent finishes building.")