/**
 * The all-time high's eye. It is drawn from the info stream rather than from a
 * spec, so it has no entry in the per-timeframe defaults: toggled as `!undefined`
 * its first click did nothing, and a timeframe switch forgot it.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { ATH_LEVEL_ID } from './selectors';
import { useTerminalStore } from './useTerminalStore';

const INITIAL = useTerminalStore.getState();

beforeEach(() => {
  useTerminalStore.setState(INITIAL, true);
  useTerminalStore.getState().requestChart('RUN', '1m');
});

describe('the all-time-high eye', () => {
  it('hides the line on the first click', () => {
    useTerminalStore.getState().toggleIndicator(ATH_LEVEL_ID);
    expect(useTerminalStore.getState().visibility[ATH_LEVEL_ID]).toBe(false);
  });

  it('shows it again on the second', () => {
    useTerminalStore.getState().toggleIndicator(ATH_LEVEL_ID);
    useTerminalStore.getState().toggleIndicator(ATH_LEVEL_ID);
    expect(useTerminalStore.getState().visibility[ATH_LEVEL_ID]).toBe(true);
  });

  it('stays off across a timeframe switch', () => {
    useTerminalStore.getState().toggleIndicator(ATH_LEVEL_ID);
    useTerminalStore.getState().requestChart('RUN', '1d');
    expect(useTerminalStore.getState().visibility[ATH_LEVEL_ID]).toBe(false);
  });
});
