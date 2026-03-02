'use client';

import { useState } from 'react';
import { certificateApi } from '@/lib/api';
import {
  X,
  Loader,
  Shield,
  Download,
  Copy,
  CheckCircle,
  AlertCircle,
  FileKey,
} from 'lucide-react';

interface CertificateGenerateModalProps {
  customerId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function CertificateGenerateModal({
  customerId,
  onClose,
  onSuccess,
}: CertificateGenerateModalProps) {
  const [formData, setFormData] = useState({
    organization: '',
    organizational_unit: '',
    country: '',
    email: '',
    validity_days: 365,
    notes: '',
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [generated, setGenerated] = useState<any>(null);
  const [p12Downloaded, setP12Downloaded] = useState(false);
  const [crtDownloaded, setCrtDownloaded] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const result = await certificateApi.issueCertificate({
        customer_id: customerId,
        organization: formData.organization || undefined,
        organizational_unit: formData.organizational_unit || undefined,
        country: formData.country || undefined,
        email: formData.email || undefined,
        validity_days: formData.validity_days,
        notes: formData.notes || undefined,
      });

      setGenerated(result);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate certificate');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadCRT = async () => {
    if (!generated) return;

    try {
      const { blob, filename } = await certificateApi.downloadCertificateCRT(
        generated.certificate_id
      );

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setCrtDownloaded(true);
    } catch (err: any) {
      setError(err.message || 'Failed to download CRT file');
    }
  };

  const handleDownloadP12 = async () => {
    if (!generated) return;

    try {
      const { blob, password, filename } = await certificateApi.downloadCertificateP12(
        generated.certificate_id
      );

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setP12Downloaded(true);
    } catch (err: any) {
      setError(err.message || 'Failed to download P12 file');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const handleClose = () => {
    if (generated && !crtDownloaded && !p12Downloaded) {
      if (!confirm('You have not downloaded the certificate files yet. Are you sure you want to close?')) {
        return;
      }
    }
    if (generated) {
      onSuccess();
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Shield className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">Generate Client Certificate</h2>
              <p className="text-sm text-gray-600">Customer: {customerId}</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-1 text-gray-500 hover:bg-gray-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6">
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          )}

          {!generated ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                <p className="text-sm text-blue-900">
                  This will generate an X.509 client certificate for mTLS authentication.
                  The certificate will be packaged as a P12/PFX file for easy installation.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Organization
                  </label>
                  <input
                    type="text"
                    value={formData.organization}
                    onChange={(e) => setFormData({ ...formData, organization: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., Acme Corp"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Department
                  </label>
                  <input
                    type="text"
                    value={formData.organizational_unit}
                    onChange={(e) => setFormData({ ...formData, organizational_unit: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., IT Department"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Country Code
                  </label>
                  <input
                    type="text"
                    maxLength={2}
                    value={formData.country}
                    onChange={(e) => setFormData({ ...formData, country: e.target.value.toUpperCase() })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., US, MX, DE"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Contact Email
                  </label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., admin@example.com"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Validity Period (days)
                </label>
                <input
                  type="number"
                  min={30}
                  max={1825}
                  value={formData.validity_days}
                  onChange={(e) => setFormData({ ...formData, validity_days: parseInt(e.target.value) })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Recommended: 365 days (1 year) for client certificates
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Notes (optional)
                </label>
                <textarea
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Optional notes about this certificate"
                />
              </div>

              <div className="flex gap-3 justify-end pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={handleClose}
                  disabled={loading}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {loading ? (
                    <>
                      <Loader className="w-4 h-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Shield className="w-4 h-4" />
                      Generate Certificate
                    </>
                  )}
                </button>
              </div>
            </form>
          ) : (
            <div className="space-y-6">
              <div className="p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-green-900">Certificate Generated Successfully</p>
                  <p className="text-sm text-green-700 mt-1">{generated.message}</p>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="font-semibold text-gray-900">Certificate Details</h3>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Serial Number:</span>
                    <p className="font-mono text-xs break-all">{generated.serial_number}</p>
                  </div>
                  <div>
                    <span className="text-gray-600">Common Name:</span>
                    <p className="font-medium">{generated.common_name}</p>
                  </div>
                  <div>
                    <span className="text-gray-600">Issued:</span>
                    <p>{new Date(generated.issued_at).toLocaleDateString()}</p>
                  </div>
                  <div>
                    <span className="text-gray-600">Expires:</span>
                    <p>{new Date(generated.expires_at).toLocaleDateString()}</p>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                  <FileKey className="w-5 h-5 text-amber-600" />
                  Certificate Files
                </h3>
                
                {/* CRT File for SAP STRUST */}
                <div className="p-4 bg-blue-50 border border-blue-300 rounded-lg">
                  <div className="flex items-start gap-3 mb-3">
                    <Shield className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="font-semibold text-blue-900 mb-1">Public Certificate (.crt)</h4>
                      <p className="text-sm text-blue-800">
                        For SAP STRUST: Import this file into <strong>SSL client → SSL Client (Anonymous) → Certificate List</strong>
                      </p>
                    </div>
                  </div>
                  
                  <button
                    onClick={handleDownloadCRT}
                    className="w-full px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2 font-medium"
                  >
                    <Download className="w-5 h-5" />
                    Download .CRT (Public Certificate for SAP)
                  </button>

                  {crtDownloaded && (
                    <div className="mt-2 p-2 bg-green-50 border border-green-200 rounded text-sm text-green-800 flex items-center gap-2">
                      <CheckCircle className="w-4 h-4" />
                      CRT file downloaded successfully
                    </div>
                  )}
                </div>

                {/* P12 File with Private Key */}
                <div className="p-4 bg-amber-50 border border-amber-300 rounded-lg">
                  <div className="flex items-start gap-3 mb-3">
                    <FileKey className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="font-semibold text-amber-900 mb-1">P12 Bundle (with Private Key)</h4>
                      <p className="text-sm text-amber-800">
                        For Postman, API clients, or programmatic access. Contains private key - keep secure!
                      </p>
                    </div>
                  </div>
                  
                  <p className="text-sm font-semibold text-amber-900 mb-2">
                    ⚠️ IMPORTANT: Store the password securely. It will not be shown again.
                  </p>
                  <div className="space-y-2">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">
                        P12 Password:
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          readOnly
                          value={generated.p12_password}
                          className="flex-1 px-3 py-2 border border-amber-300 rounded-lg bg-white font-mono text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => copyToClipboard(generated.p12_password)}
                          className="px-3 py-2 border border-amber-300 rounded-lg hover:bg-amber-100 flex items-center gap-1"
                          title="Copy password"
                        >
                          <Copy className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    <button
                      onClick={handleDownloadP12}
                      className="w-full px-4 py-3 bg-amber-600 text-white rounded-lg hover:bg-amber-700 flex items-center justify-center gap-2 font-medium"
                    >
                      <Download className="w-5 h-5" />
                      Download .P12 (Full Bundle with Private Key)
                    </button>

                    {p12Downloaded && (
                      <div className="p-2 bg-green-50 border border-green-200 rounded text-sm text-green-800 flex items-center gap-2">
                        <CheckCircle className="w-4 h-4" />
                        P12 file downloaded successfully
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                <h4 className="font-medium text-gray-900 mb-2">📝 Installation Guide:</h4>
                <div className="space-y-3 text-sm">
                  <div className="border-l-4 border-blue-500 pl-3">
                    <p className="font-semibold text-blue-900 mb-1">For SAP STRUST (Recommended):</p>
                    <ol className="list-decimal list-inside text-gray-700 space-y-1">
                      <li>Download the <strong>.CRT file</strong> (public certificate)</li>
                      <li>Open SAP STRUST transaction</li>
                      <li>Navigate to: SSL client → SSL Client (Anonymous) → SAPERPHANAO07_ERP_00</li>
                      <li>Click "Import Certificate" button (left panel)</li>
                      <li>Select the .CRT file</li>
                      <li>Click "Add to Certificate List"</li>
                      <li>Save your changes</li>
                    </ol>
                  </div>
                  
                  <div className="border-l-4 border-amber-500 pl-3">
                    <p className="font-semibold text-amber-900 mb-1">For Postman / API Testing:</p>
                    <ol className="list-decimal list-inside text-gray-700 space-y-1">
                      <li>Download the <strong>.P12 file</strong> and copy the password</li>
                      <li>Open Postman → Settings → Certificates</li>
                      <li>Add Certificate → Select .P12 file</li>
                      <li>Enter the password</li>
                    </ol>
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-4 border-t border-gray-200">
                <button
                  onClick={handleClose}
                  className="px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-800"
                >
                  Done
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
