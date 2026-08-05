# Sample Data — First Customer Demo

Use **existing** fixture files under `zodiac-api/` (do not invent new formats).

## Recommended demo invoices

| File | Use |
|------|-----|
| `zodiac-api/test_invoice_001.xml` | Generic invoice smoke |
| `zodiac-api/test_invoice_simple.xml` | Short happy-path upload |
| `zodiac-api/test_files/TEC940201K89_INVOICE.xml` | Mexico-style supplier invoice demo |
| `zodiac-api/test_files/TEC940201K89_CREDIT_NOTE.xml` | Credit note path |
| `zodiac-api/test_files/TEC940201K89_PAYMENT.xml` | Payment complement |
| `zodiac-api/test_cfdi_output.xml` | CFDI-shaped output discussion |

## Demo customer (staging only)

| Field | Suggested value |
|-------|-----------------|
| `customer_id` | `DEMO_PILOT_MX` (or real pilot ID) |
| Display name | Pilot customer legal name |
| Country adapter | `mx_cfdi` |
| ERP `connection_key` | `primary` |
| `erp_update_mode` | `auto` |
| Government endpoint | Customer **sandbox** URL or mock HTTPS |

## Secret refs (examples — not real secrets)

```text
env:PILOT_ERP_TOKEN
env:PILOT_GOV_TOKEN
# or
vault:pilot/erp/token
```

Set matching env vars on the API host before demo.

## Do not demo in production

- `sample_gst` adapter as a customer-facing path  
- `SECRET_RESOLVER=literal`  
- `CORS_ALLOW_ALL=true`  
- Placeholder `SECRET_KEY`
