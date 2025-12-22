"""
Dashboard API endpoints for statistics, analytics, and AI insights
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import json

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..api.auth import get_current_user
from ..config.config import OPENAI_API_KEY
from ..services.database import extract_supplier_info_from_string
from ..services.file_service import read_file_from_storage

# OpenAI client (optional)
try:
    from openai import OpenAI
    openai_available = True
except ImportError:
    openai_available = False

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger("zodiac-api.dashboard")


@router.get("/statistics")
async def get_dashboard_statistics(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30  # Default to last 30 days
):
    """
    Get comprehensive dashboard statistics including:
    - Overview (total, successful, failed, success rate)
    - Timeline data (invoices per day)
    - Format distribution
    - Customer distribution
    - Request type distribution (Web vs API)
    - Recent activity
    """
    try:
        logger.info(f"📊 Fetching dashboard statistics for user {current_user.id} (last {days} days)")
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # ============================================================
        # 1. OVERVIEW STATISTICS
        # ============================================================
        successful_count = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).count()
        
        failed_count = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).count()
        
        total_count = successful_count + failed_count
        success_rate = (successful_count / total_count * 100) if total_count > 0 else 0
        
        # ============================================================
        # 2. TIMELINE DATA (Invoices per day)
        # ============================================================
        # Successful invoices timeline
        success_timeline = db.query(
            cast(SuccessModel.uploaded_at, Date).label('date'),
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.uploaded_at >= start_date
        ).group_by(cast(SuccessModel.uploaded_at, Date)).all()
        
        # Failed invoices timeline
        failed_timeline = db.query(
            cast(FailedModel.uploaded_at, Date).label('date'),
            func.count(FailedModel.id).label('count')
        ).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None),
            FailedModel.uploaded_at >= start_date
        ).group_by(cast(FailedModel.uploaded_at, Date)).all()
        
        # Merge timelines into a single dict
        timeline_dict = defaultdict(lambda: {"date": None, "successful": 0, "failed": 0, "total": 0})
        
        for item in success_timeline:
            date_str = item.date.strftime('%Y-%m-%d')
            timeline_dict[date_str]["date"] = date_str
            timeline_dict[date_str]["successful"] = item.count
            timeline_dict[date_str]["total"] += item.count
        
        for item in failed_timeline:
            date_str = item.date.strftime('%Y-%m-%d')
            timeline_dict[date_str]["date"] = date_str
            timeline_dict[date_str]["failed"] = item.count
            timeline_dict[date_str]["total"] += item.count
        
        # Convert to sorted list
        timeline_data = sorted(timeline_dict.values(), key=lambda x: x["date"])
        
        # ============================================================
        # 3. FORMAT DISTRIBUTION (Successful invoices only)
        # ============================================================
        # Query successful invoices within date range
        success_format_query = db.query(
            SuccessModel.target_file_format,
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.uploaded_at >= start_date  # Apply date range filter
        ).group_by(SuccessModel.target_file_format).all()
        
        # Convert to list format
        format_distribution = [
            {"format": item.target_file_format or "Unknown", "count": item.count}
            for item in success_format_query
        ]
        
        # Sort by count descending
        format_distribution = sorted(format_distribution, key=lambda x: x["count"], reverse=True)
        
        # ============================================================
        # 4. CUSTOMER DISTRIBUTION (Top 10)
        # ============================================================
        # Get successful and failed invoices to extract customer info
        success_invoices = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).order_by(SuccessModel.uploaded_at.desc()).limit(500).all()  # Limit for performance
        
        failed_invoices_for_customers = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).order_by(FailedModel.uploaded_at.desc()).limit(500).all()  # Limit for performance
        
        customer_stats = defaultdict(lambda: {"successful": 0, "failed": 0, "name": None})
        
        # Process successful invoices
        for invoice in success_invoices:
            try:
                # Get XML path (blob or local)
                xml_path = invoice.blob_xml_path or invoice.xml_path
                
                if xml_path:
                    # Read XML content
                    xml_content = read_file_from_storage(xml_path)
                    
                    if xml_content:
                        # Extract customer info from XML
                        customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                        
                        if customer_id and customer_name:
                            # Use customer name as key (more readable than ID)
                            customer_stats[customer_name]["successful"] += 1
                            customer_stats[customer_name]["name"] = customer_name
                        elif customer_id:
                            # Use ID if no name available
                            customer_stats[customer_id]["successful"] += 1
                            customer_stats[customer_id]["name"] = customer_id
            except Exception as e:
                logger.warning(f"⚠️ Failed to extract customer from invoice {invoice.id}: {e}")
                continue
        
        # Process failed invoices
        for invoice in failed_invoices_for_customers:
            try:
                # Get XML path (blob or local)
                xml_path = invoice.blob_xml_path or invoice.xml_path
                
                if xml_path:
                    # Read XML content
                    xml_content = read_file_from_storage(xml_path)
                    
                    if xml_content:
                        # Extract customer info from XML
                        customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                        
                        if customer_id and customer_name:
                            customer_stats[customer_name]["failed"] += 1
                            customer_stats[customer_name]["name"] = customer_name
                        elif customer_id:
                            customer_stats[customer_id]["failed"] += 1
                            customer_stats[customer_id]["name"] = customer_id
            except Exception as e:
                logger.warning(f"⚠️ Failed to extract customer from failed invoice {invoice.id}: {e}")
                continue
        
        # Convert to list and filter out entries with no valid data
        customer_distribution = [
            {
                "customer": stats["name"] or customer_key,
                "successful": stats["successful"],
                "failed": stats["failed"],
                "total": stats["successful"] + stats["failed"]
            }
            for customer_key, stats in customer_stats.items()
            if stats["successful"] > 0 or stats["failed"] > 0  # Only include customers with invoices
        ]
        
        # Sort by total and get top 10
        customer_distribution = sorted(customer_distribution, key=lambda x: x["total"], reverse=True)[:10]
        
        # If no customer data found, provide helpful message
        if not customer_distribution:
            customer_distribution = [{
                "customer": "No Data Available",
                "successful": 0,
                "failed": 0,
                "total": 0
            }]
        
        # ============================================================
        # 5. REQUEST TYPE DISTRIBUTION (Web vs API)
        # ============================================================
        # Query successful invoices
        success_request_type_query = db.query(
            SuccessModel.request_type,
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).group_by(SuccessModel.request_type).all()
        
        # Query failed invoices
        failed_request_type_query = db.query(
            FailedModel.request_type,
            func.count(FailedModel.id).label('count')
        ).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).group_by(FailedModel.request_type).all()
        
        # Normalize and combine web/null entries from both success and failed
        type_counts = {"web": 0, "api": 0}
        
        for item in success_request_type_query:
            request_type = item.request_type
            # Normalize: treat null, empty, or 'web' as 'web'
            if not request_type or request_type.lower() == 'web':
                type_counts["web"] += item.count
            elif request_type.lower() == 'api':
                type_counts["api"] += item.count
        
        for item in failed_request_type_query:
            request_type = item.request_type
            # Normalize: treat null, empty, or 'web' as 'web'
            if not request_type or request_type.lower() == 'web':
                type_counts["web"] += item.count
            elif request_type.lower() == 'api':
                type_counts["api"] += item.count
        
        # Convert to list format, excluding zero counts
        request_type_distribution = [
            {"type": type_key, "count": count}
            for type_key, count in type_counts.items()
            if count > 0
        ]
        
        # ============================================================
        # 6. RECENT ACTIVITY (Last 10 invoices)
        # ============================================================
        recent_success = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).order_by(SuccessModel.uploaded_at.desc()).limit(5).all()
        
        recent_failed = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).order_by(FailedModel.uploaded_at.desc()).limit(5).all()
        
        recent_activity = []
        
        for inv in recent_success:
            recent_activity.append({
                "id": inv.id,
                "tracking_id": str(inv.tracking_id),
                "status": "successful",
                "format": inv.target_file_format,
                "uploaded_at": inv.uploaded_at.isoformat() if inv.uploaded_at else None,
                "request_type": inv.request_type
            })
        
        for inv in recent_failed:
            recent_activity.append({
                "id": inv.id,
                "tracking_id": str(inv.tracking_id),
                "status": "failed",
                "format": inv.target_file_format,
                "uploaded_at": inv.uploaded_at.isoformat() if inv.uploaded_at else None,
                "request_type": inv.request_type
            })
        
        # Sort by date and limit to 10
        recent_activity = sorted(
            recent_activity,
            key=lambda x: x["uploaded_at"] or "",
            reverse=True
        )[:10]
        
        # ============================================================
        # RESPONSE
        # ============================================================
        logger.info(f"✅ Dashboard statistics calculated successfully")
        
        return {
            "overview": {
                "total": total_count,
                "successful": successful_count,
                "failed": failed_count,
                "success_rate": round(success_rate, 2)
            },
            "timeline": timeline_data,
            "format_distribution": format_distribution,
            "customer_distribution": customer_distribution,
            "request_type_distribution": request_type_distribution,
            "recent_activity": recent_activity,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get dashboard statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard statistics: {str(e)}"
        )


@router.get("/ai-insights")
async def get_ai_insights(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get AI-powered insights and analysis for failed invoices.
    Analyzes error patterns, identifies root causes, and provides actionable recommendations.
    """
    try:
        logger.info(f"🤖 Generating AI insights for user {current_user.id}")
        
        # Get recent failed invoices
        failed_invoices = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).order_by(FailedModel.uploaded_at.desc()).limit(20).all()
        
        if not failed_invoices:
            return {
                "summary": "🎉 No failed invoices found. Your processing is running smoothly!",
                "insights": [],
                "recommendations": [
                    "Continue monitoring your invoice processing for optimal performance.",
                    "Consider implementing automated validation checks before upload.",
                    "Review your success patterns to maintain high quality."
                ],
                "error_patterns": [],
                "root_causes": [],
                "total_failed": 0,
                "analyzed_at": datetime.utcnow().isoformat()
            }
        
        # ============================================================
        # ANALYZE ERROR PATTERNS
        # ============================================================
        error_patterns = defaultdict(int)
        error_details = []
        
        for invoice in failed_invoices:
            if invoice.processing_steps:
                for step in invoice.processing_steps:
                    if isinstance(step, dict):
                        if not step.get('success', True) and step.get('error_details'):
                            errors = step['error_details']
                            if isinstance(errors, list):
                                for error in errors:
                                    if isinstance(error, dict):
                                        error_code = error.get('error_code', 'UNKNOWN')
                                        error_patterns[error_code] += 1
                                        error_details.append({
                                            'code': error_code,
                                            'message': error.get('user_message', ''),
                                            'severity': error.get('severity', 'ERROR'),
                                            'tracking_id': str(invoice.tracking_id)
                                        })
        
        # Prepare context for AI
        total_failed = len(failed_invoices)
        top_errors = sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)[:5]
        
        error_summary = "\n".join([f"- {code}: {count} occurrences" for code, count in top_errors])
        
        sample_errors = error_details[:10]  # Take first 10 for AI analysis
        sample_errors_text = "\n".join([
            f"- [{e['severity']}] {e['code']}: {e['message']}"
            for e in sample_errors
        ])
        
        # ============================================================
        # AI ANALYSIS (if available)
        # ============================================================
        if OPENAI_API_KEY and openai_available:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                
                prompt = f"""
You are an expert EDI and e-invoice processing analyst. Analyze the following error patterns from {total_failed} failed invoice processing attempts and provide actionable insights.

Error Frequency:
{error_summary}

Sample Error Details:
{sample_errors_text}

Provide a JSON response with the following structure:
{{
    "summary": "Brief overview of the main issues (2-3 sentences)",
    "insights": [
        "Specific insight 1 about patterns or trends",
        "Specific insight 2 about common failure points",
        "Specific insight 3 about system behavior"
    ],
    "recommendations": [
        "Actionable recommendation 1",
        "Actionable recommendation 2",
        "Actionable recommendation 3"
    ],
    "root_causes": [
        "Identified root cause 1",
        "Identified root cause 2"
    ]
}}

Focus on:
1. Common patterns across errors
2. Root causes (XML structure, missing data, format issues, customer configuration)
3. Practical, actionable solutions
4. Prevention strategies
5. Priority of fixes (high impact first)

Keep insights concise, professional, and actionable. Respond ONLY with valid JSON, no markdown or extra text.
"""
                
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    response_format={"type": "json_object"}
                )
                
                ai_response = json.loads(completion.choices[0].message.content)
                
                logger.info(f"✅ AI insights generated successfully")
                
                return {
                    "summary": ai_response.get("summary", "Analysis complete"),
                    "insights": ai_response.get("insights", []),
                    "recommendations": ai_response.get("recommendations", []),
                    "root_causes": ai_response.get("root_causes", []),
                    "error_patterns": [
                        {
                            "code": code,
                            "count": count,
                            "percentage": round(count / total_failed * 100, 1)
                        }
                        for code, count in top_errors
                    ],
                    "total_failed": total_failed,
                    "analyzed_at": datetime.utcnow().isoformat()
                }
            
            except Exception as ai_error:
                logger.warning(f"⚠️ AI analysis failed, using fallback: {ai_error}")
                # Continue to fallback
        
        # ============================================================
        # FALLBACK INSIGHTS (if AI not available or fails)
        # ============================================================
        return {
            "summary": f"Analyzed {total_failed} failed invoices. The most common issues are related to validation and format errors.",
            "insights": [
                f"Most frequent error: {top_errors[0][0]} ({top_errors[0][1]} occurrences)" if top_errors else "No specific error pattern detected",
                "XML validation errors are the primary cause of failures",
                "Review customer format configurations to ensure they match invoice types",
                "Consider enabling AI auto-correction to fix common issues automatically"
            ],
            "recommendations": [
                "✅ Validate XML files against UBL 2.1 schema before uploading",
                "✅ Ensure all required fields are populated (invoice ID, dates, parties)",
                "✅ Verify customer format configuration matches your invoice format",
                "✅ Use the AI correction feature to automatically fix common errors",
                "✅ Review failed invoice details to understand specific issues"
            ],
            "root_causes": [
                "XML schema validation failures",
                "Missing required fields or elements",
                "Format mismatch between invoice and customer configuration",
                "Invalid data formats (dates, amounts, identifiers)"
            ],
            "error_patterns": [
                {
                    "code": code,
                    "count": count,
                    "percentage": round(count / total_failed * 100, 1)
                }
                for code, count in top_errors
            ],
            "total_failed": total_failed,
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to generate AI insights: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate AI insights: {str(e)}"
        )

