import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { adminNavGroups, isNavActive } from './navConfig.ts';

describe('adminNavGroups', () => {
  it('groups Understand / Ask / Operate / Manage', () => {
    const groups = adminNavGroups({ isAdmin: true, workspaceUi: true });
    assert.deepEqual(groups.map((g) => g.id), ['understand', 'ask', 'operate', 'manage']);
    const paths = groups.flatMap((g) => g.items.map((i) => i.path));
    assert.ok(paths.includes('/overview'));
    assert.ok(paths.includes('/dashboard/ai'));
    assert.ok(paths.includes('/dashboard'));
    assert.ok(paths.includes('/settings'));
  });

  it('hides customer users unless admin', () => {
    const groups = adminNavGroups({ isAdmin: false, workspaceUi: false });
    const ids = groups.flatMap((g) => g.items.map((i) => i.id));
    assert.equal(ids.includes('customer-users'), false);
    assert.equal(ids.includes('workspaces'), false);
  });
});

describe('isNavActive', () => {
  it('does not mark AI Analyst active on EDI dashboard', () => {
    assert.equal(isNavActive('/dashboard', { id: 'edi', label: 'EDI', path: '/dashboard', description: '', icon: 'x' }), true);
    assert.equal(isNavActive('/dashboard/ai', { id: 'edi', label: 'EDI', path: '/dashboard', description: '', icon: 'x' }), false);
    assert.equal(isNavActive('/dashboard/ai', { id: 'ai', label: 'AI', path: '/dashboard/ai', description: '', icon: 'x' }), true);
  });
});

describe('SUPPORTED_INVESTIGATIONS', () => {
  it('does not include inventory aging', async () => {
    const { SUPPORTED_INVESTIGATIONS } = await import('./navConfig.ts');
    assert.equal(SUPPORTED_INVESTIGATIONS.some((x) => /aging/i.test(x.question)), false);
  });
});
