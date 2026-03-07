# AI Chat Integration Debug Guide

## Overview
This guide helps debug issues with missing data or charts in the AI chatbot on the Dashboard AI Analysis page.

## Common Issues & Solutions

### 1. Charts Not Showing

**Possible Causes:**
- ✅ **No numeric data**: Charts require at least one numeric column in the query results
- ✅ **Column name mismatch**: LLM suggests wrong column names that don't exist in data
- ✅ **Empty query results**: No data returned from database
- ✅ **Chart generation disabled**: Only "new" and "compare" actions generate charts

**How to Debug:**
1. Open browser DevTools (F12) → Console tab
2. Look for these log messages:
   - `📊 AI Analysis Response:` - Shows full backend response
   - `📊 Extracted Charts:` - Shows parsed chart data
   - `📊 AIChartRenderer:` - Shows charts being rendered
   - `📊 Analyzing X rows for visualization` - Backend chart generation
   - `❌` markers indicate failures

**Solutions:**
- Ask questions that return numeric data (e.g., "Show revenue by customer")
- Check that your database has data for the time period
- Look at the "Action: X • SQL executed • N rows • M chart(s)" label under AI messages

### 2. Missing or Incomplete Data

**Possible Causes:**
- Database has no data for the selected time period
- Query returns only text columns (no numbers)
- SAP connection issues
- Filters too restrictive

**How to Debug:**
1. Check the metadata under each AI response:
   - `Action: new` - New query executed
   - `SQL executed` - Database query ran
   - `N rows` - How many rows returned
   - `M chart(s)` - How many charts generated

2. Backend logs (check terminal):
   ```
   📊 Analyzing 50 rows for visualization
   📊 Found 3 numeric columns: [total_amount, quantity, net_value]
   📊 Found 2 categorical columns: [customer_name, country]
   ✅ Generated 2 chart(s) for user query
   ```

**Solutions:**
- Try broader time periods (e.g., last 90 days instead of 7 days)
- Ask for queries that definitely have numeric results (totals, counts, averages)
- Check that your SAP database has invoice data

### 3. Backend Not Returning Charts

**Check Backend Response Structure:**
The backend should return:
```json
{
  "reply": "text response",
  "action": "new",
  "sql": "SELECT ...",
  "rows_preview": [...],
  "charts": [
    {
      "chart_type": "bar",
      "title": "Chart Title",
      "description": "Chart description",
      "data": [...],
      "x_key": "category",
      "y_keys": ["value1", "value2"],
      "colors": [...],
      "show_legend": true,
      "show_grid": true
    }
  ]
}
```

**What Actions Generate Charts:**
- ✅ `new` - New SQL queries
- ✅ `compare` - Comparison queries
- ❌ `follow-up` - Uses cached data, no new charts
- ❌ `reuse` - Reuses previous query
- ❌ `chitchat` - No data query
- ❌ `knowledge` - Saving notes

### 4. Chart Rendering Errors

**Frontend Validation:**
Each chart type requires specific keys:
- **Bar/Line/Area**: Must have `x_key` and `y_keys[]`
- **Pie**: Must have `name_key` and `value_key`
- **Table**: Uses all columns from data

**Error Messages:**
If you see "Chart configuration error" in the UI:
- Check console for: `📊 Chart X missing required keys`
- The backend likely suggested incorrect column names
- Solution: Ask the question differently or check your database schema

## Testing Chart Generation

### Step 1: Basic Revenue Chart
```
Ask: "Show total revenue by customer for the last 30 days"
Expected: Bar chart with customers on X-axis, revenue on Y-axis
```

### Step 2: Time Series
```
Ask: "Show daily invoice count for the last 14 days"
Expected: Line chart with dates on X-axis, count on Y-axis
```

### Step 3: Distribution
```
Ask: "Show invoice distribution by status"
Expected: Pie chart with status categories and counts
```

### Step 4: Comparison
```
Ask: "Compare revenue between last month and this month"
Expected: Text response + comparison charts
```

## Monitoring Logs

### Frontend (Browser Console)
Look for:
- `🚀 API Request:` - Outgoing API calls
- `✅ API Response:` - Successful responses
- `❌ API Error:` - Failed requests
- `📊 AI Analysis Response:` - Full backend data
- `📊 Extracted Charts:` - Parsed chart array
- `📊 Has Charts:` - Boolean indicating charts present

### Backend (Terminal/Logs)
Look for:
- `📊 Attempting chart generation for query with X rows`
- `📊 Found N numeric columns: [...]`
- `📊 LLM recommended M chart(s)`
- `✅ Generated N chart(s) for user query`
- `❌ Chart generation failed:` - Error details

## Quick Fixes

### Chart Panel Not Showing
**Issue**: Charts exist in data but panel doesn't appear
**Fix**: Check `messagesWithCharts` is not empty (console.log in ChatPanel)

### Charts Show Wrong Data
**Issue**: LLM picked wrong column names
**Fix**: Backend now uses fuzzy matching (_find_matching_key) to find correct columns

### Charts Appear Then Disappear
**Issue**: State management or re-render issue
**Fix**: Charts are now keyed by message index to preserve state

### All Messages Show Same Chart
**Issue**: Was only showing last message's charts
**Fix**: Now shows all charts from all messages in conversation

## Architecture

### Data Flow
```
User Question
  ↓
Frontend (DashboardAIAnalysis.tsx)
  ↓
API (dashboardApi.postAIAnalysisChat)
  ↓
Backend (dashboard.py: /ai-analysis/chat)
  ↓
Orchestrator (ai_analysis_orchestrator.py)
  ↓
SQL Agent (sap_sql_agent.py) - Generates SQL & runs query
  ↓
Chart Generator (ai_chart_generator.py) - Analyzes results & creates chart specs
  ↓
Return to Frontend
  ↓
AIChartRenderer.tsx - Renders charts with Recharts
```

### Key Files
- **Frontend**: 
  - `zodiac-front/src/components/DashboardAIAnalysis.tsx` - Main component
  - `zodiac-front/src/components/ai/AIChartRenderer.tsx` - Chart rendering
  - `zodiac-front/src/lib/api.ts` - API client

- **Backend**:
  - `zodiac-api/app/api/dashboard.py` - API endpoints
  - `zodiac-api/app/services/ai_analysis_orchestrator.py` - Main orchestration
  - `zodiac-api/app/services/ai_chart_generator.py` - Chart generation logic
  - `zodiac-api/app/services/sap_sql_agent.py` - SQL generation

## Improvements Made

### ✅ Frontend Improvements
1. **All charts visible**: Changed from showing only last message's charts to all messages
2. **Better validation**: Added checks for undefined meta/charts
3. **Debug logging**: Added console.log statements throughout
4. **Error boundaries**: Wrapped chart rendering in try-catch
5. **Key validation**: Validate chart has required keys before rendering
6. **Metadata display**: Show action, SQL, row count, chart count under each message

### ✅ Backend Improvements
1. **Fuzzy key matching**: _find_matching_key() handles case differences and variations
2. **Better logging**: Added emoji-prefixed logs for easy debugging
3. **Fallback logic**: If exact key not found, tries partial matches
4. **Data validation**: Ensures data has required columns before creating charts
5. **Error details**: Better error messages with context

## Need More Help?

If issues persist:
1. Share the browser console logs (filter by 📊 emoji)
2. Share the backend terminal output
3. Share the exact question asked and expected vs actual behavior
