"""
SAT Supplier Mapping Service
Manages RFC to SAP G/L Account mappings.
"""
import logging
import pandas as pd
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping

logger = logging.getLogger("zodiac-api.sat_supplier_mapping")


class SATSupplierMappingService:
    def __init__(self, db: Session):
        self.db = db
    
    def parse_excel_mapping_file(self, file_content: bytes) -> List[Dict]:
        """
        Parse Excel file containing supplier RFC to G/L account mappings.
        Expected columns: RFC, CTA (G/L Account), CTAS (Description), IS_ACTIVE
        """
        try:
            # Read Excel file
            df = pd.read_excel(file_content, engine='openpyxl')
            
            # Normalize column names
            df.columns = self._normalize_column_names(df.columns)
            
            logger.info(f"📊 Excel columns: {list(df.columns)}")
            
            # Validate required columns
            required = ['rfc', 'cta']
            missing = [col for col in required if col not in df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")
            
            # Convert to list of dicts
            mappings = []
            for _, row in df.iterrows():
                try:
                    mapping = {
                        'supplier_rfc': str(row['rfc']).strip().upper(),
                        'sap_gl_account': str(row['cta']).strip(),
                        'account_description': str(row.get('ctas', '')) if pd.notna(row.get('ctas')) else None,
                        'is_active': self._parse_boolean(row.get('is_active', True))
                    }
                    
                    # Skip empty rows
                    if not mapping['supplier_rfc'] or mapping['supplier_rfc'] == 'NAN':
                        continue
                    
                    mappings.append(mapping)
                except Exception as e:
                    logger.warning(f"⚠️ Skipping row due to error: {e}")
                    continue
            
            logger.info(f"✅ Parsed {len(mappings)} mappings from Excel")
            return mappings
            
        except Exception as e:
            logger.error(f"❌ Failed to parse Excel file: {e}")
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
    
    def _normalize_column_names(self, columns):
        """Normalize column names to lowercase and remove spaces."""
        normalized = []
        for col in columns:
            col_lower = str(col).lower().strip()
            # Map common variations
            if col_lower in ['rfc', 'supplier_rfc', 'vendor_rfc']:
                normalized.append('rfc')
            elif col_lower in ['cta', 'gl_account', 'sap_gl_account', 'account']:
                normalized.append('cta')
            elif col_lower in ['ctas', 'description', 'account_description']:
                normalized.append('ctas')
            elif col_lower in ['is_active', 'active', 'status']:
                normalized.append('is_active')
            else:
                normalized.append(col_lower)
        return normalized
    
    def _parse_boolean(self, value) -> bool:
        """Parse boolean from various formats."""
        if pd.isna(value):
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ['true', 'yes', '1', 'active', 'y']
        return True
    
    def bulk_upsert_mappings(self, mappings: List[Dict]) -> Dict[str, int]:
        """
        Bulk insert or update supplier mappings.
        Returns counts of created, updated, and skipped records.
        """
        created = 0
        updated = 0
        skipped = 0
        
        for mapping_data in mappings:
            try:
                rfc = mapping_data['supplier_rfc']
                
                # Check if mapping exists
                existing = self.db.query(SATSupplierAccountMapping).filter(
                    SATSupplierAccountMapping.supplier_rfc == rfc
                ).first()
                
                if existing:
                    # Update
                    existing.sap_gl_account = mapping_data['sap_gl_account']
                    existing.account_description = mapping_data.get('account_description')
                    existing.is_active = mapping_data.get('is_active', True)
                    updated += 1
                else:
                    # Create
                    new_mapping = SATSupplierAccountMapping(
                        supplier_rfc=rfc,
                        sap_gl_account=mapping_data['sap_gl_account'],
                        account_description=mapping_data.get('account_description'),
                        is_active=mapping_data.get('is_active', True),
                        is_default=False
                    )
                    self.db.add(new_mapping)
                    created += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to process mapping for {mapping_data.get('supplier_rfc')}: {e}")
                skipped += 1
                continue
        
        self.db.commit()
        
        logger.info(f"✅ Bulk upsert complete: {created} created, {updated} updated, {skipped} skipped")
        return {"created": created, "updated": updated, "skipped": skipped}
    
    def get_mapping_by_rfc(self, supplier_rfc: str) -> Optional[SATSupplierAccountMapping]:
        """Get mapping for a specific supplier RFC."""
        return self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.supplier_rfc == supplier_rfc.upper(),
            SATSupplierAccountMapping.is_active == True
        ).first()
    
    def get_all_mappings(self, active_only: bool = False, skip: int = 0, limit: int = 100) -> Dict:
        """Get all supplier mappings."""
        query = self.db.query(SATSupplierAccountMapping)
        
        if active_only:
            query = query.filter(SATSupplierAccountMapping.is_active == True)
        
        total = query.count()
        mappings = query.order_by(
            SATSupplierAccountMapping.supplier_rfc
        ).offset(skip).limit(limit).all()
        
        return {
            "total": total,
            "mappings": [
                {
                    "id": m.id,
                    "supplier_rfc": m.supplier_rfc,
                    "sap_gl_account": m.sap_gl_account,
                    "account_description": m.account_description,
                    "is_active": m.is_active,
                    "is_default": m.is_default,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None
                }
                for m in mappings
            ]
        }
    
    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a supplier mapping."""
        mapping = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.id == mapping_id
        ).first()
        
        if not mapping:
            return False
        
        # Don't allow deleting default mapping
        if mapping.is_default:
            raise ValueError("Cannot delete default mapping")
        
        self.db.delete(mapping)
        self.db.commit()
        return True
    
    def get_or_create_default_mapping(self) -> Optional[SATSupplierAccountMapping]:
        """Get or create the default G/L account mapping."""
        default = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.is_default == True
        ).first()
        
        if not default:
            # Create default mapping
            default = SATSupplierAccountMapping(
                supplier_rfc='DEFAULT',
                sap_gl_account='9999999999',
                account_description='Default unmapped supplier account',
                is_active=True,
                is_default=True
            )
            self.db.add(default)
            self.db.commit()
            self.db.refresh(default)
            logger.info("✅ Created default supplier mapping")
        
        return default

