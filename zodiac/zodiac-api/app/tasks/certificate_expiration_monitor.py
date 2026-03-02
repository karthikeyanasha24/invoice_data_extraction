"""
Certificate Expiration Monitor
Background task that checks certificate expiration and sends alerts.
Should be run daily via cron job or task scheduler.

Usage:
    python -m app.tasks.certificate_expiration_monitor
    
Or add to crontab:
    0 9 * * * cd /path/to/zodiac-api && python -m app.tasks.certificate_expiration_monitor
"""
import sys
import os
import logging
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import SessionLocal
from app.models.customer_certificate import CustomerCertificate, CertificateStatus
from app.services.certificate_service import update_certificate_statuses
from app.services.certificate_lifecycle import (
    auto_create_renewal_requests,
    get_certificate_health_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("certificate_monitor")


def send_expiration_alert(
    customer_id: str,
    certificate_id: int,
    common_name: str,
    expires_at: datetime,
    days_until_expiry: int,
):
    """
    Send expiration alert to admin and customer.
    
    In production, this should:
    - Send email to customer contact
    - Send Slack/Teams notification to admin
    - Create dashboard alert
    - Log to monitoring system
    
    Args:
        customer_id: Customer identifier
        certificate_id: Certificate ID
        common_name: Certificate CN
        expires_at: Expiration timestamp
        days_until_expiry: Days remaining
    """
    logger.warning(
        f"🔔 CERTIFICATE EXPIRATION ALERT: "
        f"customer_id={customer_id}, "
        f"cert_id={certificate_id}, "
        f"cn={common_name}, "
        f"expires_at={expires_at}, "
        f"days_left={days_until_expiry}"
    )
    
    # TODO: Implement email notification
    # Example using SMTP:
    # from app.utils.email import send_email
    # send_email(
    #     to=customer_email,
    #     subject=f"Certificate Expiring in {days_until_expiry} Days",
    #     body=f"Your client certificate (CN: {common_name}) will expire on {expires_at}. "
    #          f"Please renew it to avoid service interruption."
    # )
    
    # TODO: Implement Slack/Teams notification
    # Example:
    # from app.utils.notifications import send_slack_alert
    # send_slack_alert(
    #     channel="#certificates",
    #     message=f"Certificate Alert: {customer_id} cert expires in {days_until_expiry} days"
    # )


def check_expiring_certificates(db):
    """Check and alert for certificates expiring at specific thresholds"""
    now = datetime.utcnow()
    alert_thresholds = [90, 60, 30, 7]
    
    alerts_sent = 0
    
    for days in alert_thresholds:
        threshold_date = now + timedelta(days=days)
        
        # Find certificates expiring around this threshold (within +/- 1 day window)
        certs = db.query(CustomerCertificate).filter(
            CustomerCertificate.status.in_([
                CertificateStatus.ACTIVE.value,
                CertificateStatus.EXPIRING_SOON.value
            ]),
            CustomerCertificate.expires_at >= now,
            CustomerCertificate.expires_at <= threshold_date + timedelta(days=1),
            CustomerCertificate.expires_at >= threshold_date - timedelta(days=1),
        ).all()
        
        for cert in certs:
            days_left = (cert.expires_at - now).days
            send_expiration_alert(
                customer_id=cert.customer_id,
                certificate_id=cert.id,
                common_name=cert.common_name,
                expires_at=cert.expires_at,
                days_until_expiry=days_left,
            )
            alerts_sent += 1
    
    return alerts_sent


def run_certificate_monitor():
    """Main monitoring function"""
    logger.info("=" * 70)
    logger.info("Starting Certificate Expiration Monitor")
    logger.info(f"Run time: {datetime.utcnow().isoformat()}")
    logger.info("=" * 70)
    
    db = SessionLocal()
    
    try:
        # Step 1: Update certificate statuses
        logger.info("Step 1: Updating certificate statuses...")
        status_stats = update_certificate_statuses(db)
        logger.info(f"✅ Status update complete: {status_stats}")
        
        # Step 2: Check for expiring certificates and send alerts
        logger.info("Step 2: Checking for expiring certificates...")
        alerts_sent = check_expiring_certificates(db)
        logger.info(f"✅ Alerts sent: {alerts_sent}")
        
        # Step 3: Auto-create renewal requests for certificates < 30 days
        logger.info("Step 3: Auto-creating renewal requests...")
        renewal_requests = auto_create_renewal_requests(db, days_threshold=30)
        logger.info(f"✅ Renewal requests created: {len(renewal_requests)}")
        
        # Step 4: Generate health summary
        logger.info("Step 4: Generating certificate health summary...")
        health = get_certificate_health_summary(db)
        logger.info(f"📊 Certificate Health Summary:")
        logger.info(f"   Total: {health['total_certificates']}")
        logger.info(f"   Active: {health['active']}")
        logger.info(f"   Expiring Soon: {health['expiring_soon']}")
        logger.info(f"   Expired: {health['expired']}")
        logger.info(f"   Revoked: {health['revoked']}")
        logger.info(f"   Pending Renewals: {health['pending_renewal_requests']}")
        logger.info(f"   Expiring within 7 days: {health['expiring_within']['7_days']}")
        logger.info(f"   Expiring within 30 days: {health['expiring_within']['30_days']}")
        logger.info(f"   Expiring within 90 days: {health['expiring_within']['90_days']}")
        
        logger.info("=" * 70)
        logger.info("✅ Certificate monitor completed successfully")
        logger.info("=" * 70)
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Certificate monitor failed: {e}", exc_info=True)
        return False
    
    finally:
        db.close()


if __name__ == "__main__":
    success = run_certificate_monitor()
    sys.exit(0 if success else 1)
