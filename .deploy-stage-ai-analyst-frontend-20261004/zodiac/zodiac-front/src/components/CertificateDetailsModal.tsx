'use client';

import { useState, useEffect } from 'react';
import { certificateApi } from '@/lib/api';
import {
  X,
  Loader,
  Shield,
  Download,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Calendar,
  FileText,
  Hash,
  Building2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface CertificateDetailsModalProps {
  certificateId: number;
  onClose: () => void;
  onRenewed?: () => void;
  onRevoked?: () => void;
}

const STATUS_CONFIG: Record<string, { icon: any; color: string; bgColor: string; label: string }> = {
  active: {
    icon: CheckCircle,
    color: 'text-green-700',
    bgColor: 'bg-green-100',
    label: 'Active',
  },
  expiring_soon: {
    icon: AlertTriangle,
    color: 'text-yellow-700',
    bgColor: 'bg-yellow-100',
    label: 'Expiring Soon',
  },
  expired: {
    icon: XCircle,
    color: 'text-red-700',
    bgColor: 'bg-red-100',
    label: 'Expired',
  },
  revoked: {
    icon: XCircle,
    color: 'text-gray-700',
    bgColor: 'bg-gray-200',
    label: 'Revoked',
  },
  renewed: {
    icon: RefreshCw,
    color: 'text-blue-700',
    bgColor: 'bg-blue-100',
    label: 'Renewed',
  },
};

export default function CertificateDetailsModal({
  certificateId,
  onClose,
  onRenewed,
  onRevoked,
}: CertificateDetailsModalProps) {
  const [certificate, setCertificate] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    loadCertificate();
  }, [certificateId]);

  const loadCertificate = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await certificateApi.getCertificate(certificateId);
      setCertificate(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load certificate');
    } finally {
      setLoading(false);
    }
  };

  const handleRenew = async () => {
    if (!confirm('Generate a new certificate for this customer? The old certificate will remain valid until its expiration date.')) {
      return;
    }

    setActionLoading(true);
    setError('');
    try {
      await certificateApi.renewCertificate(certificateId, { validity_days: 365 });
      if (onRenewed) onRenewed();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to renew certificate');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevoke = async () => {
    const reason = prompt('Enter reason for revocation (optional):');
    if (reason === null) return;

    if (!confirm('Revoke this certificate? This action cannot be undone and the certificate will be immediately invalid.')) {
      return;
    }

    setActionLoading(true);
    setError('');
    try {
      await certificateApi.revokeCertificate(certificateId, reason || undefined);
      if (onRevoked) onRevoked();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to revoke certificate');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDownloadCRT = async () => {
    try {
      const { blob, filename } = await certificateApi.downloadCertificateCRT(certificateId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err.message || 'Failed to download CRT file');
    }
  };

  const handleDownloadP12 = async () => {
    try {
      const { blob, filename } = await certificateApi.downloadCertificateP12(certificateId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err.message || 'Failed to download P12 file');
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
        <div className="bg-white rounded-lg shadow-xl p-8 flex items-center gap-3">
          <Loader className="w-6 h-6 animate-spin text-blue-600" />
          <span className="text-gray-700">Loading certificate...</span>
        </div>
      </div>
    );
  }

  if (!certificate) {
    return null;
  }

  const statusConfig = STATUS_CONFIG[certificate.status] || STATUS_CONFIG.active;
  const StatusIcon = statusConfig.icon;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Shield className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">Certificate Details</h2>
              <p className="text-sm text-gray-600">ID: {certificate.id}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 text-gray-500 hover:bg-gray-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {error && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
              <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          )}

          <div className="flex items-center gap-3">
            <span className={cn('px-3 py-1 rounded-full text-sm font-medium flex items-center gap-2', statusConfig.bgColor, statusConfig.color)}>
              <StatusIcon className="w-4 h-4" />
              {statusConfig.label}
            </span>
            {certificate.days_until_expiry !== null && certificate.days_until_expiry !== undefined && (
              <span className="text-sm text-gray-600">
                {certificate.days_until_expiry > 0
                  ? `${certificate.days_until_expiry} days until expiry`
                  : `Expired ${Math.abs(certificate.days_until_expiry)} days ago`}
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-500">Customer ID</label>
                <p className="font-medium text-gray-900">{certificate.customer_id}</p>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500">Common Name</label>
                <p className="font-mono text-sm text-gray-900">{certificate.common_name}</p>
              </div>
              {certificate.organization && (
                <div>
                  <label className="text-xs font-medium text-gray-500">Organization</label>
                  <p className="text-gray-900">{certificate.organization}</p>
                </div>
              )}
              {certificate.country && (
                <div>
                  <label className="text-xs font-medium text-gray-500">Country</label>
                  <p className="text-gray-900">{certificate.country}</p>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-500">Issued Date</label>
                <p className="text-gray-900">{new Date(certificate.issued_at).toLocaleString()}</p>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500">Expiration Date</label>
                <p className="text-gray-900">{new Date(certificate.expires_at).toLocaleString()}</p>
              </div>
              {certificate.revoked_at && (
                <div>
                  <label className="text-xs font-medium text-gray-500">Revoked Date</label>
                  <p className="text-red-700">{new Date(certificate.revoked_at).toLocaleString()}</p>
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-gray-200 pt-4">
            <div>
              <label className="text-xs font-medium text-gray-500">Fingerprint (SHA-256)</label>
              <p className="font-mono text-xs text-gray-700 break-all">{certificate.fingerprint_sha256}</p>
            </div>
          </div>

          {certificate.notes && (
            <div className="border-t border-gray-200 pt-4">
              <label className="text-xs font-medium text-gray-500">Notes</label>
              <p className="text-sm text-gray-700 mt-1">{certificate.notes}</p>
            </div>
          )}

          {/* Download Options */}
          {(certificate.status === 'active' || certificate.status === 'expiring_soon') && (
            <div className="border-t border-gray-200 pt-4">
              <h4 className="font-medium text-gray-900 mb-3">Download Options</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-xs font-semibold text-blue-900 mb-2">For SAP STRUST</p>
                  <button
                    onClick={handleDownloadCRT}
                    className="w-full px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center justify-center gap-2 text-sm"
                  >
                    <Download className="w-4 h-4" />
                    Download .CRT
                  </button>
                  <p className="text-xs text-blue-700 mt-2">Public certificate only (no private key)</p>
                </div>
                
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-xs font-semibold text-amber-900 mb-2">For Postman/API Clients</p>
                  <button
                    onClick={handleDownloadP12}
                    className="w-full px-3 py-2 bg-amber-600 text-white rounded hover:bg-amber-700 flex items-center justify-center gap-2 text-sm"
                  >
                    <Download className="w-4 h-4" />
                    Download .P12
                  </button>
                  <p className="text-xs text-amber-700 mt-2">Full bundle with private key (password required)</p>
                </div>
              </div>
            </div>
          )}

          <div className="flex gap-3 justify-end pt-4 border-t border-gray-200">
            {certificate.status === 'active' || certificate.status === 'expiring_soon' ? (
              <>
                <button
                  onClick={handleRenew}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {actionLoading ? (
                    <Loader className="w-4 h-4 animate-spin" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                  Renew
                </button>
                <button
                  onClick={handleRevoke}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {actionLoading ? (
                    <Loader className="w-4 h-4 animate-spin" />
                  ) : (
                    <XCircle className="w-4 h-4" />
                  )}
                  Revoke
                </button>
              </>
            ) : (
              <button
                onClick={onClose}
                className="px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-800"
              >
                Close
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
