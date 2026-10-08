"""Read-only runtime probe; never prints credentials or provider error bodies."""
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from app.services.ai_native_pipeline import llm_text
from app.services.analyst_model_policy import analyst_openai_model
print('model:', analyst_openai_model(), flush=True)
t = time.monotonic()
try:
    answer, provider = llm_text('Answer the question directly.', 'What is 2 plus 2?')
    print(json.dumps({'provider': provider, 'answer': answer, 'seconds': round(time.monotonic()-t, 2)}), flush=True)
except Exception as exc:
    print(json.dumps({'error_type':type(exc).__name__, 'http_status':getattr(exc,'status_code',None),'error_code':getattr(exc,'code',None),'seconds':round(time.monotonic()-t,2)}), flush=True)
from sqlalchemy import text
from app.database import get_sap_session
try:
    from app.database import SessionLocal
    db=get_sap_session() or SessionLocal()
    print('database_connected:', bool(db and db.execute(text('SELECT 1')).scalar()==1),flush=True)
    if db: db.rollback(); db.close()
except Exception as exc:
    print('database_error:',type(exc).__name__,flush=True)
