/**
 * Characterization tests for btst-decision-card metadata resolvers.
 *
 * These 4 pure helpers map domain strings (action / grade / data_quality /
 * risk_posture) to display metadata (label / textClass / badgeVariant / hint).
 * They drive the entire BTST decision card visual encoding, so locking their
 * behavior guards against silent UX regressions.
 *
 * R20-S9: previously 0 direct test coverage (component had no test file at all).
 */
import { describe, expect, it } from 'vitest';

import {
  resolveActionMeta,
  resolveDataQualityMeta,
  resolveGradeMeta,
  resolveRiskPostureMeta,
} from './btst-decision-card';

// ---------- resolveActionMeta ----------

describe('resolveActionMeta', () => {
  it('maps buy-family actions to BUY/success/green', () => {
    for (const a of ['buy', 'trade_allowed', 'long']) {
      const m = resolveActionMeta(a);
      expect(m.label).toBe('BUY');
      expect(m.badgeVariant).toBe('success');
      expect(m.textClass).toContain('text-green');
    }
  });

  it('maps sell-family actions to SELL/destructive/red', () => {
    for (const a of ['sell', 'short']) {
      const m = resolveActionMeta(a);
      expect(m.label).toBe('SELL');
      expect(m.badgeVariant).toBe('destructive');
      expect(m.textClass).toContain('text-red');
    }
  });

  it('maps confirmation actions to CONFIRM/warning/yellow', () => {
    for (const a of ['confirmation_only', 'confirm']) {
      const m = resolveActionMeta(a);
      expect(m.label).toBe('CONFIRM');
      expect(m.badgeVariant).toBe('warning');
    }
  });

  it('maps hold to HOLD/warning', () => {
    const m = resolveActionMeta('hold');
    expect(m.label).toBe('HOLD');
    expect(m.badgeVariant).toBe('warning');
  });

  it('maps skip / no_trade / unknown to SKIP/outline/muted', () => {
    for (const a of ['skip', 'no_trade', 'totally_unknown_action']) {
      const m = resolveActionMeta(a);
      expect(m.label).toBe('SKIP');
      expect(m.badgeVariant).toBe('outline');
      expect(m.textClass).toContain('text-muted-foreground');
    }
  });
});

// ---------- resolveGradeMeta ----------

describe('resolveGradeMeta', () => {
  it('maps A to high-quality green hint', () => {
    const m = resolveGradeMeta('A');
    expect(m.label).toBe('A');
    expect(m.textClass).toContain('text-green');
    expect(m.hint).toBe('高质量证据');
  });

  it('maps B to executable blue', () => {
    const m = resolveGradeMeta('B');
    expect(m.label).toBe('B');
    expect(m.textClass).toContain('text-blue');
    expect(m.hint).toBe('可执行');
  });

  it('maps C to review-needed yellow', () => {
    const m = resolveGradeMeta('C');
    expect(m.label).toBe('C');
    expect(m.textClass).toContain('text-yellow');
    expect(m.hint).toBe('需复盘');
  });

  it('maps D to not-recommended red', () => {
    const m = resolveGradeMeta('D');
    expect(m.label).toBe('D');
    expect(m.textClass).toContain('text-red');
    expect(m.hint).toBe('不建议开仓');
  });

  it('is case-insensitive (lowercase input normalized)', () => {
    expect(resolveGradeMeta('a').label).toBe('A');
    expect(resolveGradeMeta('b').label).toBe('B');
  });

  it('falls back to D for null / undefined / unknown', () => {
    expect(resolveGradeMeta(null).label).toBe('D');
    expect(resolveGradeMeta(undefined).label).toBe('D');
    expect(resolveGradeMeta('Z').label).toBe('D');
    expect(resolveGradeMeta('').label).toBe('D');
  });
});

// ---------- resolveDataQualityMeta ----------

describe('resolveDataQualityMeta', () => {
  it('maps sufficient/high to 充足/green', () => {
    for (const q of ['sufficient', 'high']) {
      const m = resolveDataQualityMeta(q);
      expect(m.label).toBe('充足');
      expect(m.textClass).toContain('text-green');
    }
  });

  it('maps partial/medium to 部分/yellow', () => {
    for (const q of ['partial', 'medium']) {
      const m = resolveDataQualityMeta(q);
      expect(m.label).toBe('部分');
      expect(m.textClass).toContain('text-yellow');
    }
  });

  it('maps insufficient/low/null/unknown to 不足/red', () => {
    for (const q of ['insufficient', 'low', null, undefined, 'garbage']) {
      const m = resolveDataQualityMeta(q);
      expect(m.label).toBe('不足');
      expect(m.textClass).toContain('text-red');
    }
  });

  it('is case-insensitive', () => {
    expect(resolveDataQualityMeta('SUFFICIENT').label).toBe('充足');
    expect(resolveDataQualityMeta('High').label).toBe('充足');
  });
});

// ---------- resolveRiskPostureMeta ----------

describe('resolveRiskPostureMeta', () => {
  it('maps aggressive to 激进/red with allow-position hint', () => {
    const m = resolveRiskPostureMeta('aggressive');
    expect(m.label).toBe('激进');
    expect(m.textClass).toContain('text-red');
    expect(m.hint).toBe('允许放仓位');
  });

  it('maps standard to 标准/blue (no hint)', () => {
    const m = resolveRiskPostureMeta('standard');
    expect(m.label).toBe('标准');
    expect(m.textClass).toContain('text-blue');
    expect(m.hint).toBeUndefined();
  });

  it('maps conservative to 保守/yellow with half-position hint', () => {
    const m = resolveRiskPostureMeta('conservative');
    expect(m.label).toBe('保守');
    expect(m.textClass).toContain('text-yellow');
    expect(m.hint).toBe('建议减半仓位');
  });

  it('maps no_trade / null / unknown to 禁开仓/muted with empty-position hint', () => {
    for (const p of ['no_trade', null, undefined, 'unknown']) {
      const m = resolveRiskPostureMeta(p);
      expect(m.label).toBe('禁开仓');
      expect(m.textClass).toContain('text-muted-foreground');
      expect(m.hint).toBe('保持空仓');
    }
  });

  it('is case-insensitive', () => {
    expect(resolveRiskPostureMeta('AGGRESSIVE').label).toBe('激进');
    expect(resolveRiskPostureMeta('Standard').label).toBe('标准');
  });
});
