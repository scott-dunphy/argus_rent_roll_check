import asyncio
from datetime import datetime
from openai import OpenAI
from agents import Agent, Runner, handoff
from agents.tool import function_tool
import os
import pandas as pd
import streamlit as st

import json
import base64
import tempfile
import time
import datetime
from pathlib import Path
import pdf2image

os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

@function_tool
def process_pdf_rent_roll(pdf_file_path: str):
    """
    Processes a rent roll PDF file by uploading it, performing OCR,
    and converting the OCR markdown output into a structured JSON response.

    Args:
        pdf_file_path (str): The path to the PDF file to process.

    Returns:
        The structured JSON response as defined by StructuredRentRoll.
    """
    import os
    from mistralai import Mistral, DocumentURLChunk, TextChunk
    from pydantic import BaseModel
    from typing import List

    # Define data models using Pydantic
    class RentRollUnits(BaseModel):
        occupant_name: str
        unit_number: str
        square_feet: float
        lease_start_date: str
        lease_end_date: str
        monthly_rent: float

    class StructuredRentRoll(BaseModel):
        units: List[RentRollUnits]

    # Set API key for Mistral

    api_key = st.secrets["MISTRAL_API_KEY"]

    # Initialize the client
    client = Mistral(api_key=api_key)

    # Upload the PDF file for OCR processing
    with open(pdf_file_path, "rb") as pdf_file:
        uploaded_pdf = client.files.upload(
            file={
                "file_name": pdf_file_path,
                "content": pdf_file,
            },
            purpose="ocr"
        )

    # Get a signed URL for the uploaded file
    signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)

    # Process the OCR using the signed URL
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed_url.url,
        },
    )

    # Aggregate the markdown outputs from all OCR pages
    markdowns = [page.markdown for page in ocr_response.pages]

    # Parse the OCR markdown into a structured JSON format
    chat_response = client.chat.parse(
        model="pixtral-12b-latest",
        messages=[
            {
                "role": "user",
                "content": [
                    DocumentURLChunk(document_url=signed_url.url),
                    TextChunk(
                        text=(
                            f"This is the document's OCR in markdown:\n{markdowns}\n.\n"
                            "Convert this into a structured JSON response "
                            "with the OCR contents in a sensible dictionnary."
                        )
                    )
                ]
            }
        ],
        response_format=StructuredRentRoll,
        temperature=0
    )

    # Return the structured JSON response
    return chat_response.choices[0].message.content

@function_tool
def convert_argus_rent_roll(pdf_file_path: str) -> dict:
    """
    Processes a PDF rent roll and converts it into a structured JSON with monthly rent calculations.

    Steps:
      1. Uploads the PDF file for OCR using the Mistral API.
      2. Retrieves the signed URL and processes OCR on the document.
      3. Uses chat parsing to convert the OCR markdown into a structured JSON format.
         The JSON includes an "analysis_date" and a list of rent roll units.
      4. For each unit, calculates the monthly rent:
           - If the lease_end_date is in the same year as the analysis_date, calculates
             the number of months between analysis_date and lease_end_date (inclusive) and
             divides potential_rent by that number.
           - Otherwise, divides potential_rent by 12.

    Args:
        pdf_file_path (str): The path to the PDF file.

    Returns:
        dict: The processed rent roll JSON with an added "monthly_rent" field for each unit.
    """
    import os
    import json
    from pathlib import Path
    from datetime import datetime
    from mistralai import Mistral, DocumentURLChunk, TextChunk
    from pydantic import BaseModel
    from typing import List

    # Define the Pydantic models for the rent roll
    class RentRollUnits(BaseModel):
        occupant_name: str
        unit_number: str
        square_feet: float
        lease_start_date: str
        lease_end_date: str
        potential_rent: float

    class StructuredRentRoll(BaseModel):
        analysis_date: str
        units: List[RentRollUnits]

    # Set the API key and initialize the client
    api_key = st.secrets["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)

    # Upload the PDF file
    with open(pdf_file_path, "rb") as pdf_file:
        uploaded_pdf = client.files.upload(
            file={
                "file_name": pdf_file_path,
                "content": pdf_file,
            },
            purpose="ocr"
        )

    # Get a signed URL for the uploaded PDF
    signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)

    # Process OCR on the document using the signed URL
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed_url.url,
        },
    )

    # Combine markdown outputs from all OCR pages
    markdowns = [page.markdown for page in ocr_response.pages]

    # Use chat parsing to convert the OCR markdown into a structured JSON response.
    # Note: The message instructs the model how to extract the analysis_date from text such as
    # "Mar, 2025 through Feb, 2026", where the analysis_date would be "3/31/2025".
    chat_response = client.chat.parse(
        model="pixtral-12b-latest",
        messages=[
            {
                "role": "user",
                "content": [
                    DocumentURLChunk(document_url=signed_url.url),
                    TextChunk(text=(
                        f"This is the document's OCR in markdown:\n{markdowns}\n.\n"
                        "Convert this into a structured JSON response "
                        "with the OCR contents in a sensible dictionnary. "
                        "The analysis_date is extracted from text like 'Mar, 2025 through Feb, 2026'. "
                        "In that example, the analysis_date would be '3/31/2025'."
                    ))
                ]
            }
        ],
        response_format=StructuredRentRoll,
        temperature=0
    )

    # Extract the unit data from the chat response.
    unit_data = chat_response.choices[0].message.content

    # Function to calculate monthly rent for each unit
    def calculate_monthly_rent(data):
        """
        Calculates the monthly rent for each unit based on the analysis_date and lease_end_date.

        For each unit:
          - If the lease_end_date is in the same year as the analysis_date, the number of months is:
              (lease_end_date.month - analysis_date.month) + 1
            and monthly_rent is potential_rent divided by that number.
          - Otherwise, monthly_rent is calculated as potential_rent divided by 12.
        """
        # If data is a string, convert it to a dictionary
        if isinstance(data, str):
            data = json.loads(data)

        # Parse the analysis_date (expected format: "%m/%d/%Y")
        analysis_date = datetime.strptime(data["analysis_date"], "%m/%d/%Y")

        # Process each unit
        for unit in data.get("units", []):
            lease_end_date = datetime.strptime(unit["lease_end_date"], "%m/%d/%Y")
            potential_rent = unit.get("potential_rent", 0)

            if lease_end_date.year == analysis_date.year:
                # Calculate number of months between analysis_date and lease_end_date (inclusive)
                months = (lease_end_date.month - analysis_date.month) + 1
                if months <= 0:
                    months = 1
                monthly_rent = potential_rent / months
            else:
                monthly_rent = potential_rent / 12

            # Add the calculated monthly_rent to the unit (rounded to 2 decimals)
            unit["monthly_rent"] = round(monthly_rent, 2)
            unit.pop("potential_rent", None)

        return data

    # Calculate monthly rent for each unit in the extracted data
    final_data = calculate_monthly_rent(unit_data)
    return final_data

comparison_agent = Agent(
    name="comparison_agent",
    instructions=(
        "Compare the two rent rolls to identify any discrepancies between the actual rent roll and the Argus rent roll."
        ""
        "When you receive data from the extraction agents:"
        "1. First identify which dataset is which by looking for the 'ACTUAL_RENT_ROLL_DATA:' and 'ARGUS_RENT_ROLL_DATA:' headers"
        "2. Parse both JSON datasets correctly and verify they have been properly loaded"
        "3. Compare the following fields between matching units:"
        "   - Unit numbers and occupant names"
        "   - Monthly rent amounts"
        "   - Square footage"
        "   - Lease expiration dates"
        "4. Create a summary table showing:"
        "   - Units present in one dataset but not the other"
        "   - Differences in values for matching units"
        "   - Calculate the total monthly rent difference and percentage variance"
        ""
        "Print all intermediate steps in your analysis to ensure data is being processed correctly."
        "Do not show discrepancies if they are rounding errors or less than $1."
        "When your analysis is complete, type 'COMPLETE'"
    ),
)


analysis_agent = Agent(
    name="Analysis_Agent",
    instructions=
        "You are responsible for comparing two rent roll datasets: the actual rent roll and the Argus (underwriting) rent roll. Do not show discrepancies if they are less then $1"
    ,
    tools=[
        process_pdf_rent_roll,
        convert_argus_rent_roll,
        ],
    handoffs=[comparison_agent],
)

# Main Orchestration
async def main(actual_rent_roll_path, argus_rent_roll_path):
    if not os.path.exists(rent_roll_pdf_path):
        print(f"Error: Rent roll file not found at: {rent_roll_pdf_path}")
        return
    output = await Runner.run(
        analysis_agent,
        f"Process rent rolls. Actual Rent Roll {actual_rent_roll_path}"
                f"Argus Rent Roll {argus_pdf_path} "
                "First pass the actual rent roll pdf path to the rent roll extraction tool."
                "Second, pass the argus rent roll pdf path to the argus extraction tool."
                "Finally, pass the extracted data to the rent roll comparison agent for analysis."
                "When finished type 'COMPLETE' to exit the job."
    )

    print(output.final_output)




if __name__ == "__main__":
    asyncio.run(main())
