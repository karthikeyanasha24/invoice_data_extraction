# # from selenium import webdriver
# # from selenium.webdriver.common.by import By
# # from selenium.webdriver.support.ui import WebDriverWait
# # from selenium.webdriver.support import expected_conditions as EC
# # import time

# # # Start a browser session
# # driver = webdriver.Chrome()

# # # Open the target webpage
# # driver.get("https://www.edination.com/edi-translator.html")

# # # Give the page some time to load initially
# # time.sleep(2)

# # # Find the file input element using its ID and upload the file
# # file_input = driver.find_element(By.ID, "upload-file-input")
# # file_input.send_keys("C:/Users/Administrator/Desktop/Test_files/invoice_exraction/0090040325.txt")  # Provide the full path to the EDI file

# # # Find the submit button using its ID and click it
# # submit_button = driver.find_element(By.ID, "upload-file-btn")
# # submit_button.click()

# # # Add a delay of 20 seconds after uploading to give the server enough time to process
# # time.sleep(20)

# # # Initialize the result variables
# # validation_status = "Valid"
# # error_message = ""

# # # Wait for the file processing and validation to complete, check for error table after the delay
# # try:
# #     # Wait for the error table to appear (if any errors are present), waiting for up to 30 seconds
# #     WebDriverWait(driver, 30).until(
# #         EC.presence_of_element_located((By.ID, "errors-table"))
# #     )
    
# #     # Now check if the error table has any error messages
# #     errors_table = driver.find_element(By.ID, "errors-table")
# #     error_rows = errors_table.find_elements(By.TAG_NAME, "tr")
    
# #     if error_rows:
# #         # If error rows are found, the file is invalid
# #         validation_status = "Invalid"
# #         for row in error_rows:
# #             error_message += row.text + "\n"  # Collect the error messages
    
# # except Exception as e:
# #     error_message = f"Error occurred: {e}"

# # # Print the result at the end
# # print(f"File upload status: {validation_status}")
# # if validation_status == "Invalid":
# #     print("Error Message(s):")
# #     print(error_message)

# # # Close the browser session
# # driver.quit()


# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.common.keys import Keys
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# import time

# def validate_x12_content(x12_content):
#     """
#     Function to validate an EDI X12 content by pasting it into the website for validation.
    
#     Args:
#         x12_content (str): The contents of the X12 file to be validated.
    
#     Returns:
#         tuple: A tuple containing the validation status ("Valid" or "Invalid") and error message (if any).
#     """
#     # Start a browser session
#     driver = webdriver.Chrome()

#     # Open the target webpage
#     driver.get("https://www.edination.com/edi-translator.html#tab_ediJson")

#     # Wait for the text area to be interactable (loaded and visible)
#     try:
#         textarea = WebDriverWait(driver, 30).until(
#             EC.element_to_be_clickable((By.CLASS_NAME, "ace_text-input"))
#         )

#         # Paste the contents of the X12 file into the text area
#         textarea.send_keys(x12_content)

#         # Execute JavaScript to trigger the saveEditor() function
#         driver.execute_script("saveEditor()")

#         # Add a delay of 20 seconds after submitting to give the server enough time to process
#         time.sleep(20)

#         # Initialize the result variables
#         validation_status = "Valid"
#         error_message = ""

#         # Wait for the file processing and validation to complete, check for error table after the delay
#         try:
#             # Wait for the error table to appear (if any errors are present), waiting for up to 30 seconds
#             WebDriverWait(driver, 30).until(
#                 EC.presence_of_element_located((By.ID, "errors-table"))
#             )
            
#             # Now check if the error table has any error messages
#             errors_table = driver.find_element(By.ID, "errors-table")
#             error_rows = errors_table.find_elements(By.TAG_NAME, "tr")
            
#             if error_rows:
#                 # If error rows are found, the file is invalid
#                 validation_status = "Invalid"
#                 for row in error_rows:
#                     error_message += row.text + "\n"  # Collect the error messages

#         except Exception as e:
#             error_message = f"Error occurred: {e}"

#         # Return validation status and error message
#         return validation_status, error_message

#     except Exception as e:
#         # Handle the case where the textarea element is not found or interactable
#         print(f"Error: {e}")
#         driver.quit()
#         return "Error", str(e)

#     finally:
#         # Close the browser session
#         driver.quit()


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

# Start a browser session
driver = webdriver.Chrome()

# Open the target webpage
driver.get("https://www.edination.com/edi-translator.html#tab_ediJson")

# Give the page some time to load initially
time.sleep(2)

# Read the content of the X12 file
file_path = "C:/Users/Administrator/Desktop/Test_files/invoice_exraction/0090039049_PEPPOL.txt"  # Provide the full path to the EDI file
with open(file_path, 'r') as file:
    x12_content = file.read()

# Find the text area element where the X12 file content needs to be pasted
textarea = driver.find_element(By.CLASS_NAME, "ace_text-input")

# Paste the contents of the X12 file into the text area
textarea.send_keys(x12_content)

# Execute JavaScript to trigger the saveEditor() function
driver.execute_script("saveEditor()")

# Add a delay of 20 seconds after submitting to give the server enough time to process
time.sleep(10)

# Initialize the result variables
validation_status = "Valid"
error_message = ""

# Wait for the file processing and validation to complete, check for error table after the delay
try:
    # Wait for the error table to appear (if any errors are present), waiting for up to 30 seconds
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "errors-table"))
    )
    
    # Now check if the error table has any error messages
    errors_table = driver.find_element(By.ID, "errors-table")
    error_rows = errors_table.find_elements(By.TAG_NAME, "tr")
    
    if error_rows:
        # If error rows are found, the file is invalid
        validation_status = "Invalid"
        for row in error_rows:
            error_message += row.text + "\n"  # Collect the error messages

except Exception as e:
    error_message = f"Error occurred: {e}"

# Print the result at the end
print(f"File upload status: {validation_status}")
if validation_status == "Invalid":
    print("Error Message(s):")
    print(error_message)

# Close the browser session
driver.quit()
