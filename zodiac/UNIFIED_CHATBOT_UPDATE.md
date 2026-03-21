# Unified Chatbot for "Both" Mode - Implementation Summary

**Date:** March 20, 2026  
**Status:** ✅ Complete

## Overview

Updated the AI Generative Page's "Both" mode to use a single unified chatbot instead of two separate chat panels. This simplifies the user experience and allows for queries that span both realtime and historical data simultaneously.

## What Changed

### Previous Design
- **Both Mode**: Showed two separate chat panels side-by-side
  - Left panel: Realtime chat (only queries realtime data)
  - Right panel: Historical chat (only queries historical data)
  - Each panel had its own message history and loading state

### New Design
- **Both Mode**: Single unified chat panel that queries both data types together
  - Top section: Grid layout showing both realtime and historical data panels
  - Bottom section: One unified AI chat that can query both datasets simultaneously
  - Single message history for combined analysis
  - Better for cross-cutting queries like "Compare realtime operations with historical trends"

## Technical Implementation

### 1. State Management
Added new state variables for unified chat:

```typescript
// New state for unified "both" messages
const [bothMessages, setBothMessages] = useState<Message[]>([]);
const [bothLoading, setBothLoading] = useState(false);
```

### 2. Type Updates
Updated type definitions to support "both" as a section:

```typescript
// Message type
type Message = {
  role: 'user' | 'assistant';
  content: string;
  meta?: AiAnalysisMeta;
  section?: 'realtime' | 'historical' | 'both';  // Added 'both'
  ts?: number;
};

// ChatPanel component
function ChatPanel({
  section: 'realtime' | 'historical' | 'both';  // Added 'both'
  // ... other props
})

// sendMessage function
const sendMessage = async (section: 'realtime' | 'historical' | 'both', text: string)
```

### 3. Context Key Handling
Updated `getContextKeys` to handle unified chat:

```typescript
const getContextKeys = (
  mode: 'realtime' | 'historical' | 'both', 
  section: 'realtime' | 'historical' | 'both'
): string[] => {
  if (!useContext) return [];
  
  if (mode === 'realtime' || (mode === 'both' && section === 'realtime')) {
    return ['stats', 'failed_summary', 'top_customers', 'inbound_summary', 'process_flow'];
  }
  if (mode === 'historical' || (mode === 'both' && section === 'historical')) {
    return ['business_summary'];
  }
  // For 'both' section (unified chat), return all keys
  return AI_CONTEXT_KEYS;
};
```

### 4. UI Layout
The "Both" mode now has a cleaner structure:

```
┌─────────────────────────────────────────────────────┐
│ 🟣 Unified Analysis Header (Realtime + Historical) │
├──────────────────┬──────────────────────────────────┤
│ 🔵 Realtime Data │ 🟣 Historical Data              │
│                  │                                  │
│ Collapsible      │ Revenue Cards                    │
│ Dashboard        │ By Customer / By Country Charts  │
│                  │                                  │
├──────────────────┴──────────────────────────────────┤
│ 💬 Unified AI Chat (Full Width)                    │
│                                                     │
│ [Compare All] [Forecast] [Overview] [Anomalies]    │
│                                                     │
│ Chat messages...                                    │
│ Input field...                                      │
└─────────────────────────────────────────────────────┘
```

### 5. Quick Action Queries
Added unified quick action buttons:

1. **Compare All**: "Compare realtime operations with historical trends"
2. **Forecast**: "Based on historical data and current operations, forecast next period performance"
3. **Full Overview**: "Give me a comprehensive overview of both realtime and historical data"
4. **Anomalies**: "Identify any anomalies or unusual patterns across both realtime and historical data"

### 6. Time Scope Handling
When section is 'both', the backend automatically receives `timeScope: 'both'` which:
- Queries both current/realtime data AND historical (1994-2010) data
- Provides comprehensive analysis across both datasets
- The AI model receives context from all data sources

## Files Modified

### Frontend
- `zodiac-front/src/components/DashboardAIAnalysis.tsx`
  - Added `bothMessages` and `bothLoading` state
  - Updated type definitions for Message, ChatPanel, sendMessage
  - Updated `getContextKeys` to handle 'both' section
  - Completely rewrote "Both" mode UI layout
  - Added unified chat panel with combined quick actions

## User Benefits

1. **Simpler Interface**: One chat instead of two reduces cognitive load
2. **Better Cross-Analysis**: Can ask questions that span both data types naturally
3. **Cleaner Layout**: Data panels on top, single chat at bottom
4. **More Context**: AI receives all context keys when in unified mode
5. **Mobile Friendly**: Single chat is easier to use on small screens

## Backend Compatibility

The backend already supports `timeScope: 'both'` from the previous implementation:
- ✅ `postAIAnalysisChat()` accepts 'both' time scope
- ✅ `postAIAnalysisMultiModel()` accepts 'both' time scope
- ✅ Backend queries both realtime and historical data sources
- ✅ AI receives combined context from all relevant tables

## Testing

To test the unified chatbot:

1. Navigate to AI Generative page
2. Select "Both" view mode (radio button at top)
3. Observe:
   - Left side shows realtime dashboard (collapsible)
   - Right side shows historical cards and charts
   - Bottom has single unified AI chat with purple accent
4. Try queries:
   - "Compare current performance with historical trends"
   - "What patterns do you see across all our data?"
   - "Forecast next period based on everything"
5. Verify:
   - AI responses consider both realtime and historical context
   - Loading states work correctly
   - Message history persists during session
   - Multi-model toggle works (if enabled)

## Next Steps (Optional Enhancements)

- Add visual indicators in chat messages to show which data source was used
- Add tabs/sections within unified chat to organize long conversations
- Add export functionality for unified analysis reports
- Add saved query templates for common cross-dataset analyses

---

**Status**: ✅ **Implementation Complete and Ready to Use**
