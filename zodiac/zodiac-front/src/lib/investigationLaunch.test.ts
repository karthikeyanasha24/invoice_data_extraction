import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  investigationLaunch,
  shouldTreatAsNew,
  analystPathWithoutQuery,
  overviewQuestionHref,
} from './investigationLaunch.ts';

describe('investigationLaunch isolation', () => {
  it('clean session + Overview URL starts a recommended investigation as new', () => {
    const r = investigationLaunch('overview-url', false);
    assert.equal(r.asNew, true);
    assert.equal(r.keepHistory, true);
    assert.equal(r.sendQuestion, true);
    assert.match(r.banner || '', /recommended/i);
  });

  it('dirty session + Overview URL does not inherit previous filters', () => {
    const r = investigationLaunch('overview-url', true);
    assert.equal(r.asNew, true);
    assert.equal(r.keepHistory, true);
    assert.match(r.banner || '', /not applied/i);
  });

  it('Overview chip is the same isolation as ?q=', () => {
    const url = investigationLaunch('overview-url', true);
    const chip = investigationLaunch('overview-chip', true);
    assert.equal(url.asNew, chip.asNew);
    assert.equal(url.keepHistory, chip.keepHistory);
  });

  it('compatible follow-up chip continues the dirty investigation', () => {
    const r = investigationLaunch('followup-chip', true);
    assert.equal(r.asNew, false);
    assert.equal(r.keepHistory, true);
    assert.match(r.banner || '', /continuing/i);
  });

  it('incompatible Overview question from a dirty session is still isolated', () => {
    const r = investigationLaunch('overview-chip', true);
    assert.equal(r.asNew, true);
    assert.match(r.banner || '', /new investigation/i);
  });

  it('explicit new investigation is asNew and keeps visible history', () => {
    const r = investigationLaunch('explicit-new', true);
    assert.equal(r.asNew, true);
    assert.equal(r.keepHistory, true);
    assert.match(r.banner || '', /new investigation/i);
  });

  it('dirty Overview concentration launch is a new investigation without wiping history', () => {
    const r = investigationLaunch('overview-chip', true);
    assert.equal(r.asNew, true);
    assert.equal(r.keepHistory, true);
    assert.equal(r.sendQuestion, true);
  });

  it('saved restore is a new question and does not steal current filters', () => {
    const r = investigationLaunch('saved-restore', true);
    assert.equal(r.asNew, true);
    assert.equal(r.sendQuestion, true);
  });

  it('refresh / history restore does not send a new question', () => {
    const refresh = investigationLaunch('refresh', true);
    const hist = investigationLaunch('history-restore', true);
    assert.equal(refresh.sendQuestion, false);
    assert.equal(hist.sendQuestion, false);
    assert.equal(refresh.asNew, false);
  });
});

describe('shouldTreatAsNew', () => {
  it('typed continue is not new', () => {
    assert.equal(shouldTreatAsNew({ source: 'typed-continue' }), false);
  });

  it('toggle and asNew flag win', () => {
    assert.equal(shouldTreatAsNew({ newQuestionToggle: true }), true);
    assert.equal(shouldTreatAsNew({ asNewFlag: true }), true);
  });
});

describe('overview deep link', () => {
  it('routes Overview questions through AI Analyst ?q=', () => {
    assert.equal(
      overviewQuestionHref('Show supplier concentration.'),
      '/dashboard/ai?q=Show%20supplier%20concentration.',
    );
  });

  it('refresh path drops q so the question is not re-asked', () => {
    assert.equal(analystPathWithoutQuery(), '/dashboard/ai');
  });
});
