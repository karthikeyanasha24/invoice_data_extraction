import requests
import json

# Replace with your actual API key
api_key = '3ecf6b1c5cf34bd797a5f4c57951a1cf'

# Replace with the path to your X.12 file
file_path = '0090039049_PEPPOL'

# Replace with the path where you want to save the output file
output_file_path = 'out.edi'

# Read the X.12 file
with open(file_path, 'r') as file:
    edi_content = file.read()

# Define the API endpoint for reading X.12 to JSON
read_url = 'https://api.edination.com/v2/x12/read'

# Set up the headers
headers = {
    'Ocp-Apim-Subscription-Key': api_key,
    'Content-Type': 'application/octet-stream'
}

# Send the POST request to read the X.12 file
read_response = requests.post(read_url, headers=headers, data=edi_content.encode('utf-8'))

if read_response.status_code == 200:
    # Convert the X.12 file to JSON
    edi_json = read_response.json()
    # Define the API endpoint for writing JSON to X.12
    write_url = 'https://api.edination.com/v2/x12/write'
    # Send the POST request to write the JSON back to X.12
    write_response = requests.post(write_url, headers=headers, json=edi_json)
    if write_response.status_code == 200:
        # Write the X.12 content to the output file
        with open(output_file_path, 'wb') as output_file:
            output_file.write(write_response.content)
        print(f"X.12 file has been written to {output_file_path}")
    else:
        print(f"Write request failed with status code {write_response.status_code}")
        print(write_response.text)
else:
    print(f"Read request failed with status code {read_response.status_code}")
    print(read_response.text)
