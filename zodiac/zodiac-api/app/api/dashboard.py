"""
Dashboard API endpoints for statistics, analytics, and AI insights
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, Numeric, inspect, text
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import json
import os
import re

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..models.correction_cache import CorrectionCache
from ..models.invoice_business_data import InvoiceBusinessData
from ..models.invoice_v2_business_data import InvoiceV2BusinessData
from ..models.invoice_v2_validated import InvoiceV2Validated
from ..models.invoice_v2_document import InvoiceV2Document
from ..models.sat_simple_merged import SATSimpleMerged
from ..models.sat_document import SATDocument
from ..models.supplier_token import SupplierToken
from ..models.converted_invoice import ConvertedInvoice
from ..api.auth import get_current_user
from ..config.config import OPENAI_API_KEY, USE_SAP_DB_FOR_AI
from ..database import get_sap_session
from ..services.database import extract_supplier_info_from_string
from ..services.file_service import read_file_from_storage
from ..services.invoice_v2_business_intelligence import InvoiceV2BusinessIntelligence
from ..services.sap_sql_agent import answer_with_sap_sql_agent
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
        # 1. OVERVIEW STATISTICS (Outbound Invoices)
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
        # 1b. SAT DOCUMENT STATISTICS (Inbound)
        # ============================================================
        try:
            # Use SATSimpleMerged which tracks sent_to_sap status
            # Total SAT merged documents (each represents a batch sent to SAP)
            sat_total = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id
            ).scalar() or 0
            
            # SAT documents successfully sent to SAP
            sat_sent_count = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.sent_to_sap == True
            ).scalar() or 0
            
            # SAT documents pending (not yet sent)
            sat_pending_count = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.sent_to_sap == False
            ).scalar() or 0
            
            logger.info(f"📄 SAT Stats: {sat_total} total, {sat_sent_count} sent to SAP, {sat_pending_count} pending")
        except Exception as sat_err:
            logger.warning(f"⚠️ Could not fetch SAT statistics: {sat_err}")
            sat_total = 0
            sat_sent_count = 0
            sat_pending_count = 0
        
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
            "sat_overview": {
                "total": sat_total,
                "sent_to_sap": sat_sent_count,
                "pending": sat_pending_count
            },
            "timeline": timeline_data if timeline_data else [],
            "format_distribution": format_distribution if format_distribution else [],
            "customer_distribution": customer_distribution,
            "request_type_distribution": request_type_distribution if request_type_distribution else [],
            "recent_activity": recent_activity,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days
            },
            "has_data": total_count > 0 or sat_total > 0
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
        # INBOUND: SAT Documents uploaded to send TO SAP
        # OUTBOUND: Invoices received FROM SAP and processed
        
        try:
            # Inbound: SAT Documents (files going TO SAP)
            # Use SATSimpleMerged which tracks sent_to_sap status
            inbound_total = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date
            ).scalar() or 0
            
            # Count how many were successfully sent to SAP (sent_to_sap = True)
            inbound_successful = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == True
            ).scalar() or 0
            
            # Failed/pending inbound (not yet sent to SAP)
            inbound_failed = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == False
            ).scalar() or 0
            
            logger.info(f"📥 Inbound (SAT): {inbound_total} total, {inbound_successful} sent to SAP, {inbound_failed} pending")
        except Exception as sat_err:
            logger.warning(f"⚠️ Could not fetch SAT inbound stats: {sat_err}")
            inbound_total = 0
            inbound_successful = 0
            inbound_failed = 0
        
        # Outbound: Invoices (files FROM SAP being processed)
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
        has_operations_data = (
            (inbound_successful + inbound_failed) > 0 or 
            (outbound_successful + outbound_failed) > 0
        )
        
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
                "breakdown": auto_fix_list if auto_fix_list else []
            },
            "processingTime": {
                "hourly": processing_time_data if processing_time_data else [],
                "average": round(
                    sum(pt['avgTime'] for pt in processing_time_data) / len(processing_time_data), 2
                ) if processing_time_data else 0
            },
            "externalSystems": {
                "successful": external_success,
                "failed": external_failed,
                "pending": external_pending,
                "total": external_success + external_failed + external_pending
            },
            "has_data": has_operations_data
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch operations statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch operations statistics: {str(e)}"
        )


# ==================== Dashboard v2 endpoints ====================


@router.get("/v2/inbound")
async def get_dashboard_v2_inbound(
    days: int = Query(default=30, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dashboard v2 - Inbound process stats (SAT documents, merges, suppliers by RFC, tokens)."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        total_documents = db.query(func.count(SATDocument.id)).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.received_at >= cutoff_date
        ).scalar() or 0

        doc_type_rows = db.query(
            SATDocument.doc_type,
            func.count(SATDocument.id).label("count")
        ).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.received_at >= cutoff_date
        ).group_by(SATDocument.doc_type).all()
        by_document_type = [{"doc_type": row.doc_type, "count": row.count} for row in doc_type_rows]

        source_rows = db.query(
            SATDocument.source,
            func.count(SATDocument.id).label("count")
        ).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.received_at >= cutoff_date
        ).group_by(SATDocument.source).all()
        by_source = [{"source": row.source, "count": row.count} for row in source_rows]

        period_rows = db.query(
            SATDocument.fiscal_year,
            SATDocument.fiscal_period,
            func.count(SATDocument.id).label("count")
        ).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.received_at >= cutoff_date,
            SATDocument.fiscal_year.isnot(None),
            SATDocument.fiscal_period.isnot(None)
        ).group_by(SATDocument.fiscal_year, SATDocument.fiscal_period).order_by(
            SATDocument.fiscal_year.desc(),
            SATDocument.fiscal_period.desc()
        ).limit(24).all()
        by_period = [
            {"fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period, "count": r.count}
            for r in period_rows
        ]

        supplier_rows = db.query(
            SATDocument.supplier_rfc,
            SATDocument.supplier_name,
            func.count(SATDocument.id).label("count"),
            func.coalesce(
                func.sum(cast(func.nullif(func.trim(SATDocument.total), ""), Numeric(15, 2))),
                0
            ).label("total_amount")
        ).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.received_at >= cutoff_date
        ).group_by(SATDocument.supplier_rfc, SATDocument.supplier_name).order_by(
            func.count(SATDocument.id).desc()
        ).limit(10).all()
        top_suppliers = [
            {
                "supplier_rfc": r.supplier_rfc,
                "supplier_name": r.supplier_name or r.supplier_rfc,
                "count": r.count,
                "total_amount": float(r.total_amount) if r.total_amount is not None else 0.0,
            }
            for r in supplier_rows
        ]

        merges_total = db.query(func.count(SATSimpleMerged.id)).filter(
            SATSimpleMerged.user_id == current_user.id,
            SATSimpleMerged.created_at >= cutoff_date
        ).scalar() or 0
        merges_sent = db.query(func.count(SATSimpleMerged.id)).filter(
            SATSimpleMerged.user_id == current_user.id,
            SATSimpleMerged.created_at >= cutoff_date,
            SATSimpleMerged.sent_to_sap == True
        ).scalar() or 0
        merges_pending = db.query(func.count(SATSimpleMerged.id)).filter(
            SATSimpleMerged.user_id == current_user.id,
            SATSimpleMerged.created_at >= cutoff_date,
            SATSimpleMerged.sent_to_sap == False
        ).scalar() or 0

        token_total = db.query(func.count(SupplierToken.id)).scalar() or 0
        token_active = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.is_active == True,
            (SupplierToken.expires_at.is_(None)) | (SupplierToken.expires_at >= datetime.utcnow())
        ).scalar() or 0
        token_expired = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.expires_at < datetime.utcnow(),
            SupplierToken.is_active == True
        ).scalar() or 0
        token_recently_used = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.last_used_at >= (datetime.utcnow() - timedelta(days=7))
        ).scalar() or 0

        return {
            "summary": {
                "total_documents": total_documents,
                "merges_total": merges_total,
                "merges_sent_to_sap": merges_sent,
                "merges_pending": merges_pending,
            },
            "by_document_type": by_document_type,
            "by_source": by_source,
            "by_period": by_period,
            "top_suppliers": top_suppliers,
            "tokens": {
                "total": token_total,
                "active": token_active,
                "expired": token_expired,
                "recently_used": token_recently_used,
            },
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 inbound: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/v2/outbound")
async def get_dashboard_v2_outbound(
    days: int = Query(default=30, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dashboard v2 - Outbound process stats (V2 documents, validated, converted)."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        documents_received = db.query(func.count(InvoiceV2Document.id)).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.deleted_at.is_(None),
            InvoiceV2Document.uploaded_at >= cutoff_date
        ).scalar() or 0

        validated_query = db.query(
            InvoiceV2Validated.status,
            func.count(InvoiceV2Validated.id).label("count")
        ).join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.uploaded_at >= cutoff_date
        ).group_by(InvoiceV2Validated.status).all()
        validated_success = sum(c for s, c in validated_query if s == "success")
        validated_failed = sum(c for s, c in validated_query if s == "failed")

        converted_query = db.query(
            ConvertedInvoice.conversion_status,
            func.count(ConvertedInvoice.id).label("count")
        ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
            InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.uploaded_at >= cutoff_date
        ).group_by(ConvertedInvoice.conversion_status).all()
        converted_success = sum(c for s, c in converted_query if s == "success")
        converted_failed = sum(c for s, c in converted_query if s == "failed")
        converted_pending = sum(c for s, c in converted_query if s == "pending")
        converted_total = converted_success + converted_failed + converted_pending

        format_rows = db.query(
            ConvertedInvoice.target_format,
            func.count(ConvertedInvoice.id).label("count")
        ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
            InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.uploaded_at >= cutoff_date,
            ConvertedInvoice.conversion_status == "success"
        ).group_by(ConvertedInvoice.target_format).all()
        by_format = [{"format": r.target_format, "count": r.count} for r in format_rows]

        customer_rows = db.query(
            ConvertedInvoice.customer_id,
            func.max(InvoiceV2Validated.invoice_data["customer_name"].astext).label("customer_name"),
            func.max(InvoiceV2Validated.invoice_data["currency"].astext).label("currency"),
            func.count(ConvertedInvoice.id).label("count"),
        ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
            InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.uploaded_at >= cutoff_date
        ).filter(ConvertedInvoice.customer_id.isnot(None)).group_by(
            ConvertedInvoice.customer_id
        ).order_by(func.count(ConvertedInvoice.id).desc()).limit(10).all()
        top_customers = [
            {
                "customer_id": r.customer_id,
                "customer_name": r.customer_name or r.customer_id,
                "currency": r.currency or "—",
                "count": r.count,
            }
            for r in customer_rows
        ]

        timeline_docs = db.query(
            cast(InvoiceV2Document.uploaded_at, Date).label("date"),
            func.count(InvoiceV2Document.id).label("count")
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.deleted_at.is_(None),
            InvoiceV2Document.uploaded_at >= cutoff_date
        ).group_by(cast(InvoiceV2Document.uploaded_at, Date)).order_by(
            cast(InvoiceV2Document.uploaded_at, Date)
        ).all()
        timeline = [{"date": d.date.strftime("%Y-%m-%d") if d.date else None, "documents": d.count} for d in timeline_docs]

        validation_rate = (validated_success / (validated_success + validated_failed) * 100) if (validated_success + validated_failed) > 0 else 0
        conversion_rate = (converted_success / converted_total * 100) if converted_total > 0 else 0

        return {
            "funnel": {
                "documents_received": documents_received,
                "validated_success": validated_success,
                "validated_failed": validated_failed,
                "converted_success": converted_success,
                "converted_failed": converted_failed,
                "converted_pending": converted_pending,
                "converted_total": converted_total,
            },
            "summary": {
                "documents_received": documents_received,
                "validated_total": validated_success + validated_failed,
                "validated_success": validated_success,
                "validated_failed": validated_failed,
                "validation_success_rate_pct": round(validation_rate, 1),
                "converted_total": converted_total,
                "converted_success": converted_success,
                "converted_failed": converted_failed,
                "converted_pending": converted_pending,
                "conversion_success_rate_pct": round(conversion_rate, 1),
            },
            "by_format": by_format,
            "top_customers": top_customers,
            "timeline": timeline,
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 outbound: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/v2/failed-invoices-analysis")
async def get_dashboard_v2_failed_invoices_analysis(
    days: int = Query(default=30, ge=1, le=365),
    demo: bool = Query(default=False, description="Return mock data for UI preview"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dashboard v2 - Failed invoices analytics: failure reasons, one-time vs repetitive, revenue loss."""
    if demo:
        return {
            "total_failed": 4,
            "failure_reasons": [
                {"reason": "missing:customer_name,tax_percentage", "count": 2},
                {"reason": "Invalid date format (issue_date)", "count": 1},
                {"reason": "Invalid currency code", "count": 1},
            ],
            "one_time_count": 2,
            "repetitive_count": 1,
            "repetitive_customer_ids": ["CUST-002"],
            "revenue_loss_by_currency": {"USD": 1250.5, "MXN": 15000.0},
            "by_date": [
                {"date": (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d"), "failed_count": 2, "revenue_loss": 500.0},
                {"date": (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"), "failed_count": 2, "revenue_loss": 750.5},
            ],
        }
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        failed_list = (
            db.query(InvoiceV2Validated)
            .join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id)
            .filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.deleted_at.is_(None),
                InvoiceV2Document.uploaded_at >= cutoff_date,
                InvoiceV2Validated.status == "failed",
            )
            .order_by(InvoiceV2Validated.validated_at.desc())
            .all()
        )
        total_failed = len(failed_list)

        failure_reasons_map = defaultdict(int)
        revenue_by_currency = defaultdict(float)
        customer_fail_counts = defaultdict(int)
        by_date_map = defaultdict(lambda: {"failed_count": 0, "revenue_loss": 0.0})

        for v in failed_list:
            reasons = []
            if v.missing_fields:
                key = "missing:" + ",".join(sorted(v.missing_fields))
                reasons.append(key)
            if v.validation_errors:
                for err in v.validation_errors if isinstance(v.validation_errors, list) else []:
                    if isinstance(err, dict):
                        msg = err.get("message", "") or err.get("field", "error")
                        reasons.append((msg[:50] + "..") if len(msg) > 50 else msg)
                    else:
                        reasons.append("validation_error")
            if not reasons:
                reasons.append("unknown")
            for r in reasons:
                failure_reasons_map[r] += 1

            inv = v.invoice_data or {}
            try:
                total_val = inv.get("total") or inv.get("payable_amount")
                if total_val is not None:
                    amt = float(total_val) if not isinstance(total_val, (int, float)) else float(total_val)
                    cur = (inv.get("currency") or "USD").strip() or "USD"
                    revenue_by_currency[cur] += amt
            except (TypeError, ValueError):
                pass

            cid = (inv.get("customer_id") or "").strip() or "unknown"
            customer_fail_counts[cid] += 1

            vdate = v.validated_at.date() if v.validated_at else None
            if vdate:
                by_date_map[vdate.strftime("%Y-%m-%d")]["failed_count"] += 1
                try:
                    total_val = inv.get("total") or inv.get("payable_amount")
                    if total_val is not None:
                        amt = float(total_val) if not isinstance(total_val, (int, float)) else float(total_val)
                        by_date_map[vdate.strftime("%Y-%m-%d")]["revenue_loss"] += amt
                except (TypeError, ValueError):
                    pass

        one_time_count = sum(1 for c in customer_fail_counts.values() if c == 1)
        repetitive_count = sum(1 for c in customer_fail_counts.values() if c > 1)
        repetitive_customer_ids = [cid for cid, count in customer_fail_counts.items() if count > 1 and cid != "unknown"]

        failure_reasons = [{"reason": r, "count": c} for r, c in sorted(failure_reasons_map.items(), key=lambda x: -x[1])]
        revenue_loss_by_currency = dict(revenue_by_currency)
        by_date = [
            {"date": d, "failed_count": by_date_map[d]["failed_count"], "revenue_loss": round(by_date_map[d]["revenue_loss"], 2)}
            for d in sorted(by_date_map.keys())
        ]

        return {
            "total_failed": total_failed,
            "failure_reasons": failure_reasons,
            "one_time_count": one_time_count,
            "repetitive_count": repetitive_count,
            "repetitive_customer_ids": repetitive_customer_ids,
            "revenue_loss_by_currency": revenue_loss_by_currency,
            "by_date": by_date,
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 failed-invoices-analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/v2/failed-invoices-ai-insights")
async def get_dashboard_v2_failed_invoices_ai_insights(
    days: int = Query(default=30, ge=1, le=365),
    demo: bool = Query(default=False, description="Return mock AI insights for UI preview"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dashboard v2 - AI insights for failed invoices (summary, insights, recommendations, root causes)."""
    if demo:
        return {
            "summary": "Demo: 4 failed invoices in the period. Main issues are missing required fields (customer_name, tax_percentage), invalid date format, and invalid currency. One customer has repetitive failures.",
            "insights": [
                "Missing customer_name and tax_percentage is the most frequent failure reason (2 invoices).",
                "One customer (CUST-002) has multiple failures; consider a dedicated review for this customer.",
                "Revenue at risk: USD 1,250.50 and MXN 15,000.00 across failed validations.",
            ],
            "recommendations": [
                "Ensure UBL invoices include AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name and tax percentage where required.",
                "Validate date formats (issue_date, due_date) against ISO 8601 before submission.",
                "Review currency codes against ISO 4217; fix invalid or empty currency in source systems.",
            ],
            "root_causes": [
                "Incomplete or blank required fields in supplier XML export.",
                "Date/currency format mismatches between ERP and validation rules.",
            ],
            "revenue_impact_note": "Total revenue at risk: USD 1,250.50, MXN 15,000.00.",
            "analyzed_at": datetime.utcnow().isoformat(),
        }
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        failed_list = (
            db.query(InvoiceV2Validated)
            .join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id)
            .filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.deleted_at.is_(None),
                InvoiceV2Document.uploaded_at >= cutoff_date,
                InvoiceV2Validated.status == "failed",
            )
            .order_by(InvoiceV2Validated.validated_at.desc())
            .limit(50)
            .all()
        )
        if not failed_list:
            return {
                "summary": "No failed invoices in this period.",
                "insights": [],
                "recommendations": [],
                "root_causes": [],
                "revenue_impact_note": None,
                "analyzed_at": datetime.utcnow().isoformat(),
            }
        failure_reasons_map = defaultdict(int)
        revenue_by_currency = defaultdict(float)
        customer_fail_counts = defaultdict(int)
        examples = []
        for v in failed_list[:10]:
            inv = v.invoice_data or {}
            reasons = []
            if v.missing_fields:
                reasons.append("missing: " + ", ".join(v.missing_fields))
            if v.validation_errors and isinstance(v.validation_errors, list):
                for err in v.validation_errors:
                    if isinstance(err, dict):
                        reasons.append(err.get("message", err.get("field", "error")))
            if not reasons:
                reasons.append("unknown")
            examples.append({
                "customer_id": inv.get("customer_id", "—"),
                "customer_name": inv.get("customer_name", "—"),
                "total": inv.get("total") or inv.get("payable_amount"),
                "currency": inv.get("currency", "—"),
                "reasons": reasons,
            })
            if v.missing_fields:
                key = "missing:" + ",".join(sorted(v.missing_fields))
                failure_reasons_map[key] += 1
            if v.validation_errors and isinstance(v.validation_errors, list):
                for err in v.validation_errors:
                    if isinstance(err, dict):
                        msg = (err.get("message") or err.get("field") or "error")[:80]
                        failure_reasons_map[msg] += 1
            try:
                total_val = inv.get("total") or inv.get("payable_amount")
                if total_val is not None:
                    amt = float(total_val) if not isinstance(total_val, (int, float)) else float(total_val)
                    cur = (inv.get("currency") or "USD").strip() or "USD"
                    revenue_by_currency[cur] += amt
            except (TypeError, ValueError):
                pass
            cid = (inv.get("customer_id") or "").strip() or "unknown"
            customer_fail_counts[cid] += 1
        one_time = sum(1 for c in customer_fail_counts.values() if c == 1)
        repetitive = sum(1 for c in customer_fail_counts.values() if c > 1)
        top_reasons = sorted(failure_reasons_map.items(), key=lambda x: -x[1])[:8]
        reason_text = "\n".join([f"- {r}: {c} occurrences" for r, c in top_reasons])
        revenue_text = ", ".join([f"{cur} {amt:.2f}" for cur, amt in revenue_by_currency.items()])
        examples_text = "\n".join([
            f"Customer {ex['customer_id']} ({ex['customer_name']}), total {ex['currency']} {ex['total']}: " + "; ".join(ex["reasons"])
            for ex in examples[:3]
        ])
        context = f"""
Failed invoices in period: {len(failed_list)} (showing up to 50).

Failure reason counts:
{reason_text}

Revenue at risk by currency: {revenue_text or 'None'}

One-time failures (customers with 1 failure): {one_time}. Repetitive (customers with >1 failure): {repetitive}.

Example failed invoices and their reasons:
{examples_text}
"""
        if OPENAI_API_KEY and openai_available:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                prompt = f"""
You are an expert e-invoice and UBL analyst. Analyze the following failed invoice validation data and provide actionable insights.

{context}

Provide a JSON response with this exact structure:
{{
    "summary": "Brief 2-3 sentence overview of the main issues",
    "insights": ["Specific insight 1", "Specific insight 2", "Specific insight 3"],
    "recommendations": ["Actionable recommendation 1", "Actionable recommendation 2", "Actionable recommendation 3"],
    "root_causes": ["Root cause 1", "Root cause 2"],
    "revenue_impact_note": "One sentence on revenue at risk by currency, or null if none"
}}

Focus on: common patterns, missing/required fields, format issues, repetitive vs one-time, and practical fixes.
Respond ONLY with valid JSON, no markdown or extra text.
"""
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                ai_response = json.loads(completion.choices[0].message.content)
                return {
                    "summary": ai_response.get("summary", "Analysis complete."),
                    "insights": ai_response.get("insights", []),
                    "recommendations": ai_response.get("recommendations", []),
                    "root_causes": ai_response.get("root_causes", []),
                    "revenue_impact_note": ai_response.get("revenue_impact_note"),
                    "analyzed_at": datetime.utcnow().isoformat(),
                }
            except Exception as ai_err:
                logger.warning(f"V2 failed-invoices AI insights OpenAI error: {ai_err}")
        top_3 = top_reasons[:3]
        return {
            "summary": f"Analyzed {len(failed_list)} failed invoices. Top issues: " + "; ".join([f"{r} ({c})" for r, c in top_3]) + ".",
            "insights": [
                f"Most frequent: {top_3[0][0]} ({top_3[0][1]} occurrences)" if top_3 else "No patterns",
                "Review missing_fields and validation_errors in the Failed tab for details.",
                f"Revenue at risk: {revenue_text}" if revenue_text else "No revenue totals in failed records.",
            ],
            "recommendations": [
                "Fix missing required fields in source XML (see failure_reasons).",
                "Validate date and currency formats before upload.",
                "For repetitive failures by customer, check customer-specific configuration.",
            ],
            "root_causes": [
                "Missing or invalid required UBL fields.",
                "Format validation failures (dates, amounts, codes).",
            ],
            "revenue_impact_note": f"Total at risk: {revenue_text}" if revenue_text else None,
            "analyzed_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 failed-invoices-ai-insights: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/v2/business")
async def get_dashboard_v2_business(
    days: int = Query(default=90, ge=1, le=365),
    currency: str = Query(default=None, description="Filter by currency code (e.g. NZD, USD). Omit for all."),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dashboard v2 - Business: products by industry, industry breakdown, trend. Data comes from successful invoices' line_items."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        rows = db.query(InvoiceV2BusinessData).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.products.isnot(None),
            InvoiceV2BusinessData.industry.isnot(None),
        ).all()

        # If no BI data yet but user has successful validated invoices, backfill from line_items
        if not rows:
            success_count = db.query(InvoiceV2Validated).join(
                InvoiceV2Document,
                InvoiceV2Validated.document_id == InvoiceV2Document.id
            ).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Validated.status == "success"
            ).count()
            if success_count > 0:
                _run_backfill_invoice_v2_bi(db, current_user, max_invoices=500)
                rows = db.query(InvoiceV2BusinessData).filter(
                    InvoiceV2BusinessData.user_id == current_user.id,
                    InvoiceV2BusinessData.created_at >= cutoff_date,
                    InvoiceV2BusinessData.products.isnot(None),
                    InvoiceV2BusinessData.industry.isnot(None),
                ).all()

        # Revenue by currency (from full dataset, before currency filter)
        currency_revenue = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})
        for r in rows:
            curr = (r.currency or "Unknown").strip() or "Unknown"
            currency_revenue[curr]["count"] += 1
            currency_revenue[curr]["revenue"] += (r.total_amount or Decimal("0"))
        revenue_by_currency = [
            {
                "currency": curr,
                "invoice_count": int(data["count"]),
                "total_revenue": float(data["revenue"]),
            }
            for curr, data in sorted(currency_revenue.items(), key=lambda x: -x[1]["revenue"])
        ][:15]

        # Currency filter (optional): restrict to selected currency
        if currency and str(currency).strip():
            curr_upper = str(currency).strip().upper()
            rows = [r for r in rows if (r.currency or "").strip().upper() == curr_upper]

        product_industry = defaultdict(lambda: {"count": 0, "revenue": Decimal("0"), "quantity": Decimal("0"), "unit_counts": defaultdict(int)})
        industry_totals = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})

        for r in rows:
            industry = r.industry or "General"
            amount = (r.total_amount or Decimal("0"))
            products = r.products if isinstance(r.products, list) else []
            industry_totals[industry]["count"] += 1
            industry_totals[industry]["revenue"] += amount
            for p in products:
                if not isinstance(p, dict):
                    continue
                name = (p.get("name") or p.get("item_name") or "Unknown").strip() or "Unknown"
                key = (name, industry)
                product_industry[key]["count"] += 1
                unit = (p.get("unit_code") or "").strip() or None
                if unit:
                    product_industry[key]["unit_counts"][unit] += 1
                qty = p.get("quantity")
                if qty is not None:
                    try:
                        product_industry[key]["quantity"] += Decimal(str(qty))
                    except Exception:
                        pass
                line_revenue = p.get("revenue") or p.get("line_extension_amount")
                if line_revenue is not None:
                    try:
                        product_industry[key]["revenue"] += Decimal(str(line_revenue))
                    except Exception:
                        product_industry[key]["revenue"] += amount / len(products) if products else amount
                else:
                    product_industry[key]["revenue"] += amount / len(products) if products else amount

        def _most_common_unit(unit_counts):
            if not unit_counts:
                return None
            return max(unit_counts.items(), key=lambda x: x[1])[0]

        products_by_industry = [
            {
                "product_name": name,
                "industry": ind,
                "unit_of_measure": _most_common_unit(data["unit_counts"]) or "—",
                "invoice_count": data["count"],
                "revenue": float(data["revenue"]),
            }
            for (name, ind), data in sorted(product_industry.items(), key=lambda x: -x[1]["revenue"])
        ][:100]

        # Quantity & price analysis: total units sold, avg price per product+industry (for scatter chart)
        quantity_price_analysis = []
        for (name, ind), data in product_industry.items():
            total_qty = float(data["quantity"])
            rev = float(data["revenue"])
            avg_price = (rev / total_qty) if total_qty and total_qty > 0 else None
            quantity_price_analysis.append({
                "product_name": name,
                "industry": ind,
                "unit_of_measure": _most_common_unit(data["unit_counts"]) or "—",
                "total_quantity": round(total_qty, 2),
                "avg_price": round(avg_price, 2) if avg_price is not None else None,
                "revenue": rev,
            })
        quantity_price_analysis = sorted(
            [x for x in quantity_price_analysis if x["total_quantity"] > 0],
            key=lambda x: -x["total_quantity"]
        )[:50]

        industry_breakdown = [
            {"industry": ind, "count": data["count"], "total_revenue": float(data["revenue"])}
            for ind, data in sorted(industry_totals.items(), key=lambda x: -x[1]["revenue"])
        ]

        # Revenue by customer (customer_id = RFC from successful data)
        customer_revenue = defaultdict(lambda: {"customer_name": None, "count": 0, "revenue": Decimal("0")})
        for r in rows:
            cid = r.customer_id or "Unknown"
            customer_revenue[cid]["customer_name"] = r.customer_name or cid
            customer_revenue[cid]["count"] += 1
            customer_revenue[cid]["revenue"] += (r.total_amount or Decimal("0"))
        revenue_by_customer = [
            {
                "customer_id": cid,
                "customer_name": data["customer_name"] or cid,
                "invoice_count": data["count"],
                "total_revenue": float(data["revenue"]),
            }
            for cid, data in sorted(customer_revenue.items(), key=lambda x: -x[1]["revenue"])
        ][:50]

        # Revenue by country (customer_country from successful invoices)
        country_revenue = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})
        for r in rows:
            country = r.customer_country or "Unknown"
            country_revenue[country]["count"] += 1
            country_revenue[country]["revenue"] += (r.total_amount or Decimal("0"))
        revenue_by_country = [
            {
                "country": country,
                "country_name": _country_code_to_name(country),
                "invoice_count": int(data["count"]),
                "total_revenue": float(data["revenue"]),
            }
            for country, data in sorted(country_revenue.items(), key=lambda x: -x[1]["revenue"])
        ][:20]

        # Customers by country (distinct customers per country - histogram)
        country_customers = defaultdict(set)  # country -> set of customer_id
        for r in rows:
            country = r.customer_country or "Unknown"
            cust_key = r.customer_id or r.customer_name or f"anon_{r.id}"
            country_customers[country].add(cust_key)
        customers_by_country = [
            {
                "country": country,
                "country_name": _country_code_to_name(country),
                "customer_count": len(cust_set),
            }
            for country, cust_set in sorted(country_customers.items(), key=lambda x: -len(x[1]))
        ][:20]

        mid = cutoff_date + (datetime.utcnow() - cutoff_date) / 2
        prev_cutoff = cutoff_date - (datetime.utcnow() - cutoff_date)
        current_revenue = db.query(func.coalesce(func.sum(InvoiceV2BusinessData.total_amount), 0)).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= mid,
        ).scalar() or 0
        previous_revenue = db.query(func.coalesce(func.sum(InvoiceV2BusinessData.total_amount), 0)).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= prev_cutoff,
            InvoiceV2BusinessData.created_at < mid,
        ).scalar() or 0
        try:
            current_revenue = float(current_revenue)
            previous_revenue = float(previous_revenue)
        except Exception:
            current_revenue = previous_revenue = 0.0
        trend_pct = ((current_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue else 0.0

        trend = {
            "current_period_revenue": current_revenue,
            "previous_period_revenue": previous_revenue,
            "revenue_change_pct": round(trend_pct, 1),
        }

        # AI insights about the whole business tab (using existing API key)
        ai_insights = None
        if OPENAI_API_KEY and openai_available and rows:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                prompt = f"""You are a business analyst. Based on the following dashboard data (from validated invoices), provide concise AI insights in JSON format.

REVENUE TREND:
- Current period revenue: {current_revenue}
- Previous period revenue: {previous_revenue}
- Change: {trend_pct:+.1f}%

INDUSTRY BREAKDOWN (top 10):
{json.dumps(industry_breakdown[:10], indent=2)}

REVENUE BY CUSTOMER (top 10):
{json.dumps(revenue_by_customer[:10], indent=2)}

REVENUE BY COUNTRY (top 10):
{json.dumps(revenue_by_country[:10], indent=2)}

REVENUE BY CURRENCY:
{json.dumps(revenue_by_currency, indent=2)}

CUSTOMERS BY COUNTRY (top 10):
{json.dumps(customers_by_country[:10], indent=2)}

PRODUCTS BY INDUSTRY (top 15):
{json.dumps(products_by_industry[:15], indent=2)}

Respond with a single JSON object with this structure (no markdown, only valid JSON):
{{
  "summary": "2-3 sentence overall summary of the business situation",
  "revenue_insights": ["insight about revenue trend"],
  "industry_insights": ["insight about industry mix"],
  "customer_insights": ["insight about top customers / concentration"],
  "country_insights": ["insight about geographic distribution / top countries"],
  "currency_insights": ["insight about revenue by currency / multi-currency mix"],
  "product_insights": ["insight about product performance"],
  "recommendations": ["1-3 actionable recommendations"]
}}"""

                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                    response_format={"type": "json_object"},
                )
                ai_insights = json.loads(completion.choices[0].message.content)
                logger.info("AI business insights generated for v2/business")
            except Exception as ai_err:
                logger.warning(f"AI insights for v2/business failed: {ai_err}")
                ai_insights = None

        return {
            "products_by_industry": products_by_industry,
            "industry_breakdown": industry_breakdown,
            "quantity_price_analysis": quantity_price_analysis,
            "revenue_by_customer": revenue_by_customer,
            "revenue_by_country": revenue_by_country,
            "revenue_by_currency": revenue_by_currency,
            "customers_by_country": customers_by_country,
            "trend": trend,
            "ai_insights": ai_insights,
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 business: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/v2/sap-historical")
async def get_dashboard_sap_historical(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Dashboard analytics from SAP migrated data (1994-2010).
    Queries VBRP (billing items), VBRK (billing header), KNA1 (customer master), 
    T016T (industry text) tables for historical analysis.
    
    Returns revenue trends, top customers, top products, country/industry breakdowns
    from the migrated SAP dataset (1994-2010 period).
    """
    try:
        logger.info(f"📊 Fetching SAP historical dashboard for user {current_user.id}")
        
        # Date range for SAP historical data (1994-2010)
        start_date = '1994-01-01'
        end_date = '2010-12-31'
        
        # Check if SAP tables exist
        inspector = inspect(db.bind)
        available_tables = [t.lower() for t in inspector.get_table_names()]
        has_vbrp = 'vbrp' in available_tables
        has_vbrk = 'vbrk' in available_tables
        has_kna1 = 'kna1' in available_tables
        
        if not (has_vbrp and has_vbrk):
            logger.warning("SAP tables (VBRP, VBRK) not found in database")
            return {
                "period": {"start_date": start_date, "end_date": end_date},
                "summary": {
                    "total_revenue": 0,
                    "total_invoices": 0,
                    "unique_customers": 0,
                    "unique_products": 0,
                    "date_range": {"min": start_date, "max": end_date}
                },
                "revenue_trend": [],
                "revenue_by_customer": [],
                "revenue_by_product": [],
                "revenue_by_country": [],
                "revenue_by_industry": [],
                "message": "SAP historical data tables not available"
            }
        
        # === SUMMARY STATISTICS ===
        summary_query = text("""
            SELECT 
                COUNT(DISTINCT vbrk.vbeln) as total_invoices,
                COALESCE(SUM(vbrp.netwr), 0) as total_revenue,
                COUNT(DISTINCT vbrk.kunag) as unique_customers,
                COUNT(DISTINCT vbrp.matnr) as unique_products,
                MIN(vbrk.fkdat) as min_date,
                MAX(vbrk.fkdat) as max_date
            FROM vbrp
            JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
            WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
        """)
        summary_result = db.execute(summary_query, {"start_date": start_date, "end_date": end_date}).fetchone()
        
        summary = {
            "total_revenue": float(summary_result[1] if summary_result[1] else 0),
            "total_invoices": int(summary_result[0] if summary_result[0] else 0),
            "unique_customers": int(summary_result[2] if summary_result[2] else 0),
            "unique_products": int(summary_result[3] if summary_result[3] else 0),
            "date_range": {
                "min": str(summary_result[4]) if summary_result[4] else start_date,
                "max": str(summary_result[5]) if summary_result[5] else end_date
            }
        }
        
        # === REVENUE TREND (by year) ===
        trend_query = text("""
            SELECT 
                EXTRACT(YEAR FROM vbrk.fkdat)::INTEGER as year,
                COUNT(DISTINCT vbrk.vbeln) as invoice_count,
                COALESCE(SUM(vbrp.netwr), 0) as total_revenue
            FROM vbrp
            JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
            WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
            GROUP BY EXTRACT(YEAR FROM vbrk.fkdat)
            ORDER BY year ASC
        """)
        trend_results = db.execute(trend_query, {"start_date": start_date, "end_date": end_date}).fetchall()
        
        revenue_trend = [
            {
                "year": int(row[0]),
                "invoice_count": int(row[1]),
                "total_revenue": float(row[2])
            }
            for row in trend_results
        ]
        
        # === REVENUE BY CUSTOMER ===
        if has_kna1:
            customer_query = text("""
                SELECT 
                    vbrk.kunag as customer_id,
                    COALESCE(kna1.name1, vbrk.kunag) as customer_name,
                    COALESCE(kna1.land1, 'Unknown') as country,
                    COUNT(DISTINCT vbrk.vbeln) as invoice_count,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                LEFT JOIN kna1 ON vbrk.kunag = kna1.kunnr
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY vbrk.kunag, kna1.name1, kna1.land1
                ORDER BY total_revenue DESC
                LIMIT 50
            """)
        else:
            customer_query = text("""
                SELECT 
                    vbrk.kunag as customer_id,
                    vbrk.kunag as customer_name,
                    'Unknown' as country,
                    COUNT(DISTINCT vbrk.vbeln) as invoice_count,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY vbrk.kunag
                ORDER BY total_revenue DESC
                LIMIT 50
            """)
        
        customer_results = db.execute(customer_query, {"start_date": start_date, "end_date": end_date}).fetchall()
        
        revenue_by_customer = [
            {
                "customer_id": str(row[0]) if row[0] else "Unknown",
                "customer_name": str(row[1]) if row[1] else "Unknown",
                "country": str(row[2]) if row[2] else "Unknown",
                "invoice_count": int(row[3]),
                "total_revenue": float(row[4])
            }
            for row in customer_results
        ]
        
        # === REVENUE BY PRODUCT ===
        # Check if MAKT (material descriptions) table exists
        has_makt = 'makt' in available_tables
        
        if has_makt:
            product_query = text("""
                SELECT 
                    vbrp.matnr as product_id,
                    COALESCE(makt.maktx, vbrp.matnr) as product_name,
                    COALESCE(SUM(vbrp.fkimg), 0) as quantity,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                LEFT JOIN makt ON vbrp.matnr = makt.matnr AND makt.spras = 'E'
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY vbrp.matnr, makt.maktx
                ORDER BY total_revenue DESC
                LIMIT 50
            """)
        else:
            product_query = text("""
                SELECT 
                    vbrp.matnr as product_id,
                    vbrp.matnr as product_name,
                    COALESCE(SUM(vbrp.fkimg), 0) as quantity,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY vbrp.matnr
                ORDER BY total_revenue DESC
                LIMIT 50
            """)
        
        product_results = db.execute(product_query, {"start_date": start_date, "end_date": end_date}).fetchall()
        
        revenue_by_product = [
            {
                "product_id": str(row[0]) if row[0] else "Unknown",
                "product_name": str(row[1]) if row[1] else "Unknown",
                "quantity": float(row[2]),
                "total_revenue": float(row[3])
            }
            for row in product_results
        ]
        
        # === REVENUE BY COUNTRY ===
        if has_kna1:
            country_query = text("""
                SELECT 
                    COALESCE(kna1.land1, 'Unknown') as country,
                    COUNT(DISTINCT vbrk.vbeln) as invoice_count,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                LEFT JOIN kna1 ON vbrk.kunag = kna1.kunnr
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY kna1.land1
                ORDER BY total_revenue DESC
                LIMIT 20
            """)
            country_results = db.execute(country_query, {"start_date": start_date, "end_date": end_date}).fetchall()
            
            revenue_by_country = [
                {
                    "country": str(row[0]) if row[0] else "Unknown",
                    "invoice_count": int(row[1]),
                    "total_revenue": float(row[2])
                }
                for row in country_results
            ]
        else:
            revenue_by_country = []
        
        # === REVENUE BY INDUSTRY ===
        has_t016t = 't016t' in available_tables
        
        if has_kna1 and has_t016t:
            industry_query = text("""
                SELECT 
                    COALESCE(t016t.brtxt, 'General') as industry,
                    COUNT(DISTINCT vbrk.vbeln) as invoice_count,
                    COALESCE(SUM(vbrp.netwr), 0) as total_revenue
                FROM vbrp
                JOIN vbrk ON vbrp.vbeln = vbrk.vbeln
                LEFT JOIN kna1 ON vbrk.kunag = kna1.kunnr
                LEFT JOIN t016t ON kna1.brsch = t016t.brsch AND t016t.spras = 'E'
                WHERE vbrk.fkdat BETWEEN :start_date AND :end_date
                GROUP BY t016t.brtxt
                ORDER BY total_revenue DESC
                LIMIT 20
            """)
            industry_results = db.execute(industry_query, {"start_date": start_date, "end_date": end_date}).fetchall()
            
            revenue_by_industry = [
                {
                    "industry": str(row[0]) if row[0] else "General",
                    "invoice_count": int(row[1]),
                    "total_revenue": float(row[2])
                }
                for row in industry_results
            ]
        else:
            revenue_by_industry = []
        
        logger.info(f"✅ SAP historical dashboard fetched: {summary['total_invoices']} invoices, ${summary['total_revenue']:,.2f} revenue")
        
        return {
            "period": {"start_date": start_date, "end_date": end_date},
            "summary": summary,
            "revenue_trend": revenue_trend,
            "revenue_by_customer": revenue_by_customer,
            "revenue_by_product": revenue_by_product,
            "revenue_by_country": revenue_by_country,
            "revenue_by_industry": revenue_by_industry,
        }
        
    except Exception as e:
        logger.error(f"❌ Dashboard SAP historical: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/v2/customer-comparison")
async def get_dashboard_v2_customer_comparison(
    days: int = Query(default=90, ge=1, le=365),
    currency: str = Query(default=None, description="Filter by currency code. Omit for all."),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Customer comparison: per-customer product breakdown and revenue. For interactive customer vs customer analysis."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        rows = db.query(InvoiceV2BusinessData).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.products.isnot(None),
        ).all()

        if not rows:
            success_count = db.query(InvoiceV2Validated).join(
                InvoiceV2Document,
                InvoiceV2Validated.document_id == InvoiceV2Document.id
            ).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Validated.status == "success"
            ).count()
            if success_count > 0:
                _run_backfill_invoice_v2_bi(db, current_user, max_invoices=500)
                rows = db.query(InvoiceV2BusinessData).filter(
                    InvoiceV2BusinessData.user_id == current_user.id,
                    InvoiceV2BusinessData.created_at >= cutoff_date,
                    InvoiceV2BusinessData.products.isnot(None),
                ).all()

        # Currency filter
        if currency and str(currency).strip():
            curr_upper = str(currency).strip().upper()
            rows = [r for r in rows if (r.currency or "").strip().upper() == curr_upper]

        # Revenue by currency (for filter dropdown, from full dataset)
        all_rows = db.query(InvoiceV2BusinessData).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.products.isnot(None),
        ).all()
        curr_rev = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})
        for r in all_rows:
            c = (r.currency or "Unknown").strip() or "Unknown"
            curr_rev[c]["count"] += 1
            curr_rev[c]["revenue"] += (r.total_amount or Decimal("0"))
        revenue_by_currency = [
            {"currency": c, "invoice_count": d["count"], "total_revenue": float(d["revenue"])}
            for c, d in sorted(curr_rev.items(), key=lambda x: -x[1]["revenue"])
        ]

        # Aggregate: customer -> { total_revenue, invoice_count, industry_counts, currency_revenue, products }
        cust_data = defaultdict(lambda: {
            "customer_id": None,
            "customer_name": None,
            "customer_country": None,
            "invoice_count": 0,
            "total_revenue": Decimal("0"),
            "industry_counts": defaultdict(int),
            "currency_revenue": defaultdict(lambda: Decimal("0")),
            "products": defaultdict(lambda: {"revenue": Decimal("0"), "quantity": Decimal("0"), "unit": None}),
        })
        for r in rows:
            cid = r.customer_id or r.customer_name or f"anon_{r.id}"
            cust_data[cid]["customer_id"] = r.customer_id
            cust_data[cid]["customer_name"] = r.customer_name or cid
            cust_data[cid]["customer_country"] = r.customer_country
            cust_data[cid]["invoice_count"] += 1
            cust_data[cid]["total_revenue"] += (r.total_amount or Decimal("0"))
            if r.industry:
                cust_data[cid]["industry_counts"][r.industry] += 1
            curr = (r.currency or "Unknown").strip() or "Unknown"
            cust_data[cid]["currency_revenue"][curr] += (r.total_amount or Decimal("0"))
            products = r.products if isinstance(r.products, list) else []
            for p in products:
                if not isinstance(p, dict):
                    continue
                name = (p.get("name") or p.get("item_name") or "Unknown").strip() or "Unknown"
                rev = p.get("revenue") or p.get("line_extension_amount")
                qty = p.get("quantity")
                unit = (p.get("unit_code") or "").strip() or None
                try:
                    if rev is not None:
                        cust_data[cid]["products"][name]["revenue"] += Decimal(str(rev))
                    if qty is not None:
                        cust_data[cid]["products"][name]["quantity"] += Decimal(str(qty))
                    if unit:
                        cust_data[cid]["products"][name]["unit"] = unit
                except Exception:
                    pass

        # Revenue by country (for map)
        country_revenue = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})
        for r in rows:
            c = (r.customer_country or "Unknown").strip() or "Unknown"
            country_revenue[c]["count"] += 1
            country_revenue[c]["revenue"] += (r.total_amount or Decimal("0"))
        revenue_by_country = [
            {"country": c, "country_name": _country_code_to_name(c), "invoice_count": d["count"], "total_revenue": float(d["revenue"])}
            for c, d in sorted(country_revenue.items(), key=lambda x: -float(x[1]["revenue"]))
        ][:30]

        customers = []
        for cid, data in sorted(cust_data.items(), key=lambda x: -float(x[1]["total_revenue"])):
            products_list = [
                {
                    "product_name": pname,
                    "revenue": round(float(pdata["revenue"]), 2),
                    "quantity": round(float(pdata["quantity"]), 2),
                    "unit": pdata["unit"] or "—",
                }
                for pname, pdata in sorted(data["products"].items(), key=lambda y: -float(y[1]["revenue"]))
            ]
            industry = max(data["industry_counts"].items(), key=lambda x: x[1])[0] if data["industry_counts"] else None
            currencies = [{"currency": c, "revenue": round(float(rev), 2)} for c, rev in sorted(data["currency_revenue"].items(), key=lambda x: -float(x[1]))]
            customers.append({
                "customer_id": data["customer_id"],
                "customer_name": data["customer_name"],
                "customer_country": data["customer_country"],
                "industry": industry,
                "currencies": currencies,
                "invoice_count": data["invoice_count"],
                "total_revenue": round(float(data["total_revenue"]), 2),
                "products": products_list,
            })

        return {
            "customers": customers,
            "revenue_by_currency": revenue_by_currency,
            "revenue_by_country": revenue_by_country,
        }
    except Exception as e:
        logger.error(f"❌ Dashboard v2 customer-comparison: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/v2/customer-comparison-chat")
async def post_customer_comparison_chat(
    message: str = Body(..., embed=True),
    customer_a: dict = Body(..., embed=True),
    customer_b: dict = Body(..., embed=True),
    conversation_history: list = Body(default=[], embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """AI chat for customer comparison: initial summary and follow-up Q&A about two customers."""
    if not OPENAI_API_KEY or not openai_available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI chat not available (OpenAI key missing)")
    try:
        sys_content = f"""You are a business analyst assistant. The user is comparing two customers. Use ONLY the data below to answer. Be concise and factual.

CUSTOMER A:
- Name: {customer_a.get('customer_name', 'N/A')}
- Country: {customer_a.get('customer_country', 'N/A')}
- Industry: {customer_a.get('industry', 'N/A')}
- Total Revenue: {customer_a.get('total_revenue', 0)}
- Invoices: {customer_a.get('invoice_count', 0)}
- Currencies: {json.dumps(customer_a.get('currencies', []))}
- Top products: {json.dumps((customer_a.get('products') or [])[:5])}

CUSTOMER B:
- Name: {customer_b.get('customer_name', 'N/A')}
- Country: {customer_b.get('customer_country', 'N/A')}
- Industry: {customer_b.get('industry', 'N/A')}
- Total Revenue: {customer_b.get('total_revenue', 0)}
- Invoices: {customer_b.get('invoice_count', 0)}
- Currencies: {json.dumps(customer_b.get('currencies', []))}
- Top products: {json.dumps((customer_b.get('products') or [])[:5])}

Answer the user's question based only on this data. If asked for a summary first, provide 2-3 sentences comparing revenue, geography, industry, and product mix."""
        messages = [{"role": "system", "content": sys_content}]
        for h in conversation_history[-10:]:
            if isinstance(h, dict) and h.get("role") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])[:2000]})
        messages.append({"role": "user", "content": message[:1500]})
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
            max_tokens=500,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {"reply": reply}
    except Exception as e:
        logger.warning(f"Customer comparison chat failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


def _get_ai_analysis_config():
    """
    Use same env var names as invoice-bot (config.example) for the AI analysis page only.
    Enables a single set of env vars (e.g. OPENAI_API_KEY) for both invoice-bot and this page.
    """
    openai_key = os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY
    return openai_key


def _get_sales_by_product_from_vbrp(db: Session, limit: int = 10) -> list[dict]:
    """
    Highest sales by product from vbrp, enriched with:
    - product_name (from MAKT.MAKTX if available)
    - total_quantity (sum of FKIMG or similar)
    - unit_of_measure (VRKME / MEINS)
    - currency (from VBRK.WAERK if available)
    """
    bind = db.get_bind()
    if bind is None:
        return []

    inspector = inspect(bind)
    table_names = inspector.get_table_names()
    table_map = {name.lower(): name for name in table_names}

    vbrp_table = table_map.get("vbrp")
    if not vbrp_table:
        return []

    vbrp_cols = inspector.get_columns(vbrp_table)
    vbrp_map = {c["name"].lower(): c["name"] for c in vbrp_cols}

    product_candidates = ["matnr", "product_id", "material"]
    value_candidates = ["netwr", "net_value", "amount", "sales_value"]
    qty_candidates = ["fkimg", "quantity", "qty"]
    uom_candidates = ["vrkme", "meins", "unit"]

    product_col = next((vbrp_map[c] for c in product_candidates if c in vbrp_map), None)
    value_col = next((vbrp_map[c] for c in value_candidates if c in vbrp_map), None)
    qty_col = next((vbrp_map[c] for c in qty_candidates if c in vbrp_map), None)
    uom_col = next((vbrp_map[c] for c in uom_candidates if c in vbrp_map), None)

    if not product_col or not value_col:
        return []

    # Optional product description (MAKT)
    makt_table = table_map.get("makt")
    makt_matnr = makt_maktx = None
    if makt_table:
        makt_cols = inspector.get_columns(makt_table)
        makt_map = {c["name"].lower(): c["name"] for c in makt_cols}
        makt_matnr = makt_map.get("matnr")
        makt_maktx = makt_map.get("maktx")

    # Optional currency from billing header (VBRK)
    vbrk_table = table_map.get("vbrk")
    vbrk_vbeln = vbrk_waerk = None
    if vbrk_table:
        vbrk_cols = inspector.get_columns(vbrk_table)
        vbrk_map = {c["name"].lower(): c["name"] for c in vbrk_cols}
        vbrk_vbeln = vbrk_map.get("vbeln")
        vbrk_waerk = vbrk_map.get("waerk")

    vbeln_vbrp = vbrp_map.get("vbeln")

    select_parts = [f"vbrp.{product_col} AS product_id"]
    group_by_parts = [f"vbrp.{product_col}"]

    if makt_table and makt_matnr and makt_maktx and vbrp_map.get("matnr"):
        select_parts.append(f"m.{makt_maktx} AS product_name")
        group_by_parts.append(f"m.{makt_maktx}")

    if qty_col:
        select_parts.append(f"SUM(CAST(vbrp.{qty_col} AS NUMERIC)) AS total_quantity")
    if uom_col:
        select_parts.append(f"vbrp.{uom_col} AS unit_of_measure")
        group_by_parts.append(f"vbrp.{uom_col}")

    if vbrk_table and vbrk_vbeln and vbrk_waerk and vbeln_vbrp:
        select_parts.append(f"vbrk.{vbrk_waerk} AS currency")
        group_by_parts.append(f"vbrk.{vbrk_waerk}")

    select_parts.append(f"SUM(CAST(vbrp.{value_col} AS NUMERIC)) AS total_sales")

    join_makt = ""
    if makt_table and makt_matnr and vbrp_map.get("matnr"):
        join_makt = f'LEFT JOIN "{makt_table}" m ON vbrp.{vbrp_map["matnr"]} = m.{makt_matnr}'

    join_vbrk = ""
    if vbrk_table and vbrk_vbeln and vbeln_vbrp:
        join_vbrk = f'LEFT JOIN "{vbrk_table}" vbrk ON vbrp.{vbeln_vbrp} = vbrk.{vbrk_vbeln}'

    sql = f"""
        SELECT
            {", ".join(select_parts)}
        FROM "{vbrp_table}" vbrp
        {join_makt}
        {join_vbrk}
        GROUP BY {", ".join(group_by_parts)}
        ORDER BY total_sales DESC
        LIMIT :limit
    """

    rows = db.execute(text(sql), {"limit": limit}).fetchall()

    results: list[dict] = []
    for r in rows:
        total = r.total_sales
        if isinstance(total, Decimal):
            total = float(total)
        total_qty = getattr(r, "total_quantity", None)
        if isinstance(total_qty, Decimal):
            total_qty = float(total_qty)
        results.append(
            {
                "product_id": str(getattr(r, "product_id", "")),
                "product_name": str(getattr(r, "product_name", "")) if hasattr(r, "product_name") else None,
                "total_sales": float(total) if total is not None else 0.0,
                "total_quantity": float(total_qty) if total_qty is not None else None,
                "unit_of_measure": str(getattr(r, "unit_of_measure", "")) if hasattr(r, "unit_of_measure") else None,
                "currency": str(getattr(r, "currency", "")) if hasattr(r, "currency") else None,
            }
        )

    return results


def _get_sales_vs_invoice_v2(db: Session) -> dict:
    """
    Compare total sales from vbrp with total revenue from InvoiceV2BusinessData.
    Used so AI can talk about differences between raw SAP billing data and Zodiac invoice BI data.
    """
    bind = db.get_bind()
    if bind is None:
        return {}

    inspector = inspect(bind)
    table_names = inspector.get_table_names()
    table_map = {name.lower(): name for name in table_names}

    vbrp_table = table_map.get("vbrp")
    if not vbrp_table:
        return {}

    cols = inspector.get_columns(vbrp_table)
    name_map = {c["name"].lower(): c["name"] for c in cols}
    value_candidates = ["netwr", "net_value", "amount", "sales_value"]
    value_col = next((name_map[c] for c in value_candidates if c in name_map), None)
    if not value_col:
        return {}

    # Sum from vbrp
    q_vbrp = text(f"SELECT SUM(CAST({value_col} AS NUMERIC)) AS total_sales FROM {vbrp_table}")
    row = db.execute(q_vbrp).fetchone()
    sales_total = row.total_sales if row and row.total_sales is not None else 0
    if isinstance(sales_total, Decimal):
        sales_total = float(sales_total)

    # Sum from InvoiceV2BusinessData (Zodiac BI)
    inv_total = db.query(func.coalesce(func.sum(InvoiceV2BusinessData.total_amount), 0)).scalar() or 0
    try:
        inv_total = float(inv_total)
    except Exception:
        inv_total = 0.0

    diff = sales_total - inv_total
    return {
        "sales_total_from_vbrp": sales_total,
        "revenue_total_from_invoice_v2": inv_total,
        "difference": diff,
    }


def _get_lowest_sales_by_customer_country(db: Session, limit: int = 10) -> list[dict]:
    """
    Aggregate lowest sales by customer and country using vbrp + vbrk + kna1 if present.
    """
    bind = db.get_bind()
    if bind is None:
        return []

    inspector = inspect(bind)
    tables = {t.lower(): t for t in inspector.get_table_names()}
    vbrp_table = tables.get("vbrp")
    vbrk_table = tables.get("vbrk")
    kna1_table = tables.get("kna1")
    if not vbrp_table or not vbrk_table:
        return []

    # Column maps (case-insensitive)
    vbrp_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrp_table)}
    vbrk_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrk_table)}
    kna1_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(kna1_table)} if kna1_table else {}

    # Join keys and fields
    vbeln_vbrp = vbrp_cols.get("vbeln")
    vbeln_vbrk = vbrk_cols.get("vbeln")
    kunag = vbrk_cols.get("kunag")
    if not vbeln_vbrp or not vbeln_vbrk or not kunag:
        return []

    value_candidates = ["netwr", "net_value", "amount", "sales_value"]
    value_col = next((vbrp_cols[c] for c in value_candidates if c in vbrp_cols), None)
    if not value_col:
        return []

    kna1_kunnr = kna1_cols.get("kunnr")
    kna1_name1 = kna1_cols.get("name1") or kna1_cols.get("name")
    kna1_land1 = kna1_cols.get("land1") or kna1_cols.get("country")

    customer_expr = f"COALESCE(k.{kna1_name1}, vbrk.{kunag})" if kna1_table and kna1_name1 else f"vbrk.{kunag}"
    country_expr = f"COALESCE(k.{kna1_land1}, 'Unknown')" if kna1_table and kna1_land1 else "'Unknown'"

    join_kna1 = ""
    if kna1_table and kna1_kunnr:
        # Quote the table name so Postgres uses the actual mixed-case identifier (e.g. "KNA1")
        join_kna1 = f'LEFT JOIN "{kna1_table}" k ON vbrk.{kunag} = k.{kna1_kunnr}'

    sql = f"""
        SELECT
            {customer_expr} AS customer_name,
            {country_expr} AS country,
            SUM(CAST(vbrp.{value_col} AS NUMERIC)) AS total_sales
        FROM "{vbrp_table}" vbrp
        JOIN "{vbrk_table}" vbrk ON vbrp.{vbeln_vbrp} = vbrk.{vbeln_vbrk}
        {join_kna1}
        GROUP BY {customer_expr}, {country_expr}
        ORDER BY total_sales ASC
        LIMIT :limit
    """
    rows = db.execute(text(sql), {"limit": limit}).fetchall()

    results: list[dict] = []
    for r in rows:
        total = r.total_sales
        if isinstance(total, Decimal):
            total = float(total)
        results.append(
            {
                "customer_name": str(r.customer_name) if r.customer_name is not None else "Unknown",
                "country": str(r.country) if r.country is not None else "Unknown",
                "total_sales": float(total) if total is not None else 0.0,
            }
        )
    return results


def _get_sales_by_country_industry(db: Session, limit: int = 20) -> list[dict]:
    """
    Aggregate sales by country and industry using vbrp + vbrk + kna1 (BRSCH) if present.
    """
    bind = db.get_bind()
    if bind is None:
        return []

    inspector = inspect(bind)
    tables = {t.lower(): t for t in inspector.get_table_names()}
    vbrp_table = tables.get("vbrp")
    vbrk_table = tables.get("vbrk")
    kna1_table = tables.get("kna1")
    if not vbrp_table or not vbrk_table or not kna1_table:
        return []

    vbrp_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrp_table)}
    vbrk_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrk_table)}
    kna1_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(kna1_table)}

    vbeln_vbrp = vbrp_cols.get("vbeln")
    vbeln_vbrk = vbrk_cols.get("vbeln")
    kunag = vbrk_cols.get("kunag")
    if not vbeln_vbrp or not vbeln_vbrk or not kunag:
        return []

    value_candidates = ["netwr", "net_value", "amount", "sales_value"]
    value_col = next((vbrp_cols[c] for c in value_candidates if c in vbrp_cols), None)
    if not value_col:
        return []

    kna1_kunnr = kna1_cols.get("kunnr")
    kna1_land1 = kna1_cols.get("land1") or kna1_cols.get("country")
    kna1_brsch = kna1_cols.get("brsch") or kna1_cols.get("industry")
    if not kna1_kunnr or not kna1_land1 or not kna1_brsch:
        return []

    sql = f"""
        SELECT
            k.{kna1_land1} AS country,
            k.{kna1_brsch} AS industry,
            SUM(CAST(vbrp.{value_col} AS NUMERIC)) AS total_sales,
            COUNT(DISTINCT vbrk.{kunag}) AS customer_count
        FROM "{vbrp_table}" vbrp
        JOIN "{vbrk_table}" vbrk ON vbrp.{vbeln_vbrp} = vbrk.{vbeln_vbrk}
        JOIN "{kna1_table}" k ON vbrk.{kunag} = k.{kna1_kunnr}
        GROUP BY k.{kna1_land1}, k.{kna1_brsch}
        ORDER BY total_sales DESC
        LIMIT :limit
    """
    rows = db.execute(text(sql), {"limit": limit}).fetchall()

    results: list[dict] = []
    for r in rows:
        total = r.total_sales
        if isinstance(total, Decimal):
            total = float(total)
        results.append(
            {
                "country": str(r.country) if r.country is not None else "Unknown",
                "industry": str(r.industry) if r.industry is not None else "Unknown",
                "total_sales": float(total) if total is not None else 0.0,
                "customer_count": int(r.customer_count or 0),
            }
        )
    return results


def _get_sales_by_customer_product_country(db: Session, limit: int = 10) -> list[dict]:
    """
    Aggregate highest sales by customer, product, and country using vbrp + vbrk + kna1.
    """
    bind = db.get_bind()
    if bind is None:
        return []

    inspector = inspect(bind)
    tables = {t.lower(): t for t in inspector.get_table_names()}
    vbrp_table = tables.get("vbrp")
    vbrk_table = tables.get("vbrk")
    kna1_table = tables.get("kna1")
    if not vbrp_table or not vbrk_table:
        return []

    vbrp_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrp_table)}
    vbrk_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(vbrk_table)}
    kna1_cols = {c["name"].lower(): c["name"] for c in inspector.get_columns(kna1_table)} if kna1_table else {}

    vbeln_vbrp = vbrp_cols.get("vbeln")
    vbeln_vbrk = vbrk_cols.get("vbeln")
    kunag = vbrk_cols.get("kunag")
    if not vbeln_vbrp or not vbeln_vbrk or not kunag:
        return []

    product_candidates = ["matnr", "product_id", "material"]
    value_candidates = ["netwr", "net_value", "amount", "sales_value"]
    product_col = next((vbrp_cols[c] for c in product_candidates if c in vbrp_cols), None)
    value_col = next((vbrp_cols[c] for c in value_candidates if c in vbrp_cols), None)
    if not product_col or not value_col:
        return []

    kna1_kunnr = kna1_cols.get("kunnr")
    kna1_name1 = kna1_cols.get("name1") or kna1_cols.get("name")
    kna1_land1 = kna1_cols.get("land1") or kna1_cols.get("country")

    customer_expr = f"COALESCE(k.{kna1_name1}, vbrk.{kunag})" if kna1_table and kna1_name1 else f"vbrk.{kunag}"
    country_expr = f"COALESCE(k.{kna1_land1}, 'Unknown')" if kna1_table and kna1_land1 else "'Unknown'"

    join_kna1 = ""
    if kna1_table and kna1_kunnr:
        # Quote the table name so Postgres uses the actual mixed-case identifier (e.g. "KNA1")
        join_kna1 = f'LEFT JOIN "{kna1_table}" k ON vbrk.{kunag} = k.{kna1_kunnr}'

    sql = f"""
        SELECT
            {customer_expr} AS customer_name,
            {country_expr} AS country,
            vbrp.{product_col} AS product_id,
            SUM(CAST(vbrp.{value_col} AS NUMERIC)) AS total_sales
        FROM "{vbrp_table}" vbrp
        JOIN "{vbrk_table}" vbrk ON vbrp.{vbeln_vbrp} = vbrk.{vbeln_vbrk}
        {join_kna1}
        GROUP BY {customer_expr}, {country_expr}, vbrp.{product_col}
        ORDER BY total_sales DESC
        LIMIT :limit
    """
    rows = db.execute(text(sql), {"limit": limit}).fetchall()

    results: list[dict] = []
    for r in rows:
        total = r.total_sales
        if isinstance(total, Decimal):
            total = float(total)
        results.append(
            {
                "customer_name": str(r.customer_name) if r.customer_name is not None else "Unknown",
                "country": str(r.country) if r.country is not None else "Unknown",
                "product_id": str(r.product_id),
                "total_sales": float(total) if total is not None else 0.0,
            }
        )
    return results


def _build_ai_analysis_context(context_keys: list, current_user: ZodiacUser, db: Session, days: int = 30) -> str:
    """Build context string for AI analysis chat from requested context_keys.
    Uses V2 pipeline (InvoiceV2Document, InvoiceV2Validated, ConvertedInvoice) for outbound;
    SATDocument, SATSimpleMerged for inbound. Context keys: stats, failed_summary, top_customers,
    inbound_summary, business_summary, process_flow.
    
    Also includes table availability and date ranges from cached schemas.
    """
    if not context_keys:
        return ""
    parts = []
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    if "stats" in context_keys:
        try:
            documents_received = db.query(func.count(InvoiceV2Document.id)).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.deleted_at.is_(None),
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).scalar() or 0
            validated_query = db.query(
                InvoiceV2Validated.status,
                func.count(InvoiceV2Validated.id).label("count"),
            ).join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).group_by(InvoiceV2Validated.status).all()
            validated_success = sum(c for s, c in validated_query if s == "success")
            validated_failed = sum(c for s, c in validated_query if s == "failed")
            converted_query = db.query(
                ConvertedInvoice.conversion_status,
                func.count(ConvertedInvoice.id).label("count"),
            ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
                InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id,
            ).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).group_by(ConvertedInvoice.conversion_status).all()
            converted_success = sum(c for s, c in converted_query if s == "success")
            converted_failed = sum(c for s, c in converted_query if s == "failed")
            converted_pending = sum(c for s, c in converted_query if s == "pending")
            converted_total = converted_success + converted_failed + converted_pending
            validation_rate = (
                (validated_success / (validated_success + validated_failed) * 100)
                if (validated_success + validated_failed) > 0 else 0
            )
            conversion_rate = (converted_success / converted_total * 100) if converted_total > 0 else 0
        except Exception:
            documents_received = validated_success = validated_failed = 0
            converted_success = converted_failed = converted_pending = converted_total = 0
            validation_rate = conversion_rate = 0
        try:
            sat_total = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
            ).scalar() or 0
            sat_sent = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == True,
            ).scalar() or 0
            sat_pending = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == False,
            ).scalar() or 0
        except Exception:
            sat_total = sat_sent = sat_pending = 0
        parts.append(
            f"Dashboard statistics (last {days} days). "
            f"Outbound (V2): {documents_received} documents received; "
            f"validated: {validated_success} success, {validated_failed} failed (rate {validation_rate:.1f}%); "
            f"converted: {converted_success} success, {converted_failed} failed, {converted_pending} pending (rate {conversion_rate:.1f}%). "
            f"Inbound (SAT): {sat_total} merged documents ({sat_sent} sent to SAP, {sat_pending} pending)."
        )

    if "failed_summary" in context_keys:
        try:
            failed_count_v2 = (
                db.query(InvoiceV2Validated)
                .join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id)
                .filter(
                    InvoiceV2Document.user_id == current_user.id,
                    InvoiceV2Document.deleted_at.is_(None),
                    InvoiceV2Document.uploaded_at >= cutoff_date,
                    InvoiceV2Validated.status == "failed",
                )
                .count()
            )
            parts.append(
                f"Failed invoices (V2 validations, last {days} days): {failed_count_v2} failed."
            )
        except Exception:
            parts.append("Failed invoices (V2): data unavailable.")

    if "top_customers" in context_keys:
        try:
            customer_rows = db.query(
                ConvertedInvoice.customer_id,
                func.max(InvoiceV2Validated.invoice_data["customer_name"].astext).label("customer_name"),
                func.max(InvoiceV2Validated.invoice_data["currency"].astext).label("currency"),
                func.count(ConvertedInvoice.id).label("count"),
            ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
                InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id,
            ).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).filter(ConvertedInvoice.customer_id.isnot(None)).group_by(
                ConvertedInvoice.customer_id,
            ).order_by(func.count(ConvertedInvoice.id).desc()).limit(10).all()
            top_customers_list = [
                {
                    "customer_id": r.customer_id,
                    "customer_name": (r.customer_name or r.customer_id) or "—",
                    "currency": (r.currency or "—").strip() or "—",
                    "invoice_count": r.count,
                }
                for r in customer_rows
            ]
            if top_customers_list:
                parts.append("Top customers (outbound, by invoice count): " + json.dumps(top_customers_list))
            else:
                parts.append("Top customers (outbound): no customer data in the period.")
        except Exception as e:
            logger.warning(f"AI context top_customers: {e}")
            parts.append("Top customers (outbound): data unavailable.")

    if "inbound_summary" in context_keys:
        try:
            total_documents = db.query(func.count(SATDocument.id)).filter(
                SATDocument.user_id == current_user.id,
                SATDocument.received_at >= cutoff_date,
            ).scalar() or 0
            merges_total = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
            ).scalar() or 0
            merges_sent = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == True,
            ).scalar() or 0
            merges_pending = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == False,
            ).scalar() or 0
            supplier_rows = db.query(
                SATDocument.supplier_rfc,
                SATDocument.supplier_name,
                func.count(SATDocument.id).label("count"),
                func.coalesce(
                    func.sum(cast(func.nullif(func.trim(SATDocument.total), ""), Numeric(15, 2))),
                    0,
                ).label("total_amount"),
            ).filter(
                SATDocument.user_id == current_user.id,
                SATDocument.received_at >= cutoff_date,
            ).group_by(SATDocument.supplier_rfc, SATDocument.supplier_name).order_by(
                func.count(SATDocument.id).desc(),
            ).limit(10).all()
            top_suppliers = [
                {
                    "supplier_rfc": r.supplier_rfc,
                    "supplier_name": (r.supplier_name or r.supplier_rfc) or "—",
                    "count": r.count,
                    "total_amount": float(r.total_amount) if r.total_amount is not None else 0.0,
                }
                for r in supplier_rows
            ]
            parts.append(
                f"Inbound (SAT): {total_documents} documents received; "
                f"{merges_total} merges ({merges_sent} sent to SAP, {merges_pending} pending). "
                f"Top suppliers: " + json.dumps(top_suppliers),
            )
        except Exception as e:
            logger.warning(f"AI context inbound_summary: {e}")
            parts.append("Inbound (SAT): data unavailable.")

    if "business_summary" in context_keys:
        try:
            rows = db.query(InvoiceV2BusinessData).filter(
                InvoiceV2BusinessData.user_id == current_user.id,
                InvoiceV2BusinessData.created_at >= cutoff_date,
            ).all()
            customer_revenue = defaultdict(lambda: {"customer_name": None, "count": 0, "revenue": Decimal("0")})
            country_revenue = defaultdict(lambda: {"count": 0, "revenue": Decimal("0")})
            for r in rows:
                cid = r.customer_id or "Unknown"
                customer_revenue[cid]["customer_name"] = r.customer_name or cid
                customer_revenue[cid]["count"] += 1
                customer_revenue[cid]["revenue"] += (r.total_amount or Decimal("0"))
                country = r.customer_country or "Unknown"
                country_revenue[country]["count"] += 1
                country_revenue[country]["revenue"] += (r.total_amount or Decimal("0"))
            revenue_by_customer = sorted(
                [
                    {"customer_id": cid, "customer_name": d["customer_name"] or cid, "invoice_count": d["count"], "total_revenue": float(d["revenue"])}
                    for cid, d in customer_revenue.items()
                ],
                key=lambda x: -x["total_revenue"],
            )[:10]
            revenue_by_country = sorted(
                [
                    {"country": c, "invoice_count": d["count"], "total_revenue": float(d["revenue"])}
                    for c, d in country_revenue.items()
                ],
                key=lambda x: -x["total_revenue"],
            )[:5]
            mid = cutoff_date + (datetime.utcnow() - cutoff_date) / 2
            prev_cutoff = cutoff_date - (datetime.utcnow() - cutoff_date)
            current_revenue = db.query(func.coalesce(func.sum(InvoiceV2BusinessData.total_amount), 0)).filter(
                InvoiceV2BusinessData.user_id == current_user.id,
                InvoiceV2BusinessData.created_at >= mid,
            ).scalar() or 0
            previous_revenue = db.query(func.coalesce(func.sum(InvoiceV2BusinessData.total_amount), 0)).filter(
                InvoiceV2BusinessData.user_id == current_user.id,
                InvoiceV2BusinessData.created_at >= prev_cutoff,
                InvoiceV2BusinessData.created_at < mid,
            ).scalar() or 0
            try:
                current_revenue = float(current_revenue)
                previous_revenue = float(previous_revenue)
            except Exception:
                current_revenue = previous_revenue = 0.0
            trend_pct = ((current_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue else 0.0
            # Optional: derive sales by product and related breakdowns directly from vbrp in the primary DB
            product_sales: list[dict] = []
            lowest_sales_by_customer_country: list[dict] = []
            sales_by_country_industry: list[dict] = []
            sales_by_customer_product_country: list[dict] = []
            sales_vs_invoice = {}
            try:
                product_sales = _get_sales_by_product_from_vbrp(db, limit=10)
            except Exception as e2:
                logger.warning(f"AI context product_sales from vbrp: {e2}")
            try:
                lowest_sales_by_customer_country = _get_lowest_sales_by_customer_country(db, limit=10)
            except Exception as e2:
                logger.warning(f"AI context lowest_sales_by_customer_country: {e2}")
            try:
                sales_by_country_industry = _get_sales_by_country_industry(db, limit=20)
            except Exception as e2:
                logger.warning(f"AI context sales_by_country_industry: {e2}")
            try:
                sales_by_customer_product_country = _get_sales_by_customer_product_country(db, limit=10)
            except Exception as e2:
                logger.warning(f"AI context sales_by_customer_product_country: {e2}")
            try:
                sales_vs_invoice = _get_sales_vs_invoice_v2(db)
            except Exception as e2:
                logger.warning(f"AI context sales_vs_invoice_v2: {e2}")

            parts.append(
                f"Business (revenue): current period {current_revenue:.0f}, previous {previous_revenue:.0f} (change {trend_pct:+.1f}%). "
                f"Revenue by customer (top 10): {json.dumps(revenue_by_customer)}. "
                f"Revenue by country (top 5): {json.dumps(revenue_by_country)}. "
                f"Sales by product (top 10 from vbrp): {json.dumps(product_sales)}. "
                f"Lowest sales by customer and country (from vbrp/vbrk/kna1): {json.dumps(lowest_sales_by_customer_country)}. "
                f"Sales by country and industry (from vbrp/vbrk/kna1): {json.dumps(sales_by_country_industry)}. "
                f"Highest sales by customer, product, and country (from vbrp/vbrk/kna1): {json.dumps(sales_by_customer_product_country)}. "
                f"Comparison of total sales (vbrp) vs InvoiceV2BusinessData: {json.dumps(sales_vs_invoice)}.",
            )
        except Exception as e:
            logger.warning(f"AI context business_summary: {e}")
            parts.append("Business summary: data unavailable.")

    if "process_flow" in context_keys:
        try:
            documents_received = db.query(func.count(InvoiceV2Document.id)).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.deleted_at.is_(None),
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).scalar() or 0
            validated_query = db.query(
                InvoiceV2Validated.status,
                func.count(InvoiceV2Validated.id).label("count"),
            ).join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).group_by(InvoiceV2Validated.status).all()
            validated_success = sum(c for s, c in validated_query if s == "success")
            validated_failed = sum(c for s, c in validated_query if s == "failed")
            converted_query = db.query(
                ConvertedInvoice.conversion_status,
                func.count(ConvertedInvoice.id).label("count"),
            ).join(InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id).join(
                InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id,
            ).filter(
                InvoiceV2Document.user_id == current_user.id,
                InvoiceV2Document.uploaded_at >= cutoff_date,
            ).group_by(ConvertedInvoice.conversion_status).all()
            converted_success = sum(c for s, c in converted_query if s == "success")
            converted_failed = sum(c for s, c in converted_query if s == "failed")
            converted_pending = sum(c for s, c in converted_query if s == "pending")
            merges_total = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
            ).scalar() or 0
            merges_sent = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == True,
            ).scalar() or 0
            merges_pending = db.query(func.count(SATSimpleMerged.id)).filter(
                SATSimpleMerged.user_id == current_user.id,
                SATSimpleMerged.created_at >= cutoff_date,
                SATSimpleMerged.sent_to_sap == False,
            ).scalar() or 0
            parts.append(
                "Standard process flows. Outbound: Document received -> Validation (success/fail) -> Conversion (format, success/fail/pending) -> Output. "
                f"Current outbound counts: received {documents_received}, validated success {validated_success} failed {validated_failed}, "
                f"converted success {converted_success} failed {converted_failed} pending {converted_pending}. "
                "Inbound: SAT documents received -> Merge (batch) -> Send to SAP. "
                f"Current inbound: {merges_total} merges, {merges_sent} sent to SAP, {merges_pending} pending.",
            )
        except Exception as e:
            logger.warning(f"AI context process_flow: {e}")
            parts.append(
                "Standard process flows. Outbound: Document received -> Validation -> Conversion -> Output. "
                "Inbound: SAT documents -> Merge -> Send to SAP. Current counts unavailable.",
            )
    
    # Add table availability and date ranges from cached schemas
    try:
        from ..services.table_schema_manager import get_all_cached_schemas
        cached_schemas = get_all_cached_schemas(db)
        
        if cached_schemas:
            table_info_parts = ["\n\nAvailable data tables for SQL queries:"]
            for schema in cached_schemas[:15]:  # Limit to top 15 tables
                table_name = schema["table_name"]
                row_count = schema.get("row_count", 0)
                date_range = schema.get("date_range")
                description = schema.get("description", "")
                
                info = f"- {table_name}"
                if description:
                    info += f" ({description[:80]})"
                info += f": {row_count:,} rows"
                
                if date_range:
                    info += f", date range {date_range.get('min_date', 'N/A')} to {date_range.get('max_date', 'N/A')}"
                
                table_info_parts.append(info)
            
            parts.append("\n".join(table_info_parts))
            logger.info(f"📊 Added {len(cached_schemas)} table availability info to context")
    except Exception as schema_err:
        logger.debug(f"Schema cache not available (not critical): {schema_err}")
    
    return "\n".join(parts) if parts else ""


def _extract_first_select_statement(sql: str) -> str:
    """
    When the user pastes multi-statement SQL (several queries separated by ';'
    or SQL comment blocks like '-- ----'), extract only the first complete SELECT
    statement so execution and storage work correctly.
    Also removes SQLAlchemy-style bind parameters (%(x)s, :x) that would crash
    at execution time.
    """
    if not sql or not sql.strip():
        return sql or ""
    # Remove inline SQLAlchemy bind parameters: %(year)s → replaced with empty-string
    # guard so the SQL doesn't crash; users can refine after seeing the result.
    import re as _re
    sql = _re.sub(r'%\([^)]+\)s', "''", sql)
    sql = _re.sub(r'(?<!\w):([a-zA-Z_][a-zA-Z0-9_]*)\b', "''", sql)
    # Split on statement terminator ';' — keep only the first non-empty SELECT
    statements = [s.strip() for s in sql.split(";")]
    for stmt in statements:
        # Strip leading SQL comment blocks (-- ---- style dividers)
        clean = _re.sub(r"(^|\n)\s*--[^\n]*", "", stmt).strip()
        if clean.upper().startswith("SELECT"):
            return clean
    # Fallback: return original (single-statement case)
    return sql.strip()


def _validation_to_payload(validation) -> Dict[str, Any]:
    if not validation:
        return {}
    return {
        "errors": list(getattr(validation, "errors", []) or []),
        "warnings": list(getattr(validation, "warnings", []) or []),
        "tables": list(getattr(validation, "tables", []) or []),
        "columns": list(getattr(validation, "columns", []) or []),
        "date_normalizations": list(getattr(validation, "date_normalizations", []) or []),
        "aggregate_functions": list(getattr(validation, "aggregate_functions", []) or []),
    }


def _non_blocking_validation_payload(validation) -> Dict[str, Any]:
    if not validation:
        return {}
    payload = _validation_to_payload(validation)
    payload["errors"] = []
    return payload


def _validation_warning_requires_refinement(warnings: List[str]) -> bool:
    return any("Question mentions a year" in warning for warning in (warnings or []))


def _format_validation_detail(prefix: str, errors: List[str], warnings: List[str]) -> str:
    details = list(errors or []) or list(warnings or [])
    if not details:
        return prefix
    return f"{prefix}: {' '.join(details[:2])}"


def _validate_sql_candidate(sql_db: Session, question: str, sql: str):
    from ..services.ai_query_memory_service import validate_sql_for_safe_execution
    from ..services.sap_sql_precision_validator import validate_sql_precision_for_db
    from ..services.sql_generation_sanitizers import sanitize_generated_sap_sql

    sql = sanitize_generated_sap_sql(sql, question)

    is_valid, err = validate_sql_for_safe_execution(sql)
    if not is_valid:
        return None, f"Invalid SQL: {err}"

    validation = validate_sql_precision_for_db(sql_db, sql, question=question)
    if not validation.is_valid:
        return validation, _format_validation_detail(
            "SQL blocked by SAP precision validation",
            validation.errors,
            validation.warnings,
        )
    if _validation_warning_requires_refinement(validation.warnings):
        return validation, _format_validation_detail(
            "SQL needs refinement before it can be used",
            validation.errors,
            validation.warnings,
        )
    return validation, None
    
@router.post("/ai-analysis/chat")
async def post_ai_analysis_chat(
    message: str = Body(..., embed=True),
    conversation_history: list = Body(default=[], embed=True),
    context_keys: list = Body(default=[], embed=True),
    days: int = Body(default=30, embed=True),
    time_scope: str = Body(default="current", embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generative AI analysis chat: answer user questions, optionally grounded in dashboard context.
    context_keys: stats, failed_summary, top_customers, inbound_summary, business_summary, process_flow.
    days: period for context (default 30).
    time_scope: 'current' (recent data), 'historical' (1994-2010), or 'both' (compare periods).
    Uses same config env vars as invoice-bot (OPENAI_API_KEY)."""
    ai_openai_key = _get_ai_analysis_config()
    if not ai_openai_key or not openai_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis not available (set OPENAI_API_KEY, or Zodiac OPEN_AI_KEY)",
        )
    days = max(1, min(365, days)) if isinstance(days, (int, float)) else 30
    try:
        # 1) Build the existing dashboard context (Zodiac mode or SAP mode)
        if USE_SAP_DB_FOR_AI:
            from ..services.sap_ai_context import build_ai_context_from_sap
            sap_session_for_context = get_sap_session()
            context_str = ""
            if sap_session_for_context is not None:
                try:
                    context_str = build_ai_context_from_sap(
                        context_keys if isinstance(context_keys, list) else [],
                        sap_session_for_context,
                        days=int(days),
                    )
                except Exception as sap_e:
                    logger.warning("SAP AI context failed: %s", sap_e)
                finally:
                    sap_session_for_context.close()
        else:
            context_str = _build_ai_analysis_context(
                context_keys if isinstance(context_keys, list) else [],
                current_user,
                db,
                days=int(days),
            )

        # 2) INVOICE_BOT-like orchestrator: decide action, run SQL if needed, persist memory, and answer
        from ..services.ai_analysis_orchestrator import run_ai_analysis_orchestrator, orchestrator_payload

        sap_session_for_sql = get_sap_session() if USE_SAP_DB_FOR_AI else None
        try:
            orch = run_ai_analysis_orchestrator(
                api_key=ai_openai_key,
                user_id=current_user.id,
                user_query=message or "",
                db=db,
                conversation_history=conversation_history or [],
                context_str=context_str or "",
                sap_db=sap_session_for_sql,
                time_scope=time_scope or "current",
                days=int(days),
            )
            payload = orchestrator_payload(orch)
            # Use Zodiac app DB for operational resolver results (Zodiac tables not in SAP schema).
            _is_operational_payload = (payload.get("sql_path_reason") or "").startswith("operational_")
            validation_db = db if _is_operational_payload else (sap_session_for_sql or db)
            # Skip SAP precision validation for operational Zodiac queries — they use app DB tables
            # not present in the SAP schema, so validation would produce false "unknown table" errors.
            if payload.get("sql") and not _is_operational_payload:
                validation, blocking_detail = _validate_sql_candidate(validation_db, message or "", payload["sql"])
                if validation and not blocking_detail:
                    payload["validation"] = _validation_to_payload(validation)
                elif validation and payload.get("rows_preview"):
                    logger.warning(
                        "Skipping blocking validation metadata for executed SQL because rows were returned. "
                        "question=%r errors=%s",
                        (message or "")[:120],
                        getattr(validation, "errors", []),
                    )
                    non_blocking_payload = _non_blocking_validation_payload(validation)
                    if non_blocking_payload.get("warnings") or non_blocking_payload.get("date_normalizations"):
                        payload["validation"] = non_blocking_payload
            if payload.get("proposed_sql") and not _is_operational_payload:
                proposed_validation, _ = _validate_sql_candidate(validation_db, message or "", payload["proposed_sql"])
                if proposed_validation:
                    payload["proposed_sql"] = proposed_validation.normalized_sql
                    payload["proposed_validation"] = _non_blocking_validation_payload(proposed_validation)
        finally:
            if sap_session_for_sql is not None:
                sap_session_for_sql.close()

        return payload
    except Exception as e:
        logger.warning(f"AI analysis chat failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/ai-analysis/store-query")
async def post_ai_analysis_store_query(
    question: str = Body(..., embed=True),
    sql_query: str = Body(..., embed=True),
    time_scope: str = Body(default="both", embed=True),
    approval_source: str = Body(default="assistant_sql", embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Store user-confirmed SQL (Yes case). No execution - query was already run successfully.
    """
    from ..services.ai_query_memory_service import store_approved_query
    from ..services.training_data_collector import log_query_feedback_attempt

    sql_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
    try:
        validation, blocking_detail = _validate_sql_candidate(sql_db or db, question, sql_query)
        if blocking_detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=blocking_detail)

        normalized_sql = validation.normalized_sql if validation else sql_query
        stored = store_approved_query(
            db,
            current_user.id,
            question,
            normalized_sql,
            source="user",
            model_used=None,
            tables_used=list(validation.tables or []) if validation else None,
        )
        if not stored:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store query")

        try:
            from ..services.ai_intent_classifier import classify_intent
            from ..services.join_graph import tables_linked_to_graph
            _intent_tags = classify_intent(question).tags
            _linked_to_graph = tables_linked_to_graph(list(execution.validation.tables or []))
        except Exception:
            _intent_tags = []
            _linked_to_graph = False

        log_query_feedback_attempt(
            db=db,
            user_id=current_user.id,
            user_query=question,
            sql_query=normalized_sql,
            feedback_status="approved",
            attempt_source=approval_source or "assistant_sql",
            time_scope=time_scope,
            validation=_validation_to_payload(validation),
            extra_metadata={"stored_for_reuse": True, "store_mode": "confirmed_existing_result"},
        )
        return {
            "success": True,
            "message": "Query stored for future use.",
            "validation": _validation_to_payload(validation),
        }
    finally:
        if USE_SAP_DB_FOR_AI and sql_db is not None and sql_db is not db:
            sql_db.close()


@router.post("/ai-analysis/reject-query")
async def post_ai_analysis_reject_query(
    question: str = Body(..., embed=True),
    rejected_sql: str = Body(..., embed=True),
    time_scope: str = Body(default="both", embed=True),
    attempt_source: str = Body(default="assistant_sql", embed=True),
    feedback_reason: str = Body(default="rejected_by_user", embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..services.training_data_collector import log_query_feedback_attempt

    sql_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
    try:
        validation = None
        if rejected_sql and rejected_sql.strip():
            validation, _ = _validate_sql_candidate(sql_db or db, question, rejected_sql)
        record_id = log_query_feedback_attempt(
            db=db,
            user_id=current_user.id,
            user_query=question,
            sql_query=rejected_sql,
            feedback_status="rejected",
            attempt_source=attempt_source or "assistant_sql",
            time_scope=time_scope,
            feedback_reason=feedback_reason or "rejected_by_user",
            validation=_validation_to_payload(validation),
            extra_metadata={"stored_for_reuse": False},
        )
        return {"success": True, "feedback_record_id": record_id}
    finally:
        if USE_SAP_DB_FOR_AI and sql_db is not None and sql_db is not db:
            sql_db.close()


@router.post("/ai-analysis/suggest-sql")
async def post_ai_analysis_suggest_sql(
    question: str = Body(..., embed=True),
    time_scope: str = Body(default="both", embed=True),
    instructions: str = Body(default="", embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Suggest SQL for the question. Uses ai_query_memory first (user-approved), then
    sql_catalog, then ChatGPT. Returns proposed_sql only (no execution).
    Optional `instructions`: free-text guidance from the user to ChatGPT about how
    to write the SQL (e.g. "use FKDAT for year 2000, group by customer, show negatives first").
    When instructions are provided, memory/catalog lookups are skipped so ChatGPT always
    generates fresh SQL following the user's directions.
    """
    from ..services.schema_loader import get_schema_text
    from ..services.ai_query_memory_service import (
        find_similar_stored_query,
    )
    from ..services.sap_sql_agent import _lookup_sql_catalog, _quote_catalog_sql_tables
    from ..config.config import USE_SAP_DB_FOR_AI

    ai_openai_key = _get_ai_analysis_config()
    if not ai_openai_key or not openai_available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI not available (set OPENAI_API_KEY)")

    sql_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
    try:
        has_instructions = bool((instructions or "").strip())

        # 1) Try ai_query_memory first — only if user hasn't provided custom instructions
        if not has_instructions:
            stored_sql = find_similar_stored_query(db, question, current_user.id, mark_used=False)
            if stored_sql:
                quoted = _quote_catalog_sql_tables(stored_sql)
                validation, blocking_detail = _validate_sql_candidate(sql_db or db, question, quoted)
                if validation and not blocking_detail:
                    return {
                        "proposed_sql": validation.normalized_sql,
                        "validation": _validation_to_payload(validation),
                        "suggestion_source": "approved_memory",
                        "time_scope": time_scope,
                    }

            # 2) Try catalog — only if no custom instructions
            catalog_sql = _lookup_sql_catalog(question)
            if catalog_sql:
                quoted = _quote_catalog_sql_tables(catalog_sql)
                validation, blocking_detail = _validate_sql_candidate(sql_db or db, question, quoted)
                if validation and not blocking_detail:
                    return {
                        "proposed_sql": validation.normalized_sql,
                        "validation": _validation_to_payload(validation),
                        "suggestion_source": "sql_catalog",
                        "time_scope": time_scope,
                    }

        # 3) ChatGPT generation — always runs when instructions provided, fallback otherwise
        schema_text = get_schema_text(sql_db, include_semantic_map=True)
        from openai import OpenAI
        client = OpenAI(api_key=ai_openai_key)

        # Build user instructions block
        instructions_block = ""
        if has_instructions:
            instructions_block = f"""
User instructions for how to write this SQL:
{instructions.strip()}

Follow these instructions exactly when writing the query.
"""

        prompt = f"""You are an SAP PostgreSQL expert. The user asked: "{question}"
{instructions_block}
CRITICAL DATA RULES (confirmed facts about this database — ignore at your peril):
- VBRK.gjahr contains '0000' for ALL rows. NEVER filter or group by gjahr. ALWAYS use FKDAT:
    WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000'
- vbrp.netwr is TEXT. ALWAYS cast using:
    SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric))
- JOIN vbrp to VBRK with LPAD: ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
- Uppercase SAP tables need double quotes: "VBRK" "KNA1" "MAKT" (vbrp is lowercase)
- Do not use PostgreSQL ::type shorthand; SQL may be executed through SQLAlchemy text(). Use CAST(... AS ...) instead.
- NEGATIVE SALES = individual billing LINE ITEMS with netwr < 0, NOT year totals.
    WRONG (always 0 rows): HAVING SUM(netwr) < 0
    RIGHT: WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) < 0
    Example for "negative sales in year 2000":
        SELECT v."vbeln", v."matnr", r."fkdat",
               CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) AS netwr
        FROM vbrp v
        JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
        WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000'
          AND CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) < 0
        ORDER BY CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) ASC
- LOWEST SALES: Use ORDER BY CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) ASC (no HAVING filter). Show individual line items.

Database schema (PostgreSQL):
{schema_text[:6000]}

Generate a single PostgreSQL SELECT query. Rules:
- SELECT only (no DELETE, UPDATE, DROP, INSERT)
- Return ONLY the SQL, no explanation, no markdown code blocks."""
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        raw = (resp.choices[0].message.content or "").strip()
        import re
        if "```" in raw:
            m = re.search(r"```(?:\w+)?\s*([\s\S]*?)```", raw)
            if m:
                raw = m.group(1).strip()
        proposed_sql = raw if raw and "SELECT" in raw.upper() else None
        if not proposed_sql:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ChatGPT could not generate valid SQL")
        validation, blocking_detail = _validate_sql_candidate(sql_db or db, question, proposed_sql)
        if blocking_detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=blocking_detail)
        return {
            "proposed_sql": validation.normalized_sql if validation else proposed_sql,
            "validation": _validation_to_payload(validation),
            "suggestion_source": "chatgpt",
            "time_scope": time_scope,
        }
    finally:
        if USE_SAP_DB_FOR_AI and sql_db is not None and sql_db is not db:
            sql_db.close()

@router.get("/ai-analysis/schema")
async def get_ai_analysis_schema(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the full table→columns schema available for SQL queries.
    Used by the frontend schema browser when users write SQL manually.
    Merges db_table_mapping.json (typed columns) with live DB introspection
    for any tables not in the mapping file.
    """
    from ..services.schema_context_builder import load_schema
    import sqlalchemy

    # 1) Load typed columns from mapping file (48 SAP tables with full metadata)
    try:
        mapping = load_schema()
    except Exception:
        mapping = {}

    schema_out: dict = {}
    for table_name, info in mapping.items():
        cols = list(info.get("columns", {}).keys())
        schema_out[table_name] = {
            "columns": cols,
            "description": info.get("description", ""),
            "source": "mapping",
        }

    # 2) Supplement with live DB introspection for all remaining tables
    try:
        sql_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
        try:
            # Get all table names from the DB
            result = sql_db.execute(sqlalchemy.text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )).fetchall()
            live_tables = [row[0] for row in result]

            for tbl in live_tables:
                if tbl in schema_out:
                    continue  # already covered by mapping
                try:
                    col_result = sql_db.execute(sqlalchemy.text(
                        """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = :tbl
                        ORDER BY ordinal_position
                        """
                    ), {"tbl": tbl}).fetchall()
                    schema_out[tbl] = {
                        "columns": [r[0] for r in col_result],
                        "description": "",
                        "source": "live",
                    }
                except Exception:
                    pass
        finally:
            if USE_SAP_DB_FOR_AI and sql_db is not db:
                sql_db.close()
    except Exception as e:
        logger.warning("Live DB schema introspection failed: %s", e)

    return {"schema": schema_out, "table_count": len(schema_out)}


@router.post("/ai-analysis/approve-query")
async def post_ai_analysis_approve_query(
    question: str = Body(..., embed=True),
    proposed_sql: str = Body(..., embed=True),
    time_scope: str = Body(default="both", embed=True),
    approval_source: str = Body(default="chatgpt", embed=True),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Andy's training loop: User approves ChatGPT-proposed SQL.
    Stores question→SQL in ai_query_memory, executes, and returns full result.
    """
    try:
        return _do_approve_query(question, proposed_sql, time_scope, approval_source, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approve failed: {str(e)}",
        )


def _do_approve_query(question: str, proposed_sql: str, time_scope: str, approval_source: str, current_user, db):
    from ..services.ai_query_memory_service import store_approved_query
    from ..services.ai_analysis_orchestrator import orchestrator_payload
    from ..services.sap_sql_agent import SqlAgentResult
    from ..services.sap_sql_precision_validator import execute_sql_with_precision_checks
    from ..services.training_data_collector import log_query_feedback_attempt
    from ..config.config import USE_SAP_DB_FOR_AI

    # ── Pre-process: strip multi-statement SQL to first valid SELECT ──────────
    proposed_sql = _extract_first_select_statement(proposed_sql)

    sql_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
    try:  # outer try — finally block ensures sql_db.close() always runs
        # ── Step 1: Execute SQL with precision checks ──────────────────────────
        execution = None
        try:
            execution = execute_sql_with_precision_checks(sql_db or db, proposed_sql, question=question)
        except HTTPException:
            raise
        except Exception as _exec_err:
            # DB execution error (e.g. type mismatch, column not found).
            # Auto-fix using ChatGPT with the error context and offer fixed SQL.
            _err_str = str(_exec_err)
            logger.warning("_do_approve_query: execution error: %s", _err_str[:300])
            # Roll back the failed transaction so the session is still usable
            try:
                (sql_db or db).rollback()
            except Exception:
                pass
            _fixed_sql = None
            try:
                from openai import OpenAI
                _ai_key = _get_ai_analysis_config()
                if _ai_key:
                    _fix_prompt = f"""The following PostgreSQL SQL failed with an error. Fix it and return ONLY the corrected SQL.

Original SQL:
{proposed_sql}

Error message:
{_err_str[:500]}

Key rules for SAP data:
- Keep the user's filter intent intact. Do NOT broaden the query, remove year filters, or switch to all periods unless the error explicitly requires it.
- Do NOT invent or prepend schemas like public. Use the actual SAP table names already present in the SQL.
- Preserve SAP table casing exactly. In this database, examples include lowercase vbrp and quoted uppercase "VBRK".
- If the SQL already joins the right tables, prefer the minimal fix instead of rewriting the whole query.
- YEAR FILTERING: VBRK.gjahr stores '0000' and is UNRELIABLE. Filter by fkdat instead: SUBSTRING(TRIM(fkdat), 1, 4) = '2000' for year 2000. NEVER use gjahr for year filters.
- NEVER use SQLAlchemy bind parameters (%(year)s, %(x)s, :year, :x) — inline all literal values.
- Do not use PostgreSQL ::type shorthand; SQL may be executed through SQLAlchemy text(). Use CAST(... AS ...) instead.
- CKIS.wertn and CKIS.gpreis are TEXT columns. Use SUM(CAST(NULLIF(TRIM(CAST(wertn AS text)), '') AS numeric)) NOT COALESCE(wertn, 0).
- vbrp.netwr is also TEXT; cast with CAST(NULLIF(TRIM(CAST(netwr AS text)), '') AS numeric) if needed.
- NEGATIVE SALES: Use WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS text)), '') AS numeric) < 0 on individual rows. NEVER use HAVING SUM(netwr) < 0 (no year has a negative total — it returns 0 rows).
- Return ONLY a single SELECT statement, no multiple statements, no comments, no markdown."""
                    _client = OpenAI(api_key=_ai_key)
                    _resp = _client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": _fix_prompt}],
                        temperature=0,
                        max_tokens=1000,
                    )
                    _raw = (_resp.choices[0].message.content or "").strip()
                    if "```" in _raw:
                        import re as _re2
                        _m = _re2.search(r"```(?:\w+)?\s*([\s\S]*?)```", _raw)
                        if _m:
                            _raw = _m.group(1).strip()
                    if _raw and "SELECT" in _raw.upper():
                        _fixed_sql = _raw
            except Exception as _fix_err:
                logger.debug("auto-fix SQL failed: %s", _fix_err)
            if _fixed_sql:
                return {
                    "reply": (
                        f"The SQL ran into a database error: {_err_str[:200]}. "
                        "I've generated a corrected version below — please review and approve."
                    ),
                    "action": "new",
                    "reason": "sql_execution_error_auto_fixed",
                    "sql": proposed_sql,
                    "rows_preview": [],
                    "charts": None,
                    "needs_approval": True,
                    "proposed_sql": _fixed_sql,
                    "validation": {},
                    "period_info": "All Periods" if time_scope == "both" else time_scope,
                }
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Approve failed: {_err_str[:400]}",
            )

        validation_payload = _validation_to_payload(execution.validation)
        if not execution.validation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_format_validation_detail(
                    "SQL blocked by SAP precision validation",
                    execution.validation.errors,
                    execution.validation.warnings,
                ),
            )

        # ── Step 2: Storage + summarisation ───────────────────────────────────
        quoted_sql = execution.sql
        rows = execution.rows

        # Determine whether this is a hard "NULL aggregate" failure vs. a soft
        # "no rows found" result.  For entity-specific queries (customer/vendor/
        # product by name), zero rows means the entity simply has no data in the
        # current period — the SQL itself is correct and should still be stored so
        # the user can reuse it.  We only block storage for genuinely malformed
        # results (NULL aggregates) or when the "should_refine" flag is set for
        # reasons other than a sparse/filtered dataset.
        _is_null_aggregate = execution.no_data_reason == "null_aggregate"
        _is_entity_query = False
        _has_explicit_time_filter = False
        try:
            from ..services.sap_sql_agent import _is_entity_specific_question, _question_has_explicit_time_constraint
            _is_entity_query = _is_entity_specific_question(question)
            _has_explicit_time_filter = _question_has_explicit_time_constraint(question)
        except Exception:
            pass
        if not _has_explicit_time_filter and proposed_sql:
            _has_explicit_time_filter = bool(
                re.search(r"\b(?:GJAHR|RYEAR|FKDAT|BUDAT|AUDAT|BEDAT|ERDAT|AUGDT|LFDAT|DATUV)\b\s*(?:=|>=|<=|>|<|BETWEEN|IN)", proposed_sql, re.IGNORECASE)
                or re.search(r"EXTRACT\s*\(\s*YEAR\s+FROM", proposed_sql, re.IGNORECASE)
                or re.search(r"\b(?:19|20)\d{2}\b", proposed_sql)
            )

        # Block storage only for non-entity queries with NULL aggregates or 0 rows.
        # For entity-specific queries (customer/vendor/product by name), NULL SUM or 0 rows
        # simply means the named entity has no billing records — the SQL is correct and
        # should be stored so the user can reuse it later.
        _allow_empty_result = _is_entity_query or _has_explicit_time_filter
        _should_block_storage = (_is_null_aggregate and not _allow_empty_result) or (execution.should_refine and not _allow_empty_result)

        if _should_block_storage or (not rows and not _allow_empty_result):
            log_query_feedback_attempt(
                db=db,
                user_id=current_user.id,
                user_query=question,
                sql_query=quoted_sql,
                feedback_status="rejected",
                attempt_source=approval_source or "chatgpt",
                time_scope=time_scope,
                feedback_reason=execution.no_data_reason or "needs_refinement",
                validation=validation_payload,
                extra_metadata={"stored_for_reuse": False, "warnings": execution.warnings},
            )
            detail_message = _format_validation_detail(
                "SQL ran but needs refinement before it can be stored",
                [],
                execution.warnings,
            )
            return {
                "reply": detail_message,
                "action": "new",
                "reason": execution.no_data_reason or "approved_query_needs_refinement",
                "sql": quoted_sql,
                "rows_preview": [],
                "charts": None,
                "needs_approval": True,
                "proposed_sql": quoted_sql,
                "validation": validation_payload,
                "period_info": "All Periods" if time_scope == "both" else time_scope,
            }

        # Narrow broad result sets when the approved question targets a specific item.
        try:
            from ..services.invoice_bot_helpers import filter_dataframe_by_specific_entity_if_requested
            rows = filter_dataframe_by_specific_entity_if_requested(question, rows)
        except Exception:
            pass

        stored = store_approved_query(
            db,
            current_user.id,
            question,
            quoted_sql,
            source="user" if approval_source == "manual" else "chatgpt",
            model_used="gpt-4o" if approval_source != "manual" else None,
            tables_used=list(execution.validation.tables or []),
        )
        if not stored:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store approved query")

        # Classify intent for metadata tagging (must be defined before log_query_feedback_attempt)
        try:
            from ..services.ai_intent_classifier import classify_intent
            from ..services.join_graph import tables_linked_to_graph
            _intent_tags = classify_intent(question).tags
            _linked_to_graph = tables_linked_to_graph(list(execution.validation.tables or []))
        except Exception:
            _intent_tags = []
            _linked_to_graph = False

        log_query_feedback_attempt(
            db=db,
            user_id=current_user.id,
            user_query=question,
            sql_query=quoted_sql,
            feedback_status="approved",
            attempt_source=approval_source or "chatgpt",
            time_scope=time_scope,
            validation=validation_payload,
            extra_metadata={
                "stored_for_reuse": True,
                "row_count": len(rows),
                "intent_tags": _intent_tags,
                "linked_to_graph": _linked_to_graph,
                "standalone_saved": not _linked_to_graph,
            },
        )

        # Run full orchestrator flow for summarization (reuse last SQL path)
        ai_openai_key = _get_ai_analysis_config()
        if ai_openai_key:
            from ..services.ai_analysis_memory_store import load_memory, save_memory
            from ..services.ai_analysis_orchestrator import OrchestratorResult
            from ..services.ai_chart_generator import analyze_visualization_needs, chart_specs_to_json
            try:
                from ..analysis import compute_metrics, generate_analytics_insights, generate_chart_from_rows
            except ImportError:
                compute_metrics = None
                generate_analytics_insights = None
            mem = load_memory(db, current_user.id)
            mem.last_sql = quoted_sql
            mem.last_rows_json = json.dumps(rows[:80], default=str)
            save_memory(db, mem)
            result = SqlAgentResult(sql=quoted_sql, rows=rows)
            from ..services.ai_analysis_orchestrator import (
                _compute_global_numeric_stats,
                _build_result_scope,
                _select_representative_rows_for_llm,
                _enforce_narrative_stats_consistency,
            )
            from ..services.adaptive_ai_context import (
                analyze_sql_result_shape,
                build_adaptive_query_profile,
                build_result_bound_summary_block,
            )
            result_scope = _build_result_scope(rows, quoted_sql)
            _ap_profile = build_adaptive_query_profile(question)
            _ap_shape = analyze_sql_result_shape(rows, quoted_sql)
            _ap_bind = build_result_bound_summary_block(_ap_profile, _ap_shape)
            global_stats = _compute_global_numeric_stats(rows, question=question, result_scope=result_scope)
            preview_rows_for_llm = _select_representative_rows_for_llm(rows, global_stats, max_rows=20)
            preview = preview_rows_for_llm
            metrics_out = None
            analytics_insights_out = None
            if compute_metrics and generate_analytics_insights:
                try:
                    metrics_out = compute_metrics(rows)
                    analytics_insights_out = generate_analytics_insights(
                        question,
                        rows,
                        metrics=metrics_out,
                        sql=quoted_sql,
                        global_stats=global_stats,
                        representative_rows=preview_rows_for_llm,
                        result_scope=result_scope,
                        binding_block=_ap_bind,
                    )
                except Exception:
                    pass
            charts_data = None
            try:
                chart_specs = analyze_visualization_needs(
                    rows,
                    question,
                    "new",
                    quoted_sql,
                    result_scope=result_scope,
                    query_profile=_ap_profile,
                    result_shape=_ap_shape,
                )
                if chart_specs:
                    charts_data = chart_specs_to_json(chart_specs)
            except Exception:
                pass
            from openai import OpenAI
            client = OpenAI(api_key=ai_openai_key)
            summarization_prompt = f"""You are a data analyst. The user asked: "{question}"

{_ap_bind}

SQL executed:
{quoted_sql[:1500]}

Representative rows (context only; not complete):
{json.dumps(preview[:20], default=str, indent=2)}

GLOBAL_NUMERIC_STATS (source of truth for numeric claims):
{json.dumps(global_stats, default=str, indent=2)}

RESULT_SCOPE (scope of valid claims):
{json.dumps(result_scope, default=str, indent=2)}

STRICT RULES:
- GLOBAL_NUMERIC_STATS MUST be consistent with the narrative.
- If the question is about negative/lowest line amounts:
  * If count_negative = 0, you MUST state that there are no net line amounts < 0.
  * You MUST NOT claim "all amounts are 0" unless min_netwr == max_netwr == 0 and count_positive == 0 and count_negative == 0.
- Never claim "all rows in the dataset/table/year" when RESULT_SCOPE.kind == "limited".
- If RESULT_SCOPE.kind == "limited", explicitly say the summary is based on limited returned rows.

Summarize the answer in 3-8 sentences using MARKDOWN. Use **bold** for key numbers. Use bullet points if listing items."""
            if rows:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": summarization_prompt}],
                    temperature=0.4,
                    max_tokens=700,
                )
                reply = (resp.choices[0].message.content or "").strip()
                # Deterministic guardrail to prevent "all zeros" contradictions.
                try:
                    reply = _enforce_narrative_stats_consistency(
                        reply or "",
                        question,
                        global_stats,
                        result_scope=result_scope,
                    )
                except Exception:
                    pass
            else:
                reply = "The SQL executed successfully but returned **0 rows** for the requested filters."
            period_info, date_range = ("All Periods (1994-2026)", {"min_date": "1994-01-01", "max_date": "2026-12-31"}) if time_scope == "both" else ("Last 30 days", {})
            orch = OrchestratorResult(
                reply=reply or "Query executed successfully.",
                action="new",
                reason="approved_and_stored",
                sql=quoted_sql,
                rows_preview=preview,
                charts=charts_data,
                metrics=metrics_out,
                analytics_insights=analytics_insights_out,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info,
                needs_approval=False,
            )
            payload = orchestrator_payload(orch)
            payload["validation"] = validation_payload
            return payload
        return {
            "reply": "Query executed and stored for future use.",
            "sql": quoted_sql,
            "rows_preview": rows[:30],
            "needs_approval": False,
            "validation": validation_payload,
        }
    finally:
        if USE_SAP_DB_FOR_AI and sql_db is not None and sql_db is not db:
            sql_db.close()


@router.post("/ai-analysis-multi-model")
async def ai_analysis_multi_model_chat(
    message: str = Query(..., description="User's natural language query"),
    context_keys: Optional[list] = Query(None, description="Dashboard context keys to include"),
    days: int = Query(30, ge=1, le=365, description="Time period for context data"),
    time_scope: str = Query("current", description="Data scope: 'current', 'historical' (1994-2010), or 'both'"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    AI analysis chat endpoint with multi-model comparison (GPT-4o + Gemini + Claude).

    Accuracy design:
      1. Run the primary SQL orchestrator first — same as the single-model endpoint.
      2. Pass the REAL result rows + GLOBAL_NUMERIC_STATS to all three models.
      3. Each model writes NARRATIVE ONLY from the same actual data → no hallucination.

    time_scope: 'current' (recent data), 'historical' (1994-2010), or 'both' (compare periods).
    """
    try:
        from ..config.config import ENABLE_MULTI_MODEL, USE_SAP_DB_FOR_AI
        from ..services.multi_model_orchestrator import run_all_models_parallel

        if not ENABLE_MULTI_MODEL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multi-model mode is not enabled. Set ENABLE_MULTI_MODEL=true in .env"
            )

        # ── Step 1: Execute SQL via main orchestrator to get real data ────────
        sql_result_rows = None
        sql_executed = None
        global_numeric_stats = None
        result_scope_data = None

        try:
            from ..services.ai_analysis_orchestrator import (
                run_ai_analysis_orchestrator,
                _compute_global_numeric_stats,
                _build_result_scope,
            )

            ai_openai_key = _get_ai_analysis_config()
            sap_db_for_mm = get_sap_session() if USE_SAP_DB_FOR_AI else None
            try:
                orch = run_ai_analysis_orchestrator(
                    api_key=ai_openai_key,
                    user_id=current_user.id,
                    user_query=message,
                    db=db,
                    conversation_history=[],
                    context_str="",
                    sap_db=sap_db_for_mm,
                    time_scope=time_scope,
                    days=int(days),
                )
            finally:
                if sap_db_for_mm is not None:
                    sap_db_for_mm.close()

            rows = getattr(orch, "rows_preview", None) or []
            sql_executed = getattr(orch, "sql", None) or ""
            if rows:
                sql_result_rows = rows
                result_scope_data = _build_result_scope(rows, sql_executed)
                global_numeric_stats = _compute_global_numeric_stats(
                    rows,
                    question=message,
                    result_scope=result_scope_data,
                )
                logger.info(
                    "multi-model: SQL returned %d rows — passing real data to all 3 models",
                    len(rows),
                )
            else:
                logger.warning("multi-model: orchestrator returned no rows — falling back to context mode")
        except Exception as orch_err:
            logger.error("multi-model: orchestrator failed: %s", orch_err)

        # ── Step 2: Build legacy context string (used only if SQL returned nothing) ──
        context_str = ""
        if not sql_result_rows:
            try:
                if USE_SAP_DB_FOR_AI:
                    from ..database import get_sap_session
                    from ..services.sap_ai_context import build_ai_context_from_sap
                    sap_session_for_context = get_sap_session()
                    try:
                        context_str = build_ai_context_from_sap(
                            context_keys if isinstance(context_keys, list) else [],
                            sap_session_for_context,
                            days=int(days),
                        )
                    finally:
                        sap_session_for_context.close()
                else:
                    context_str = _build_ai_analysis_context(
                        context_keys if isinstance(context_keys, list) else [],
                        current_user,
                        db,
                        days=int(days),
                    )
            except Exception as ctx_err:
                logger.warning("multi-model: context build failed: %s", ctx_err)

        # ── Step 3: Run all three models with data-grounded prompt ────────────
        result = await run_all_models_parallel(
            user_query=message,
            context=context_str,
            time_scope=time_scope,
            days=int(days),
            global_numeric_stats=global_numeric_stats,
            result_scope=result_scope_data,
            sql_result_rows=sql_result_rows,
            sql_executed=sql_executed,
        )

        return {
            "synthesized_answer": result.synthesized_answer,
            "best_model": result.best_model,
            "total_time_ms": result.total_time_ms,
            "time_scope": result.time_scope,
            "date_range": result.date_range,
            "period_info": result.period_info,
            # Expose SQL + row count so the frontend can show "based on N rows"
            "sql": sql_executed or "",
            "row_count": len(sql_result_rows) if sql_result_rows else 0,
            "models": [
                {
                    "name": r.model_name,
                    "content": r.content,
                    "response_time_ms": r.response_time_ms,
                    "success": r.success,
                    "error": r.error,
                    "token_usage": r.token_usage,
                }
                for r in result.individual_responses
            ],
        }

    except Exception as e:
        logger.error(f"Multi-model analysis failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/training-feedback")
async def submit_training_feedback(
    record_id: int = Query(..., description="Training data record ID"),
    feedback_score: int = Query(..., ge=1, le=5, description="Rating 1-5"),
    feedback_comment: str = Query(None, description="Optional feedback comment"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Submit user feedback for an AI analysis response.
    Used to build training dataset for fine-tuning.
    """
    try:
        from ..services.training_data_collector import submit_feedback
        
        success = submit_feedback(
            db=db,
            record_id=record_id,
            feedback_score=feedback_score,
            feedback_comment=feedback_comment,
        )
        
        if success:
            return {"success": True, "message": "Feedback submitted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to submit feedback"
            )
    
    except Exception as e:
        logger.error(f"Feedback submission failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/voice-transcribe")
async def transcribe_voice(
    audio_file: UploadFile = File(..., description="Audio file to transcribe"),
    language: str = Query("en", description="Language code (e.g., 'en', 'es')"),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Transcribe audio file using OpenAI Whisper API.
    Supports WebM, MP3, WAV, and other common audio formats.
    """
    try:
        from ..services.voice_transcription import transcribe_audio
        
        # Read audio file content
        audio_content = await audio_file.read()
        
        if not audio_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty audio file"
            )
        
        # Determine file format
        file_format = "webm"  # default
        if audio_file.filename:
            file_ext = audio_file.filename.split('.')[-1].lower()
            if file_ext in ['mp3', 'wav', 'm4a', 'flac', 'ogg', 'webm']:
                file_format = file_ext
        
        # Transcribe
        result = transcribe_audio(
            audio_file_content=audio_content,
            file_format=file_format,
            language=language if language != "auto" else None,
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result["error"]
            )
        
        return result
    
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/training-stats")
async def get_training_statistics(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get training data collection statistics for the current user.
    """
    try:
        from ..services.training_data_collector import get_training_stats
        
        stats = get_training_stats(db, user_id=current_user.id)
        return stats
    
    except Exception as e:
        logger.error(f"Failed to get training stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
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
            
            # Check if user has any invoices at all
            total_invoices = (
                db.query(func.count(SuccessModel.id))
                .filter(SuccessModel.user_id == current_user.id)
                .scalar() or 0
            ) + (
                db.query(func.count(FailedModel.id))
                .filter(FailedModel.user_id == current_user.id)
                .scalar() or 0
            )
            
            if total_invoices > 0:
                logger.info(f"🔄 Auto-triggering backfill for {total_invoices} invoices")
                # Automatically trigger backfill in background
                try:
                    from ..services.business_intelligence_service import BusinessIntelligenceExtractor
                    from ..models.invoice_business_data import InvoiceBusinessData
                    import uuid
                    
                    bi_extractor = BusinessIntelligenceExtractor()
                    
                    # Process a limited batch to avoid timeout (first 25 invoices)
                    success_invoices = db.query(SuccessModel).filter(
                        SuccessModel.user_id == current_user.id
                    ).limit(25).all()
                    
                    failed_invoices = db.query(FailedModel).filter(
                        FailedModel.user_id == current_user.id
                    ).limit(25).all()
                    
                    processed = 0
                    errors = []
                    
                    # Process successful invoices
                    for invoice in success_invoices:
                        try:
                            xml_content = None
                            if invoice.edi_file_path:
                                try:
                                    xml_content = await read_file_from_storage(invoice.edi_file_path)
                                except Exception as read_err:
                                    logger.warning(f"Could not read file for invoice {invoice.id}: {read_err}")
                            
                            # Extract BI data
                            if xml_content:
                                bi_data = bi_extractor.extract_from_xml(xml_content)
                            else:
                                bi_data = {}
                            
                            # Determine lifecycle stage
                            current_stage = "SENT"
                            stage_status = "SUCCESS"
                            
                            # Create BI record
                            bi_record = InvoiceBusinessData(
                                tracking_id=invoice.tracking_id if hasattr(invoice, 'tracking_id') else uuid.uuid4(),
                                user_id=current_user.id,
                                success_invoice_id=invoice.id,
                                failed_invoice_id=None,
                                customer_id=bi_data.get('customer', {}).get('id'),
                                customer_name=bi_data.get('customer', {}).get('name'),
                                customer_country=bi_data.get('customer', {}).get('country'),
                                supplier_id=bi_data.get('supplier', {}).get('id'),
                                supplier_name=bi_data.get('supplier', {}).get('name'),
                                products=bi_data.get('products', []),
                                total_products_count=len(bi_data.get('products', [])),
                                total_amount=bi_data.get('financial', {}).get('total_amount'),
                                tax_amount=bi_data.get('financial', {}).get('tax_amount'),
                                currency=bi_data.get('financial', {}).get('currency'),
                                invoice_date=bi_data.get('financial', {}).get('invoice_date'),
                                industry=bi_data.get('industry', {}).get('name'),
                                industry_confidence=bi_data.get('industry', {}).get('confidence'),
                                current_stage=current_stage,
                                stage_status=stage_status,
                                source_file_format=invoice.file_format if hasattr(invoice, 'file_format') else None,
                                target_file_format=invoice.target_file_format if hasattr(invoice, 'target_file_format') else None
                            )
                            
                            db.add(bi_record)
                            db.commit()
                            processed += 1
                            
                        except Exception as e:
                            db.rollback()
                            error_msg = f"Invoice {invoice.id}: {str(e)}"
                            logger.error(f"Error processing invoice {invoice.id}: {e}")
                            errors.append(error_msg)
                            continue
                    
                    # Process failed invoices
                    for invoice in failed_invoices:
                        try:
                            xml_content = None
                            if invoice.edi_file_path:
                                try:
                                    xml_content = await read_file_from_storage(invoice.edi_file_path)
                                except Exception as read_err:
                                    logger.warning(f"Could not read file for invoice {invoice.id}: {read_err}")
                            
                            # Extract BI data
                            if xml_content:
                                bi_data = bi_extractor.extract_from_xml(xml_content)
                            else:
                                bi_data = {}
                            
                            # Determine failure stage
                            current_stage = "VALIDATED"
                            stage_status = "FAILED"
                            failed_at_stage = "VALIDATED"
                            
                            # Create BI record
                            bi_record = InvoiceBusinessData(
                                tracking_id=invoice.tracking_id if hasattr(invoice, 'tracking_id') else uuid.uuid4(),
                                user_id=current_user.id,
                                success_invoice_id=None,
                                failed_invoice_id=invoice.id,
                                customer_id=bi_data.get('customer', {}).get('id'),
                                customer_name=bi_data.get('customer', {}).get('name'),
                                customer_country=bi_data.get('customer', {}).get('country'),
                                supplier_id=bi_data.get('supplier', {}).get('id'),
                                supplier_name=bi_data.get('supplier', {}).get('name'),
                                products=bi_data.get('products', []),
                                total_products_count=len(bi_data.get('products', [])),
                                total_amount=bi_data.get('financial', {}).get('total_amount'),
                                tax_amount=bi_data.get('financial', {}).get('tax_amount'),
                                currency=bi_data.get('financial', {}).get('currency'),
                                invoice_date=bi_data.get('financial', {}).get('invoice_date'),
                                industry=bi_data.get('industry', {}).get('name'),
                                industry_confidence=bi_data.get('industry', {}).get('confidence'),
                                current_stage=current_stage,
                                stage_status=stage_status,
                                failed_at_stage=failed_at_stage,
                                failure_reason=invoice.error_message if hasattr(invoice, 'error_message') else None,
                                source_file_format=invoice.file_format if hasattr(invoice, 'file_format') else None,
                                target_file_format=invoice.target_file_format if hasattr(invoice, 'target_file_format') else None
                            )
                            
                            db.add(bi_record)
                            db.commit()
                            processed += 1
                            
                        except Exception as e:
                            db.rollback()
                            error_msg = f"Invoice {invoice.id}: {str(e)}"
                            logger.error(f"Error processing invoice {invoice.id}: {e}")
                            errors.append(error_msg)
                            continue
                    
                    logger.info(f"✅ Auto-backfill processed {processed} invoices (errors: {len(errors)})")
                    
                    if processed > 0:
                        return {
                            "message": f"Successfully processed {processed} of {total_invoices} invoices! Refresh to see your analytics.",
                            "needs_backfill": False,  # Set to false so it shows data on next refresh
                            "auto_backfill_triggered": True,
                            "processed_count": processed,
                            "total_invoices": total_invoices,
                            "errors_count": len(errors),
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
                    else:
                        logger.error(f"❌ No invoices processed. Errors: {errors[:5]}")
                        
                except Exception as e:
                    logger.error(f"❌ Auto-backfill failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            # Return empty structure with helpful message
            return {
                "message": "No business data available yet. Upload invoices or SAT documents to see business analytics." if total_invoices == 0 else "Processing your invoices... Please refresh in a moment.",
                "needs_backfill": total_invoices > 0,
                "has_data": False,
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
        
        logger.info(f"✅ Found {total_bi_records} legacy business intelligence records")
        
        # Check for Invoice V2 BI records
        total_v2_bi_records = db.query(func.count(InvoiceV2BusinessData.id)).filter(
            InvoiceV2BusinessData.user_id == current_user.id
        ).scalar() or 0
        
        logger.info(f"✅ Found {total_v2_bi_records} Invoice V2 business intelligence records")
        
        # ============================================================
        # 1. E2E LIFECYCLE FUNNEL
        # ============================================================
        # Count invoices at each stage (legacy)
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
        
        # Count Invoice V2 invoices at each stage
        v2_stage_counts = db.query(
            InvoiceV2BusinessData.current_stage,
            InvoiceV2BusinessData.stage_status,
            func.count(InvoiceV2BusinessData.id).label('count')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date
        ).group_by(
            InvoiceV2BusinessData.current_stage,
            InvoiceV2BusinessData.stage_status
        ).all()
        
        # Build lifecycle funnel (combine legacy + V2)
        lifecycle_funnel = {
            'RECEIVED': {'total': 0, 'success': 0, 'failed': 0},
            'VALIDATED': {'total': 0, 'success': 0, 'failed': 0},
            'CONVERTED': {'total': 0, 'success': 0, 'failed': 0},
            'SENT': {'total': 0, 'success': 0, 'failed': 0},
            'ACKNOWLEDGED': {'total': 0, 'success': 0, 'failed': 0},
        }
        
        # Add legacy data
        for stage, status, count in stage_counts:
            if stage in lifecycle_funnel:
                lifecycle_funnel[stage]['total'] += count
                if status == 'SUCCESS':
                    lifecycle_funnel[stage]['success'] += count
                elif status == 'FAILED':
                    lifecycle_funnel[stage]['failed'] += count
        
        # Add V2 data
        for stage, status, count in v2_stage_counts:
            if stage in lifecycle_funnel:
                lifecycle_funnel[stage]['total'] += count
                if status == 'SUCCESS':
                    lifecycle_funnel[stage]['success'] += count
                elif status == 'FAILED':
                    lifecycle_funnel[stage]['failed'] += count
        
        # ============================================================
        # 2. CUSTOMER ANALYSIS
        # ============================================================
        # Top customers with success/failed counts (legacy)
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
        
        # Top customers (Invoice V2)
        v2_customer_stats = db.query(
            InvoiceV2BusinessData.customer_id,
            InvoiceV2BusinessData.customer_name,
            InvoiceV2BusinessData.customer_country,
            InvoiceV2BusinessData.stage_status,
            func.count(InvoiceV2BusinessData.id).label('count'),
            func.sum(InvoiceV2BusinessData.total_amount).label('total_revenue')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.customer_name.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.customer_id,
            InvoiceV2BusinessData.customer_name,
            InvoiceV2BusinessData.customer_country,
            InvoiceV2BusinessData.stage_status
        ).all()
        
        # Aggregate customer data (legacy + V2)
        customer_map = {}
        
        # Add legacy data
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
        
        # Add V2 data
        for cust_id, cust_name, country, status, count, revenue in v2_customer_stats:
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
        # Legacy data
        country_stats = db.query(
            InvoiceBusinessData.customer_country,
            func.count(InvoiceBusinessData.id).label('count')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.customer_country.isnot(None)
        ).group_by(
            InvoiceBusinessData.customer_country
        ).all()
        
        # V2 data
        v2_country_stats = db.query(
            InvoiceV2BusinessData.customer_country,
            func.count(InvoiceV2BusinessData.id).label('count')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.customer_country.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.customer_country
        ).all()
        
        # Combine and aggregate
        country_map = {}
        for country, count in country_stats:
            country_map[country] = country_map.get(country, 0) + count
        for country, count in v2_country_stats:
            country_map[country] = country_map.get(country, 0) + count
        
        # Sort and limit
        country_distribution = [
            {'country': country, 'count': count}
            for country, count in sorted(country_map.items(), key=lambda x: x[1], reverse=True)[:15]
        ]
        
        # ============================================================
        # 4. INDUSTRY BREAKDOWN
        # ============================================================
        # Legacy data
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
        ).all()
        
        # V2 data
        v2_industry_stats = db.query(
            InvoiceV2BusinessData.industry,
            func.count(InvoiceV2BusinessData.id).label('count'),
            func.sum(InvoiceV2BusinessData.total_amount).label('total_revenue')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.industry.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.industry
        ).all()
        
        # Combine and aggregate
        industry_map = {}
        for industry, count, revenue in industry_stats:
            if industry not in industry_map:
                industry_map[industry] = {'count': 0, 'total_revenue': 0}
            industry_map[industry]['count'] += count
            industry_map[industry]['total_revenue'] += float(revenue or 0)
        
        for industry, count, revenue in v2_industry_stats:
            if industry not in industry_map:
                industry_map[industry] = {'count': 0, 'total_revenue': 0}
            industry_map[industry]['count'] += count
            industry_map[industry]['total_revenue'] += float(revenue or 0)
        
        # Sort by count
        industry_breakdown = [
            {
                'industry': industry,
                'count': data['count'],
                'total_revenue': data['total_revenue']
            }
            for industry, data in sorted(industry_map.items(), key=lambda x: x[1]['count'], reverse=True)
        ]
        
        # ============================================================
        # 5. PRODUCT ANALYSIS (Top products across all invoices)
        # ============================================================
        # This requires parsing the products JSONB field
        product_counts = {}
        
        # Legacy products
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
                    product_counts[product_name]['total_quantity'] += float(product.get('quantity', 0))
                    product_counts[product_name]['total_revenue'] += float(product.get('line_total', 0))
        
        # V2 products
        v2_bi_records_with_products = db.query(InvoiceV2BusinessData).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.products.isnot(None)
        ).all()
        
        for record in v2_bi_records_with_products:
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
                    product_counts[product_name]['total_quantity'] += float(product.get('quantity', 0))
                    product_counts[product_name]['total_revenue'] += float(product.get('revenue', 0))
        
        # Sort by count and get top 10
        top_products = sorted(product_counts.values(), key=lambda x: x['count'], reverse=True)[:10]
        
        # ============================================================
        # 6. SUPPLIER ANALYSIS
        # ============================================================
        # Legacy suppliers
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
        ).all()
        
        # V2 suppliers
        v2_supplier_stats = db.query(
            InvoiceV2BusinessData.supplier_id,
            InvoiceV2BusinessData.supplier_name,
            func.count(InvoiceV2BusinessData.id).label('count')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.supplier_name.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.supplier_id,
            InvoiceV2BusinessData.supplier_name
        ).all()
        
        # Combine and aggregate
        supplier_map = {}
        for supplier_id, supplier_name, count in supplier_stats:
            key = supplier_id or supplier_name
            if key not in supplier_map:
                supplier_map[key] = {
                    'supplier_id': supplier_id,
                    'supplier_name': supplier_name,
                    'count': 0
                }
            supplier_map[key]['count'] += count
        
        for supplier_id, supplier_name, count in v2_supplier_stats:
            key = supplier_id or supplier_name
            if key not in supplier_map:
                supplier_map[key] = {
                    'supplier_id': supplier_id,
                    'supplier_name': supplier_name,
                    'count': 0
                }
            supplier_map[key]['count'] += count
        
        # Sort and limit to top 10
        top_suppliers = sorted(supplier_map.values(), key=lambda x: x['count'], reverse=True)[:10]
        
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
        import traceback
        logger.error(traceback.format_exc())
        
        # Return empty data instead of 500 error
        return {
            "lifecycle_funnel": {
                'RECEIVED': {'total': 0, 'success': 0, 'failed': 0},
                'VALIDATED': {'total': 0, 'success': 0, 'failed': 0},
                'CONVERTED': {'total': 0, 'success': 0, 'failed': 0},
                'SENT': {'total': 0, 'success': 0, 'failed': 0},
                'ACKNOWLEDGED': {'total': 0, 'success': 0, 'failed': 0},
            },
            "customer_analysis": {"top_customers": [], "total_customers": 0, "by_country": []},
            "country_distribution": [],
            "industry_breakdown": [],
            "product_analysis": {"top_products": [], "total_products": 0},
            "supplier_analysis": {"top_suppliers": []}
        }


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
            logger.warning(f"⚠️ No product data found for user {current_user.id}")
            return {
                "message": "No product data available yet. Upload invoices with product information to see industry intelligence.",
                "has_data": False,
                "summary": {
                    "total_products": 0,
                    "underperforming": 0,
                    "optimal": 0,
                    "outperforming": 0,
                    "total_revenue": 0
                },
                "products": [],
                "industry_benchmarks": {},
                "ai_insights": None,
                "date_range": {
                    "start": cutoff_date.isoformat(),
                    "end": datetime.utcnow().isoformat(),
                    "days": days
                }
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


# Common ISO 3166-1 alpha-2 country codes to full names (for display)
COUNTRY_CODE_NAMES = {
    "NZ": "New Zealand", "AU": "Australia", "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom",
    "DE": "Germany", "FR": "France", "JP": "Japan", "CN": "China", "IN": "India", "SG": "Singapore",
    "MY": "Malaysia", "TH": "Thailand", "ID": "Indonesia", "PH": "Philippines", "VN": "Vietnam",
    "KR": "South Korea", "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "ES": "Spain", "IT": "Italy",
    "NL": "Netherlands", "CH": "Switzerland", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "IE": "Ireland", "BE": "Belgium", "AT": "Austria", "PL": "Poland",
    "AE": "United Arab Emirates", "SA": "Saudi Arabia", "ZA": "South Africa", "HK": "Hong Kong",
}


def _country_code_to_name(code: str) -> str:
    """Return full country name for ISO code, or code itself if unknown."""
    if not code or code == "Unknown":
        return code or "Unknown"
    return COUNTRY_CODE_NAMES.get(str(code).upper(), code)


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


# ============================================================================
# Invoice V2 Business Intelligence Endpoints
# ============================================================================

@router.get("/revenue-analysis")
async def get_revenue_analysis(
    days: int = Query(default=90, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get revenue analysis by country, season, and fiscal quarter.
    Combines legacy and Invoice V2 data.
    """
    logger.info(f"📊 Fetching revenue analysis for last {days} days")
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # ============================================================
        # REVENUE BY COUNTRY
        # ============================================================
        # Legacy data
        country_revenue_legacy = db.query(
            InvoiceBusinessData.customer_country,
            func.count(InvoiceBusinessData.id).label('invoice_count'),
            func.sum(InvoiceBusinessData.total_amount).label('revenue')
        ).filter(
            InvoiceBusinessData.user_id == current_user.id,
            InvoiceBusinessData.created_at >= cutoff_date,
            InvoiceBusinessData.customer_country.isnot(None)
        ).group_by(
            InvoiceBusinessData.customer_country
        ).all()
        
        # V2 data
        country_revenue_v2 = db.query(
            InvoiceV2BusinessData.customer_country,
            func.count(InvoiceV2BusinessData.id).label('invoice_count'),
            func.sum(InvoiceV2BusinessData.total_amount).label('revenue')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.customer_country.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.customer_country
        ).all()
        
        # Combine
        country_map = {}
        for country, count, revenue in country_revenue_legacy:
            country_map[country] = {
                'country': country,
                'revenue': float(revenue or 0),
                'invoice_count': count
            }
        
        for country, count, revenue in country_revenue_v2:
            if country not in country_map:
                country_map[country] = {
                    'country': country,
                    'revenue': 0,
                    'invoice_count': 0
                }
            country_map[country]['revenue'] += float(revenue or 0)
            country_map[country]['invoice_count'] += count
        
        by_country = sorted(country_map.values(), key=lambda x: x['revenue'], reverse=True)
        
        # ============================================================
        # REVENUE BY SEASON
        # ============================================================
        # V2 data (has season field)
        season_revenue = db.query(
            InvoiceV2BusinessData.season,
            func.sum(InvoiceV2BusinessData.total_amount).label('revenue'),
            func.count(InvoiceV2BusinessData.id).label('invoice_count')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.season.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.season
        ).all()
        
        by_season = [
            {
                'season': season,
                'revenue': float(revenue or 0),
                'invoice_count': count
            }
            for season, revenue, count in season_revenue
        ]
        
        # ============================================================
        # REVENUE BY FISCAL QUARTER
        # ============================================================
        # V2 data (has fiscal quarter field)
        quarter_revenue = db.query(
            InvoiceV2BusinessData.fiscal_quarter,
            InvoiceV2BusinessData.fiscal_year,
            func.sum(InvoiceV2BusinessData.total_amount).label('revenue'),
            func.count(InvoiceV2BusinessData.id).label('invoice_count')
        ).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.fiscal_quarter.isnot(None)
        ).group_by(
            InvoiceV2BusinessData.fiscal_quarter,
            InvoiceV2BusinessData.fiscal_year
        ).order_by(
            InvoiceV2BusinessData.fiscal_year.desc(),
            InvoiceV2BusinessData.fiscal_quarter.desc()
        ).all()
        
        by_quarter = [
            {
                'quarter': quarter,
                'year': year,
                'revenue': float(revenue or 0),
                'invoice_count': count
            }
            for quarter, year, revenue, count in quarter_revenue
        ]
        
        return {
            "by_country": by_country,
            "by_season": by_season,
            "by_quarter": by_quarter,
            "period_days": days
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch revenue analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Revenue analysis failed: {str(e)}"
        )


@router.get("/product-demand")
async def get_product_demand_analysis(
    days: int = Query(default=90, ge=1, le=365),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get product demand analysis including:
    - Trending products (increasing/stable/decreasing)
    - Top customers per product
    - Top countries per product
    """
    logger.info(f"📊 Fetching product demand analysis for last {days} days")
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get all V2 BI records with products
        v2_records = db.query(InvoiceV2BusinessData).filter(
            InvoiceV2BusinessData.user_id == current_user.id,
            InvoiceV2BusinessData.created_at >= cutoff_date,
            InvoiceV2BusinessData.products.isnot(None)
        ).order_by(
            InvoiceV2BusinessData.invoice_date.desc()
        ).all()
        
        # Aggregate product data
        product_data = {}
        customer_product_map = {}  # Track which customers buy which products
        country_product_map = {}   # Track which countries buy which products
        
        for record in v2_records:
            products = record.products
            if not products or not isinstance(products, list):
                continue
            
            for product in products:
                product_name = product.get('name', 'Unknown')
                
                # Initialize product data
                if product_name not in product_data:
                    product_data[product_name] = {
                        'name': product_name,
                        'total_quantity': 0,
                        'total_revenue': 0,
                        'order_count': 0,
                        'customers': set(),
                        'countries': set(),
                        'monthly_counts': {}
                    }
                
                # Aggregate metrics
                product_data[product_name]['total_quantity'] += float(product.get('quantity', 0))
                product_data[product_name]['total_revenue'] += float(product.get('revenue', 0))
                product_data[product_name]['order_count'] += 1
                
                if record.customer_name:
                    product_data[product_name]['customers'].add(record.customer_name)
                    
                    # Track customer-product relationship
                    if record.customer_name not in customer_product_map:
                        customer_product_map[record.customer_name] = {}
                    if product_name not in customer_product_map[record.customer_name]:
                        customer_product_map[record.customer_name][product_name] = 0
                    customer_product_map[record.customer_name][product_name] += 1
                
                if record.customer_country:
                    product_data[product_name]['countries'].add(record.customer_country)
                    
                    # Track country-product relationship
                    if record.customer_country not in country_product_map:
                        country_product_map[record.customer_country] = {}
                    if product_name not in country_product_map[record.customer_country]:
                        country_product_map[record.customer_country][product_name] = 0
                    country_product_map[record.customer_country][product_name] += 1
                
                # Track monthly counts for trend analysis
                if record.invoice_date:
                    month_key = f"{record.invoice_date.year}-{record.invoice_date.month:02d}"
                    if month_key not in product_data[product_name]['monthly_counts']:
                        product_data[product_name]['monthly_counts'][month_key] = 0
                    product_data[product_name]['monthly_counts'][month_key] += 1
        
        # Calculate trends for each product
        trending_products = []
        for product_name, data in product_data.items():
            # Simple trend: compare first half vs second half of period
            monthly_counts = sorted(data['monthly_counts'].items())
            if len(monthly_counts) >= 2:
                mid = len(monthly_counts) // 2
                first_half_avg = sum(c for _, c in monthly_counts[:mid]) / mid
                second_half_avg = sum(c for _, c in monthly_counts[mid:]) / (len(monthly_counts) - mid)
                
                if second_half_avg > first_half_avg * 1.2:
                    trend = "increasing"
                    growth = ((second_half_avg - first_half_avg) / first_half_avg) * 100
                elif second_half_avg < first_half_avg * 0.8:
                    trend = "decreasing"
                    growth = ((second_half_avg - first_half_avg) / first_half_avg) * 100
                else:
                    trend = "stable"
                    growth = 0
            else:
                trend = "insufficient_data"
                growth = 0
            
            # Get top customers for this product
            top_customers = sorted(
                [(cust, count) for cust, products in customer_product_map.items() if product_name in products
                 for count in [products[product_name]]],
                key=lambda x: x[1],
                reverse=True
            )[:3]
            
            # Get top countries for this product
            top_countries = sorted(
                [(country, count) for country, products in country_product_map.items() if product_name in products
                 for count in [products[product_name]]],
                key=lambda x: x[1],
                reverse=True
            )[:3]
            
            trending_products.append({
                'name': product_name,
                'trend': trend,
                'monthly_growth': round(growth, 1) if growth else 0,
                'total_quantity': data['total_quantity'],
                'total_revenue': data['total_revenue'],
                'order_count': data['order_count'],
                'customer_count': len(data['customers']),
                'top_customers': [cust for cust, _ in top_customers],
                'top_countries': [country for country, _ in top_countries]
            })
        
        # Sort by order count (most popular first)
        trending_products = sorted(trending_products, key=lambda x: x['order_count'], reverse=True)[:20]
        
        # Customer preferences (top products per customer)
        customer_preferences = []
        for customer_name, products in customer_product_map.items():
            if not products:
                continue
            
            # Get top 3 products for this customer
            top_products = sorted(products.items(), key=lambda x: x[1], reverse=True)[:3]
            
            # Calculate purchase frequency (rough estimate)
            total_purchases = sum(products.values())
            if total_purchases >= 10:
                frequency = "frequent"
            elif total_purchases >= 5:
                frequency = "monthly"
            elif total_purchases >= 2:
                frequency = "occasional"
            else:
                frequency = "rare"
            
            customer_preferences.append({
                'customer_name': customer_name,
                'favorite_products': [prod for prod, _ in top_products],
                'purchase_frequency': frequency,
                'total_purchases': total_purchases
            })
        
        # Sort by total purchases
        customer_preferences = sorted(customer_preferences, key=lambda x: x['total_purchases'], reverse=True)[:15]
        
        return {
            "trending_products": trending_products,
            "customer_preferences": customer_preferences,
            "period_days": days
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch product demand analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/dashboard-data-stats")
async def get_dashboard_data_stats(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Counts for the Invoices "Dashboard data" tab: successful validated, converted, and BI records.
    Used so users can see how much data is available and trigger extraction for the Business tab.
    """
    try:
        validated_success = db.query(func.count(InvoiceV2Validated.id)).join(
            InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.deleted_at.is_(None),
            InvoiceV2Validated.status == "success"
        ).scalar() or 0
        converted_count = db.query(func.count(ConvertedInvoice.id)).join(
            InvoiceV2Validated, ConvertedInvoice.validated_invoice_id == InvoiceV2Validated.id
        ).join(InvoiceV2Document, InvoiceV2Validated.document_id == InvoiceV2Document.id).filter(
            InvoiceV2Document.user_id == current_user.id
        ).scalar() or 0
        bi_count = db.query(func.count(InvoiceV2BusinessData.id)).filter(
            InvoiceV2BusinessData.user_id == current_user.id
        ).scalar() or 0
        return {
            "validated_success_count": validated_success,
            "converted_count": converted_count,
            "bi_extracted_count": bi_count,
        }
    except Exception as e:
        logger.error(f"Dashboard data stats: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


def _run_backfill_invoice_v2_bi(db: Session, current_user: ZodiacUser, max_invoices: int = 2000) -> tuple:
    """
    Backfill InvoiceV2BusinessData from successful validated invoices (line_items -> products).
    Returns (processed, skipped, errors, total).
    """
    bi_service = InvoiceV2BusinessIntelligence()
    validated_invoices = db.query(InvoiceV2Validated).join(
        InvoiceV2Document,
        InvoiceV2Validated.document_id == InvoiceV2Document.id
    ).filter(
        InvoiceV2Document.user_id == current_user.id,
        InvoiceV2Validated.status == "success"
    ).limit(max_invoices).all()

    processed = skipped = errors = 0
    for validated_invoice in validated_invoices:
        try:
            existing = db.query(InvoiceV2BusinessData).filter(
                InvoiceV2BusinessData.validated_invoice_id == validated_invoice.id
            ).first()
            if existing:
                skipped += 1
                continue
            bi_data = bi_service.extract_bi_data(validated_invoice)
            user_id = bi_data.get("user_id") or current_user.id
            bi_record = InvoiceV2BusinessData(
                validated_invoice_id=bi_data["validated_invoice_id"],
                user_id=user_id,
                customer_id=bi_data["customer"].get("id"),
                customer_name=bi_data["customer"].get("name"),
                customer_country=bi_data["customer"].get("country"),
                supplier_id=bi_data["supplier"].get("id"),
                supplier_name=bi_data["supplier"].get("name"),
                products=bi_data["products"],
                total_products_count=bi_data["total_products_count"],
                total_amount=bi_data["financial"].get("total_amount"),
                tax_amount=bi_data["financial"].get("tax_amount"),
                currency=bi_data["financial"].get("currency"),
                industry=bi_data["industry"],
                industry_confidence=bi_data["industry_confidence"],
                industry_keywords_matched=bi_data["industry_keywords_matched"],
                invoice_date=bi_data["temporal"].get("invoice_date"),
                fiscal_quarter=bi_data["temporal"].get("fiscal_quarter"),
                fiscal_year=bi_data["temporal"].get("fiscal_year"),
                season=bi_data["temporal"].get("season"),
                current_stage=bi_data["lifecycle"].get("current_stage"),
                stage_status=bi_data["lifecycle"].get("stage_status"),
            )
            db.add(bi_record)
            processed += 1
            if processed % 50 == 0:
                db.commit()
        except Exception as e:
            logger.warning(f"Backfill BI invoice {getattr(validated_invoice, 'id', '?')}: {e}")
            errors += 1
    if processed > 0 or errors > 0:
        db.commit()
    return (processed, skipped, errors, len(validated_invoices))


@router.post("/backfill-invoice-v2-bi")
async def backfill_invoice_v2_bi(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Backfill business intelligence data from existing Invoice V2 validated invoices.
    Uses line_items from each successful validated invoice to populate products for the Business tab.
    """
    logger.info(f"🔄 Starting Invoice V2 BI backfill for user {current_user.id}")
    try:
        processed, skipped, errors, total = _run_backfill_invoice_v2_bi(db, current_user)
        logger.info(f"✅ Backfill completed: {processed} processed, {skipped} skipped, {errors} errors")
        return {
            "success": True,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
            "total": total,
            "message": f"Successfully backfilled BI data for {processed} invoices (products from line_items)",
        }
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backfill failed: {str(e)}"
        )

