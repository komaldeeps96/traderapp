import { describe, expect, it } from 'vitest';

import type { QuoteMessage } from '@/types/protocol';

import { buildQuoteView, spreadTone } from './selectors';

function quote(bid: number, ask: number): QuoteMessage {
  return { type: 'quote', symbol: 'RUN', bid, ask, bs: 100, as: 100, t: 0 };
}

describe('spread tiers at their edges', () => {
  it.each([
    [3.0, 3.2],
    [1.0, 1.2],
    [0.8, 1.0],
    [12.35, 12.55],
  ])('a twenty-cent spread from %f to %f is the same tier at any price', (bid, ask) => {
    // In floats 3.20 - 3.00 is 0.20000000000000018 and 1.20 - 1.00 is
    // 0.19999999999999996: the same spread, coloured two ways.
    expect(buildQuoteView(quote(bid, ask))?.tone).toBe('ok');
  });

  it('reports the spread itself exactly', () => {
    expect(buildQuoteView(quote(3.0, 3.2))?.spread).toBe(0.2);
  });

  it.each([
    [0.1, 'tight'],
    [0.1001, 'ok'],
    [0.2, 'ok'],
    [0.2001, 'wide'],
    [0.5, 'wide'],
    [0.5001, 'untradeable'],
  ] as const)('%f is %s', (spread, tone) => {
    expect(spreadTone(spread)).toBe(tone);
  });
});
