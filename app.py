import streamlit as st
import openai
import re
import streamlit.components.v1 as components

st.set_page_config(page_title="AI Web Builder Pro", page_icon="🚀", layout="wide")

def check_password():
    """Returns True if the user enters the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 Private Access")
        st.markdown("Please enter the password to access the AI Web Builder.")
        
        password = st.text_input("Password", type="password")
        
        if st.button("Login"):
            # You can change "sky2024" to whatever password you want!
            if password == "sky2024": 
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 Incorrect password. Please try again.")
        return False
    return True

# If the password is not correct, stop the app here and don't load the rest
if not check_password():
    st.stop()

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
    
    st.divider()
    st.subheader("🖼️ AI Magic Media")
    use_dalle = st.toggle("✨ Auto-Generate Hero Image", help="Uses DALL-E 3 to create a custom hero image and automatically insert it into your website.")

st.title("✨ AI Web Builder Pro")
st.markdown("Describe the website you want to build. The AI will write the code and render a live preview below.")

if "generated_html" not in st.session_state:
    st.session_state.generated_html = ""

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        # If it's the AI, don't flood the screen with raw HTML code
        if msg["role"] == "assistant":
            st.write("✅ Code generated & applied!")
        else:
            st.write(msg["content"])

prompt = st.chat_input(f"E.g., Build a dark-mode landing page for a {template}...")

if prompt:
    if not api_key:
        st.error("Please enter your OpenAI API Key in the sidebar.")
    else:
        # Initialize OpenAI Client once for both images and text
        client = openai.OpenAI(api_key=api_key)
        
        # --- DALL-E Image Generation Logic ---
        image_context = ""
        if use_dalle:
            with st.chat_message("assistant"):
                with st.spinner("🎨 Generating custom hero image with DALL-E 3..."):
                    try:
                        # 1. Generate the image
                        img_response = client.images.generate(
                            model="dall-e-3",
                            prompt=f"A beautiful, clean, modern web design hero image for a {template}. Professional photography, high resolution, no text overlay. Request context: {prompt}",
                            size="1024x1024",
                            quality="standard",
                            n=1,
                        )
                        image_url = img_response.data[0].url
                        # 2. Create a hidden instruction to force the AI to use this image
                        image_context = f"\n\nCRITICAL INSTRUCTION: You MUST use this exact image URL as the main hero/header image in the HTML layout: {image_url}"
                        st.image(image_url, caption="Generated Custom Asset")
                    except Exception as e:
                        st.error(f"Image generation failed: {e}")

        # 3. Add user prompt (plus hidden image instruction) to memory
        enhanced_prompt = prompt + image_context
        st.session_state.messages.append({"role": "user", "content": enhanced_prompt})
        
        with st.chat_message("user"):
            st.write(prompt) # Only show the clean prompt to the user
            if image_context:
                st.caption("📎 Attached custom DALL-E image to request.")
            
        with st.chat_message("assistant"):
            with st.spinner("Building your website... (This takes about 15-30 seconds)"):
                try:
                    # 4. Update system prompt to handle iterative edits
                    system_prompt = f"""You are an expert frontend web developer. 
                    Create a beautiful, modern, mobile-responsive HTML webpage for a {template}. 
                    CRITICAL: You MUST include all HTML, CSS (use Tailwind via CDN), and JavaScript in a SINGLE file.
                    Output ONLY the raw HTML code inside a ```html codeblock. Do not add explanations.
                    If the user asks for a modification to the existing code, output the ENTIRE updated HTML file."""
                    
                    # 5. Combine system prompt with the full conversation history
                    api_messages = [{"role": "system", "content": system_prompt}] + st.session_state.messages
                    
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=api_messages,
                        temperature=0.7
                    )
                    
                    raw_output = response.choices[0].message.content
                    
                    # 6. Save the AI's response to memory and show success message
                    st.session_state.messages.append({"role": "assistant", "content": raw_output})
                    st.write("✅ Code generated & applied!")
                    
                    # 7. Extract the HTML for the preview
                    html_match = re.search(r"```html\n(.*?)\n```", raw_output, re.DOTALL)
                    if html_match:
                        st.session_state.generated_html = html_match.group(1)
                    else:
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