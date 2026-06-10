/**
 * P2-5: CustomWeightsPanel 展示型组件测试。
 *
 * 验证交互逻辑 (纯前端, 不触发网络):
 *   - 默认等权 (各 0.25, 和=1.00) → Apply 启用
 *   - 拖动滑块更新数值显示 + 权重和; 和 != 1.00 → Apply 禁用 + Badge 变红
 *   - 恢复和=1.00 → Apply 重新启用
 *   - 点击 Apply 调用 onApply 传入当前 4 权重
 *   - isApplying 禁用按钮 + 显示「应用中…」
 *   - errorMessage 渲染
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CustomWeightsPanel } from './custom-weights-panel';

describe('CustomWeightsPanel', () => {
  it('renders with equal default weights (sum=1.00) and Apply enabled', () => {
    const onApply = vi.fn();
    render(<CustomWeightsPanel onApply={onApply} />);

    expect(screen.getByTestId('custom-weights-panel')).toBeDefined();
    expect(screen.getByTestId('weight-sum').textContent).toContain('权重和: 1.00');
    expect(screen.getByTestId('weight-trend').getAttribute('value')).toBe('0.25');
    // Apply enabled when sum valid
    const applyBtn = screen.getByTestId('weight-apply') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(false);
  });

  it('updates value display + disables Apply when weight sum != 1.00', () => {
    const onApply = vi.fn();
    render(<CustomWeightsPanel onApply={onApply} />);

    // Move trend 0.25 → 0.50; sum becomes 1.25
    const trendSlider = screen.getByTestId('weight-trend');
    fireEvent.change(trendSlider, { target: { value: '0.50' } });

    expect(screen.getByTestId('weight-value-trend').textContent).toBe('0.50');
    expect(screen.getByTestId('weight-sum').textContent).toContain('1.25');
    expect(screen.getByTestId('weight-sum').textContent).toContain('需=1.00');
    const applyBtn = screen.getByTestId('weight-apply') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(true);
  });

  it('re-enables Apply when sum returns to 1.00', () => {
    const onApply = vi.fn();
    render(<CustomWeightsPanel onApply={onApply} />);

    // trend 0.25 → 0.50 (sum 1.25), then fundamental 0.25 → 0.00 (sum back to 1.00)
    fireEvent.change(screen.getByTestId('weight-trend'), { target: { value: '0.50' } });
    fireEvent.change(screen.getByTestId('weight-fundamental'), { target: { value: '0.00' } });

    expect(screen.getByTestId('weight-sum').textContent).toContain('1.00');
    const applyBtn = screen.getByTestId('weight-apply') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(false);
  });

  it('calls onApply with the current weights when Apply clicked', () => {
    const onApply = vi.fn();
    render(<CustomWeightsPanel onApply={onApply} />);

    fireEvent.change(screen.getByTestId('weight-trend'), { target: { value: '0.40' } });
    fireEvent.change(screen.getByTestId('weight-mean_reversion'), { target: { value: '0.20' } });
    fireEvent.change(screen.getByTestId('weight-fundamental'), { target: { value: '0.30' } });
    fireEvent.change(screen.getByTestId('weight-event_sentiment'), { target: { value: '0.10' } });

    fireEvent.click(screen.getByTestId('weight-apply'));

    expect(onApply).toHaveBeenCalledOnce();
    expect(onApply).toHaveBeenCalledWith({
      trend: 0.4,
      mean_reversion: 0.2,
      fundamental: 0.3,
      event_sentiment: 0.1,
    });
  });

  it('does not call onApply when sum is invalid even if clicked', () => {
    const onApply = vi.fn();
    render(<CustomWeightsPanel onApply={onApply} />);

    fireEvent.change(screen.getByTestId('weight-trend'), { target: { value: '0.90' } }); // sum 1.65
    // Button is disabled, but guard handleApply defensively too
    const applyBtn = screen.getByTestId('weight-apply') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(true);
    fireEvent.click(applyBtn);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('disables Apply and shows 应用中… while isApplying', () => {
    render(<CustomWeightsPanel onApply={vi.fn()} isApplying={true} />);

    const applyBtn = screen.getByTestId('weight-apply') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(true);
    expect(applyBtn.textContent).toContain('应用中');
  });

  it('renders errorMessage from parent', () => {
    render(<CustomWeightsPanel onApply={vi.fn()} errorMessage="HTTP 422: 权重之和必须为 1.0" />);

    expect(screen.getByTestId('weight-error').textContent).toContain('HTTP 422');
  });
});
