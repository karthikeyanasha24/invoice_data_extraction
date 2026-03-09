# Testing Period Information Display

## Quick Test Steps

1. **Start the backend API:**
   ```bash
   cd zodiac/zodiac-api
   python -m uvicorn app.main:app --reload --port 8000
   ```

2. **Start the frontend:**
   ```bash
   cd zodiac/zodiac-front
   npm run dev
   ```

3. **Test queries with different time scopes:**

### Test Case 1: Current Period Query
- Navigate to Dashboard → AI Analysis
- Click "Historical" tab
- Ask: "Show me revenue trends"
- Select **"Current Period"** in the modal
- **Expected Result:** Badge shows "Last 30 days" with date range

### Test Case 2: Historical Period Query  
- Ask: "What were the revenue patterns?"
- Select **"Historical Data"** in the modal
- **Expected Result:** Badge shows "Historical Data (1994-2010)" with fixed date range

### Test Case 3: Both Periods Query
- Ask: "Compare current performance to historical trends"
- Select **"Both Periods"** in the modal
- **Expected Result:** Badge shows "All Periods (1994-2026)" with full date range

### Test Case 4: Quick Action Tiles
- Click one of the quick action tiles (Forecast, Compare periods, Anomalies, Growth drivers)
- These should trigger the time scope modal
- **Expected Result:** Period badge appears based on selection

## What to Look For

### Period Badge Display
- Should appear **below the AI response message**
- Should have a **blue background** with calendar icon
- Should show **period description** (e.g., "Last 30 days")
- Should show **date range** in parentheses
- Should appear **above** the Action/SQL metadata line

### Console Logs
Open browser DevTools and check for:
```
📊 AI Analysis Response: { ..., period_info: "Last 30 days", date_range: {...} }
📊 Period Info: Last 30 days { min_date: '...', max_date: '...' }
```

## Verification Checklist

- [ ] Period badge appears for all query types
- [ ] Current period shows correct day range (e.g., "Last 30 days")
- [ ] Historical period shows "Historical Data (1994-2010)"
- [ ] Both periods shows "All Periods (1994-{current_year})"
- [ ] Date ranges are accurate and formatted correctly
- [ ] Badge styling matches the rest of the UI
- [ ] Period info persists when scrolling through chat history
- [ ] Works for both single-model and multi-model queries

## Common Issues

### Issue: Period badge not appearing
- **Check:** Browser console for period_info in the response
- **Fix:** Verify backend is running latest code
- **Debug:** Look for `time_scope`, `date_range`, `period_info` in API response

### Issue: Wrong date range
- **Check:** Time scope modal selection
- **Fix:** Ensure modal state is being passed to sendMessage
- **Debug:** Console.log the `scopeToUse` variable in sendMessage

### Issue: Badge styling looks off
- **Check:** Tailwind classes are loading
- **Fix:** Refresh browser, check for CSS conflicts
- **Debug:** Inspect element in DevTools

## API Response Example

Expected structure:
```json
{
  "reply": "Analysis results...",
  "action": "new",
  "sql": "SELECT ...",
  "rows_preview": [...],
  "charts": [...],
  "time_scope": "current",
  "date_range": {
    "min_date": "2026-02-07",
    "max_date": "2026-03-09"
  },
  "period_info": "Last 30 days",
  "performance": {...}
}
```

## Success Criteria

✅ Users can clearly see what time period each query analyzed  
✅ Historical data analysis (1994-2010) is clearly indicated  
✅ Current period shows the actual date range being queried  
✅ Period information helps users interpret trends and patterns correctly  
✅ No confusion about which data scope was used  

## Date: March 9, 2026
