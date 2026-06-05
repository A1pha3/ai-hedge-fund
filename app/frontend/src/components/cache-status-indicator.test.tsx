import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Use vi.hoisted so the mock fn is available inside vi.mock factory
const { mockGetStats } = vi.hoisted(() => ({
  mockGetStats: vi.fn(),
}));

vi.mock('@/services/cache-api', () => ({
  cacheApi: {
    getStats: mockGetStats,
  },
}));

vi.mock('@/services/auth-api', () => ({
  authFetch: vi.fn(),
  authHeaders: vi.fn(() => ({})),
  getStoredToken: vi.fn(() => 'test-token'),
}));

import { CacheStatusIndicator } from '@/components/cache-status-indicator';
import type { CacheRuntimeInfo } from '@/services/cache-api';

const FAKE_INFO: CacheRuntimeInfo = {
  lru_maxsize: 128,
  redis_available: false,
  disk_available: true,
  disk_path: '/tmp/cache.sqlite',
  disk_entry_count: 42,
  disk_file_size_bytes: 1048576,
  stats: {
    lru_hits: 80,
    redis_hits: 0,
    disk_hits: 10,
    misses: 20,
    sets: 110,
    total_hits: 90,
    total_requests: 110,
    hit_rate: 0.8182,
  },
};

describe('CacheStatusIndicator', () => {
  beforeEach(() => {
    mockGetStats.mockReset();
  });

  it('renders hit rate percentage after loading', async () => {
    mockGetStats.mockResolvedValue(FAKE_INFO);

    render(<CacheStatusIndicator />);

    const el = await screen.findByLabelText(/Cache hit rate/i);
    expect(el).toHaveTextContent('82%');
  });

  it('shows "..." while loading', () => {
    mockGetStats.mockReturnValue(new Promise(() => {})); // never resolves

    render(<CacheStatusIndicator />);

    expect(screen.getByText('...')).toBeInTheDocument();
  });

  it('opens popover with detailed stats on click', async () => {
    const user = userEvent.setup();
    mockGetStats.mockResolvedValue(FAKE_INFO);

    render(<CacheStatusIndicator />);

    await screen.findByLabelText(/Cache hit rate/i);
    await user.click(screen.getByLabelText(/Cache hit rate/i));

    expect(screen.getByText('Cache Status')).toBeInTheDocument();
    expect(screen.getByText('80')).toBeInTheDocument(); // LRU hits
    expect(screen.getByText('42')).toBeInTheDocument(); // disk entries
  });

  it('uses green styling for hit rate >= 80%', async () => {
    const highRateInfo = {
      ...FAKE_INFO,
      stats: { ...FAKE_INFO.stats, hit_rate: 0.9 },
    };
    mockGetStats.mockResolvedValue(highRateInfo);

    render(<CacheStatusIndicator />);

    const trigger = await screen.findByLabelText(/Cache hit rate: 90%/i);
    expect(trigger).toBeInTheDocument();
    expect(trigger.className).toContain('bg-green-500');
  });

  it('uses red styling for hit rate < 50%', async () => {
    const lowRateInfo: CacheRuntimeInfo = {
      ...FAKE_INFO,
      stats: {
        lru_hits: 1,
        redis_hits: 0,
        disk_hits: 0,
        misses: 10,
        sets: 11,
        total_hits: 1,
        total_requests: 11,
        hit_rate: 0.0909,
      },
    };
    mockGetStats.mockResolvedValue(lowRateInfo);

    render(<CacheStatusIndicator />);

    const trigger = await screen.findByLabelText(/Cache hit rate: 9%/i);
    expect(trigger).toBeInTheDocument();
    expect(trigger.className).toContain('bg-red-500');
  });
});
