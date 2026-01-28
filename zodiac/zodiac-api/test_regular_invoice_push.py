"""
Test pushing a REGULAR invoice (not CFDI) via API
This simulates SAP pushing a standard invoice for EDI conversion
"""

import requests

BASE_URL = "http://localhost:8000"
API_BASE_URL = f"{BASE_URL}/api/v1"

# Your API key from the previous test
API_KEY = "NmxwS2sxNnRsZy1SVThOVkFWdTMtN3p5MGJhLU1IQUF5TExGVmRFaUNqNndycW0xRlk0VTM4TTN4bG4xSV9DNGVhbk0wMll0bFU4LVliQU5NbFZEelE="

# Create a simple test invoice XML (not CFDI)
test_invoice_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice>
    <Header>
        <InvoiceNumber>INV-2025-001</InvoiceNumber>
        <InvoiceDate>2025-01-22</InvoiceDate>
        <Currency>USD</Currency>
    </Header>
    <Seller>
        <Name>INDISTRIA ILUMINADORA DE ALMACENES</Name>
        <ID>IIA040805DZ4</ID>
        <Address>
            <Street>123 Main St</Street>
            <City>Mexico City</City>
            <PostalCode>54720</PostalCode>
            <Country>Mexico</Country>
        </Address>
    </Seller>
    <Buyer>
        <Name>EDIFACTMX</Name>
        <ID>EDI101020E99</ID>
        <Address>
            <Street>456 Commerce Ave</Street>
            <City>Cancun</City>
            <PostalCode>97133</PostalCode>
            <Country>Mexico</Country>
        </Address>
    </Buyer>
    <LineItems>
        <LineItem>
            <ProductCode>01010101</ProductCode>
            <Description>iPhone 16e</Description>
            <Quantity>1.000000</Quantity>
            <UnitPrice>663.77</UnitPrice>
            <TotalPrice>663.77</TotalPrice>
        </LineItem>
    </LineItems>
    <Summary>
        <SubTotal>663.77</SubTotal>
        <Tax>106.20</Tax>
        <Total>769.97</Total>
    </Summary>
</Invoice>"""

print("=" * 80)
print("Testing Regular Invoice Push (SAP Simulation)")
print("=" * 80)

# Save to file
with open("test_regular_invoice.xml", "w", encoding="utf-8") as f:
    f.write(test_invoice_xml)

print("✅ Created test_regular_invoice.xml")
print(f"📄 File size: {len(test_invoice_xml)} bytes")

# Push to Bridge Portal
print("\n📤 Pushing invoice to Bridge Portal...")
print(f"Endpoint: POST {API_BASE_URL}/invoices/api/process")

files = {
    'file': ('test_regular_invoice.xml', test_invoice_xml, 'application/xml')
}

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

response = requests.post(
    f"{API_BASE_URL}/invoices/api/process",
    headers=headers,
    files=files
)

print(f"\n📊 Response Status: {response.status_code}")

if response.status_code in [200, 202]:
    data = response.json()
    print("✅ Invoice pushed successfully!")
    print(f"   Tracking ID: {data.get('tracking_id')}")
    print(f"   Message: {data.get('message')}")
    print(f"   Status: {data.get('status')}")
else:
    print("❌ Invoice push failed!")
    print(f"   Response: {response.text}")

print("\n" + "=" * 80)
print("Test completed!")
print("=" * 80)

