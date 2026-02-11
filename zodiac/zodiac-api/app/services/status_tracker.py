"""
Status tracking service for real-time invoice processing updates.
Uses in-memory cache to store processing status by tracking_id.
"""
from typing import Dict, Optional, List
from datetime import datetime
import uuid
import logging
from ..schemas.invoice import ProcessingStepResult, InvoiceProcessingResponse

logger = logging.getLogger("zodiac-api.status_tracker")

class StatusTracker:
    """In-memory status tracker for invoice processing"""
    
    def __init__(self):
        # Store: tracking_id -> InvoiceProcessingResponse
        self._status_cache: Dict[str, InvoiceProcessingResponse] = {}
        # Store completion status: tracking_id -> bool
        self._completed: Dict[str, bool] = {}
        # Store success/failure status: tracking_id -> bool
        self._success: Dict[str, bool] = {}
        # Store timestamps: tracking_id -> datetime
        self._timestamps: Dict[str, datetime] = {}
    
    def initialize_status(self, tracking_id: uuid.UUID) -> None:
        """Initialize status tracking for a new invoice processing"""
        tracking_str = str(tracking_id)
        self._status_cache[tracking_str] = InvoiceProcessingResponse(
            tracking_id=tracking_id,
            processing_steps=[]
        )
        self._completed[tracking_str] = False
        self._timestamps[tracking_str] = datetime.utcnow()
        logger.info(f"📊 Status tracker initialized for tracking_id: {tracking_id}")
    
    def update_step(self, tracking_id: uuid.UUID, step: ProcessingStepResult) -> None:
        """Update a processing step status"""
        tracking_str = str(tracking_id)
        
        if tracking_str not in self._status_cache:
            logger.warning(f"⚠️ Status not initialized for tracking_id: {tracking_id}, initializing now")
            self.initialize_status(tracking_id)
        
        # Get current status
        current_status = self._status_cache[tracking_str]
        
        # Update or add step
        if current_status.processing_steps is None:
            current_status.processing_steps = []
        
        # Find existing step or add new one
        step_index = None
        for i, existing_step in enumerate(current_status.processing_steps):
            if existing_step.step_number == step.step_number:
                step_index = i
                break
        
        if step_index is not None:
            # Update existing step
            current_status.processing_steps[step_index] = step
            logger.info(f"📊 Updated step {step.step_number} ({step.step_name}) for tracking_id: {tracking_id}")
            logger.info(f"📊 Current steps in tracker: {len(current_status.processing_steps)} steps")
            logger.info(f"📊 Steps: {[f'Step {s.step_number} ({s.step_name}) - Success: {s.success}' for s in current_status.processing_steps]}")
        else:
            # Add new step
            current_status.processing_steps.append(step)
            logger.info(f"📊 Added step {step.step_number} ({step.step_name}) for tracking_id: {tracking_id}")
            logger.info(f"📊 Current steps in tracker: {len(current_status.processing_steps)} steps")
            logger.info(f"📊 Steps: {[f'Step {s.step_number} ({s.step_name}) - Success: {s.success}' for s in current_status.processing_steps]}")
        
        # Update cache - CRITICAL: create a new response object to ensure proper serialization
        self._status_cache[tracking_str] = InvoiceProcessingResponse(
            tracking_id=current_status.tracking_id,
            processing_steps=current_status.processing_steps
        )
    
    def mark_completed(self, tracking_id: uuid.UUID, success: bool = True) -> None:
        """Mark processing as completed
        
        Args:
            tracking_id: The tracking ID for the invoice processing
            success: Whether the processing completed successfully (default: True)
        """
        tracking_str = str(tracking_id)
        self._completed[tracking_str] = True
        self._success[tracking_str] = success
        logger.info(f"{'✅' if success else '❌'} Marked processing as {'completed successfully' if success else 'failed'} for tracking_id: {tracking_id}")
    
    def get_status(self, tracking_id: uuid.UUID) -> Optional[InvoiceProcessingResponse]:
        """Get current processing status"""
        tracking_str = str(tracking_id)
        status = self._status_cache.get(tracking_str)
        if status:
            logger.info(f"📊 Retrieved status for tracking_id: {tracking_id}")
            logger.info(f"📊 Current steps: {len(status.processing_steps) if status.processing_steps else 0}")
            if status.processing_steps:
                logger.info(f"📊 Steps details: {[f'Step {s.step_number} ({s.step_name}) - Success: {s.success}' for s in status.processing_steps]}")
        else:
            logger.info(f"📊 Status not found in tracker for tracking_id: {tracking_id}")
        return status
    
    def is_completed(self, tracking_id: uuid.UUID) -> bool:
        """Check if processing is completed"""
        tracking_str = str(tracking_id)
        return self._completed.get(tracking_str, False)
    
    def is_successful(self, tracking_id: uuid.UUID) -> Optional[bool]:
        """Check if processing completed successfully
        
        Returns:
            True if successful, False if failed, None if not completed
        """
        tracking_str = str(tracking_id)
        if not self.is_completed(tracking_id):
            return None
        return self._success.get(tracking_str, True)
    
    def cleanup_old_statuses(self, max_age_hours: int = 24) -> None:
        """Clean up old status entries (older than max_age_hours)"""
        now = datetime.utcnow()
        to_remove = []
        
        for tracking_str, timestamp in self._timestamps.items():
            age = (now - timestamp).total_seconds() / 3600  # hours
            if age > max_age_hours:
                to_remove.append(tracking_str)
        
        for tracking_str in to_remove:
            del self._status_cache[tracking_str]
            del self._completed[tracking_str]
            if tracking_str in self._success:
                del self._success[tracking_str]
            del self._timestamps[tracking_str]
            logger.info(f"🧹 Cleaned up old status for tracking_id: {tracking_str}")
        
        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} old status entries")

# Global instance
status_tracker = StatusTracker()

