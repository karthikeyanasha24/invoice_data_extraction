# import requests
# from starlette.responses import StreamingResponse
# from invoice_converter import convert_xml_to_x12
# # from validation import validate_edi_file
# try:
#         # response = requests.get("https://run.mocky.io/v3/bcd077f9-6b8a-4366-a849-67a1297f3aec")

#         url = "http://saperphana007.local:8000/psif_inv_xml3/invoice?inv=0090040051"

#         payload = {}
#         headers = {
#             'Authorization': 'Basic YW5kaXg6aW5pdDEyMzQ=',
#             'Cookie': 'SAP_SESSIONID_ERP_800=-lQ5baiiE5l_ntEcN7aOEA2h6SPrfxHvr_aA-luPFoQ%3d; sap-usercontext=sap-client=800'
#         }

#         response = requests.request("GET", url, headers=headers, data=payload)

#         print(response.text)


#         x12_content = convert_xml_to_x12(response.text)
#         print(x12_content)


# except Exception as e:
#         raise e

# result = StreamingResponse(x12_content, media_type="application/text")
# print(result)


import requests
from invoice_converter import convert_xml_to_x12
from validation import validate_x12_content
try:
    # Step 1: Get the invoice number (inv) from user input
    inv_number = input("Enter the invoice number (e.g., 0090040051): ")

    # Step 2: Modify the URL to include the dynamic invoice number
    url = f"http://saperphana007.local:8000/psif_inv_xml3/invoice?inv={inv_number}"

    payload = {}
    headers = {
        'Authorization': 'Basic YW5kaXg6aW5pdDEyMzQ=',
        'Cookie': 'SAP_SESSIONID_ERP_800=-lQ5baiiE5l_ntEcN7aOEA2h6SPrfxHvr_aA-luPFoQ%3d; sap-usercontext=sap-client=800'
    }

    # Step 3: Send the GET request to the URL
    response = requests.get(url, headers=headers, data=payload)

    if response.status_code == 200:
        print(f"Successfully fetched data for invoice {inv_number}.")
        x12_content = convert_xml_to_x12(response.text)
        print(x12_content)
        
        # Step 4: Validate the X12 content
        validation_status, error_message = validate_x12_content(x12_content)
        
        # Step 5: Print validation results
        print(f"File upload status: {validation_status}")
        if validation_status == "Invalid":
            print("Error Message(s):")
            print(error_message)

    else:
        print(f"Failed to fetch data for invoice {inv_number}. HTTP Status Code: {response.status_code}")

except Exception as e:
    print(f"An error occurred: {e}")
    raise e
