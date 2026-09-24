import streamlit as st
import openai
import re
import streamlit.components.v1 as components

st.set_page_config(page_title="AI Web Builder Pro", page_icon="🚀", layout="wide")

with st.sidebar:
    st.title("⚙️ Builder Settings")
    st.divider()
    
    # Safely get the API key from Streamlit secrets, or let the user type it locally
    default_key = ""
    try:
        default_key = st.secrets["OPENAI_API_KEY"]
    except:
        pass
        
    api_key = st.text_input("OpenAI API Key", value=default_key, type="password")
    
    st.divider()
    st.subheader("🎨 Business Templates")
    template = st.selectbox("Select a layout style:", [
        "Nail Salon & Spa",
        "Tattoo Artist Portfolio",
        "E-Commerce Boutique",
        "Modern SaaS Startup"
    ])

st.title("✨ AI Web Builder Pro")
st.markdown("Describe the website you want to build. The AI will write the code and render a live preview below.")

if "generated_html" not in st.session_state:
    st.session_state.generated_html = ""

prompt = st.chat_input(f"E.g., Build a dark-mode landing page for a {template}...")

if prompt:
    if not api_key:
        st.error("Please enter your OpenAI API Key in the sidebar.")
    else:
        # Display the user's prompt
        with st.chat_message("user"):
            st.write(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Building your website... (This takes about 15-30 seconds)"):
                try:
                    client = openai.OpenAI(api_key=api_key)
                    
                    system_prompt = f"""You are an expert frontend web developer. 
                    Create a beautiful, modern, mobile-responsive HTML webpage for a {template}. 
                    CRITICAL: You MUST include all HTML, CSS (use Tailwind via CDN), and JavaScript in a SINGLE file.
                    Output ONLY the raw HTML code inside a ```html codeblock. Do not add explanations."""
                    
                    response = client.chat.completions.create(
                        model="gpt-4o-mini", # Using the fast/cheap model for speed
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.7
                    )
                    
                    raw_output = response.choices[0].message.content
                    
                    # We use regex to find code between ```html and ```
                    html_match = re.search(r"```html\n(.*?)\n```", raw_output, re.DOTALL)
                    if html_match:
                        st.session_state.generated_html = html_match.group(1)
                    else:
                        # Fallback if the AI forgets the formatting
                        st.session_state.generated_html = raw_output
                        
                except Exception as e:
                    st.error(f"An error occurred: {e}")

if st.session_state.generated_html:
    st.success("✅ Website generated successfully!")
    
    # Create tabs to switch between the visual preview and the raw code
    tab1, tab2 = st.tabs(["👁️ Live Preview", "💻 Raw Code"])
    
    with tab1:
        # Render the HTML safely in a Streamlit iframe
        components.html(st.session_state.generated_html, height=600, scrolling=True)
        
    with tab2:
        st.code(st.session_state.generated_html, language='html')
        
    # Provide a one-click download button for the generated file
    st.download_button(
        label="⬇️ Download index.html",
        data=st.session_state.generated_html,
        file_name="index.html",
        mime="text/html",
        type="primary"
    )