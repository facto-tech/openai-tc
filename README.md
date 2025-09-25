# openai-tc
Fork of MV test case generation repo


# Usage

Clone this repo  

Run `pip install -r requirements.txt`  

Create a 'docs' and an 'output' folder under the openai-tc folder  

Upload technical specifications into the docs folder, supports .pdf or .docx extensions  

Use python or py3 (depending on install version) to run tc_api.py  

Outputs are uploaded to the output folder  



# Example

To run the webUI use the below:

`streamlit run tc_api.py` from the lib folder

# Development options
## Run with auto-rerun enabled
`streamlit run app.py --server.runOnSave true`

## Run on a specific port
`streamlit run app.py --server.port 8502`

## Run in development mode with more verbose logging
`streamlit run app.py --logger.level debug`

##  Disable CORS (useful for development)
`streamlit run app.py --server.enableCORS false`


