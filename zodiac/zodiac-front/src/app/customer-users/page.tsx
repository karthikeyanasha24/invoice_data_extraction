'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import { customerUsersApi, customerApi, type CustomerUserResponse } from '@/lib/api';
import { Plus, Users, Edit2, Loader, X, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function CustomerUsersPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [list, setList] = useState<CustomerUserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [assignModalOpen, setAssignModalOpen] = useState<CustomerUserResponse | null>(null);
  const [allCustomers, setAllCustomers] = useState<{ customer_id: string }[]>([]);
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<string[]>([]);
  const [assignSaving, setAssignSaving] = useState(false);

  // Only redirect after auth has finished loading; never redirect while auth is loading
  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace('/');
      return;
    }
    if (!user.is_admin) {
      router.replace('/dashboard');
    }
  }, [user, authLoading, router]);

  const loadCustomerUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await customerUsersApi.list();
      setList(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load customer users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.is_admin) loadCustomerUsers();
  }, [user?.is_admin]);

  const openAssignModal = async (cu: CustomerUserResponse) => {
    setAssignModalOpen(cu);
    setSelectedCustomerIds(cu.customer_ids || []);
    try {
      const data = await customerApi.getCustomers(0, 500);
      setAllCustomers(data.customers || []);
    } catch {
      setAllCustomers([]);
    }
  };

  const saveAssignCustomers = async () => {
    if (!assignModalOpen) return;
    try {
      setAssignSaving(true);
      await customerUsersApi.assignCustomers(assignModalOpen.id, selectedCustomerIds);
      await loadCustomerUsers();
      setAssignModalOpen(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to assign customers');
    } finally {
      setAssignSaving(false);
    }
  };

  // Show loader until auth is settled; then only show content if admin (otherwise redirect runs above)
  const authSettled = !authLoading;
  const isAdmin = user?.is_admin === true;
  const showContent = authSettled && !!user && isAdmin;

  if (!authSettled || !showContent) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center min-h-[50vh]">
          <Loader className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout>
      <div className="p-6 max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <Users className="h-7 w-7" />
            Customer users
          </h1>
          <button
            type="button"
            onClick={() => setCreateModalOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            Create customer user
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <Loader className="h-8 w-8 animate-spin text-blue-500" />
          </div>
        ) : (
          <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 text-sm font-medium text-gray-700">
              Customer users and assigned customer IDs
            </div>
            {list.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                No customer users yet. Create one to assign customer IDs.
              </div>
            ) : (
              <ul className="divide-y divide-gray-200">
                {list.map((cu) => (
                  <li key={cu.id} className="px-4 py-3 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-medium text-gray-900">{cu.email}</span>
                      <span className="text-gray-500 ml-2">({cu.username})</span>
                      <div className="text-sm text-gray-600 mt-0.5">
                        Assigned: {cu.customer_ids?.length ? cu.customer_ids.join(', ') : '—'}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openAssignModal(cu)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
                    >
                      <Edit2 className="h-3.5 w-3.5" />
                      Edit customers
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {createModalOpen && (
          <CreateCustomerUserModal
            onClose={() => setCreateModalOpen(false)}
            onCreated={() => {
              setCreateModalOpen(false);
              loadCustomerUsers();
            }}
          />
        )}

        {assignModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full max-h-[90vh] flex flex-col">
              <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">
                  Assign customers — {assignModalOpen.email}
                </h2>
                <button type="button" onClick={() => setAssignModalOpen(null)} className="p-1 hover:bg-gray-100 rounded">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-4 overflow-y-auto flex-1">
                <p className="text-sm text-gray-600 mb-3">
                  Select customer IDs this user can see (documents by customer).
                </p>
                <ul className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {allCustomers.map((c) => (
                    <li key={c.customer_id}>
                      <label
                        className={cn(
                          'flex items-center gap-2 cursor-pointer rounded-md px-2 py-1.5 transition-colors',
                          selectedCustomerIds.includes(c.customer_id)
                            ? 'bg-emerald-50 text-emerald-900'
                            : 'hover:bg-slate-100 text-slate-800'
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selectedCustomerIds.includes(c.customer_id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedCustomerIds((prev) => [...prev, c.customer_id]);
                            } else {
                              setSelectedCustomerIds((prev) => prev.filter((id) => id !== c.customer_id));
                            }
                          }}
                          className="h-4 w-4 rounded border-slate-400 text-emerald-600 focus:ring-emerald-500"
                        />
                        <span className="text-sm font-mono font-medium">{c.customer_id}</span>
                      </label>
                    </li>
                  ))}
                </ul>
                {allCustomers.length === 0 && (
                  <p className="text-sm text-gray-500">No customers in the system. Add customers first.</p>
                )}
              </div>
              <div className="px-4 py-3 border-t border-gray-200 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setAssignModalOpen(null)}
                  className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={saveAssignCustomers}
                  disabled={assignSaving}
                  className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {assignSaving ? <Loader className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </MainLayout>
  );
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/;

function validateCreateCustomerUser(email: string, username: string, password: string): string | null {
  const e = (email || '').trim().toLowerCase();
  const u = (username || '').trim();
  if (!e) return 'Email is required.';
  if (!EMAIL_REGEX.test(e)) return 'Please enter a valid email address.';
  if (!u) return 'Username is required.';
  if (u.length < 2) return 'Username must be at least 2 characters.';
  if (u.length > 64) return 'Username must be at most 64 characters.';
  if (!USERNAME_REGEX.test(u)) return 'Username may only contain letters, numbers, dots, hyphens and underscores.';
  if (!password) return 'Password is required.';
  if (password.length < 8) return 'Password must be at least 8 characters.';
  return null;
}

function CreateCustomerUserModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<string[]>([]);
  const [allCustomers, setAllCustomers] = useState<{ customer_id: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    customerApi.getCustomers(0, 500).then((data) => {
      if (!cancelled) setAllCustomers(data.customers || []);
    }).catch(() => { if (!cancelled) setAllCustomers([]); });
    return () => { cancelled = true; };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    const validationError = validateCreateCustomerUser(email, username, password);
    if (validationError) {
      setErr(validationError);
      return;
    }
    try {
      setSubmitting(true);
      await customerUsersApi.create({
        email: email.trim().toLowerCase(),
        username: username.trim(),
        password,
        customer_ids: selectedCustomerIds,
      });
      onCreated();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to create customer user.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full max-h-[90vh] flex flex-col">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Create customer user</h2>
          <button type="button" onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 overflow-y-auto flex-1 space-y-4">
          {err && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{err}</div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setErr(null); }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              placeholder="user@example.com"
              autoComplete="email"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => { setUsername(e.target.value); setErr(null); }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              placeholder="Letters, numbers, dots, hyphens, underscores (2–64 chars)"
              maxLength={64}
            />
            <p className="text-xs text-gray-500 mt-0.5">2–64 characters</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setErr(null); }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              placeholder="Minimum 8 characters"
              minLength={8}
              autoComplete="new-password"
            />
            <p className="text-xs text-gray-500 mt-0.5">Minimum 8 characters required</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Assign customers</label>
            <p className="text-xs text-gray-500 mb-2">
              Select which customer IDs this user can see (documents by customer).
            </p>
            <ul className="space-y-2 max-h-40 overflow-y-auto border border-slate-200 rounded-lg p-2 bg-slate-50">
              {allCustomers.map((c) => (
                <li key={c.customer_id}>
                  <label
                    className={cn(
                      'flex items-center gap-2 cursor-pointer rounded-md px-2 py-1.5 transition-colors',
                      selectedCustomerIds.includes(c.customer_id)
                        ? 'bg-emerald-50 text-emerald-900'
                        : 'hover:bg-slate-100 text-slate-800'
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={selectedCustomerIds.includes(c.customer_id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedCustomerIds((prev) => [...prev, c.customer_id]);
                        } else {
                          setSelectedCustomerIds((prev) => prev.filter((id) => id !== c.customer_id));
                        }
                      }}
                      className="h-4 w-4 rounded border-slate-400 text-emerald-600 focus:ring-emerald-500"
                    />
                    <span className="text-sm font-mono font-medium">{c.customer_id}</span>
                  </label>
                </li>
              ))}
            </ul>
            {allCustomers.length === 0 && (
              <p className="text-sm text-gray-500 mt-1">No customers in the system. You can assign later.</p>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50">
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50',
              )}
            >
              {submitting && <Loader className="h-4 w-4 animate-spin" />}
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
