# Visual Period Display Examples

## What Changed

Query results now display a **prominent period badge** showing exactly what time range was analyzed.

## Visual Examples

### Before (No Period Information)
```
┌─────────────────────────────────────────────┐
│ AI Response                                 │
│ Revenue by customer analysis shows...       │
└─────────────────────────────────────────────┘
Action: new • SQL executed • 45 rows
⏱ 2.3s • sql: 450ms
```
❌ **Problem:** User doesn't know if this is current or historical data

### After (With Period Information)
```
┌─────────────────────────────────────────────┐
│ AI Response                                 │
│ Revenue by customer analysis shows...       │
└─────────────────────────────────────────────┘
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 📅 Last 30 days                            ┃
┃    (2026-02-07 to 2026-03-09)             ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
Action: new • SQL executed • 45 rows
⏱ 2.3s • sql: 450ms
```
✅ **Fixed:** Clear indication this is current period data

## Period Badge Variations

### 1. Current Period (Default)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 📅 Last 30 days                       ┃
┃    (2026-02-07 to 2026-03-09)        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
- Shows recent data window
- Date range updates dynamically based on query date
- Useful for real-time monitoring

### 2. Historical Period
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 📅 Historical Data (1994-2010)       ┃
┃    (1994-01-01 to 2010-12-31)        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
- Fixed date range for historical analysis
- Critical for users analyzing archived data
- Prevents confusion with current data

### 3. Both Periods (Comparison)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 📅 All Periods (1994-2026)           ┃
┃    (1994-01-01 to 2026-03-09)        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
- Includes all data from historical to present
- Useful for trend analysis across time
- Shows complete timeline

### 4. Custom Days Range
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 📅 Last 90 days                      ┃
┃    (2025-12-09 to 2026-03-09)        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
- Adapts to user-selected day range
- Shows when analyzing longer periods

## UI Placement

The period badge appears:
1. **Below the AI message content**
2. **Above the action/SQL metadata**
3. **With blue background for visibility**
4. **With calendar icon for recognition**

## Badge Styling

```css
background: blue-50        /* Light blue background */
border: blue-200           /* Subtle border */
text: blue-700             /* Dark blue text */
padding: 0.5rem            /* Comfortable spacing */
rounded: medium            /* Rounded corners */
font: monospace semibold   /* Clear, technical font */
```

## User Flow

1. User asks a question in the AI chat
2. Time scope modal appears
3. User selects period (Current/Historical/Both)
4. Query executes with selected scope
5. **Period badge appears in results** ← NEW
6. User can verify correct period was analyzed

## Use Cases

### Historical Analysis
**Query:** "What were the top revenue customers in the historical period?"
**Badge:** Historical Data (1994-2010)
**Benefit:** User confirms they're analyzing archived data, not current

### Trend Comparison
**Query:** "Compare current revenue to historical patterns"
**Badge:** All Periods (1994-2026)
**Benefit:** User sees the full time span being compared

### Recent Activity
**Query:** "Show me failed invoices"
**Badge:** Last 30 days
**Benefit:** User knows they're seeing recent failures only

### Custom Ranges
**Query:** "Revenue in the last quarter"
**Badge:** Last 90 days (with exact dates)
**Benefit:** User verifies the correct quarter was analyzed

## Technical Details

- Period info is computed on the **backend** for accuracy
- Date calculations use **server time** (not client time)
- Historical period is **fixed** (1994-2010) per business requirements
- Current period is **dynamic** based on query date
- Both periods span from **1994 to present**

## Accessibility

- Period badge has sufficient color contrast (WCAG AA compliant)
- Icon + text provides redundant information
- Monospace font ensures date alignment
- Screen readers can access the period information

## Date: March 9, 2026
