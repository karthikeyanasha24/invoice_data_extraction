'use client';

import { useState, useEffect } from 'react';
import { certificateApi } from '@/lib/api';
import {
  Shield,
  Plus,
  Eye,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader,
  RefreshCw,
  Calendar,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import CertificateGenerateModal from './CertificateGenerateModal';
import CertificateDetailsModal from './CertificateDetailsModal';

interface CertificateManagementProps {
  customerId: string;
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
  pending: {
    icon: Loader,
    color: 'text-gray-700',
    bgColor: 'bg-gray-100',
    label: 'Pending',
  },
};

export default function CertificateManagement({ customerId }: CertificateManagementProps) {
  const [certificates, setCertificates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [selectedCertificateId, setSelectedCertificateId] = useState<number | null>(null);

  useEffect(() => {
    loadCertificates();
  }, [customerId]);

  const loadCertificates = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await certificateApi.listCertificates(customerId, undefined, 0, 100);
      setCertificates(data.certificates || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load certificates');
      setCertificates([]);
    } finally {
      setLoading(false);
    }
  };

  const activeCertificate = certificates.find(
    (c) => c.status === 'active' || c.status === 'expiring_soon'
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Shield className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Client Certificates (mTLS)</h3>
            <p className="text-sm text-gray-600">X.509 certificates for mutual TLS authentication</p>
          </div>
        </div>
        <button
          onClick={() => setShowGenerateModal(true)}
          disabled={loading}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-all disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />
          Generate Certificate
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
          <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-blue-600 animate-spin" />
        </div>
      ) : certificates.length === 0 ? (
        <div className="text-center py-8 bg-gray-50 rounded-lg border border-gray-200">
          <Shield className="w-12 h-12 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-600 mb-2">No certificates found</p>
          <p className="text-sm text-gray-500">Generate a client certificate to enable mTLS authentication</p>
        </div>
      ) : (
        <div className="space-y-3">
          {activeCertificate && (
            <div className="p-4 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-300 rounded-lg">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-blue-600" />
                  <span className="font-semibold text-blue-900">Active Certificate</span>
                </div>
                <span className={cn('px-2 py-1 rounded-full text-xs font-medium', STATUS_CONFIG[activeCertificate.status].bgColor, STATUS_CONFIG[activeCertificate.status].color)}>
                  {STATUS_CONFIG[activeCertificate.status].label}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm mb-3">
                <div>
                  <span className="text-gray-600">Common Name:</span>
                  <p className="font-mono text-xs mt-1">{activeCertificate.common_name}</p>
                </div>
                <div>
                  <span className="text-gray-600">Expires:</span>
                  <p className="font-medium mt-1">{new Date(activeCertificate.expires_at).toLocaleDateString()}</p>
                </div>
              </div>
              {activeCertificate.days_until_expiry !== null && (
                <div className="text-sm">
                  {activeCertificate.days_until_expiry > 90 ? (
                    <p className="text-green-700">
                      ✓ Certificate valid for {activeCertificate.days_until_expiry} more days
                    </p>
                  ) : activeCertificate.days_until_expiry > 0 ? (
                    <p className="text-yellow-700 font-medium">
                      ⚠ Expires in {activeCertificate.days_until_expiry} days - Consider renewal
                    </p>
                  ) : (
                    <p className="text-red-700 font-medium">
                      ✗ Expired {Math.abs(activeCertificate.days_until_expiry)} days ago
                    </p>
                  )}
                </div>
              )}
              <button
                onClick={() => setSelectedCertificateId(activeCertificate.id)}
                className="mt-3 w-full px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2 text-sm font-medium"
              >
                <Eye className="w-4 h-4" />
                View Details & Manage
              </button>
            </div>
          )}

          {certificates.filter((c) => c.status !== 'active' && c.status !== 'expiring_soon').length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Certificate History</h4>
              <div className="space-y-2">
                {certificates
                  .filter((c) => c.status !== 'active' && c.status !== 'expiring_soon')
                  .map((cert) => {
                    const config = STATUS_CONFIG[cert.status] || STATUS_CONFIG.active;
                    const StatusIcon = config.icon;
                    return (
                      <div
                        key={cert.id}
                        className="p-3 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 cursor-pointer"
                        onClick={() => setSelectedCertificateId(cert.id)}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <StatusIcon className={cn('w-4 h-4', config.color)} />
                            <div>
                              <p className="font-mono text-xs text-gray-700">{cert.common_name}</p>
                              <p className="text-xs text-gray-500">
                                {new Date(cert.issued_at).toLocaleDateString()} - {new Date(cert.expires_at).toLocaleDateString()}
                              </p>
                            </div>
                          </div>
                          <span className={cn('px-2 py-1 rounded-full text-xs font-medium', config.bgColor, config.color)}>
                            {config.label}
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
        </div>
      )}

      {showGenerateModal && (
        <CertificateGenerateModal
          customerId={customerId}
          onClose={() => setShowGenerateModal(false)}
          onSuccess={loadCertificates}
        />
      )}

      {selectedCertificateId && (
        <CertificateDetailsModal
          certificateId={selectedCertificateId}
          onClose={() => setSelectedCertificateId(null)}
          onRenewed={loadCertificates}
          onRevoked={loadCertificates}
        />
      )}
    </div>
  );
}
