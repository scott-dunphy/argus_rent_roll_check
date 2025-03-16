import streamlit as st
import asyncio
import os
import tempfile
from utils import main as process_rent_rolls

# Set page configuration
st.set_page_config(page_title="Compare Actual Rent Roll to Argus Rent Roll", layout="wide")

# Function to run async functions in Streamlit
def async_to_sync(async_func):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(async_func)
    loop.close()
    return result

# Override the main function from utils.py to accept file paths
async def run_analysis(actual_rent_roll_path, argus_rent_roll_path):
    if not os.path.exists(actual_rent_roll_path):
        return f"Error: Actual rent roll file not found at: {actual_rent_roll_path}"
    if not os.path.exists(argus_rent_roll_path):
        return f"Error: Argus rent roll file not found at: {argus_rent_roll_path}"
    
    # Import the Runner and analysis_agent from utils
    from utils import Runner, analysis_agent
    
    output = await Runner.run(
        analysis_agent,
        f"Process rent rolls. Actual Rent Roll {actual_rent_roll_path} "
        f"Argus Rent Roll {argus_rent_roll_path} "
        "First pass the actual rent roll pdf path to the rent roll extraction tool. "
        "Second, pass the argus rent roll pdf path to the argus extraction tool. "
        "Finally, pass the extracted data to the rent roll comparison agent for analysis. "
        "When finished type 'COMPLETE' to exit the job."
    )
    
    return output.final_output

# UI for the Streamlit app
st.title("Rent Roll Comparison Tool")

st.markdown("""
This application compares an actual rent roll with an Argus (underwriting) rent roll to identify discrepancies.
Upload both PDF files to begin the analysis.
""")

# Check for Mistral API key in secrets
try:
    # Set API key from secrets to environment variable
    os.environ["MISTRAL_API_KEY"] = st.secrets["MISTRAL_API_KEY"]
    st.success("✅ Mistral API key loaded from secrets!")
except Exception:
    st.warning("⚠️ Mistral API key not found in secrets. Please add it to your .streamlit/secrets.toml file.")
    st.info("Format in secrets.toml: MISTRAL_API_KEY = 'your-api-key-here'")

# File upload section
st.header("Upload Rent Roll Files")

col1, col2 = st.columns(2)
with col1:
    actual_rent_roll = st.file_uploader("Upload Actual Rent Roll PDF", type=["pdf"])
with col2:
    argus_rent_roll = st.file_uploader("Upload Argus (Underwriting) Rent Roll PDF", type=["pdf"])

# Process files when both are uploaded
if actual_rent_roll and argus_rent_roll:
    # Create temporary directory for uploaded files
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save uploaded files
        actual_path = os.path.join(temp_dir, "actual_rent_roll.pdf")
        with open(actual_path, "wb") as f:
            f.write(actual_rent_roll.getbuffer())
        
        argus_path = os.path.join(temp_dir, "argus_rent_roll.pdf")
        with open(argus_path, "wb") as f:
            f.write(argus_rent_roll.getbuffer())
        
        st.success("Files uploaded successfully!")
        
        # Run analysis button
        if st.button("Run Comparison Analysis"):
            with st.spinner("Processing rent rolls... This may take a few minutes."):
                try:
                    # Run the analysis
                    result = async_to_sync(run_analysis(actual_path, argus_path))
                    
                    # Display results
                    st.header("Analysis Results")
                    st.markdown(result)
                    
                except Exception as e:
                    st.error(f"An error occurred during analysis: {str(e)}")
                    st.exception(e)  # This will display the full traceback for debugging
else:
    st.info("Please upload both PDF files to continue.")

# Information about the tool
with st.expander("About this tool"):
    st.markdown("""
    This tool compares actual rent roll data with Argus (underwriting) rent roll data to identify discrepancies.
    
    The analysis compares:
    - Unit numbers and occupant names
    - Monthly rent amounts
    - Square footage
    - Lease expiration dates
    
    The tool uses the Mistral API for OCR and data extraction from the PDF files.
    API credentials are stored securely in Streamlit secrets.
    """)

# Add section about setting up secrets
with st.expander("Setup Instructions"):
    st.markdown("""
    ### Setting up Streamlit Secrets
    
    1. Create a file named `.streamlit/secrets.toml` in your project directory
    2. Add your Mistral API key in this format:
       ```
       MISTRAL_API_KEY = "your-api-key-here"
       ```
    3. Make sure the `.streamlit` directory is in your .gitignore file to avoid exposing your API key
    
    For more information on Streamlit secrets management, visit [Streamlit's documentation](https://docs.streamlit.io/streamlit-cloud/get-started/deploy-an-app/connect-to-data-sources/secrets-management).
    """)
