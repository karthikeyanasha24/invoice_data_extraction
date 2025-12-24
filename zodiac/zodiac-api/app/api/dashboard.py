"""
Dashboard API endpoints for statistics, analytics, and AI insights
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import json

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..models.correction_cache import CorrectionCache
from ..models.invoice_business_data import InvoiceBusinessData
from ..api.auth import get_current_user
from ..config.config import OPENAI_API_KEY
from ..services.database import extract_supplier_info_from_string
from ..services.file_service import read_file_from_storage
from collections import defaultdict
from decimal import Decimal

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
        # Get all successful invoices within date range to extract actual formats
        success_invoices_for_format = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.uploaded_at >= start_date
        ).all()
        
        format_counts = defaultdict(int)
        
        for invoice in success_invoices_for_format:
            format_name = None
            
            # First, try to get from target_file_format if available
            if invoice.target_file_format:
                format_name = invoice.target_file_format
            else:
                # Extract from EDI file path/extension
                edi_path = invoice.blob_edi_path or invoice.edi_path
                
                if edi_path:
                    # Determine format from file extension
                    if edi_path.endswith('.x12') or edi_path.endswith('.810'):
                        format_name = 'X12'
                    elif edi_path.endswith('.edi') or edi_path.endswith('.edifact'):
                        format_name = 'EDIFACT'
                    elif edi_path.endswith('.xml'):
                        # Check if it's an embedded format
                        xml_path = invoice.blob_xml_path or invoice.xml_path
                        if xml_path:
                            # Try to detect embedded format from filename
                            if 'embed' in xml_path.lower():
                                format_name = 'XML_EMBED'
                            else:
                                format_name = 'XML'
                        else:
                            format_name = 'XML'
                    else:
                        # Check processing steps to determine format
                        if invoice.processing_steps:
                            try:
                                steps = invoice.processing_steps
                                for step in steps:
                                    if isinstance(step, dict):
                                        # Look for format hints in step messages
                                        message = step.get('message', '').lower()
                                        if 'x12' in message or '810' in message:
                                            format_name = 'X12'
                                            break
                                        elif 'edifact' in message:
                                            format_name = 'EDIFACT'
                                            break
                                        elif 'xml' in message and 'embed' in message:
                                            format_name = 'XML_EMBED'
                                            break
                            except:
                                pass
            
            # If still no format found, check if it has an EDI path (likely X12) or XML only
            if not format_name:
                edi_path = invoice.blob_edi_path or invoice.edi_path
                if edi_path:
                    format_name = 'X12'  # Most common EDI format
                else:
                    format_name = 'XML'  # Pure XML without conversion
            
            format_counts[format_name] += 1
        
        format_distribution = [
            {"format": format_name, "count": count}
            for format_name, count in format_counts.items()
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


@router.get("/operations")
async def get_operations_statistics(
    days: int = Query(default=30, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get operations statistics for the dashboard Operations tab:
    - Inbound/Outbound message counts
    - Auto-fix breakdown and savings
    - Processing time trends
    - External system status
    """
    try:
        logger.info(f"📊 Fetching operations statistics for last {days} days")
        
        # Calculate date range
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # ============================================================
        # 1. INBOUND/OUTBOUND MESSAGES
        # ============================================================
        # Inbound: Messages received from external systems (API pushes)
        # Outbound: Messages pushed to external systems (web uploads + processing)
        
        inbound_successful = db.query(func.count(SuccessModel.id)).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date,
            SuccessModel.request_type == 'api'
        ).scalar() or 0
        
        inbound_failed = db.query(func.count(FailedModel.id)).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.uploaded_at >= cutoff_date,
            FailedModel.request_type == 'api'
        ).scalar() or 0
        
        # Outbound: All messages (both web and api) that we tried to send out
        outbound_successful = db.query(func.count(SuccessModel.id)).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date
        ).scalar() or 0
        
        outbound_failed = db.query(func.count(FailedModel.id)).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.uploaded_at >= cutoff_date
        ).scalar() or 0
        
        # ============================================================
        # 2. AUTO-FIX BREAKDOWN
        # ============================================================
        # Query correction cache for auto-fix statistics
        # Note: correction_cache stores corrections per customer, but we filter by user
        try:
            correction_stats = db.query(
                CorrectionCache.error_type,
                func.sum(CorrectionCache.success_count).label('total_fixes')
            ).filter(
                CorrectionCache.created_by_user_id == current_user.id,
                CorrectionCache.created_at >= cutoff_date,
                CorrectionCache.is_active == True
            ).group_by(CorrectionCache.error_type).all()
        except Exception as e:
            logger.warning(f"⚠️ Could not query correction_cache: {e}")
            correction_stats = []
        
        # Calculate total auto-fixes
        total_auto_fixes = sum(int(stat.total_fixes or 0) for stat in correction_stats) if correction_stats else 0
        
        # Map error types to user-friendly names and estimate time saved
        error_type_mapping = {
            'missing_invoice_id': {'name': 'Missing Fields', 'time_per_fix': 5},
            'missing_field': {'name': 'Missing Fields', 'time_per_fix': 5},
            'date_format': {'name': 'Date Format', 'time_per_fix': 3},
            'invalid_date': {'name': 'Date Format', 'time_per_fix': 3},
            'id_padding': {'name': 'ID Padding', 'time_per_fix': 2},
            'invalid_id_format': {'name': 'ID Padding', 'time_per_fix': 2},
            'party_info': {'name': 'Party Info', 'time_per_fix': 4},
            'missing_party': {'name': 'Party Info', 'time_per_fix': 4},
        }
        
        # Aggregate by user-friendly names
        auto_fix_breakdown = {}
        for stat in correction_stats:
            mapping = error_type_mapping.get(stat.error_type, {'name': 'Other', 'time_per_fix': 3})
            friendly_name = mapping['name']
            fix_count = int(stat.total_fixes or 0)
            time_saved = fix_count * mapping['time_per_fix']
            
            if friendly_name in auto_fix_breakdown:
                auto_fix_breakdown[friendly_name]['count'] += fix_count
                auto_fix_breakdown[friendly_name]['saved'] += time_saved
            else:
                auto_fix_breakdown[friendly_name] = {
                    'type': friendly_name,
                    'count': fix_count,
                    'saved': time_saved
                }
        
        # Convert to list and sort by count
        auto_fix_list = sorted(auto_fix_breakdown.values(), key=lambda x: x['count'], reverse=True) if auto_fix_breakdown else []
        
        # ============================================================
        # 3. PROCESSING TIME TREND (hourly averages)
        # ============================================================
        # Extract processing times from successful invoices
        processing_time_data = []
        
        # Get all successful invoices with processing_steps
        recent_invoices = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date,
            SuccessModel.processing_steps.isnot(None)
        ).all()
        
        # Aggregate by hour of day
        hourly_times = {}
        for invoice in recent_invoices:
            try:
                hour = invoice.uploaded_at.hour
                steps = json.loads(invoice.processing_steps) if isinstance(invoice.processing_steps, str) else invoice.processing_steps
                
                # Calculate total processing time
                total_time = sum(
                    step.get('duration_seconds', 0) 
                    for step in steps 
                    if isinstance(step, dict)
                )
                
                if hour not in hourly_times:
                    hourly_times[hour] = []
                hourly_times[hour].append(total_time)
            except:
                continue
        
        # Calculate averages
        for hour in range(24):
            times = hourly_times.get(hour, [])
            avg_time = round(sum(times) / len(times), 2) if times else 0
            processing_time_data.append({
                'hour': f'{hour:02d}:00',
                'avgTime': avg_time,
                'count': len(times)
            })
        
        # ============================================================
        # 4. EXTERNAL SYSTEM STATUS
        # ============================================================
        # Check external_status field (only exists in SuccessModel)
        external_success = db.query(func.count(SuccessModel.id)).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date,
            SuccessModel.external_status == 'success'
        ).scalar() or 0
        
        external_failed = db.query(func.count(SuccessModel.id)).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date,
            SuccessModel.external_status.in_(['failed', 'error'])
        ).scalar() or 0
        
        # All failed invoices are considered external failures
        # (since they failed before reaching external systems successfully)
        failed_invoice_count = db.query(func.count(FailedModel.id)).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.uploaded_at >= cutoff_date
        ).scalar() or 0
        
        external_failed += failed_invoice_count
        
        external_pending = db.query(func.count(SuccessModel.id)).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.uploaded_at >= cutoff_date,
            SuccessModel.external_status.in_(['pending', 'processing', 'False', None])
        ).scalar() or 0
        
        # ============================================================
        # RETURN RESPONSE
        # ============================================================
        return {
            "inbound": {
                "successful": inbound_successful,
                "failed": inbound_failed,
                "total": inbound_successful + inbound_failed
            },
            "outbound": {
                "successful": outbound_successful,
                "failed": outbound_failed,
                "total": outbound_successful + outbound_failed
            },
            "autoFix": {
                "total": total_auto_fixes,
                "successful": total_auto_fixes,  # Assume all cached corrections were successful
                "breakdown": auto_fix_list
            },
            "processingTime": {
                "hourly": processing_time_data,
                "average": round(
                    sum(pt['avgTime'] for pt in processing_time_data) / len(processing_time_data), 2
                ) if processing_time_data else 0
            },
            "externalSystems": {
                "successful": external_success,
                "failed": external_failed,
                "pending": external_pending,
                "total": external_success + external_failed + external_pending
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch operations statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch operations statistics: {str(e)}"
        )


@router.get("/auto-fix-details")
async def get_auto_fix_details(
    fix_type: str = Query(..., description="Type of fix to get details for"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific auto-fix type:
    - Which invoices had this fix applied
    - Before and after values
    - Customer information
    - Success/failure status
    """
    try:
        logger.info(f"🔍 Fetching auto-fix details for: {fix_type}")
        
        # Map user-friendly names back to error types
        error_type_reverse_mapping = {
            'Missing Fields': ['missing_invoice_id', 'missing_field'],
            'Date Format': ['date_format', 'invalid_date'],
            'ID Padding': ['id_padding', 'invalid_id_format'],
            'Party Info': ['party_info', 'missing_party'],
        }
        
        error_types = error_type_reverse_mapping.get(fix_type, [fix_type.lower().replace(' ', '_')])
        
        # Query correction cache
        corrections = db.query(CorrectionCache).filter(
            CorrectionCache.error_type.in_(error_types),
            CorrectionCache.success_count > 0
        ).all()
        
        if not corrections:
            return {
                "fix_type": fix_type,
                "total_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "details": []
            }
        
        # Build detailed response
        details = []
        total_successful = 0
        total_failed = 0
        
        for correction in corrections:
            # Get transformation rule (contains before/after values)
            try:
                transform_rule = json.loads(correction.transformation_rule) if isinstance(
                    correction.transformation_rule, str
                ) else correction.transformation_rule
            except:
                transform_rule = {}
            
            # Get customer information
            customer_name = correction.customer_name or "Unknown Customer"
            
            # Extract before/after values
            before_value = transform_rule.get('original_value', 'null')
            after_value = transform_rule.get('corrected_value', 'N/A')
            fix_description = transform_rule.get('description', f"Applied {fix_type} fix")
            
            # Find a sample invoice that used this correction
            # Since invoices don't have customer_id, we find by user and check processing steps
            sample_invoice = db.query(SuccessModel).filter(
                SuccessModel.user_id == current_user.id,
                SuccessModel.processing_steps.isnot(None)
            ).order_by(SuccessModel.uploaded_at.desc()).first()
            
            if sample_invoice:
                # Parse processing steps to find AI corrections
                try:
                    steps = json.loads(sample_invoice.processing_steps) if isinstance(
                        sample_invoice.processing_steps, str
                    ) else sample_invoice.processing_steps
                    
                    # Look for AI correction step
                    for step in steps:
                        if step.get('step_name') == 'AI Correction' or 'AI' in step.get('message', ''):
                            error_details = step.get('error_details', {})
                            if isinstance(error_details, dict):
                                before_value = error_details.get('before', before_value)
                                after_value = error_details.get('after', after_value)
                                break
                except:
                    pass
            
            # Count successes and failures
            success_count = correction.success_count or 0
            failure_count = correction.failure_count or 0
            
            total_successful += success_count
            total_failed += failure_count
            
            # Create detail entry for each successful fix
            for i in range(min(success_count, 5)):  # Limit to 5 examples per correction type
                details.append({
                    "invoice_id": sample_invoice.id if sample_invoice else 0,
                    "tracking_id": sample_invoice.tracking_id if sample_invoice else f"N/A-{i}",
                    "customer_name": customer_name,
                    "fix_applied": fix_description,
                    "before_value": str(before_value),
                    "after_value": str(after_value),
                    "success": True,
                    "timestamp": (sample_invoice.uploaded_at if sample_invoice else datetime.utcnow()).isoformat()
                })
        
        # Sort by timestamp (most recent first)
        details.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Limit to top 20 details
        details = details[:20]
        
        return {
            "fix_type": fix_type,
            "total_count": total_successful + total_failed,
            "successful_count": total_successful,
            "failed_count": total_failed,
            "details": details
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch auto-fix details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch auto-fix details: {str(e)}"
        )


@router.get("/business")
async def get_business_analytics(
    days: int = Query(default=30, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get business analytics for the dashboard Business tab:
    - E2E lifecycle funnel
    - Customer analysis (top customers, success rates, countries)
    - Country distribution
    - Product/Industry breakdown
    - Supplier analysis
    """
    try:
        logger.info(f"📊 Fetching business analytics for last {days} days")
        
        # Calculate date range
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Check if BI table has any data
        total_bi_records = db.query(func.count(InvoiceBusinessData.id)).filter(
            InvoiceBusinessData.user_id == current_user.id
        ).scalar() or 0
        
        if total_bi_records == 0:
            logger.warning(f"⚠️ No business intelligence data found for user {current_user.id}")
            # Return empty structure with helpful message
            return {
                "message": "No business intelligence data available. Please run the backfill script or upload new invoices.",
                "needs_backfill": True,
                "lifecycle_funnel": {
                    'RECEIVED': {'total': 0, 'success': 0, 'failed': 0},
                    'VALIDATED': {'total': 0, 'success': 0, 'failed': 0},
                    'CONVERTED': {'total': 0, 'success': 0, 'failed': 0},
                    'SENT': {'total': 0, 'success': 0, 'failed': 0},
                    'ACKNOWLEDGED': {'total': 0, 'success': 0, 'failed': 0},
                },
                "customer_analysis": {"top_customers": [], "total_customers": 0},
                "country_distribution": [],
                "industry_breakdown": [],
                "product_analysis": {"top_products": [], "total_products": 0},
                "supplier_analysis": {"top_suppliers": []}
            }
        
        logger.info(f"✅ Found {total_bi_records} business intelligence records")
        
        # ============================================================
        # 1. E2E LIFECYCLE FUNNEL
        # ============================================================
        # Count invoices at each stage
        stage_counts = db.query(
            InvoiceBusinessData.current_stage,
            InvoiceBusinessData.stage_status,
            func.count(InvoiceBusinessData.id).label('count')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date
        ).group_by(
            InvoiceBusinessData.current_stage,
            InvoiceBusinessData.stage_status
        ).all()
        
        # Build lifecycle funnel
        lifecycle_funnel = {
            'RECEIVED': {'total': 0, 'success': 0, 'failed': 0},
            'VALIDATED': {'total': 0, 'success': 0, 'failed': 0},
            'CONVERTED': {'total': 0, 'success': 0, 'failed': 0},
            'SENT': {'total': 0, 'success': 0, 'failed': 0},
            'ACKNOWLEDGED': {'total': 0, 'success': 0, 'failed': 0},
        }
        
        for stage, status, count in stage_counts:
            if stage in lifecycle_funnel:
                lifecycle_funnel[stage]['total'] += count
                if status == 'SUCCESS':
                    lifecycle_funnel[stage]['success'] += count
                elif status == 'FAILED':
                    lifecycle_funnel[stage]['failed'] += count
        
        # ============================================================
        # 2. CUSTOMER ANALYSIS
        # ============================================================
        # Top customers with success/failed counts
        customer_stats = db.query(
            InvoiceBusinessData.customer_id,
            InvoiceBusinessData.customer_name,
            InvoiceBusinessData.customer_country,
            InvoiceBusinessData.stage_status,
            func.count(InvoiceBusinessData.id).label('count'),
            func.sum(InvoiceBusinessData.total_amount).label('total_revenue')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.customer_name.isnot(None)
        ).group_by(
            InvoiceBusinessData.customer_id,
            InvoiceBusinessData.customer_name,
            InvoiceBusinessData.customer_country,
            InvoiceBusinessData.stage_status
        ).all()
        
        # Aggregate customer data
        customer_map = {}
        for cust_id, cust_name, country, status, count, revenue in customer_stats:
            key = cust_id or cust_name
            if key not in customer_map:
                customer_map[key] = {
                    'customer_id': cust_id,
                    'customer_name': cust_name,
                    'customer_country': country,
                    'total_invoices': 0,
                    'successful': 0,
                    'failed': 0,
                    'total_revenue': 0
                }
            
            customer_map[key]['total_invoices'] += count
            if status == 'SUCCESS':
                customer_map[key]['successful'] += count
            elif status == 'FAILED':
                customer_map[key]['failed'] += count
            customer_map[key]['total_revenue'] += float(revenue or 0)
        
        # Convert to list and calculate success rates
        customer_list = []
        for customer in customer_map.values():
            success_rate = 0
            if customer['total_invoices'] > 0:
                success_rate = round((customer['successful'] / customer['total_invoices']) * 100, 1)
            
            customer_list.append({
                **customer,
                'success_rate': success_rate
            })
        
        # Sort by total invoices and get top 10
        top_customers = sorted(customer_list, key=lambda x: x['total_invoices'], reverse=True)[:10]
        
        # ============================================================
        # 3. COUNTRY DISTRIBUTION
        # ============================================================
        country_stats = db.query(
            InvoiceBusinessData.customer_country,
            func.count(InvoiceBusinessData.id).label('count')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.customer_country.isnot(None)
        ).group_by(
            InvoiceBusinessData.customer_country
        ).order_by(
            func.count(InvoiceBusinessData.id).desc()
        ).limit(15).all()
        
        country_distribution = [
            {
                'country': country,
                'count': count
            }
            for country, count in country_stats
        ]
        
        # ============================================================
        # 4. INDUSTRY BREAKDOWN
        # ============================================================
        industry_stats = db.query(
            InvoiceBusinessData.industry,
            func.count(InvoiceBusinessData.id).label('count'),
            func.sum(InvoiceBusinessData.total_amount).label('total_revenue')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.industry.isnot(None)
        ).group_by(
            InvoiceBusinessData.industry
        ).order_by(
            func.count(InvoiceBusinessData.id).desc()
        ).all()
        
        industry_breakdown = [
            {
                'industry': industry,
                'count': count,
                'total_revenue': float(revenue or 0)
            }
            for industry, count, revenue in industry_stats
        ]
        
        # ============================================================
        # 5. PRODUCT ANALYSIS (Top products across all invoices)
        # ============================================================
        # This requires parsing the products JSONB field
        product_counts = {}
        bi_records_with_products = db.query(InvoiceBusinessData).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.products.isnot(None)
        ).all()
        
        for record in bi_records_with_products:
            products = record.products
            if products and isinstance(products, list):
                for product in products:
                    product_name = product.get('name', 'Unknown')
                    if product_name not in product_counts:
                        product_counts[product_name] = {
                            'name': product_name,
                            'count': 0,
                            'total_quantity': 0,
                            'total_revenue': 0
                        }
                    product_counts[product_name]['count'] += 1
                    product_counts[product_name]['total_quantity'] += product.get('quantity', 0)
                    product_counts[product_name]['total_revenue'] += product.get('line_total', 0)
        
        # Sort by count and get top 10
        top_products = sorted(product_counts.values(), key=lambda x: x['count'], reverse=True)[:10]
        
        # ============================================================
        # 6. SUPPLIER ANALYSIS
        # ============================================================
        supplier_stats = db.query(
            InvoiceBusinessData.supplier_id,
            InvoiceBusinessData.supplier_name,
            func.count(InvoiceBusinessData.id).label('count')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.supplier_name.isnot(None)
        ).group_by(
            InvoiceBusinessData.supplier_id,
            InvoiceBusinessData.supplier_name
        ).order_by(
            func.count(InvoiceBusinessData.id).desc()
        ).limit(10).all()
        
        top_suppliers = [
            {
                'supplier_id': supplier_id,
                'supplier_name': supplier_name,
                'count': count
            }
            for supplier_id, supplier_name, count in supplier_stats
        ]
        
        # ============================================================
        # RETURN RESPONSE
        # ============================================================
        return {
            "lifecycle_funnel": lifecycle_funnel,
            "customer_analysis": {
                "top_customers": top_customers,
                "total_customers": len(customer_list)
            },
            "country_distribution": country_distribution,
            "industry_breakdown": industry_breakdown,
            "product_analysis": {
                "top_products": top_products,
                "total_products": len(product_counts)
            },
            "supplier_analysis": {
                "top_suppliers": top_suppliers
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch business analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch business analytics: {str(e)}"
        )


@router.get("/industry-intelligence")
async def get_industry_intelligence(
    days: int = Query(default=30, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get Product Performance & Industry Intelligence:
    - Product performance metrics with industry benchmarks
    - Performance indicators (underperforming/optimal/outperforming)
    - AI-powered insights and recommendations
    - Industry standards and competitive positioning
    """
    try:
        logger.info(f"📊 Fetching industry intelligence for last {days} days")
        
        # Calculate date range
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get all BI records with products
        bi_records = db.query(InvoiceBusinessData).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.products.isnot(None)
        ).all()
        
        if not bi_records:
            return {
                "message": "No product data available yet",
                "products": [],
                "industry_benchmarks": {},
                "overall_insights": []
            }
        
        # ============================================================
        # 1. AGGREGATE PRODUCT DATA
        # ============================================================
        product_data = defaultdict(lambda: {
            'name': '',
            'industry': 'General',
            'total_quantity': 0,
            'total_revenue': 0,
            'order_count': 0,
            'prices': [],
            'invoices': []
        })
        
        industry_products = defaultdict(lambda: defaultdict(list))
        
        for record in bi_records:
            industry = record.industry or 'General'
            products = record.products if isinstance(record.products, list) else []
            
            for product in products:
                product_name = product.get('name', 'Unknown')
                quantity = float(product.get('quantity', 0))
                unit_price = float(product.get('unit_price', 0))
                line_total = float(product.get('line_total', 0))
                
                # Aggregate by product name
                product_data[product_name]['name'] = product_name
                product_data[product_name]['industry'] = industry
                product_data[product_name]['total_quantity'] += quantity
                product_data[product_name]['total_revenue'] += line_total
                product_data[product_name]['order_count'] += 1
                if unit_price > 0:
                    product_data[product_name]['prices'].append(unit_price)
                product_data[product_name]['invoices'].append(record.tracking_id)
                
                # Track for industry benchmarking
                if unit_price > 0:
                    industry_products[industry][product_name].append({
                        'price': unit_price,
                        'quantity': quantity,
                        'revenue': line_total
                    })
        
        # ============================================================
        # 2. CALCULATE INDUSTRY BENCHMARKS
        # ============================================================
        industry_benchmarks = {}
        
        for industry, products in industry_products.items():
            all_prices = []
            all_revenues = []
            all_quantities = []
            
            for product_name, product_list in products.items():
                for p in product_list:
                    all_prices.append(p['price'])
                    all_revenues.append(p['revenue'])
                    all_quantities.append(p['quantity'])
            
            if all_prices:
                industry_benchmarks[industry] = {
                    'avg_price': round(sum(all_prices) / len(all_prices), 2),
                    'median_price': round(sorted(all_prices)[len(all_prices) // 2], 2),
                    'avg_revenue': round(sum(all_revenues) / len(all_revenues), 2),
                    'avg_quantity': round(sum(all_quantities) / len(all_quantities), 2),
                    'total_products': len(products),
                    'price_std_dev': round(_calculate_std_dev(all_prices), 2)
                }
        
        # ============================================================
        # 3. ANALYZE PRODUCT PERFORMANCE
        # ============================================================
        products_analysis = []
        
        for product_name, data in product_data.items():
            industry = data['industry']
            avg_price = sum(data['prices']) / len(data['prices']) if data['prices'] else 0
            
            # Get industry benchmark
            benchmark = industry_benchmarks.get(industry, {})
            industry_avg_price = benchmark.get('avg_price', avg_price)
            industry_avg_revenue = benchmark.get('avg_revenue', data['total_revenue'] / data['order_count'] if data['order_count'] > 0 else 0)
            
            # Calculate performance metrics
            price_diff_pct = 0
            if industry_avg_price > 0:
                price_diff_pct = round(((avg_price - industry_avg_price) / industry_avg_price) * 100, 1)
            
            avg_revenue_per_order = data['total_revenue'] / data['order_count'] if data['order_count'] > 0 else 0
            revenue_diff_pct = 0
            if industry_avg_revenue > 0:
                revenue_diff_pct = round(((avg_revenue_per_order - industry_avg_revenue) / industry_avg_revenue) * 100, 1)
            
            # Determine performance status
            performance_status = _determine_performance_status(
                price_diff_pct, 
                revenue_diff_pct, 
                data['order_count'],
                benchmark.get('total_products', 1)
            )
            
            # Price positioning
            price_position = 'Medium'
            if avg_price > industry_avg_price * 1.2:
                price_position = 'Premium'
            elif avg_price < industry_avg_price * 0.8:
                price_position = 'Economy'
            
            products_analysis.append({
                'product_name': product_name,
                'industry': industry,
                'performance_status': performance_status,
                'performance_score': _calculate_performance_score(price_diff_pct, revenue_diff_pct, data['order_count']),
                'metrics': {
                    'avg_price': round(avg_price, 2),
                    'total_quantity': round(data['total_quantity'], 2),
                    'total_revenue': round(data['total_revenue'], 2),
                    'order_count': data['order_count'],
                    'avg_revenue_per_order': round(avg_revenue_per_order, 2),
                    'price_position': price_position
                },
                'benchmarks': {
                    'industry_avg_price': round(industry_avg_price, 2),
                    'industry_avg_revenue': round(industry_avg_revenue, 2),
                    'price_diff_pct': price_diff_pct,
                    'revenue_diff_pct': revenue_diff_pct
                },
                'trend': _analyze_trend(data['invoices'], bi_records)
            })
        
        # Sort by performance score (worst first for attention)
        products_analysis.sort(key=lambda x: x['performance_score'])
        
        # ============================================================
        # 4. GENERATE AI INSIGHTS (if available)
        # ============================================================
        ai_insights = []
        
        if OPENAI_API_KEY:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=OPENAI_API_KEY)
                
                # Analyze top underperforming and top performing products
                underperforming = [p for p in products_analysis if p['performance_status'] == 'underperforming'][:3]
                outperforming = [p for p in products_analysis if p['performance_status'] == 'outperforming'][:3]
                
                if underperforming or outperforming:
                    prompt = f"""Analyze these product performance metrics and provide actionable business insights:

UNDERPERFORMING PRODUCTS:
{json.dumps(underperforming, indent=2)}

OUTPERFORMING PRODUCTS:
{json.dumps(outperforming, indent=2)}

INDUSTRY BENCHMARKS:
{json.dumps(industry_benchmarks, indent=2)}

Provide insights in JSON format:
{{
  "overall_insights": ["insight 1", "insight 2", "insight 3"],
  "product_recommendations": [
    {{
      "product_name": "Product Name",
      "issue": "What's wrong",
      "recommendation": "Specific action to take",
      "expected_impact": "Expected result"
    }}
  ],
  "industry_trends": ["trend 1", "trend 2"]
}}

Focus on: pricing strategy, demand patterns, competitive positioning, and revenue optimization."""

                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.7,
                        response_format={"type": "json_object"}
                    )
                    
                    ai_response = json.loads(completion.choices[0].message.content)
                    ai_insights = ai_response
                    
                    logger.info(f"✅ AI insights generated for {len(products_analysis)} products")
            
            except Exception as ai_error:
                logger.warning(f"⚠️ AI insights generation failed: {ai_error}")
        
        # ============================================================
        # 5. RETURN COMPREHENSIVE ANALYSIS
        # ============================================================
        return {
            "summary": {
                "total_products": len(products_analysis),
                "underperforming": len([p for p in products_analysis if p['performance_status'] == 'underperforming']),
                "optimal": len([p for p in products_analysis if p['performance_status'] == 'optimal']),
                "outperforming": len([p for p in products_analysis if p['performance_status'] == 'outperforming']),
                "total_revenue": round(sum(p['metrics']['total_revenue'] for p in products_analysis), 2)
            },
            "products": products_analysis,
            "industry_benchmarks": industry_benchmarks,
            "ai_insights": ai_insights,
            "date_range": {
                "start": cutoff_date.isoformat(),
                "end": datetime.utcnow().isoformat(),
                "days": days
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch industry intelligence: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch industry intelligence: {str(e)}"
        )


def _calculate_std_dev(values):
    """Calculate standard deviation"""
    if not values:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def _determine_performance_status(price_diff_pct, revenue_diff_pct, order_count, total_products):
    """Determine if product is underperforming, optimal, or outperforming"""
    # Score based on multiple factors
    score = 0
    
    # Revenue performance (most important)
    if revenue_diff_pct > 20:
        score += 2
    elif revenue_diff_pct > 0:
        score += 1
    elif revenue_diff_pct < -20:
        score -= 2
    else:
        score -= 1
    
    # Order frequency
    avg_orders = total_products / 3 if total_products > 3 else 1
    if order_count > avg_orders * 1.5:
        score += 1
    elif order_count < avg_orders * 0.5:
        score -= 1
    
    # Determine status
    if score >= 2:
        return 'outperforming'
    elif score <= -2:
        return 'underperforming'
    else:
        return 'optimal'


def _calculate_performance_score(price_diff_pct, revenue_diff_pct, order_count):
    """Calculate overall performance score (lower is worse, for sorting)"""
    # Negative score for underperformance
    score = revenue_diff_pct + (order_count * 5)
    return score


def _analyze_trend(invoices, all_records):
    """Analyze if product demand is increasing, stable, or declining"""
    # Simple trend analysis based on recent vs older invoices
    if len(invoices) < 2:
        return 'insufficient_data'
    
    # Get timestamps
    timestamps = []
    for record in all_records:
        if record.tracking_id in invoices:
            timestamps.append(record.created_at)
    
    timestamps.sort()
    
    if len(timestamps) < 2:
        return 'stable'
    
    # Compare first half vs second half
    mid = len(timestamps) // 2
    first_half = timestamps[:mid]
    second_half = timestamps[mid:]
    
    if len(second_half) > len(first_half) * 1.2:
        return 'increasing'
    elif len(second_half) < len(first_half) * 0.8:
        return 'declining'
    else:
        return 'stable'

