# 08 — Sequence Diagrams

**Audience:** Engineers, solution architects  
**Related:** [02_INVOICE_PROCESSING_PIPELINE.md](02_INVOICE_PROCESSING_PIPELINE.md) · [04_COUNTRY_ADAPTER_FRAMEWORK.md](04_COUNTRY_ADAPTER_FRAMEWORK.md) · [07_AI_ARCHITECTURE.md](07_AI_ARCHITECTURE.md)

Unless labeled **Current (FACT)**, diagrams describe the **Proposed** target architecture. Existing V1/V2/SAT sequences remain valid for today’s traffic.

---

## 1. Invoice Processing (Proposed Happy Path)

```mermaid
sequenceDiagram
  autonumber
  participant ERP as Customer ERP
  participant API as BridgeEDI API
  participant Auth as Auth
  participant WS as Workspace
  participant Orch as Core Orchestrator
  participant Ad as Country Adapter
  participant Gov as Government API
  participant DB as PostgreSQL

  ERP->>API: Submit document
  API->>Auth: Validate credentials
  Auth-->>API: Principal OK
  API->>WS: Resolve workspace + config
  WS-->>API: Adapter country_code, ERP refs
  API->>Orch: Start pipeline(correlation_id)
  Orch->>DB: Persist intake
  Orch->>Ad: parse_and_validate
  Orch->>Ad: apply_mappings
  Orch->>Ad: apply_business_rules
  Orch->>Ad: format_outbound
  Orch->>Ad: send
  Ad->>Gov: HTTPS submit
  Gov-->>Ad: Acceptance
  Ad-->>Orch: handle_confirmation
  Orch->>ERP: Push confirmation
  Orch->>DB: Final status + audit
```

---

## 2. ERP Integration

### 2.1 Inbound (Current capabilities reused)

```mermaid
sequenceDiagram
  participant ERP as Customer ERP / SAP
  participant API as BridgeEDI
  participant Svc as V1 or V2 services
  participant DB as PostgreSQL

  ERP->>API: POST XML (JWT)
  Note over API: /invoices/sap/process or /invoices-v2/sap/receive
  API->>Svc: Process / store
  Svc->>DB: Document rows
  API-->>ERP: Accepted / tracking id
```

### 2.2 Confirmation push (Proposed)

```mermaid
sequenceDiagram
  participant Orch as Core
  participant ERPConn as ERP Connector
  participant ERP as Customer ERP
  participant DB as PostgreSQL

  Orch->>ERPConn: push_confirmation(workspace, dto)
  ERPConn->>DB: Read ERP connection + secret refs
  ERPConn->>ERP: HTTPS status update (idempotent key)
  alt OK
    ERP-->>ERPConn: 200
    ERPConn->>DB: Mark erp_push=success
  else failure
    ERP-->>ERPConn: 5xx / timeout
    ERPConn->>DB: Schedule retry / DLQ
  end
```

---

## 3. Government Integration (Proposed)

```mermaid
sequenceDiagram
  participant Ad as Country Adapter
  participant HTTP as Shared HTTP helper
  participant Gov as Government API
  participant DB as PostgreSQL

  Ad->>HTTP: send(payload, auth_strategy)
  HTTP->>Gov: POST /documents
  alt Accepted
    Gov-->>HTTP: 200 + confirmation id
    HTTP-->>Ad: SendResult(ok)
    Ad->>DB: Store confirmation
  else Business reject
    Gov-->>HTTP: 422 + reason
    HTTP-->>Ad: SendResult(reject)
    Ad->>DB: Store reject reason
  else Transient
    Gov-->>HTTP: 503
    HTTP-->>Ad: Retryable error
  end
```

### 3.1 Current Mexico outbound (FACT) — SAP billing, not SAT.gov PAC

```mermaid
sequenceDiagram
  participant UI as Admin / API
  participant SAT as SAT routers
  participant X as sap_transformer
  participant SAP as sap_api_client
  participant DB as DB

  UI->>SAT: send-to-sap
  SAT->>X: Build SAP JSON
  X->>SAP: CSRF + POST billing_integration
  SAP-->>X: Response
  X->>DB: sap_response / doc number
```

---

## 4. Customer Workspace

```mermaid
sequenceDiagram
  participant Admin as BridgeEDI Admin
  participant API as Workspace API
  participant DB as PostgreSQL
  participant User as Customer user
  participant UI as Workspace UI

  Admin->>API: Create workspace settings for customer
  API->>DB: Insert workspace_* rows
  Admin->>API: Attach ERP + enable adapters
  API->>DB: Save connections / adapter_config
  User->>UI: Login (JWT)
  UI->>API: List workspace transactions
  API->>DB: Filtered by customer_id / workspace_id
  DB-->>UI: Isolated dataset
```

---

## 5. Adapter Selection

```mermaid
sequenceDiagram
  participant Orch as Orchestrator
  participant WS as Workspace Config
  participant Reg as AdapterRegistry
  participant MX as MxCfdiAdapter
  participant IN as IndiaAdapter

  Orch->>WS: get_enabled_country(doc)
  WS-->>Orch: "india"
  Orch->>Reg: resolve("india")
  Reg-->>Orch: IndiaAdapter
  Note over MX: Not invoked
  Orch->>IN: execute hooks
```

---

## 6. AI Analytics

```mermaid
sequenceDiagram
  participant U as User
  participant UI as AI UI
  participant AQ as Adaptive Query API
  participant Guard as Workspace guard
  participant Agent as SQL / Chart agent
  participant LLM as LLM Provider
  participant DB as PostgreSQL

  U->>UI: Natural language question
  UI->>AQ: POST /api/query/adaptive (+ workspace_id)
  AQ->>Guard: Enforce tenant predicate
  AQ->>Agent: Plan query
  Agent->>LLM: Generate SQL / narrative
  Agent->>DB: Execute constrained SQL
  DB-->>Agent: Rows
  Agent-->>UI: Answer + chart specs
  UI-->>U: Render
```

**Note:** AI reads operational data; it does not call Government send APIs.

---

## 7. Error Handling

```mermaid
sequenceDiagram
  participant Orch as Orchestrator
  participant Ad as Adapter
  participant DB as PostgreSQL
  participant Mon as Monitoring

  Orch->>Ad: parse_and_validate
  Ad-->>Orch: ValidationError(code, message)
  Orch->>DB: status=failed, error_payload
  Orch->>Mon: Emit failure event
  Orch-->>Orch: Stop before send
  Note over Orch: No government call on validation failure
```

---

## 8. Retry

```mermaid
sequenceDiagram
  participant W as Worker
  participant Out as Outbox
  participant Ad as Adapter
  participant Gov as Government API
  participant DLQ as Dead Letter Queue

  W->>Out: Claim job attempt=n
  W->>Ad: send
  Ad->>Gov: POST
  Gov-->>Ad: 503
  Ad-->>W: retryable
  alt n < max
    W->>Out: defer(backoff)
  else n >= max
    W->>DLQ: move job
    W->>Out: mark dead
  end
```

**Current:** Many retries are manual (UI send-all / reprocess). Durable worker retry is **Proposed**.

---

## 9. Confirmation Flow (End-to-End Proposed)

```mermaid
sequenceDiagram
  participant Gov as Government API
  participant Ad as Adapter
  participant Orch as Core
  participant ERP as Customer ERP
  participant DB as DB
  participant AI as AI / Dashboard

  Gov-->>Ad: Confirmation payload
  Ad->>Ad: handle_confirmation (normalize)
  Ad->>Orch: Confirmation DTO
  Orch->>DB: Persist confirmation
  Orch->>ERP: Push status update
  ERP-->>Orch: ACK
  Orch->>DB: erp_push=success
  Orch->>AI: Event visible for analytics
```

---

## 10. Current V1 EDI Path (FACT) — Reference

```mermaid
sequenceDiagram
  participant C as Client
  participant INV as /invoices/*
  participant PS as process_service
  participant FR as format_router
  participant EXT as external_api_service
  participant ST as status_tracker

  C->>INV: process upload
  INV->>ST: tracking_id (memory)
  INV->>PS: background process
  PS->>FR: choose format path
  FR->>EXT: PeppolSoft if needed
  PS->>ST: update stages
  C->>INV: poll status
```

---

*Document: `docs/architecture/08_SEQUENCE_DIAGRAMS.md`*
