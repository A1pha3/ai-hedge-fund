/**
 * P2-9: 宏观经济仪表盘 测试。
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MacroDashboard } from '@/components/macro-dashboard';
import {
  formatMacroValue,
  regimeVariant,
  regimeChinese,
  type MacroSnapshot,
} from '@/services/macro-snapshot-api';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_SNAPSHOT: MacroSnapshot = {
  date: '202605',
  cpi_yoy: 0.3,
  ppi_yoy: -2.5,
  pmi_manufacturing: 49.5,
  pmi_non_manufacturing: 51.2,
  m2_yoy: 7.8,
  social_financing: 22000,
  interest_rate_lpr_1y: 3.1,
  inflation_pressure: 'low',
  monetary_stance: 'loose',
  economic_momentum: 'stable',
};

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

describe('formatMacroValue', () => {
  it('formats percentage values', () => {
    expect(formatMacroValue('cpi_yoy', 0.3)).toBe('0.3%');
    expect(formatMacroValue('ppi_yoy', -2.5)).toBe('-2.5%');
  });

  it('formats social_financing in 万亿', () => {
    expect(formatMacroValue('social_financing', 22000)).toBe('2万亿');
  });

  it('formats PMI with one decimal', () => {
    expect(formatMacroValue('pmi_manufacturing', 49.5)).toBe('49.5');
  });

  it('returns — for null', () => {
    expect(formatMacroValue('cpi_yoy', null)).toBe('—');
  });
});

describe('regimeVariant', () => {
  it('maps positive labels to success', () => {
    expect(regimeVariant('loose')).toBe('success');
    expect(regimeVariant('expanding')).toBe('success');
  });

  it('maps negative labels to destructive', () => {
    expect(regimeVariant('tight')).toBe('destructive');
    expect(regimeVariant('contracting')).toBe('destructive');
    expect(regimeVariant('high')).toBe('destructive');
  });

  it('maps neutral labels to secondary', () => {
    expect(regimeVariant('neutral')).toBe('secondary');
    expect(regimeVariant('stable')).toBe('secondary');
    expect(regimeVariant('moderate')).toBe('secondary');
  });
});

describe('regimeChinese', () => {
  it('translates labels to Chinese', () => {
    expect(regimeChinese('loose')).toBe('宽松');
    expect(regimeChinese('tight')).toBe('收紧');
    expect(regimeChinese('expanding')).toBe('扩张');
    expect(regimeChinese('stable')).toBe('平稳');
  });

  it('returns original for unknown labels', () => {
    expect(regimeChinese('custom')).toBe('custom');
  });
});

// ---------------------------------------------------------------------------
// Component tests
// ---------------------------------------------------------------------------

describe('MacroDashboard', () => {
  it('renders macro dashboard with all indicators', () => {
    render(<MacroDashboard snapshot={MOCK_SNAPSHOT} />);

    expect(screen.getByTestId('macro-dashboard')).toBeDefined();
    expect(screen.getByText('宏观经济环境')).toBeDefined();
    expect(screen.getByText('202605')).toBeDefined();
  });

  it('renders regime badges', () => {
    render(<MacroDashboard snapshot={MOCK_SNAPSHOT} />);

    expect(screen.getByTestId('macro-regime-badges')).toBeDefined();
    expect(screen.getByText('宽松')).toBeDefined();
    expect(screen.getByText('低')).toBeDefined();
  });

  it('renders metric labels', () => {
    render(<MacroDashboard snapshot={MOCK_SNAPSHOT} />);

    expect(screen.getByText('CPI 同比')).toBeDefined();
    expect(screen.getByText('制造业 PMI')).toBeDefined();
    expect(screen.getByText('M2 同比')).toBeDefined();
  });

  it('shows empty state when snapshot is null', () => {
    render(<MacroDashboard snapshot={null} />);

    expect(screen.getByText(/暂无宏观数据/)).toBeDefined();
  });

  it('shows loading state', () => {
    render(<MacroDashboard snapshot={null} isLoading />);

    expect(screen.getByText(/加载中/)).toBeDefined();
  });

  it('handles all-null snapshot gracefully', () => {
    const emptySnapshot: MacroSnapshot = {
      date: '',
      cpi_yoy: null,
      ppi_yoy: null,
      pmi_manufacturing: null,
      pmi_non_manufacturing: null,
      m2_yoy: null,
      social_financing: null,
      interest_rate_lpr_1y: null,
      inflation_pressure: 'unknown',
      monetary_stance: 'unknown',
      economic_momentum: 'unknown',
    };

    render(<MacroDashboard snapshot={emptySnapshot} />);

    // All metric values should show —
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBe(7);
    // 3 regime badges all show '未知'
    const unknowns = screen.getAllByText('未知');
    expect(unknowns.length).toBe(3);
  });
});
