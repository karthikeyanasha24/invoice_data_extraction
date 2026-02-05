"""
SAT Data Integrity Verification Script

This script checks all SAT documents in the database for data integrity issues:
- Missing or incorrect UUIDs
- Missing folio, serie, total, currency, subtotal
- Documents with missing XML content

For documents with issues, it attempts to re-parse the XML and update the fields.
"""

import sys
import os
from datetime import datetime
from sqlalchemy.orm import Session

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.sat_document import SATDocument
from app.utils.cfdi_parser import CFDIParser

def verify_and_fix_documents():
    """
    Verify all SAT documents and fix any data integrity issues.
    """
    db: Session = SessionLocal()
    parser = CFDIParser()
    
    try:
        print("=" * 80)
        print("SAT DATA INTEGRITY VERIFICATION")
        print("=" * 80)
        print(f"Started at: {datetime.now().isoformat()}\n")
        
        # Get all documents
        all_docs = db.query(SATDocument).all()
        print(f"📊 Total documents in database: {len(all_docs)}\n")
        
        if not all_docs:
            print("No documents found in database.")
            return
        
        # Track issues
        issues_found = []
        documents_fixed = []
        documents_with_errors = []
        
        # Check each document
        for doc in all_docs:
            doc_issues = []
            doc_id = str(doc.id)
            
            # Check for missing UUID
            if not doc.cfdi_uuid:
                doc_issues.append("Missing CFDI UUID")
            
            # Check for missing folio
            if not doc.folio:
                doc_issues.append("Missing folio")
            
            # Check for missing serie
            if not doc.serie:
                doc_issues.append("Missing serie")
            
            # Check for missing total
            if not doc.total:
                doc_issues.append("Missing total amount")
            
            # Check for missing currency
            if not doc.moneda:
                doc_issues.append("Missing currency (moneda)")
            
            # Check for missing subtotal
            if not doc.subtotal:
                doc_issues.append("Missing subtotal")
            
            # Check for missing XML content
            if not doc.xml_content:
                doc_issues.append("Missing XML content (cannot fix)")
            
            if doc_issues:
                issues_found.append({
                    'id': doc_id,
                    'folio': doc.folio or 'N/A',
                    'serie': doc.serie or 'N/A',
                    'rfc': doc.supplier_rfc or 'N/A',
                    'doc_type': doc.doc_type or 'N/A',
                    'issues': doc_issues
                })
                
                # Try to fix if XML content exists
                if doc.xml_content and "Missing XML content" not in doc_issues:
                    try:
                        print(f"\n🔧 Attempting to fix document {doc_id[:8]}...")
                        print(f"   Current issues: {', '.join(doc_issues)}")
                        
                        # Re-parse XML
                        cfdi_data = parser.parse_cfdi(doc.xml_content)
                        
                        # Update fields
                        fixed_fields = []
                        
                        if not doc.cfdi_uuid and cfdi_data.get('cfdi_uuid'):
                            doc.cfdi_uuid = cfdi_data['cfdi_uuid']
                            fixed_fields.append('cfdi_uuid')
                        
                        if not doc.folio and cfdi_data.get('folio'):
                            doc.folio = cfdi_data['folio']
                            fixed_fields.append('folio')
                        
                        if not doc.serie and cfdi_data.get('serie'):
                            doc.serie = cfdi_data['serie']
                            fixed_fields.append('serie')
                        
                        if not doc.total and cfdi_data.get('total'):
                            doc.total = cfdi_data['total']
                            fixed_fields.append('total')
                        
                        if not doc.moneda and cfdi_data.get('moneda'):
                            doc.moneda = cfdi_data['moneda']
                            fixed_fields.append('moneda')
                        
                        if not doc.subtotal and cfdi_data.get('subtotal'):
                            doc.subtotal = cfdi_data['subtotal']
                            fixed_fields.append('subtotal')
                        
                        if fixed_fields:
                            db.commit()
                            print(f"   ✅ Fixed fields: {', '.join(fixed_fields)}")
                            documents_fixed.append({
                                'id': doc_id,
                                'fixed_fields': fixed_fields
                            })
                        else:
                            print(f"   ⚠️ No fields could be fixed")
                            
                    except Exception as e:
                        print(f"   ❌ Error fixing document: {e}")
                        documents_with_errors.append({
                            'id': doc_id,
                            'error': str(e)
                        })
                        db.rollback()
        
        # Print summary report
        print("\n" + "=" * 80)
        print("VERIFICATION SUMMARY")
        print("=" * 80)
        
        print(f"\n📊 Documents checked: {len(all_docs)}")
        print(f"⚠️  Documents with issues: {len(issues_found)}")
        print(f"✅ Documents fixed: {len(documents_fixed)}")
        print(f"❌ Documents with errors: {len(documents_with_errors)}")
        
        # Detailed issues report
        if issues_found:
            print("\n" + "-" * 80)
            print("DOCUMENTS WITH ISSUES")
            print("-" * 80)
            for issue in issues_found:
                print(f"\nDocument ID: {issue['id'][:8]}...")
                print(f"  RFC: {issue['rfc']}")
                print(f"  Type: {issue['doc_type']}")
                print(f"  Serie: {issue['serie']}")
                print(f"  Folio: {issue['folio']}")
                print(f"  Issues:")
                for i in issue['issues']:
                    print(f"    - {i}")
        
        # Fixed documents report
        if documents_fixed:
            print("\n" + "-" * 80)
            print("DOCUMENTS FIXED")
            print("-" * 80)
            for fixed in documents_fixed:
                print(f"\n✅ Document {fixed['id'][:8]}... fixed:")
                for field in fixed['fixed_fields']:
                    print(f"   - {field}")
        
        # Errors report
        if documents_with_errors:
            print("\n" + "-" * 80)
            print("DOCUMENTS WITH ERRORS")
            print("-" * 80)
            for error in documents_with_errors:
                print(f"\n❌ Document {error['id'][:8]}...: {error['error']}")
        
        print("\n" + "=" * 80)
        print(f"Completed at: {datetime.now().isoformat()}")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Fatal error during verification: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    print("\n🔍 Starting SAT Data Integrity Verification...\n")
    verify_and_fix_documents()
    print("\n✅ Verification complete!\n")
