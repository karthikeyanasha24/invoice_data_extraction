"""
SAT Supplier Account Mapping Service
Handles Excel upload, parsing, and mapping lookups for Supplier RFC → SAP Account mapping
"""
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import pandas as pd
import logging
from io import BytesIO

from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping

logger = logging.getLogger(__name__)


class SATSupplierMappingService:
    """Service for managing Supplier RFC → SAP Account mappings"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def parse_excel_mapping_file(self, file_content: bytes, sheet_name: str = None) -> List[Dict[str, Any]]:
        """
        Parse Excel file containing Supplier RFC → SAP Account mappings.
        
        Expected Excel columns:
        - RFC: Supplier RFC code (13 chars)
        - CTA: SAP G/L Account number
        - CTAS: Account description
        - IS_ACTIVE: Yes/No or True/False (optional, defaults to Yes)
        
        Args:
            file_content: Excel file bytes
            sheet_name: Sheet name to read (if None, reads first sheet)
        
        Returns:
            List of dictionaries with parsed mapping data
        """
        try:
            logger.info("📄 Parsing Supplier RFC mapping Excel file...")
            
            # Read Excel file
            if sheet_name:
                df = pd.read_excel(BytesIO(file_content), sheet_name=sheet_name)
            else:
                df = pd.read_excel(BytesIO(file_content))
            
            logger.info(f"📊 Found {len(df)} rows in Excel file")
            logger.info(f"📋 Columns: {list(df.columns)}")
            
            # Normalize column names
            df.columns = df.columns.str.strip().str.upper()
            
            # Validate required columns
            required_columns = ['RFC', 'CTA', 'CTAS']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}. Expected: RFC, CTA, CTAS")
            
            # Convert to list of dicts
            mappings = []
            for idx, row in df.iterrows():
                try:
                    # Skip empty rows
                    if pd.isna(row.get('RFC')) or str(row.get('RFC')).strip() == '':
                        continue
                    
                    # Parse IS_ACTIVE column
                    is_active = True
                    if 'IS_ACTIVE' in df.columns:
                        active_val = str(row.get('IS_ACTIVE', 'Yes')).strip().lower()
                        is_active = active_val in ['yes', 'true', '1', 'y', 't', 'active']
                    
                    mapping = {
                        'supplier_rfc': str(row['RFC']).strip().upper(),
                        'sap_gl_account': str(row['CTA']).strip(),
                        'account_description': str(row['CTAS']).strip(),
                        'is_active': is_active
                    }
                    
                    # Validate RFC format (should be 12-13 alphanumeric)
                    rfc = mapping['supplier_rfc']
                    if not (12 <= len(rfc) <= 13 and rfc.isalnum()):
                        logger.warning(f"Row {idx + 2}: Invalid RFC format: {rfc}")
                        continue
                    
                    # Validate required fields
                    if not mapping['sap_gl_account'] or not mapping['account_description']:
                        logger.warning(f"Row {idx + 2}: Missing SAP account or description for RFC {rfc}")
                        continue
                    
                    mappings.append(mapping)
                    
                except Exception as e:
                    logger.error(f"Error parsing row {idx + 2}: {e}")
                    continue
            
            logger.info(f"✅ Successfully parsed {len(mappings)} valid mappings")
            return mappings
            
        except Exception as e:
            logger.error(f"❌ Error parsing Excel file: {e}")
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
    
    def bulk_upsert_mappings(self, mappings: List[Dict[str, Any]], overwrite: bool = False) -> Dict[str, int]:
        """
        Bulk insert or update supplier account mappings.
        
        Args:
            mappings: List of mapping dictionaries
            overwrite: If True, update existing mappings. If False, skip duplicates.
        
        Returns:
            Dictionary with counts: {'inserted': X, 'updated': Y, 'skipped': Z}
        """
        try:
            logger.info(f"💾 Bulk upserting {len(mappings)} supplier mappings (overwrite={overwrite})...")
            
            inserted = 0
            updated = 0
            skipped = 0
            
            for mapping_data in mappings:
                rfc = mapping_data['supplier_rfc']
                
                # Check if mapping already exists
                existing = self.db.query(SATSupplierAccountMapping).filter(
                    SATSupplierAccountMapping.supplier_rfc == rfc
                ).first()
                
                if existing:
                    if overwrite:
                        # Update existing mapping
                        existing.sap_gl_account = mapping_data['sap_gl_account']
                        existing.account_description = mapping_data['account_description']
                        existing.is_active = mapping_data.get('is_active', True)
                        updated += 1
                    else:
                        # Skip duplicate
                        skipped += 1
                else:
                    # Insert new mapping
                    new_mapping = SATSupplierAccountMapping(**mapping_data)
                    self.db.add(new_mapping)
                    inserted += 1
            
            self.db.commit()
            
            logger.info(f"✅ Bulk upsert complete: {inserted} inserted, {updated} updated, {skipped} skipped")
            
            return {
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'total': len(mappings)
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Bulk upsert failed: {e}")
            raise
    
    def get_mapping_by_rfc(self, supplier_rfc: str) -> Optional[SATSupplierAccountMapping]:
        """
        Get mapping for a specific supplier RFC.
        
        Args:
            supplier_rfc: Supplier RFC code
        
        Returns:
            SATSupplierAccountMapping object or None
        """
        return self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.supplier_rfc == supplier_rfc.upper(),
            SATSupplierAccountMapping.is_active == True
        ).first()
    
    def get_all_mappings(
        self, 
        skip: int = 0, 
        limit: int = 100,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all supplier account mappings with pagination and filters.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            search: Search term for RFC, GL Account, or Description
        
        Returns:
            Dictionary with 'total' count and 'mappings' list
        """
        query = self.db.query(SATSupplierAccountMapping)
        
        # Apply filters
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (SATSupplierAccountMapping.supplier_rfc.ilike(search_term)) |
                (SATSupplierAccountMapping.sap_gl_account.ilike(search_term)) |
                (SATSupplierAccountMapping.account_description.ilike(search_term))
            )
        
        total = query.count()
        mappings = query.offset(skip).limit(limit).all()
        
        return {
            'total': total,
            'mappings': [m.to_dict() for m in mappings]
        }
    
    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a mapping by ID"""
        mapping = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.id == mapping_id
        ).first()
        
        if mapping:
            self.db.delete(mapping)
            self.db.commit()
            return True
        return False
    
    def get_or_create_default_mapping(self) -> SATSupplierAccountMapping:
        """
        Get or create a default fallback mapping for unknown suppliers.
        Uses: RFC = "DEFAULT", GL Account = "210999", Description = "Unknown Supplier"
        """
        default = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.is_default == True
        ).first()
        
        if not default:
            logger.info("Creating default fallback supplier mapping...")
            default = SATSupplierAccountMapping(
                supplier_rfc="DEFAULT",
                sap_gl_account="210999",
                account_description="Unknown Supplier / Proveedor Desconocido",
                is_default=True,
                is_active=True
            )
            self.db.add(default)
            self.db.commit()
            self.db.refresh(default)
        
        return default
    
    def lookup_gl_account(self, supplier_rfc: str) -> Dict[str, Any]:
        """
        Lookup SAP G/L Account for a supplier RFC with fallback logic.
        
        Args:
            supplier_rfc: Supplier RFC code
        
        Returns:
            Dictionary with GL account and description
        """
        # Try to find exact mapping
        mapping = self.get_mapping_by_rfc(supplier_rfc)
        
        if mapping:
            return {
                'sap_gl_account': mapping.sap_gl_account,
                'account_description': mapping.account_description,
                'found': True
            }
        
        # Fallback to default mapping
        logger.warning(f"⚠️ No mapping found for supplier RFC: {supplier_rfc}, using default")
        default = self.get_or_create_default_mapping()
        
        return {
            'sap_gl_account': default.sap_gl_account,
            'account_description': f"Unknown Supplier ({supplier_rfc})",
            'found': False,
            'original_rfc': supplier_rfc
        }
    
    def get_mapping_stats(self) -> Dict[str, Any]:
        """Get statistics about supplier mappings"""
        total = self.db.query(SATSupplierAccountMapping).count()
        active = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.is_active == True
        ).count()
        
        # Get count by GL account
        from sqlalchemy import func
        account_counts = self.db.query(
            SATSupplierAccountMapping.sap_gl_account,
            func.count(SATSupplierAccountMapping.id)
        ).group_by(SATSupplierAccountMapping.sap_gl_account).all()
        
        return {
            'total_mappings': total,
            'active_mappings': active,
            'inactive_mappings': total - active,
            'unique_accounts': len(account_counts),
            'by_account': [{'account': acc[0], 'count': acc[1]} for acc in account_counts]
        }

