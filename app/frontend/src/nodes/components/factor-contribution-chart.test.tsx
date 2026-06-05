import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  FactorContributionChart,
  type FactorContribution,
} from './factor-contribution-chart';

const SAMPLE_FACTORS: FactorContribution[] = [
  {
    name: 'trend',
    direction: 1,
    confidence: 75.0,
    completeness: 0.9,
    weight: 0.35,
    contribution: 0.2363,
  },
  {
    name: 'fundamental',
    direction: 1,
    confidence: 60.0,
    completeness: 0.8,
    weight: 0.30,
    contribution: 0.144,
  },
  {
    name: 'mean_reversion',
    direction: -1,
    confidence: 50.0,
    completeness: 0.7,
    weight: 0.20,
    contribution: 0.07,
  },
  {
    name: 'event_sentiment',
    direction: 0,
    confidence: 20.0,
    completeness: 0.5,
    weight: 0.15,
    contribution: 0.0,
  },
];

describe('FactorContributionChart', () => {
  it('renders all factor names and direction badges', () => {
    render(<FactorContributionChart factors={SAMPLE_FACTORS} />);

    expect(screen.getByText('Trend')).toBeDefined();
    expect(screen.getByText('Fundamental')).toBeDefined();
    expect(screen.getByText('Mean Reversion')).toBeDefined();
    expect(screen.getByText('Event Sentiment')).toBeDefined();

    // Direction badges
    const longBadges = screen.getAllByText('Long');
    expect(longBadges.length).toBe(2);
    expect(screen.getByText('Short')).toBeDefined();
    expect(screen.getByText('Neutral')).toBeDefined();
  });

  it('renders weight and contribution share for each factor', () => {
    render(<FactorContributionChart factors={SAMPLE_FACTORS} />);

    // Weight percentages (format: "w=35.0%" or "w35.0%")
    const trendWeight = screen.getByTestId('factor-weight-trend').textContent || '';
    expect(trendWeight).toContain('35.0%');
    const fundWeight = screen.getByTestId('factor-weight-fundamental').textContent || '';
    expect(fundWeight).toContain('30.0%');
    const mrWeight = screen.getByTestId('factor-weight-mean_reversion').textContent || '';
    expect(mrWeight).toContain('20.0%');
    const esWeight = screen.getByTestId('factor-weight-event_sentiment').textContent || '';
    expect(esWeight).toContain('15.0%');

    // Contribution share percentages (sum = 0.4503; trend ~52.5%)
    expect(screen.getByTestId('factor-share-trend').textContent).toBe('52.5%');
    expect(screen.getByTestId('factor-share-fundamental').textContent).toBe('32.0%');
    expect(screen.getByTestId('factor-share-mean_reversion').textContent).toBe('15.5%');
    expect(screen.getByTestId('factor-share-event_sentiment').textContent).toBe('0.0%');
  });

  it('renders horizontal bars for each factor', () => {
    render(<FactorContributionChart factors={SAMPLE_FACTORS} />);

    expect(screen.getByTestId('factor-bar-trend')).toBeDefined();
    expect(screen.getByTestId('factor-bar-fundamental')).toBeDefined();
    expect(screen.getByTestId('factor-bar-mean_reversion')).toBeDefined();
    expect(screen.getByTestId('factor-bar-event_sentiment')).toBeDefined();
  });

  it('renders confidence and completeness details', () => {
    render(<FactorContributionChart factors={SAMPLE_FACTORS} />);

    expect(screen.getByTestId('factor-row-trend')).toBeDefined();
    // Detail text includes conf/compl/contrib values
    expect(screen.getByText(/conf 75\.0%/)).toBeDefined();
    expect(screen.getByText(/compl 90%/)).toBeDefined();
  });

  it('returns null when factors array is empty', () => {
    const { container } = render(<FactorContributionChart factors={[]} />);
    expect(container.innerHTML).toBe('');
  });

  it('returns null when factors is undefined', () => {
    const { container } = render(
      <FactorContributionChart factors={undefined as unknown as FactorContribution[]} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('uses custom title and description when provided', () => {
    render(
      <FactorContributionChart
        factors={SAMPLE_FACTORS}
        title="Custom Title"
        description="Custom description text."
      />,
    );

    expect(screen.getByText('Custom Title')).toBeDefined();
    expect(screen.getByText('Custom description text.')).toBeDefined();
  });
});
