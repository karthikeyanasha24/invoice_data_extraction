"""
Invoice V2 Correction Cache Service - Manage customer-specific corrections
"""
import logging
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from uuid import UUID

from ..models.invoice_v2_correction_cache import InvoiceV2CorrectionCache

logger = logging.getLogger("zodiac-api.invoice_v2_correction")


class InvoiceV2CorrectionService:
    """
    Manage correction cache for V2 invoices.
    Stores and retrieves customer-specific field corrections.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def save_correction(
        self,
        customer_id: str,
        customer_name: Optional[str],
        field_name: str,
        field_value: str,
        user_id: Optional[int] = None,
        notes: Optional[str] = None
    ) -> InvoiceV2CorrectionCache:
        """
        Save a new correction to cache.
        
        Args:
            customer_id: Customer identifier
            customer_name: Customer name
            field_name: Name of the field being corrected
            field_value: The correction value
            user_id: User ID who created this correction
            notes: Optional notes about this correction
            
        Returns:
            Created CorrectionCache object
        """
        try:
            # Generate error signature (hash of customer_id + field_name)
            error_signature = self._generate_error_signature(customer_id, field_name)
            
            # Check if correction already exists
            existing = self.find_correction(customer_id, field_name)
            
            if existing:
                logger.info(f"📝 Updating existing correction for {customer_id} - {field_name}")
                # Update existing correction
                existing.field_value = field_value
                existing.customer_name = customer_name or existing.customer_name
                existing.success_count += 1
                existing.last_success_at = datetime.utcnow()
                existing.last_used_at = datetime.utcnow()
                if notes:
                    existing.notes = notes
                
                self.db.commit()
                self.db.refresh(existing)
                
                logger.info(f"✅ Updated correction ID: {existing.id}")
                return existing
            else:
                logger.info(f"💾 Creating new correction for {customer_id} - {field_name}")
                
                # Create new correction
                correction = InvoiceV2CorrectionCache(
                    customer_id=customer_id,
                    customer_name=customer_name,
                    field_name=field_name,
                    field_value=field_value,
                    error_signature=error_signature,
                    success_count=1,
                    failure_count=0,
                    is_active=True,
                    created_by_user_id=user_id,
                    notes=notes,
                    last_success_at=datetime.utcnow(),
                    last_used_at=datetime.utcnow()
                )
                
                self.db.add(correction)
                self.db.commit()
                self.db.refresh(correction)
                
                logger.info(f"✅ Created correction ID: {correction.id}")
                logger.info(f"   Customer: {customer_id}")
                logger.info(f"   Field: {field_name}")
                logger.info(f"   Value: {field_value}")
                
                return correction
                
        except Exception as e:
            logger.error(f"❌ Failed to save correction: {e}")
            logger.exception(e)
            self.db.rollback()
            raise
    
    def save_multiple_corrections(
        self,
        customer_id: str,
        customer_name: Optional[str],
        corrections: Dict[str, str],
        user_id: Optional[int] = None
    ) -> List[InvoiceV2CorrectionCache]:
        """
        Save multiple corrections at once.
        
        Args:
            customer_id: Customer identifier
            customer_name: Customer name
            corrections: Dictionary of {field_name: field_value}
            user_id: User ID who created these corrections
            
        Returns:
            List of created/updated CorrectionCache objects
        """
        saved_corrections = []
        
        for field_name, field_value in corrections.items():
            try:
                correction = self.save_correction(
                    customer_id=customer_id,
                    customer_name=customer_name,
                    field_name=field_name,
                    field_value=field_value,
                    user_id=user_id
                )
                saved_corrections.append(correction)
            except Exception as e:
                logger.error(f"Failed to save correction for field {field_name}: {e}")
        
        return saved_corrections
    
    def find_correction(
        self,
        customer_id: str,
        field_name: str
    ) -> Optional[InvoiceV2CorrectionCache]:
        """
        Find existing correction for customer + field combination.
        
        Args:
            customer_id: Customer identifier
            field_name: Field name to look up
            
        Returns:
            CorrectionCache object if found, None otherwise
        """
        try:
            logger.info(f"🔍 Searching for correction: {customer_id} - {field_name}")
            
            correction = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.customer_id == customer_id,
                InvoiceV2CorrectionCache.field_name == field_name,
                InvoiceV2CorrectionCache.is_active == True
            ).order_by(
                InvoiceV2CorrectionCache.success_count.desc()
            ).first()
            
            if correction:
                logger.info(f"✅ Found correction ID: {correction.id}")
                logger.info(f"   Value: {correction.field_value}")
                logger.info(f"   Success rate: {correction.get_success_rate():.1f}%")
                return correction
            else:
                logger.info(f"❌ No correction found")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error searching for correction: {e}")
            return None
    
    def get_customer_corrections(
        self,
        customer_id: str,
        active_only: bool = True
    ) -> List[InvoiceV2CorrectionCache]:
        """
        Get all corrections for a specific customer.
        
        Args:
            customer_id: Customer identifier
            active_only: If True, only return active corrections
            
        Returns:
            List of CorrectionCache objects
        """
        try:
            query = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.customer_id == customer_id
            )
            
            if active_only:
                query = query.filter(InvoiceV2CorrectionCache.is_active == True)
            
            corrections = query.order_by(
                InvoiceV2CorrectionCache.success_count.desc()
            ).all()
            
            logger.info(f"📋 Found {len(corrections)} corrections for customer {customer_id}")
            return corrections
            
        except Exception as e:
            logger.error(f"❌ Error fetching customer corrections: {e}")
            return []
    
    def mark_success(self, correction_id: UUID):
        """
        Mark a correction as successfully applied.
        
        Args:
            correction_id: UUID of the correction
        """
        try:
            correction = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.mark_success()
                self.db.commit()
                logger.info(f"✅ Marked correction {correction_id} as success")
                logger.info(f"   New success count: {correction.success_count}")
            else:
                logger.warning(f"⚠️ Correction {correction_id} not found")
                
        except Exception as e:
            logger.error(f"❌ Error marking success: {e}")
            self.db.rollback()
    
    def mark_failure(self, correction_id: UUID):
        """
        Mark a correction as failed when applied.
        Auto-disables if failure rate is too high.
        
        Args:
            correction_id: UUID of the correction
        """
        try:
            correction = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.mark_failure()
                self.db.commit()
                logger.info(f"⚠️ Marked correction {correction_id} as failure")
                logger.info(f"   New failure count: {correction.failure_count}")
                
                if not correction.is_active:
                    logger.warning(f"🚫 Correction {correction_id} auto-disabled due to high failure rate")
            else:
                logger.warning(f"⚠️ Correction {correction_id} not found")
                
        except Exception as e:
            logger.error(f"❌ Error marking failure: {e}")
            self.db.rollback()
    
    def deactivate_correction(self, correction_id: UUID):
        """
        Manually deactivate a correction.
        
        Args:
            correction_id: UUID of the correction
        """
        try:
            correction = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.is_active = False
                self.db.commit()
                logger.info(f"🚫 Deactivated correction {correction_id}")
            else:
                logger.warning(f"⚠️ Correction {correction_id} not found")
                
        except Exception as e:
            logger.error(f"❌ Error deactivating correction: {e}")
            self.db.rollback()
    
    def reactivate_correction(self, correction_id: UUID):
        """
        Manually reactivate a correction.
        
        Args:
            correction_id: UUID of the correction
        """
        try:
            correction = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.is_active = True
                self.db.commit()
                logger.info(f"✅ Reactivated correction {correction_id}")
            else:
                logger.warning(f"⚠️ Correction {correction_id} not found")
                
        except Exception as e:
            logger.error(f"❌ Error reactivating correction: {e}")
            self.db.rollback()
    
    def get_correction_stats(self) -> Dict[str, Any]:
        """
        Get overall correction cache statistics.
        
        Returns:
            Dictionary with statistics
        """
        try:
            total_corrections = self.db.query(InvoiceV2CorrectionCache).count()
            active_corrections = self.db.query(InvoiceV2CorrectionCache).filter(
                InvoiceV2CorrectionCache.is_active == True
            ).count()
            
            # Calculate total successes and failures
            all_corrections = self.db.query(InvoiceV2CorrectionCache).all()
            total_successes = sum(c.success_count for c in all_corrections)
            total_failures = sum(c.failure_count for c in all_corrections)
            
            # Count unique customers
            unique_customers = self.db.query(
                InvoiceV2CorrectionCache.customer_id
            ).distinct().count()
            
            return {
                "total_corrections": total_corrections,
                "active_corrections": active_corrections,
                "inactive_corrections": total_corrections - active_corrections,
                "unique_customers": unique_customers,
                "total_successful_applications": total_successes,
                "total_failed_applications": total_failures,
                "overall_success_rate": (total_successes / (total_successes + total_failures) * 100) if (total_successes + total_failures) > 0 else 0.0
            }
            
        except Exception as e:
            logger.error(f"❌ Error fetching stats: {e}")
            return {}
    
    def _generate_error_signature(self, customer_id: str, field_name: str) -> str:
        """
        Generate a unique signature for this error pattern.
        
        Args:
            customer_id: Customer identifier
            field_name: Field name
            
        Returns:
            Hash string representing this error pattern
        """
        # Create a deterministic signature
        signature_str = f"{customer_id}|{field_name}".lower()
        signature_hash = hashlib.md5(signature_str.encode()).hexdigest()
        return f"{field_name}|{signature_hash[:16]}"
