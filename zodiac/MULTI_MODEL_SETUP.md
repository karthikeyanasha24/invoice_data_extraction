# 🧠 Multi-Model AI Setup

Upgraded AI analysis to support **GPT-4, Claude 3.5, Gemini 1.5 Pro, and OpenRouter** for deeper business insights.

---

## 🎯 What Changed

### Before:
- Used `gpt-4o-mini` for all AI responses
- Basic summaries with limited depth
- No model flexibility

### After:
- **Powerful models** for final insights (GPT-4, Claude, Gemini)
- **Fast model** for quick operations (action classification, table selection)
- **Unified multi-provider client** supporting all major AI providers
- **Automatic fallback** to OpenAI if preferred model fails

---

## 📊 AI Model Architecture

```
┌─────────────────────────────────────────┐
│         User Query                      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   FAST MODEL (gpt-4o-mini)              │
│   - Action classification               │
│   - Table selection                     │
│   - Quick operations                    │
└──────────────┬──────────────────────────┘
               │
               ▼
        Execute SQL Query
               │
               ▼
┌─────────────────────────────────────────┐
│   INSIGHTS MODEL (configurable)         │
│   Options:                              │
│   • GPT-4o         (best reasoning)     │
│   • Claude 3.5     (excellent analysis) │
│   • Gemini 1.5 Pro (great insights)     │
│   • OpenRouter     (any model)          │
│                                         │
│   Generates:                            │
│   - Executive summaries                 │
│   - Detailed analysis                   │
│   - Business insights                   │
│   - Actionable recommendations          │
└─────────────────────────────────────────┘
```

---

## 🔧 Configuration

### 1. Add API Keys to `.env`

```bash
# OpenAI (required for fast operations)
OPEN_AI_KEY=sk-...

# Optional: Add ONE or more of these for better insights
GOOGLE_API_KEY=AIza...           # For Gemini models
ANTHROPIC_API_KEY=sk-ant-...     # For Claude models
OPENROUTER_API_KEY=sk-or-...     # For OpenRouter (any model)

# Choose your insights model
AI_INSIGHTS_MODEL=gpt-4o                    # Best reasoning (default)
# AI_INSIGHTS_MODEL=claude-3-5-sonnet       # Excellent analysis
# AI_INSIGHTS_MODEL=gemini-1.5-pro          # Great insights, lower cost
# AI_INSIGHTS_MODEL=gemini-1.5-flash        # Fast and cheap

AI_FAST_MODEL=gpt-4o-mini  # For quick operations
```

### 2. Supported Models

#### OpenAI
- `gpt-4o` - Best reasoning and analysis ($$$)
- `gpt-4o-mini` - Fast and balanced ($$)
- `gpt-4-turbo` - Previous generation
- `o1-preview` - Advanced reasoning

#### Anthropic Claude
- `claude-3-5-sonnet-20241022` - Latest, excellent business analysis ($$$)
- `claude-3-opus-20240229` - Most capable
- `claude-3-sonnet-20240229` - Balanced
- `claude-3-haiku-20240307` - Fast ($)

#### Google Gemini
- `gemini-1.5-pro-latest` - Great insights, 2M context window ($$)
- `gemini-1.5-flash-latest` - Very fast, good quality ($)
- `gemini-1.0-pro` - Basic model

#### OpenRouter (any model)
```bash
AI_INSIGHTS_MODEL=openrouter/anthropic/claude-3.5-sonnet
AI_INSIGHTS_MODEL=openrouter/google/gemini-pro-1.5
AI_INSIGHTS_MODEL=openrouter/meta-llama/llama-3.1-405b
```

---

## 💰 Cost Comparison (per 1M tokens)

| Model | Input | Output | Quality | Speed |
|-------|-------|--------|---------|-------|
| GPT-4o | $2.50 | $10.00 | ⭐⭐⭐⭐⭐ | ⚡⚡⚡ |
| GPT-4o-mini | $0.15 | $0.60 | ⭐⭐⭐ | ⚡⚡⚡⚡ |
| Claude 3.5 Sonnet | $3.00 | $15.00 | ⭐⭐⭐⭐⭐ | ⚡⚡⚡ |
| Gemini 1.5 Pro | $1.25 | $5.00 | ⭐⭐⭐⭐ | ⚡⚡⚡⚡ |
| Gemini 1.5 Flash | $0.08 | $0.30 | ⭐⭐⭐ | ⚡⚡⚡⚡⚡ |

**Recommended setup:**
- **Best insights**: `AI_INSIGHTS_MODEL=gpt-4o` or `claude-3-5-sonnet`
- **Balanced**: `AI_INSIGHTS_MODEL=gemini-1.5-pro` (80% quality, 50% cost)
- **Budget**: `AI_INSIGHTS_MODEL=gemini-1.5-flash` (70% quality, 5% cost)

---

## 📝 Enhanced Insights Format

The powerful models generate **structured business insights** with:

### 1. Executive Summary
- Most critical finding upfront
- Key metrics in bold with currency symbols

### 2. Detailed Analysis
- Organized with subheadings
- Breakdown by dimensions (time, geography, category)
- Trend identification and pattern recognition
- Comparisons vs benchmarks

### 3. Key Insights
- Surprising or notable findings
- Business context and implications
- Risk and opportunity identification

### 4. Actionable Recommendations
- Specific actions for leadership
- Prioritized by business impact
- Practical and implementable

---

## 🧪 Testing Different Models

### Test Query:
```
show me sales by industry and customer for 2024
```

### GPT-4o Response Example:
```markdown
### Executive Summary
Total sales for 2024 reached **$523.5M**, with Trading & Distribution 
dominating at **$522.5M (99.8%)** of total revenue.

#### Industry Breakdown
...detailed analysis with percentages and insights...

> **Key Recommendation**: Focus growth efforts on underperforming sectors 
> (Services, Healthcare) while maintaining Trading excellence.
```

### Claude 3.5 Response Example:
```markdown
### Sales Performance Analysis: 2024

**Primary Finding**: Trading sector shows exceptional concentration...
...deeper strategic analysis with business implications...
```

### Gemini 1.5 Pro Response Example:
```markdown
### 2024 Sales Analysis by Industry & Customer

The data reveals significant concentration risk...
...analytical insights with actionable steps...
```

---

## 🔄 Automatic Fallback

If your configured model fails (API error, rate limit, invalid key):
1. System automatically falls back to OpenAI `gpt-4o-mini`
2. Logs warning in terminal
3. Analysis continues without interruption

```
⚠️ Failed to use claude-3-5-sonnet, falling back to OpenAI: API key not configured
```

---

## 🚀 Installation

### Install Required Packages:

```bash
cd zodiac-api

# For Anthropic Claude
pip install anthropic>=0.18.0

# For Google Gemini
pip install google-generativeai>=0.8.0

# OpenRouter uses OpenAI client (already installed)
```

**Note**: Packages are already in `requirements.txt`!

---

## 📊 Performance Impact

| Operation | Model | Time | Cost per Query |
|-----------|-------|------|----------------|
| Action Classification | gpt-4o-mini | ~200ms | $0.0001 |
| Table Selection | gpt-4o-mini | ~300ms | $0.0002 |
| **Insights Generation** | **gpt-4o** | ~2-3s | **$0.02** |
| **Insights Generation** | **claude-3-5** | ~2-4s | **$0.03** |
| **Insights Generation** | **gemini-1.5-pro** | ~1-2s | **$0.01** |
| **Insights Generation** | **gpt-4o-mini** | ~1s | **$0.001** |

**Total query time**: 3-7 seconds (most time is SQL execution)
**Cost increase**: ~$0.01-0.03 per query for premium insights

---

## ✅ Verification

### Check Current Configuration:
```bash
# Terminal will show:
💡 Generated insights using gpt-4o
💡 Generated insights using claude-3-5-sonnet
💡 Generated insights using gemini-1.5-pro
```

### Test API Keys:
```python
# In zodiac-api directory
python -c "
from app.services.multi_llm_client import get_multi_llm_client
client = get_multi_llm_client()
print('OpenAI:', client.openai_key[:20] + '...' if client.openai_key else 'Not set')
print('Anthropic:', client.anthropic_key[:20] + '...' if client.anthropic_key else 'Not set')
print('Google:', client.google_key[:20] + '...' if client.google_key else 'Not set')
print('OpenRouter:', client.openrouter_key[:20] + '...' if client.openrouter_key else 'Not set')
"
```

---

## 🎓 Best Practices

1. **Start with GPT-4o**: Best balance of quality and reliability
2. **Try Claude for finance**: Excellent at interpreting business data
3. **Use Gemini for scale**: Great quality-to-cost ratio
4. **Keep gpt-4o-mini for fast ops**: Don't change `AI_FAST_MODEL`
5. **Monitor costs**: Check OpenAI/Anthropic/Google dashboards
6. **Test with same query**: Compare model responses side-by-side

---

## 🐛 Troubleshooting

### Model Not Working?
1. Check API key is set in `.env`
2. Verify package is installed (`pip list | grep anthropic`)
3. Check terminal logs for error messages
4. System will auto-fallback to gpt-4o-mini

### Want to Test a Model?
```bash
# Set in .env
AI_INSIGHTS_MODEL=gemini-1.5-pro

# Restart server
# (Ctrl+C then run again)

# Ask any query, check terminal for:
💡 Generated insights using gemini-1.5-pro
```

### Compare Responses:
Ask the same question 3 times with different `AI_INSIGHTS_MODEL` values to see quality differences.

---

## 📚 Next Steps

1. ✅ Add your preferred model's API key to `.env`
2. ✅ Set `AI_INSIGHTS_MODEL` in `.env`
3. ✅ Restart the backend server
4. ✅ Test with a complex query (e.g., "analyze sales trends by industry")
5. ✅ Compare response quality and depth
6. ✅ Monitor costs in provider dashboards

**Recommended**: Start with `gemini-1.5-pro` for best cost/quality balance!

---

*The system will automatically use your configured model for insights while keeping fast operations efficient with gpt-4o-mini.*
