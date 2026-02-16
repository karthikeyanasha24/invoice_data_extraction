"""
Invoice Conversion Service
Converts successful invoices to customer-specific target formats
"""
import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from lxml import etree

from ..models.invoice_v2_validated import InvoiceV2Validated
from ..models.customer import Customer
from ..models.converted_invoice import ConvertedInvoice
from ..utils.xml_to_x12 import convert_xml_to_x12_content
from ..utils.xml_to_edifact_direct import convert_xml_to_edifact_direct
from ..utils.pdf_generator import generate_pdf_from_xml
from .file_service import save_file_to_storage, read_file_from_storage

logger = logging.getLogger("zodiac-api.conversion")


class InvoiceConversionService:
    """
    Service for converting successful invoices to customer-specific formats.
    Validates invoice fields against customer requirements before conversion.
    """
    
    # Supported target formats
    SUPPORTED_FORMATS = ["X12", "EDIFACT", "PDF", "XML", "UBL", "PIDX", "CFDI"]
    
    def __init__(self, db: Session):
        self.db = db
    
    async def convert_invoice(
        self, 
        validated_invoice_id: int, 
        override_validation: bool = False
    ) -> Dict[str, Any]:
        """
        Convert a single successful invoice to its target format.
        
        Returns:
            {
                "status": "success" | "failed" | "validation_mismatch",
                "converted_invoice_id": int | None,
                "target_format": str,
                "validation_mismatches": dict | None,
                "error_message": str | None,
                "steps": list of step messages
            }
        """
        logger.info(f"🔄 Starting conversion for validated invoice ID: {validated_invoice_id}")
        
        steps = []  # Track detailed steps for user feedback
        
        try:
            # 1. Load validated invoice
            steps.append(f"📋 Step 1: Loading invoice data (ID: {validated_invoice_id})...")
            
            validated = self.db.query(InvoiceV2Validated).filter(
                InvoiceV2Validated.id == validated_invoice_id
            ).first()
            
            if not validated:
                steps.append(f"❌ Error: Invoice {validated_invoice_id} not found in database")
                return {
                    "status": "failed",
                    "error_message": f"Validated invoice {validated_invoice_id} not found",
                    "steps": steps
                }
            
            if validated.status != "success":
                steps.append(f"❌ Error: Invoice status is '{validated.status}' (only 'success' status can be converted)")
                return {
                    "status": "failed",
                    "error_message": f"Invoice status is '{validated.status}', only 'success' status can be converted",
                    "steps": steps
                }
            
            invoice_data = validated.invoice_data
            invoice_number = invoice_data.get("invoice_number", "Unknown")
            customer_id = invoice_data.get("customer_id")
            
            steps.append(f"✅ Invoice loaded: #{invoice_number}")
            steps.append(f"   Customer ID in invoice: {customer_id or 'Not specified'}")
            
            # 2. Find customer by customer_id
            steps.append(f"🔍 Step 2: Looking up customer configuration...")
            
            customer = None
            target_format = "XML"  # Default format
            
            if customer_id:
                customer = self.db.query(Customer).filter(
                    Customer.customer_id == customer_id
                ).first()
                
                if customer:
                    logger.info(f"✅ Found customer: {customer_id} (target format: {customer.target_format})")
                    steps.append(f"✅ Customer found: {customer_id}")
                    steps.append(f"   Target format: {customer.target_format}")
                    steps.append(f"   Tax settings: ${customer.tax_value} ({customer.tax_percentage}%)")
                    
                    target_format = customer.target_format.upper()
                    
                    # 3. Validate invoice fields against customer validation fields
                    if not override_validation and customer.validation_fields:
                        steps.append(f"🔍 Step 3: Validating invoice fields against customer rules...")
                        
                        is_valid, mismatches = self._validate_invoice_fields(
                            invoice_data, 
                            customer.validation_fields
                        )
                        
                        if not is_valid:
                            logger.warning(f"⚠️ Validation mismatch found for invoice {validated_invoice_id}")
                            steps.append(f"⚠️ Validation mismatch detected!")
                            steps.append(f"   Fields that don't match: {', '.join(mismatches.keys())}")
                            return {
                                "status": "validation_mismatch",
                                "validated_invoice_id": validated_invoice_id,
                                "customer_id": customer_id,
                                "validation_mismatches": mismatches,
                                "steps": steps
                            }
                        else:
                            steps.append(f"✅ All validation fields match customer requirements")
                    else:
                        if override_validation:
                            steps.append(f"⚠️ Step 3: Validation check skipped (override enabled)")
                        else:
                            steps.append(f"ℹ️ Step 3: No validation rules configured for this customer")
                else:
                    logger.info(f"ℹ️ No customer found for customer_id: {customer_id}, using default XML format")
                    steps.append(f"⚠️ Customer '{customer_id}' not found in database")
                    steps.append(f"ℹ️ Using default conversion: XML format")
            else:
                logger.info(f"ℹ️ No customer_id in invoice data, using default XML format")
                steps.append(f"ℹ️ No customer ID specified in invoice")
                steps.append(f"ℹ️ Using default conversion: XML format")
            
            # 4. Convert to target format
            logger.info(f"🔄 Converting to format: {target_format}")
            steps.append(f"🔄 Step 4: Converting invoice to {target_format} format...")
            
            try:
                converted_content, file_extension = await self._convert_to_format(
                    invoice_data,
                    target_format,
                    validated
                )
                
                if not converted_content:
                    steps.append(f"❌ Conversion failed: No content generated")
                    steps.append(f"   This may indicate an issue with the XML file or conversion logic")
                    return {
                        "status": "failed",
                        "error_message": f"Conversion to {target_format} failed - no content generated",
                        "steps": steps
                    }
                
                steps.append(f"✅ Conversion successful ({len(converted_content)} bytes generated)")
            except Exception as conv_error:
                steps.append(f"❌ Conversion failed with error: {str(conv_error)}")
                steps.append(f"   Error type: {type(conv_error).__name__}")
                logger.error(f"❌ Conversion error: {conv_error}")
                logger.exception(conv_error)
                return {
                    "status": "failed",
                    "error_message": f"Conversion error: {str(conv_error)}",
                    "steps": steps
                }
            
            # 5. Save converted file to storage
            filename = f"converted_{validated_invoice_id}_{invoice_number}_{target_format}.{file_extension}"
            
            logger.info(f"💾 Saving converted file: {filename}")
            steps.append(f"💾 Step 5: Saving converted file to storage...")
            steps.append(f"   Filename: {filename}")
            
            storage_result = await save_file_to_storage(
                file_content=converted_content,
                filename=filename
            )
            
            # Parse storage result
            converted_file_path = None
            blob_converted_path = None
            
            if isinstance(storage_result, dict):
                # Vercel Blob response
                blob_converted_path = storage_result.get('url')
                logger.info(f"📦 Saved to blob storage: {blob_converted_path}")
                steps.append(f"✅ File saved to blob storage")
            elif isinstance(storage_result, str):
                # Local file path
                converted_file_path = storage_result
                logger.info(f"📁 Saved to local storage: {converted_file_path}")
                steps.append(f"✅ File saved to local storage: {converted_file_path}")
            
            # 6. Create ConvertedInvoice record
            steps.append(f"💾 Step 6: Creating conversion record in database...")
            
            converted_invoice = ConvertedInvoice(
                validated_invoice_id=validated_invoice_id,
                customer_id=customer_id,
                target_format=target_format,
                converted_file_path=converted_file_path,
                blob_converted_path=blob_converted_path,
                conversion_status="success",
                conversion_notes=f"Converted to {target_format} successfully",
                validation_overridden=override_validation
            )
            
            self.db.add(converted_invoice)
            self.db.commit()
            self.db.refresh(converted_invoice)
            
            logger.info(f"✅ Conversion completed successfully: ID {converted_invoice.id}")
            steps.append(f"✅ Conversion record created (ID: {converted_invoice.id})")
            steps.append(f"🎉 Conversion completed successfully!")
            
            return {
                "status": "success",
                "converted_invoice_id": converted_invoice.id,
                "target_format": target_format,
                "validated_invoice_id": validated_invoice_id,
                "steps": steps
            }
            
        except Exception as e:
            logger.error(f"❌ Conversion failed: {e}")
            logger.exception(e)
            self.db.rollback()
            
            steps.append(f"❌ FATAL ERROR: {str(e)}")
            steps.append(f"   Error type: {type(e).__name__}")
            
            # Create failed record
            try:
                failed_record = ConvertedInvoice(
                    validated_invoice_id=validated_invoice_id,
                    customer_id=invoice_data.get("customer_id") if 'invoice_data' in locals() else None,
                    target_format=target_format if 'target_format' in locals() else "UNKNOWN",
                    conversion_status="failed",
                    conversion_notes=f"Conversion error: {str(e)}",
                    validation_overridden=override_validation
                )
                self.db.add(failed_record)
                self.db.commit()
                steps.append(f"💾 Failed conversion record created")
            except:
                pass  # If we can't even create the failed record, just continue
            
            return {
                "status": "failed",
                "error_message": str(e),
                "validated_invoice_id": validated_invoice_id,
                "steps": steps
            }
    
    def _validate_invoice_fields(
        self, 
        invoice_data: Dict[str, Any], 
        customer_validation_fields_json: str
    ) -> Tuple[bool, Optional[Dict[str, Dict[str, Any]]]]:
        """
        Validate invoice fields against customer expected values.
        
        Returns:
            (is_valid, mismatches_dict)
            - is_valid: True if ALL validation fields match
            - mismatches_dict: {field_name: {expected: x, actual: y}} if mismatches found
        """
        try:
            # Parse customer validation fields
            validation_fields = json.loads(customer_validation_fields_json)
            
            if not validation_fields or not isinstance(validation_fields, dict):
                # No validation fields to check
                return True, None
            
            mismatches = {}
            
            for field_name, expected_value in validation_fields.items():
                # Skip if expected value is empty/null
                if not expected_value:
                    continue
                
                actual_value = invoice_data.get(field_name)
                
                # Convert to strings for comparison
                expected_str = str(expected_value).strip()
                actual_str = str(actual_value).strip() if actual_value is not None else ""
                
                if expected_str != actual_str:
                    logger.warning(f"⚠️ Mismatch: {field_name} - expected '{expected_str}', got '{actual_str}'")
                    mismatches[field_name] = {
                        "expected": expected_str,
                        "actual": actual_str
                    }
            
            if mismatches:
                return False, mismatches
            
            logger.info(f"✅ All validation fields match")
            return True, None
            
        except Exception as e:
            logger.error(f"❌ Error validating fields: {e}")
            # If validation fails, assume it's valid (don't block conversion)
            return True, None
    
    async def _convert_to_format(
        self, 
        invoice_data: Dict[str, Any], 
        target_format: str,
        validated: InvoiceV2Validated
    ) -> Tuple[Optional[bytes], str]:
        """
        Convert invoice data to target format.
        
        Returns:
            (converted_content_bytes, file_extension)
        """
        logger.info(f"🔄 Converting to {target_format}")
        
        try:
            # Load original XML content
            xml_content = await self._load_original_xml(validated)
            
            target_format = target_format.upper()
            
            # Route to appropriate converter
            if target_format == "X12":
                return await self._convert_to_x12(xml_content, invoice_data)
            
            elif target_format == "EDIFACT":
                return await self._convert_to_edifact(xml_content, invoice_data)
            
            elif target_format == "PDF":
                return await self._convert_to_pdf(xml_content, invoice_data)
            
            elif target_format in ["XML", "UBL"]:
                # Return original XML
                return xml_content.encode('utf-8'), "xml"
            
            elif target_format == "CFDI":
                # TODO: Implement CFDI conversion if needed
                logger.warning(f"⚠️ CFDI conversion not yet implemented, returning XML")
                return xml_content.encode('utf-8'), "xml"
            
            elif target_format == "PIDX":
                # TODO: Implement PIDX conversion if needed
                logger.warning(f"⚠️ PIDX conversion not yet implemented, returning XML")
                return xml_content.encode('utf-8'), "xml"
            
            else:
                logger.error(f"❌ Unsupported format: {target_format}")
                return None, ""
        
        except Exception as e:
            logger.error(f"❌ Conversion error: {e}")
            logger.exception(e)
            return None, ""
    
    async def _load_original_xml(self, validated: InvoiceV2Validated) -> str:
        """Load original XML from the document"""
        try:
            document = validated.document
            
            if not document:
                logger.error("❌ No document associated with validated invoice")
                raise ValueError("No document associated with validated invoice")
            
            logger.info(f"📁 Loading original XML from document ID: {document.id}")
            logger.info(f"   Blob path: {document.blob_xml_path}")
            logger.info(f"   Local path: {document.xml_path}")
            
            # Load XML from storage
            if document.blob_xml_path:
                logger.info("📦 Reading from blob storage...")
                xml_bytes = await read_file_from_storage(
                    file_path=document.blob_xml_path,
                    blob_xml_path=document.blob_xml_path
                )
            elif document.xml_path:
                logger.info("📁 Reading from local storage...")
                xml_bytes = await read_file_from_storage(
                    file_path=document.xml_path,
                    blob_xml_path=None
                )
            else:
                logger.error("❌ No file path available for this document")
                raise ValueError("No file path available for this document")
            
            logger.info(f"✅ XML loaded successfully: {len(xml_bytes)} bytes")
            return xml_bytes.decode('utf-8')
            
        except Exception as e:
            logger.error(f"❌ Failed to load original XML: {e}")
            logger.exception(e)
            raise
    
    async def _convert_to_x12(self, xml_content: str, invoice_data: Dict) -> Tuple[bytes, str]:
        """Convert to X12 format"""
        try:
            logger.info("📄 Converting to X12...")
            # Convert string to bytes for the converter
            xml_bytes = xml_content.encode('utf-8')
            # Pass invoice_data (X12 converter will use it in future enhancements)
            x12_content = convert_xml_to_x12_content(xml_bytes, invoice_data=invoice_data)
            
            if not x12_content:
                raise ValueError("X12 conversion returned empty content")
            
            # Convert to bytes if string
            if isinstance(x12_content, str):
                x12_bytes = x12_content.encode('utf-8')
            else:
                x12_bytes = x12_content
            
            logger.info(f"✅ X12 conversion successful: {len(x12_bytes)} bytes")
            return x12_bytes, "edi"
            
        except Exception as e:
            logger.error(f"❌ X12 conversion failed: {e}")
            logger.exception(e)
            raise
    
    async def _convert_to_edifact(self, xml_content: str, invoice_data: Dict) -> Tuple[bytes, str]:
        """Convert to EDIFACT format with comprehensive data from invoice_data"""
        try:
            logger.info("📄 Converting to EDIFACT with all extracted data...")
            # Convert string to bytes for the converter
            xml_bytes = xml_content.encode('utf-8')
            # Pass invoice_data to preserve all extracted fields
            edifact_content = convert_xml_to_edifact_direct(xml_bytes, invoice_data=invoice_data)
            
            if not edifact_content:
                raise ValueError("EDIFACT conversion returned empty content")
            
            # Convert to bytes if string
            if isinstance(edifact_content, str):
                edifact_bytes = edifact_content.encode('utf-8')
            else:
                edifact_bytes = edifact_content
            
            logger.info(f"✅ EDIFACT conversion successful: {len(edifact_bytes)} bytes")
            return edifact_bytes, "edi"
            
        except Exception as e:
            logger.error(f"❌ EDIFACT conversion failed: {e}")
            logger.exception(e)
            raise
    
    async def _convert_to_pdf(self, xml_content: str, invoice_data: Dict) -> Tuple[bytes, str]:
        """Convert to PDF format with all extracted data"""
        try:
            logger.info("📄 Converting to PDF with all extracted data...")
            # Pass invoice_data to preserve all extracted fields
            pdf_content = await generate_pdf_from_xml(xml_content, invoice_data=invoice_data)
            
            if not pdf_content:
                raise ValueError("PDF generation returned empty content")
            
            return pdf_content, "pdf"
            
        except Exception as e:
            logger.error(f"❌ PDF conversion failed: {e}")
            raise
    
    async def update_customer_validation_fields(
        self, 
        customer_id: str, 
        invoice_data: Dict[str, Any]
    ) -> bool:
        """
        Update customer validation fields with values from invoice.
        Used when admin chooses to override and update customer configuration.
        """
        try:
            customer = self.db.query(Customer).filter(
                Customer.customer_id == customer_id
            ).first()
            
            if not customer:
                logger.error(f"❌ Customer not found: {customer_id}")
                return False
            
            # Parse existing validation fields
            existing_fields = {}
            if customer.validation_fields:
                try:
                    existing_fields = json.loads(customer.validation_fields)
                except:
                    existing_fields = {}
            
            # Update with invoice values
            # Only update fields that are in the validation_fields structure
            for field_name in existing_fields.keys():
                if field_name in invoice_data:
                    existing_fields[field_name] = invoice_data[field_name]
                    logger.info(f"✏️ Updated {field_name}: {invoice_data[field_name]}")
            
            # Save back to customer
            customer.validation_fields = json.dumps(existing_fields)
            self.db.commit()
            
            logger.info(f"✅ Customer validation fields updated for: {customer_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update customer validation fields: {e}")
            self.db.rollback()
            return False
    
    def get_converted_invoices(
        self, 
        skip: int = 0, 
        limit: int = 100,
        status_filter: Optional[str] = None
    ) -> Tuple[List[ConvertedInvoice], int]:
        """Get paginated list of converted invoices"""
        try:
            query = self.db.query(ConvertedInvoice)
            
            if status_filter:
                query = query.filter(ConvertedInvoice.conversion_status == status_filter)
            
            total = query.count()
            
            converted = query.order_by(ConvertedInvoice.converted_at.desc()).offset(skip).limit(limit).all()
            
            return converted, total
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch converted invoices: {e}")
            return [], 0
    
    def get_converted_invoice(self, converted_id: int) -> Optional[ConvertedInvoice]:
        """Get a specific converted invoice"""
        try:
            return self.db.query(ConvertedInvoice).filter(
                ConvertedInvoice.id == converted_id
            ).first()
        except Exception as e:
            logger.error(f"❌ Failed to fetch converted invoice: {e}")
            return None
