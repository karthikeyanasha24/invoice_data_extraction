"""
Certificate Cryptography Utilities
Low-level crypto operations for X.509 certificate generation and management.
"""
import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
    BestAvailableEncryption,
)


def generate_key_pair(key_size: int = 2048) -> rsa.RSAPrivateKey:
    """
    Generate RSA private/public key pair.
    
    Args:
        key_size: Key size in bits (2048 or 4096 recommended)
    
    Returns:
        RSA private key object
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend()
    )
    return private_key


def generate_serial_number() -> int:
    """Generate a random serial number for certificate"""
    return x509.random_serial_number()


def create_ca_certificate(
    common_name: str = "Zodiac Portal CA",
    organization: str = "Zodiac Systems",
    country: str = "US",
    validity_years: int = 10,
) -> Tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """
    Create a self-signed CA certificate for signing client certificates.
    
    Args:
        common_name: CA common name
        organization: CA organization name
        country: Two-letter country code
        validity_years: How long the CA cert is valid
    
    Returns:
        Tuple of (CA certificate, CA private key)
    """
    # Generate CA key pair
    ca_private_key = generate_key_pair(key_size=4096)
    
    # Build CA subject
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    
    # Build CA certificate
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_private_key.public_key())
        .serial_number(generate_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=validity_years * 365))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_private_key.public_key()),
            critical=False,
        )
        .sign(ca_private_key, hashes.SHA256(), default_backend())
    )
    
    return ca_cert, ca_private_key


def create_client_certificate(
    customer_id: str,
    common_name: str,
    ca_cert: x509.Certificate,
    ca_private_key: rsa.RSAPrivateKey,
    organization: Optional[str] = None,
    organizational_unit: Optional[str] = None,
    country: Optional[str] = None,
    email: Optional[str] = None,
    validity_days: int = 365,
) -> Tuple[x509.Certificate, rsa.RSAPrivateKey, str, str]:
    """
    Create a client certificate signed by the CA.
    
    Args:
        customer_id: Customer identifier (included in CN or SAN)
        common_name: Certificate common name (e.g., "customer-001.zodiac.com")
        ca_cert: CA certificate for signing
        ca_private_key: CA private key for signing
        organization: Organization name
        organizational_unit: Department/unit name
        country: Two-letter country code
        email: Email address
        validity_days: Certificate validity period in days
    
    Returns:
        Tuple of (client_cert, client_private_key, serial_number, fingerprint_sha256)
    """
    # Generate client key pair
    client_private_key = generate_key_pair(key_size=2048)
    
    # Build subject
    subject_components = []
    if country:
        subject_components.append(x509.NameAttribute(NameOID.COUNTRY_NAME, country))
    if organization:
        subject_components.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    if organizational_unit:
        subject_components.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit))
    subject_components.append(x509.NameAttribute(NameOID.COMMON_NAME, common_name))
    if email:
        subject_components.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    
    subject = x509.Name(subject_components)
    
    # Generate serial number
    serial = generate_serial_number()
    
    # Build client certificate
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_private_key.public_key())
        .serial_number(serial)
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=validity_days))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(client_private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
    )
    
    # Add Subject Alternative Name with customer_id
    san_entries = [x509.DNSName(common_name)]
    if email:
        san_entries.append(x509.RFC822Name(email))
    builder = builder.add_extension(
        x509.SubjectAlternativeName(san_entries),
        critical=False,
    )
    
    # Sign with CA
    client_cert = builder.sign(ca_private_key, hashes.SHA256(), default_backend())
    
    # Calculate fingerprint
    fingerprint = hashlib.sha256(client_cert.public_bytes(Encoding.DER)).hexdigest()
    
    return client_cert, client_private_key, str(serial), fingerprint


def certificate_to_pem(cert: x509.Certificate) -> str:
    """Convert certificate to PEM string"""
    return cert.public_bytes(Encoding.PEM).decode('utf-8')


def private_key_to_pem(private_key: rsa.RSAPrivateKey, password: Optional[str] = None) -> str:
    """
    Convert private key to PEM string, optionally encrypted.
    
    Args:
        private_key: RSA private key
        password: Optional password for encryption
    
    Returns:
        PEM-encoded private key string
    """
    encryption = BestAvailableEncryption(password.encode()) if password else NoEncryption()
    return private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    ).decode('utf-8')


def create_pkcs12_bundle(
    cert: x509.Certificate,
    private_key: rsa.RSAPrivateKey,
    ca_cert: Optional[x509.Certificate],
    password: str,
    friendly_name: Optional[str] = None,
) -> bytes:
    """
    Create PKCS#12 (.p12/.pfx) bundle containing certificate, private key, and CA chain.
    Compatible with SAP STRUST, Postman, browsers, etc.
    
    Args:
        cert: Client certificate
        private_key: Client private key
        ca_cert: CA certificate (optional)
        password: Password to encrypt the bundle
        friendly_name: Friendly name for the certificate
    
    Returns:
        PKCS#12 bundle as bytes
    """
    from cryptography.hazmat.primitives.serialization import pkcs12
    
    ca_certs = [ca_cert] if ca_cert else None
    
    p12_bytes = pkcs12.serialize_key_and_certificates(
        name=friendly_name.encode() if friendly_name else None,
        key=private_key,
        cert=cert,
        cas=ca_certs,
        encryption_algorithm=BestAvailableEncryption(password.encode()),
    )
    
    return p12_bytes


def load_certificate_from_pem(pem_data: str) -> x509.Certificate:
    """Load X.509 certificate from PEM string"""
    return x509.load_pem_x509_certificate(pem_data.encode(), default_backend())


def load_private_key_from_pem(pem_data: str, password: Optional[str] = None) -> rsa.RSAPrivateKey:
    """Load RSA private key from PEM string"""
    pwd = password.encode() if password else None
    return serialization.load_pem_private_key(pem_data.encode(), password=pwd, backend=default_backend())


def get_certificate_fingerprint(cert: x509.Certificate) -> str:
    """Calculate SHA-256 fingerprint of certificate"""
    return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()


def get_certificate_serial(cert: x509.Certificate) -> str:
    """Get certificate serial number as string"""
    return str(cert.serial_number)


def is_certificate_expired(cert: x509.Certificate) -> bool:
    """Check if certificate has expired"""
    return datetime.utcnow() > cert.not_valid_after


def days_until_expiry(cert: x509.Certificate) -> int:
    """Calculate days until certificate expires (negative if already expired)"""
    delta = cert.not_valid_after - datetime.utcnow()
    return delta.days


def generate_strong_password(length: int = 16) -> str:
    """Generate a cryptographically strong random password for P12 files"""
    import secrets
    import string
    
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password
