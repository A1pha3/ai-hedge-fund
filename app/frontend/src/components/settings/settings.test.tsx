import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const openTabMock = vi.fn();

vi.mock('@/contexts/tabs-context', () => ({
  useTabsContext: () => ({
    openTab: openTabMock,
  }),
}));

vi.mock('@/services/api-keys-api', () => ({
  apiKeysService: {
    getAllApiKeys: vi.fn().mockResolvedValue([]),
    getApiKey: vi.fn(),
  },
}));

import { Settings } from '@/components/settings/settings';

describe('Settings replay artifacts entry', () => {
  beforeEach(() => {
    openTabMock.mockClear();
  });

  it('opens the replay workspace from the settings entry card', async () => {
    const user = userEvent.setup();

    render(<Settings />);

    await user.click(screen.getByRole('button', { name: 'Replay Artifacts' }));

    expect(screen.getByText('Replay Artifacts 已升级为一级工作台，用于浏览 report 列表、selection artifact、funnel diagnostics、feedback 和 cache benchmark 细节。')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开 Replay Artifacts 工作台' }));

    expect(openTabMock).toHaveBeenCalledTimes(1);
    expect(openTabMock).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'replay-artifacts',
        title: 'Replay Artifacts',
      }),
    );
  });
});