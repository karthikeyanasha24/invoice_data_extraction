# 🧪 Test Message Tracker / Status Updates

## Test 1: Upload via Postman (Backend Test)

### Step 1: Upload Invoice
```http
POST http://localhost:8000/api/v1/invoices/upload
Headers:
  x-api-key: YOUR_API_KEY
Body:
  form-data
  - file: [select any valid XML file]
  - strict_validation: false
```

**Expected Response:**
```json
{
  "tracking_id": "abc-123-def-456",
  "processing_steps": [],
  "status": "PROCESSING"
}
```

**Note:** `processing_steps` will be empty initially - it's processing in background!

---

### Step 2: Check Status (Immediately After)
```http
GET http://localhost:8000/api/v1/invoices/status/abc-123-def-456
Headers:
  Authorization: Bearer YOUR_ACCESS_TOKEN
```

**Expected Response (if working):**
```json
{
  "tracking_id": "abc-123-def-456",
  "processing_steps": [
    {
      "step_name": "File Upload",
      "step_number": 1,
      "success": true,
      "duration_seconds": 0.05,
      "message": "File uploaded successfully"
    },
    {
      "step_name": "XML Validation",
      "step_number": 2,
      "success": true,
      "duration_seconds": 0.1,
      "message": "XML validation passed"
    }
    // ... more steps as processing continues
  ]
}
```

**If NOT working (Issue Found!):**
```json
{
  "tracking_id": "abc-123-def-456",
  "processing_steps": []  ← EMPTY!
}
```
OR
```json
{
  "detail": "Status not found"  ← NOT IN MEMORY!
}
```

---

### Step 3: Wait & Check Again (After 3-5 seconds)
```http
GET http://localhost:8000/api/v1/invoices/status/abc-123-def-456
Headers:
  Authorization: Bearer YOUR_ACCESS_TOKEN
```

**Should show:** All completed steps including "Database Save"

---

## Test 2: Check Backend Logs

### Step 1: Watch Server Console
While uploading, you should see:
```
📊 Status tracker initialized for tracking_id: abc-123...
📊 Status updated for tracking_id: abc-123... - Step 1: File Upload
📊 Status updated for tracking_id: abc-123... - Step 2: XML Validation
...
✅ Marked processing as completed for tracking_id: abc-123...
```

**If missing:** Backend isn't using status_tracker!

---

## Test 3: Frontend Test (Browser)

### Step 1: Open Browser Console (F12)
Go to your upload page

### Step 2: Upload File
Watch console output:

**Should see:**
```javascript
📥 Polling status for tracking_id: abc-123...
📊 Status received: { processing_steps: [...] }
✅ Step completed: File Upload
✅ Step completed: XML Validation
...
```

**If you see:**
```javascript
❌ Status not found
// OR
❌ Failed to fetch processing status
// OR
📊 Status received: { processing_steps: [] }  ← EMPTY!
```
→ Issue found!

---

## 🔍 Diagnostic Tests

### Test A: Is Status Tracker Working?

Create test file `test_status.py`:
```python
import requests
import time

API_URL = "http://localhost:8000"
API_KEY = "your_api_key_here"

# Step 1: Upload
print("1️⃣ Uploading invoice...")
with open("test_invoice.xml", "rb") as f:
    response = requests.post(
        f"{API_URL}/api/v1/invoices/upload",
        files={"file": f},
        params={"strict_validation": "false"},
        headers={"x-api-key": API_KEY}
    )

if response.status_code not in [200, 202]:
    print(f"❌ Upload failed: {response.status_code}")
    print(response.text)
    exit(1)

tracking_id = response.json()["tracking_id"]
print(f"✅ Got tracking_id: {tracking_id}")

# Step 2: Poll status
print("\n2️⃣ Polling status...")
for i in range(10):  # Poll 10 times
    time.sleep(0.5)  # Wait 500ms
    
    status_response = requests.get(
        f"{API_URL}/api/v1/invoices/status/{tracking_id}",
        headers={"x-api-key": API_KEY}
    )
    
    if status_response.status_code == 200:
        data = status_response.json()
        steps = data.get("processing_steps", [])
        print(f"   Poll {i+1}: {len(steps)} steps")
        
        for step in steps:
            status_icon = "✅" if step["success"] else "❌"
            print(f"      {status_icon} Step {step['step_number']}: {step['step_name']}")
        
        # Check if completed
        if any(s["step_name"] == "Database Save" and s["success"] for s in steps):
            print("\n✅ Processing completed!")
            break
    else:
        print(f"   Poll {i+1}: ❌ Status not found (HTTP {status_response.status_code})")

print("\n3️⃣ Final check in database...")
# Check if invoice is in database
invoices_response = requests.get(
    f"{API_URL}/api/v1/invoices/successful",
    headers={"x-api-key": API_KEY},
    params={"limit": 1}
)

if invoices_response.status_code == 200:
    invoices = invoices_response.json()
    if invoices and invoices[0]["tracking_id"] == tracking_id:
        print(f"✅ Invoice found in database")
    else:
        print(f"❌ Invoice NOT in database yet")
```

Run it:
```bash
cd zodiac-api
python test_status.py
```

---

## 🎯 What Each Result Means:

### Result 1: Status Shows Immediately
```
Poll 1: 1 steps
   ✅ Step 1: File Upload
Poll 2: 2 steps
   ✅ Step 1: File Upload
   ✅ Step 2: XML Validation
...
```
**Meaning:** ✅ Everything is working! Status tracker is fine.

---

### Result 2: Status Always Empty
```
Poll 1: 0 steps
Poll 2: 0 steps
Poll 3: 0 steps
...
✅ Invoice found in database
```
**Meaning:** ❌ Backend processes successfully BUT doesn't update status_tracker  
**Issue:** `process_invoice_internal` isn't calling `status_tracker.update_step()`

---

### Result 3: Status Not Found
```
Poll 1: ❌ Status not found (HTTP 404)
Poll 2: ❌ Status not found (HTTP 404)
...
✅ Invoice found in database
```
**Meaning:** ❌ Status tracker not initialized OR cleared too quickly  
**Issue:** `status_tracker.initialize_status()` not being called

---

### Result 4: Steps Show Then Disappear
```
Poll 1: 2 steps
Poll 2: 3 steps
Poll 3: 0 steps  ← DISAPPEARED!
```
**Meaning:** ❌ Status tracker being cleared mid-processing  
**Issue:** `cleanup_old_statuses()` running too aggressively

---

### Result 5: Auth Error
```
Poll 1: ❌ Status not found (HTTP 401)
```
**Meaning:** ❌ Authentication token invalid  
**Issue:** Need to get proper access token

---

## 🚀 Quick Manual Test (No Code)

### Option A: Postman Collection

1. **Request 1: Upload**
   - Method: POST
   - URL: `{{BASE_URL}}/api/v1/invoices/upload`
   - Headers: `x-api-key: {{API_KEY}}`
   - Body: form-data, file: your XML
   - **Save response tracking_id**

2. **Request 2: Check Status** (run multiple times)
   - Method: GET
   - URL: `{{BASE_URL}}/api/v1/invoices/status/{{tracking_id}}`
   - Headers: `x-api-key: {{API_KEY}}`
   - **Check if processing_steps array grows**

3. **Repeat Request 2** every second for 5-10 seconds
   - Steps should increase: 1 → 2 → 3 → 4 → 5
   - Last step should be "Database Save"

---

### Option B: Browser Test

1. Open frontend upload page
2. Open browser console (F12)
3. Upload a file
4. Watch for:
   ```
   📊 Processing status: Step 1 of 5
   📊 Processing status: Step 2 of 5
   ...
   ```

**If you don't see these updates → Issue confirmed!**

---

## 📝 Report Results

After running tests, tell me:

1. **Which result did you get?** (Result 1-5 above)
2. **Backend logs:** Any errors or missing status tracker messages?
3. **Browser console:** What did you see?

Then I'll know exactly what to fix!

