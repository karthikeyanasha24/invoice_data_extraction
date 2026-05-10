from __future__ import annotations

import logging
import json
import operator
from typing import Any, Dict, List, Optional, Tuple, Annotated, TypedDict

from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from .schema_intelligence import schema_intelligence
# from .sap_sql_precision_validator import _validate_sql_candidate

logger = logging.getLogger("zodiac-api.multi_stage_planner")

# ERP RULES (Ported from reference architecture)
ERP_SQL_RULES = """
══ ERP T-SQL RULES — ALL MANDATORY ══

1. Use ONLY column names that appear in the provided schema — never guess or invent columns.
2. DATE ARITHMETIC (critical for time-range queries)
   - Date columns are often strings or datetimes — always CAST to date before comparison.
   - SAP date fields may be stored as YYYYMMDD text (example: fkdat). In PostgreSQL, parse with to_date(col, 'YYYYMMDD') before filtering/grouping.
   - For "monthly trend", bucket with date_trunc('month', parsed_date) and output YYYY-MM.
3. JOINS (always explicit — direction depends on the question)
   - Normal ranking / top products / invoices (sales rows drive the grain): INNER JOIN or LEFT JOIN.
   - NEVER use implicit cross joins (missing ON clause).
4. RESULT SIZE
   - Non-aggregate SELECT → MUST include TOP (N) or LIMIT N.
   - "Top 10" questions → LIMIT 10 ... ORDER BY metric DESC.
5. NULL SAFETY
   - Wrap nullable numeric cols.
6. FORMAT
   - No semicolons at end.
   - Always alias all aggregates: SUM(x) AS TotalX, COUNT(*) AS TxnCount.
   - Always include ORDER BY for trend/ranking queries.
   - Column aliases must not contain spaces (use CamelCase or underscore).
   - PostgreSQL requires quotes for uppercase table names. You MUST quote tables like "EKKO", "EKPO" or PostgreSQL will convert them to lowercase and fail to find the table.
   - VERY IMPORTANT: In PostgreSQL, all SAP column names are LOWERCASE. You MUST use lowercase for all column names (e.g. "EKKO"."ebeln", "EKPO"."netwr", "EKKO"."lifnr"). Do NOT use uppercase column names.
7. GROUPING AND AGGREGATION (CRITICAL)
   - Every non-aggregate SELECT column must appear in GROUP BY.
   - When asked for "Top N vendors/customers/products" or similar ranking, you MUST group by the entity ID/Name and aggregate the metric (e.g., SUM(netwr) AS TotalAmount). DO NOT select all columns and just append LIMIT.
   - Example for Top 5 Vendors by Purchase Order Value:
     SELECT "EKKO".lifnr AS Vendor, SUM("EKPO".netwr) AS TotalOrderValue FROM "EKKO" INNER JOIN "EKPO" ON "EKKO".ebeln = "EKPO".ebeln GROUP BY "EKKO".lifnr ORDER BY TotalOrderValue DESC LIMIT 5
8. MASTER DATA FOR READABLE RESULTS (when user asks customers, vendors, materials, products, or industry context)
   - Include BOTH technical key AND description/name in SELECT when schema lists those columns.
   - Customers (sold-to / payer): JOIN "KNA1" ON "KNA1".kunnr = <customer key from fact table>; SELECT kunnr plus name1 (and brsch for industry if needed).
   - Materials: JOIN "MAKT" ON "MAKT".matnr = <material from lines> AND spras = 'E' (or appropriate language); SELECT matnr plus maktx.
   - Vendors: JOIN "LFA1" ON "LFA1".lifnr = <vendor from PO/header>.
9. NEVER generate DROP, DELETE, UPDATE, INSERT, ALTER statements. READ ONLY.
"""

def _extract_sql(text: str) -> str:
    if not text:
        return ""
    import re
    # Try to find markdown fences
    fenced = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    # Otherwise just strip and return
    return text.strip()


def _build_monthly_billing_revenue_sql_if_applicable(question: str) -> str:
    """Deterministic fallback for monthly VBRK billing trend queries."""
    q = (question or "").lower()
    if "monthly" not in q:
        return ""
    if "billing" not in q and "revenue" not in q:
        return ""
    if "past year" not in q and "last year" not in q and "12 month" not in q:
        return ""

    # SAP extracts often store FKDAT as YYYYMMDD text; parse safely before filtering.
    return """
SELECT
  to_char(date_trunc('month', to_date("VBRK".fkdat, 'YYYYMMDD')), 'YYYY-MM') AS billing_month,
  SUM(COALESCE(CAST("VBRK".netwr AS numeric), 0)) AS total_billing_revenue,
  "VBRK".waerk AS currency
FROM "VBRK"
WHERE "VBRK".fkdat IS NOT NULL
  AND "VBRK".fkdat ~ '^[0-9]{8}$'
  AND to_date("VBRK".fkdat, 'YYYYMMDD') >= (CURRENT_DATE - INTERVAL '12 months')
GROUP BY date_trunc('month', to_date("VBRK".fkdat, 'YYYYMMDD')), "VBRK".waerk
ORDER BY billing_month
""".strip()

# State Schema
class AgentState(TypedDict):
    question: str
    date_context: str
    table_hint: Optional[str]
    user_date_range: Dict[str, str]

    top_views: List[str]
    schema_text: str

    sample_text: str

    generated_sql: str
    checked_sql: str
    execution_result: Dict[str, Any]
    retry_count: int
    retry_errors: Annotated[List[str], operator.add]
    zero_rows_retried: bool

    rag_context: str

    final_answer: str
    final_data: List[Dict[str, Any]]
    final_sql: str
    confidence: str
    confidence_note: str
    
    node_log: Annotated[List[str], operator.add]
    chart_policy: Optional[str]
    conversation_history: List[Dict[str, Any]]

class LangGraphPlanner:
    def __init__(self, db: Session, api_key: str):
        self.db = db
        self.api_key = api_key
        # temperature=0 for SQL determinism
        self.llm_sql = ChatOpenAI(api_key=api_key, model="gpt-4o", temperature=0, max_tokens=2048)
        # temperature=0.2 for natural language answer
        self.llm_answer = ChatOpenAI(api_key=api_key, model="gpt-4o", temperature=0.2, max_tokens=1024)

    def load_schema(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: load_schema")
        
        # Use schema_intelligence to resolve tables
        from app.services.explicit_table_sql import extract_explicit_table_identifiers, strip_generative_client_routing_block
        
        # 1. Strip the [ZODIAC_GENERATIVE_CLIENT_ROUTING] block first
        clean_query = strip_generative_client_routing_block(state["question"])
        
        # 2. Try to get explicit tables (like EKKO, EKPO)
        explicit_ids = extract_explicit_table_identifiers(clean_query)
        tables = []
        
        if explicit_ids:
            for t_name in explicit_ids:
                t_obj = schema_intelligence.tables.get(t_name) or schema_intelligence.tables.get(t_name.upper())
                if t_obj:
                    tables.append(t_obj)
                    
        # 3. If no explicit tables found, use semantic resolution
        if not tables:
            tables = schema_intelligence.resolve_entities(clean_query)
            
        if not tables:
            # Fallback to some generic tables if intent resolution fails
            table_names = ["VBRK", "VBRP", "KNA1", "MARA"]
            tables = [schema_intelligence.tables.get(t) for t in table_names if t in schema_intelligence.tables]
            
        schema_text_lines = []
        top_views = []
        for t in tables:
            if not t: continue
            top_views.append(t.name)
            cols = [f"  {c.name} ({c.data_type})" for c in t.columns.values()]
            schema_text_lines.append(f"\n{t.name}:")
            schema_text_lines.extend(cols)
            
        schema_text = "\n".join(schema_text_lines)
        return {
            "top_views": top_views,
            "schema_text": schema_text,
            "node_log": ["load_schema"]
        }

    def retrieve_context(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: retrieve_context (RAG)")
        # In a full implementation, we'd query FAISS/Chroma here.
        # For now, we mock the retrieval.
        return {
            "rag_context": "",
            "node_log": ["retrieve_context"]
        }

    def generate_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: generate_sql")
        
        retry_guidance = ""
        if state.get("retry_count", 0) > 0 and state.get("retry_errors"):
            retry_guidance = f"\n\n══ PREVIOUS ERRORS — do NOT repeat these mistakes ══\n" + "\n".join(state["retry_errors"])

        system_prompt = f"""You are a SQL expert for an SAP ERP system.
Write ONE valid SQL SELECT statement that answers the user's question.
Use ONLY column names that appear in the provided schema — never guess or invent columns.
{ERP_SQL_RULES}
Output ONLY the SQL — no explanation, no markdown fences, no semicolons at end."""

        user_prompt = f"""[SCHEMA — ONLY use columns listed here]
{state.get('schema_text', '')}

[CONVERSATION HISTORY]
{chr(10).join([f"{msg['role'].upper()}: {msg['content']}" for msg in state.get('conversation_history', [])]) if state.get('conversation_history') else "No previous conversation."}

[QUESTION]
{state['question']}
{retry_guidance}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        sql = _extract_sql(response.content)
        return {"generated_sql": sql, "node_log": ["generate_sql"]}

    def check_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: check_sql")
        # Perform both LLM-based check and deterministic validator check
        system_prompt = f"""You are a SQL code reviewer for SAP data.
Your job is to FIX BUGS without changing the intent or scope of the query.
══ ABSOLUTE DO-NOT-CHANGE RULES ══
1. NEVER change FROM table name or JOIN table name.
2. NEVER increase TOP N if the user asked for a specific number.
3. NEVER remove or change a JOIN that already has a valid ON clause.
4. PostgreSQL requires quotes for uppercase table names. You MUST quote tables like "EKKO", "EKPO" or PostgreSQL will convert them to lowercase and fail to find the table.
5. VERY IMPORTANT: In PostgreSQL, all SAP column names are LOWERCASE. You MUST use lowercase for all column names (e.g. "EKKO"."ebeln", "EKPO"."netwr").

{ERP_SQL_RULES}

Output ONLY the SQL — no explanation, no markdown fences."""

        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

[SQL TO REVIEW]
{state.get('generated_sql', '')}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        checked_sql = _extract_sql(response.content)
        
        # Now run through deterministic validator
        # Note: In dashboard.py, _validate_sql_candidate is already called after the payload is returned.
        # So we skip running it here to avoid circular imports.
        # validation, blocking_detail = _validate_sql_candidate(self.db, state["question"], checked_sql)
        # if blocking_detail:
        #     logger.warning(f"[langgraph] deterministic validation blocking: {blocking_detail}")
            
        return {"checked_sql": checked_sql, "node_log": ["check_sql"]}

    def execute_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: execute_sql")
        sql = state.get("checked_sql") or state.get("generated_sql")
        
        result_data = []
        error_msg = ""
        
        # Hard firewall for DML/DDL just in case
        if any(bad in sql.upper() for bad in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER"]):
            error_msg = "Unsafe DML/DDL detected."
        else:
            try:
                result = self.db.execute(text(sql))
                result_data = [dict(row) for row in result.mappings().all()]
            except Exception as e:
                error_msg = str(e)
                try:
                    self.db.rollback()
                except Exception:
                    pass
                
        execution_result = {"error": error_msg, "data": result_data, "row_count": len(result_data)}
        
        return {
            "execution_result": execution_result,
            "final_sql": None if error_msg else sql,
            "final_data": [] if error_msg else result_data,
            "node_log": ["execute_sql"]
        }

    def error_recovery(self, state: AgentState) -> Dict[str, Any]:
        attempt = state.get("retry_count", 0) + 1
        err_msg = state.get("execution_result", {}).get("error", "unknown error")
        failed_sql = state.get("checked_sql") or state.get("generated_sql")
        logger.info(f"[langgraph] node: error_recovery attempt {attempt}, error: {err_msg}")
        
        system_prompt = f"""You are a SQL debugger. A query failed with the error shown. Fix the SQL so it executes without error.
Study the error carefully.
PostgreSQL requires quotes for uppercase table names. You MUST quote tables like "EKKO", "EKPO" or PostgreSQL will convert them to lowercase and fail to find the table.
VERY IMPORTANT: In PostgreSQL, all SAP column names are LOWERCASE. You MUST use lowercase for all column names (e.g. "EKKO"."ebeln", "EKPO"."netwr").
{ERP_SQL_RULES}
Output ONLY the corrected SQL — no explanation."""

        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

[FAILED SQL]
{failed_sql}

[DB ERROR]
{err_msg}

Fix the SQL."""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        fixed_sql = _extract_sql(response.content)
        return {
            "checked_sql": fixed_sql,
            "generated_sql": fixed_sql,
            "retry_count": attempt,
            "retry_errors": [f"Attempt {attempt}: {err_msg}"],
            "node_log": ["error_recovery"]
        }

    def zero_rows_recovery(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: zero_rows_recovery")
        deterministic_sql = _build_monthly_billing_revenue_sql_if_applicable(state.get("question", ""))
        if deterministic_sql:
            logger.info("[langgraph] zero_rows_recovery: applying deterministic monthly billing fallback")
            return {
                "generated_sql": deterministic_sql,
                "checked_sql": deterministic_sql,
                "zero_rows_retried": True,
                "node_log": ["zero_rows_recovery"]
            }

        system_prompt = f"""You are a SQL expert. A query returned 0 rows.
Common causes: date range too narrow, filter value misspelled.
Fix the query so it returns data.
{ERP_SQL_RULES}
Output ONLY the corrected SQL."""

        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

[ZERO-ROW QUERY — widen date range or relax filters]
{state.get('checked_sql') or state.get('generated_sql')}

Hint: remove or widen date filters; if filtering by name, try removing the filter."""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        fixed_sql = _extract_sql(response.content)
        return {
            "generated_sql": fixed_sql,
            "checked_sql": fixed_sql,
            "zero_rows_retried": True,
            "node_log": ["zero_rows_recovery"]
        }

    def generate_answer(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: generate_answer")
        rows = state.get("final_data", [])
        
        if not rows:
            err = state.get("execution_result", {}).get("error")
            msg = f"Could not retrieve data due to error: {err}" if err else "No matching records found. Try widening filters."
            return {
                "final_answer": msg,
                "confidence": "low",
                "confidence_note": "0 rows returned",
                "node_log": ["generate_answer"]
            }
            
        sample = json.dumps(rows[:20], default=str)
        system_prompt = """You are a business intelligence analyst for an ERP system.
Summarize the query results in 2-5 plain English sentences.
Rules:
- Lead with the single most important number or finding.
- Use standard number formatting with commas.
- Be precise — include actual numbers from the data, not vague descriptions.
- If there are totals/sums in the data, state them prominently.
- If the data shows a trend, describe the direction clearly.
- Do NOT mention SQL, database, columns, or technical details.
- Speak directly ("Total sales were...", "Revenue is...")."""

        user_prompt = f"""[QUESTION]
{state['question']}

[DATA — {len(rows)} row(s)]
{sample}"""

        response = self.llm_answer.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        return {
            "final_answer": response.content,
            "confidence": "high",
            "node_log": ["generate_answer"]
        }

    def verify_answer(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: verify_answer")
        rows = state.get("final_data", [])
        if not state.get("final_answer") or not rows:
            return {"node_log": ["verify_answer"]}
            
        sample = json.dumps(rows[:20], default=str)
        system_prompt = """You are a fact-checker.
Verify every number in the answer is correct according to the data.
If a number is wrong, silently correct it.
Respond ONLY with the (possibly corrected) answer text."""

        user_prompt = f"""[ANSWER TO VERIFY]
{state['final_answer']}

[ACTUAL DATA]
{sample}"""

        response = self.llm_answer.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        return {
            "final_answer": response.content.strip(),
            "node_log": ["verify_answer"]
        }
        
    def visualize(self, state: AgentState) -> Dict[str, Any]:
        """Detect chart policy based on data shape, matching frontend ECharts capabilities."""
        logger.info("[langgraph] node: visualize")
        rows = state.get("final_data", [])
        policy = "table"
        
        if rows:
            import decimal
            # Simple shape detection
            keys = list(rows[0].keys())
            has_numeric = False
            for k in keys:
                val = rows[0][k]
                if isinstance(val, (int, float, decimal.Decimal)):
                    has_numeric = True
                    break
                # Fallback: check if string looks like a number
                if isinstance(val, str) and val.replace(".", "", 1).replace("-", "", 1).isdigit():
                    has_numeric = True
                    break
            
            if has_numeric and len(keys) >= 2:
                policy = "bar"
                if len(rows) > 10:
                    policy = "line"
                # If there's a pie request in question
                if "pie" in state["question"].lower() or "share" in state["question"].lower():
                    policy = "pie"
                    
        return {
            "chart_policy": policy,
            "node_log": ["visualize"]
        }

def route_after_execute(state: AgentState) -> str:
    err = state.get("execution_result", {}).get("error")
    rows = len(state.get("final_data", []))
    
    if err:
        if state.get("retry_count", 0) < 3:
            return "error_recovery"
        return "generate_answer"
    
    if rows == 0 and not state.get("zero_rows_retried", False):
        return "zero_rows_recovery"
        
    return "visualize"

def build_graph(planner: LangGraphPlanner) -> Any:
    graph = StateGraph(AgentState)
    
    graph.add_node("load_schema", planner.load_schema)
    graph.add_node("retrieve_context", planner.retrieve_context)
    graph.add_node("generate_sql", planner.generate_sql)
    graph.add_node("check_sql", planner.check_sql)
    graph.add_node("execute_sql", planner.execute_sql)
    graph.add_node("error_recovery", planner.error_recovery)
    graph.add_node("zero_rows_recovery", planner.zero_rows_recovery)
    graph.add_node("visualize", planner.visualize)
    graph.add_node("generate_answer", planner.generate_answer)
    graph.add_node("verify_answer", planner.verify_answer)
    
    graph.add_edge(START, "load_schema")
    graph.add_edge("load_schema", "retrieve_context")
    graph.add_edge("retrieve_context", "generate_sql")
    graph.add_edge("generate_sql", "check_sql")
    graph.add_edge("check_sql", "execute_sql")
    
    graph.add_conditional_edges(
        "execute_sql", 
        route_after_execute,
        {
            "error_recovery": "error_recovery",
            "zero_rows_recovery": "zero_rows_recovery",
            "visualize": "visualize",
            "generate_answer": "generate_answer"
        }
    )
    
    graph.add_edge("error_recovery", "execute_sql")
    graph.add_edge("zero_rows_recovery", "execute_sql")
    
    graph.add_edge("visualize", "generate_answer")
    graph.add_edge("generate_answer", "verify_answer")
    graph.add_edge("verify_answer", END)
    
    return graph.compile()

def run_planner(db: Session, api_key: str, query: str, conversation_history: list = None) -> Dict[str, Any]:
    planner = LangGraphPlanner(db, api_key)
    app = build_graph(planner)
    
    initial_state = {
        "question": query,
        "date_context": "",
        "table_hint": None,
        "user_date_range": {},
        "top_views": [],
        "schema_text": "",
        "sample_text": "",
        "generated_sql": "",
        "checked_sql": "",
        "execution_result": {},
        "retry_count": 0,
        "retry_errors": [],
        "zero_rows_retried": False,
        "rag_context": "",
        "final_answer": "",
        "final_data": [],
        "final_sql": "",
        "confidence": "medium",
        "confidence_note": "",
        "node_log": [],
        "chart_policy": None,
        "conversation_history": conversation_history or []
    }
    
    result = app.invoke(initial_state)
    
    chart_spec = None
    if result.get("chart_policy") and result.get("chart_policy") != "table":
        chart_spec = {
            "chart_type": result["chart_policy"],
            "title": f"{result['chart_policy'].capitalize()} Chart",
            "data": result.get("final_data", []),
        }
        
    payload = {
        "reply": result.get("final_answer", "Analysis complete."),
        "action": "new",
        "reason": "langgraph_pipeline",
        "sql": result.get("final_sql", ""),
        "rows_preview": result.get("final_data", []),
        "charts": [chart_spec] if chart_spec else [],
        "time_scope": "current",
        "date_range": {},
        "period_info": "",
        "errors": result.get("retry_errors", []),
        "warnings": [],
        "confidence": result.get("confidence", "low"),
        "node_log": result.get("node_log", [])
    }
    
    return payload