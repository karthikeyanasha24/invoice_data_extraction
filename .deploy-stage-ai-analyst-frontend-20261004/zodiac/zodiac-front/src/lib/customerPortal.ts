/** Customer portal helpers — reuse existing auth roles + user_customers. */

export function isCustomerPortalUser(user: {
  is_customer_user?: boolean;
  is_admin?: boolean;
} | null | undefined): boolean {
  return !!(user?.is_customer_user && !user?.is_admin);
}

/** Pick the exclusive workspace for a portal session (never an admin-chosen list). */
export function resolvePortalCustomerId(assigned: string[]): string | null {
  if (!assigned?.length) return null;
  const sorted = [...assigned].filter(Boolean).sort((a, b) => a.localeCompare(b));
  return sorted[0] || null;
}

export const CUSTOMER_LOGIN_PATH = '/customer/login';
export const CUSTOMER_HOME_PATH = '/customer/overview';
