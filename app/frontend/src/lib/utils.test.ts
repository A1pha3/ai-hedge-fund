import { describe, expect, it } from 'vitest';

import { currencySymbolForMarket, currencySymbolForTicker, parseTickers } from './utils';

describe('currencySymbolForTicker', () => {
  it('returns ¥ for 6-digit A-share tickers', () => {
    expect(currencySymbolForTicker('000001')).toBe('¥');
    expect(currencySymbolForTicker('300118')).toBe('¥');
    expect(currencySymbolForTicker('600519')).toBe('¥');
  });

  it('returns $ for US equity tickers', () => {
    expect(currencySymbolForTicker('AAPL')).toBe('$');
    expect(currencySymbolForTicker('NVDA')).toBe('$');
    expect(currencySymbolForTicker('BRK.B')).toBe('$');
  });

  it('trims whitespace before matching', () => {
    expect(currencySymbolForTicker('  000001  ')).toBe('¥');
  });

  it('does not treat non-6-digit numeric strings as A-share', () => {
    expect(currencySymbolForTicker('12345')).toBe('$'); // 5 digits
    expect(currencySymbolForTicker('1234567')).toBe('$'); // 7 digits
  });

  it('returns $ for null / undefined / empty', () => {
    expect(currencySymbolForTicker(null)).toBe('$');
    expect(currencySymbolForTicker(undefined)).toBe('$');
    expect(currencySymbolForTicker('')).toBe('$');
  });

  it('returns $ for alphanumeric codes that contain digits but are not pure 6-digit', () => {
    expect(currencySymbolForTicker('00000A')).toBe('$');
    expect(currencySymbolForTicker('SH600519')).toBe('$');
  });
});

describe('currencySymbolForMarket', () => {
  it('returns ¥ for cn market (default, A-share-first project)', () => {
    expect(currencySymbolForMarket('cn')).toBe('¥');
    expect(currencySymbolForMarket()).toBe('¥');
  });

  it('returns $ for us market', () => {
    expect(currencySymbolForMarket('us')).toBe('$');
  });
});

describe('parseTickers (characterization)', () => {
  it('splits on English comma', () => {
    expect(parseTickers('AAPL,NVDA')).toEqual(['AAPL', 'NVDA']);
  });

  it('normalizes Chinese comma and trims', () => {
    expect(parseTickers('000001，300118 , 600519')).toEqual(['000001', '300118', '600519']);
  });

  it('returns empty array for falsy / non-string input', () => {
    expect(parseTickers('')).toEqual([]);
    // @ts-expect-error testing runtime guard
    expect(parseTickers(null)).toEqual([]);
  });
});
