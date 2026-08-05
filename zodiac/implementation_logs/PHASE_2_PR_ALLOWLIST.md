# Phase 2 PR allow-list

Include **only** these paths in a Phase 2 commit/PR.

## New
zodiac/zodiac-api/app/models/workspace.py
zodiac/zodiac-api/app/schemas/workspace.py
zodiac/zodiac-api/app/api/workspace.py
zodiac/zodiac-api/app/core/
zodiac/zodiac-api/app/migrations/
zodiac/zodiac-api/app/tests/__init__.py
zodiac/zodiac-api/app/tests/test_workspace_access.py
zodiac/zodiac-api/app/tests/test_workspace_isolation.py
zodiac/zodiac-front/src/app/workspace/
zodiac/zodiac-front/src/components/workspace/
zodiac/implementation_logs/PHASE_2.md
zodiac/implementation_logs/PHASE_2_REVIEW.md
zodiac/implementation_logs/PHASE_2_FINAL_REVIEW.md

## Modified (Phase 2 hunks only)
zodiac/zodiac-api/app/server.py
zodiac/zodiac-api/app/database.py
zodiac/zodiac-front/src/components/Sidebar.tsx
zodiac/zodiac-front/src/lib/api.ts   # ONLY the workspaceApi append — exclude AI history hunks

## Exclude (prior AI/chat — not Phase 2)
zodiac/zodiac-api/app/api/adaptive_query.py
zodiac/zodiac-api/app/services/ai_chart_generator.py
zodiac/zodiac-api/app/services/chat_thread_store.py
zodiac/zodiac-api/app/services/compare_query_router.py
zodiac/zodiac-api/app/services/dashboard_query_router.py
zodiac/zodiac-api/app/services/sap_sql_agent.py
zodiac/zodiac-front/src/components/DashboardAIAnalysis.tsx
zodiac/zodiac-front/src/components/IntelligencePage.tsx
