import uvicorn
from fastapi import FastAPI
import requests
from starlette.responses import StreamingResponse

from invoice_converter import convert_xml_to_x12

app = FastAPI()

# https://steadfast-dream-production.up.railway.app/

@app.get("/")
async def hello():
    return {"message": "Hello World"}

@app.get("/convert")
async def convert():
    try:
        # response = requests.get("https://run.mocky.io/v3/bcd077f9-6b8a-4366-a849-67a1297f3aec")

        url = "http://saperphana007.local:8000/psif_inv_xml3/invoice?inv=0090040325"

        payload = {}
        headers = {
            'Authorization': 'Basic YW5kaXg6aW5pdDEyMzQ=',
            'Cookie': 'SAP_SESSIONID_ERP_800=-lQ5baiiE5l_ntEcN7aOEA2h6SPrfxHvr_aA-luPFoQ%3d; sap-usercontext=sap-client=800'
        }

        response = requests.request("GET", url, headers=headers, data=payload)

        print(response.text)


        x12_content = convert_xml_to_x12(response.text)

        return StreamingResponse(x12_content, media_type="application/text")
    except Exception as e:
        raise e


if __name__ == "__main__":

    uvicorn.run(app, host="0.0.0.0", port=5000)
