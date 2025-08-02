from validation import validate_x12_content
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless")  # Run Chrome in headless mode (without GUI)
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
# Dummy test for the validate_x12_content function

# Sample dummy X12 content (replace with real X12 content in actual use)
dummy_x12_content = """
ISA*00*          *00*          *ZZ*TEST          *ZZ*TEST          *150101*1253*U*00401*000000001*0*P*>
GS*IN*TEST*TEST*20220101*1253*1*X*004010
ST*810*0001
BIG*20220101*12345**ACME*INVOICE
...
"""

# Call the validation function with dummy X12 content
validation_status, error_message = validate_x12_content(dummy_x12_content)

# Print the validation results
print(f"Validation Status: {validation_status}")
if validation_status == "Invalid":
    print(f"Error Message(s): {error_message}")
