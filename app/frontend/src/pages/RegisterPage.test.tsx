/**
 * Characterization tests for RegisterPage.getPasswordStrength (R20-S10).
 *
 * Pure helper scoring passwords on 5 criteria (length ≥8, lowercase,
 * uppercase, digit, bonus for length ≥12 or symbol). Maps raw 0-5 score
 * to (label, CSS class) for the password strength meter UI.
 *
 * Previously 0 direct coverage (RegisterPage had no test file at all).
 */
import { describe, expect, it } from 'vitest';

import { getPasswordStrength } from './RegisterPage';

describe('getPasswordStrength', () => {
  it('empty / null-ish / undefined / short weak inputs return score 0 with no label', () => {
    expect(getPasswordStrength('')).toEqual({ score: 0, label: '', cls: '' });
  });

  it('only length met (8+ chars) but no character variety → score 2 较弱', () => {
    // 8 lowercase → length≥8 + lowercase = 2 (length≥12 needs 12 chars, symbol needs non-alphanum)
    const r = getPasswordStrength('aaaaaaaa');
    expect(r.score).toBe(2);
    expect(r.label).toBe('较弱');
    expect(r.cls).toBe('pwd-fair');
  });

  it('length + lowercase only → score 2 较弱 (same as pure length≥8 + lowercase)', () => {
    const r = getPasswordStrength('abcdefghi');
    expect(r.score).toBe(2);
    expect(r.label).toBe('较弱');
    expect(r.cls).toBe('pwd-fair');
  });

  it('length + lowercase + uppercase → score 3 中等', () => {
    const r = getPasswordStrength('Abcdefghi');
    expect(r.score).toBe(3);
    expect(r.label).toBe('中等');
    expect(r.cls).toBe('pwd-good');
  });

  it('length + lowercase + uppercase + digit → score 4 强', () => {
    const r = getPasswordStrength('Abcdefghi1');
    expect(r.score).toBe(4);
    expect(r.label).toBe('强');
    expect(r.cls).toBe('pwd-strong');
  });

  it('all 5 criteria (length + lowercase + uppercase + digit + symbol bonus) → clamped to 4 强', () => {
    // The 5th criterion is either length >= 12 OR symbol; this password triggers both
    const r = getPasswordStrength('Abcdefghi1!@');
    expect(r.score).toBe(4);
    expect(r.cls).toBe('pwd-strong');
  });

  it('short length < 8 with all character types and symbol → score 4 强', () => {
    // 7 chars, lowercase + uppercase + digit + symbol → 4 (length < 8 skipped, no length-bonus)
    const r = getPasswordStrength('Ab1!xyz');
    expect(r.score).toBe(4);
  });

  it('exactly 12 lowercase → length ≥8 + lowercase + length ≥12 bonus = score 3 中等', () => {
    const r = getPasswordStrength('aaaaaaaaaaaa');
    expect(r.score).toBe(3);
    expect(r.label).toBe('中等');
  });

  it('empty-string is guarded (returns 0)', () => {
    const r = getPasswordStrength('');
    expect(r.score).toBe(0);
    expect(r.label).toBe('');
    expect(r.cls).toBe('');
  });

  it('common weak passwords score low (regression guard)', () => {
    // "password" = 8 lowercase → score 2
    expect(getPasswordStrength('password').score).toBeLessThanOrEqual(2);
    // "12345678" = 8 digits → score 2
    expect(getPasswordStrength('12345678').score).toBeLessThanOrEqual(2);
  });
});
