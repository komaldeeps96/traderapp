import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { onTabListKey } from './tabs';

const IDS = ['chart', 'financials', 'metrics'] as const;

function Strip() {
  const [tab, setTab] = useState<(typeof IDS)[number]>('chart');
  return (
    <div role="tablist" onKeyDown={(event) => onTabListKey(event, IDS, tab, setTab)}>
      {IDS.map((id) => (
        <button key={id} role="tab" aria-selected={tab === id} tabIndex={tab === id ? 0 : -1}>
          {id}
        </button>
      ))}
    </div>
  );
}

function selected(): string | null {
  return screen.getByRole('tab', { selected: true }).textContent;
}

describe('onTabListKey', () => {
  it('steps right and left, wrapping at both ends', () => {
    render(<Strip />);
    const strip = screen.getByRole('tablist');
    fireEvent.keyDown(strip, { key: 'ArrowRight' });
    expect(selected()).toBe('financials');
    fireEvent.keyDown(strip, { key: 'ArrowLeft' });
    fireEvent.keyDown(strip, { key: 'ArrowLeft' });
    expect(selected()).toBe('metrics');
  });

  it('jumps to either end', () => {
    render(<Strip />);
    const strip = screen.getByRole('tablist');
    fireEvent.keyDown(strip, { key: 'End' });
    expect(selected()).toBe('metrics');
    fireEvent.keyDown(strip, { key: 'Home' });
    expect(selected()).toBe('chart');
  });

  it('moves focus with the selection', () => {
    render(<Strip />);
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' });
    expect(document.activeElement?.textContent).toBe('financials');
  });

  it('leaves every other key alone', () => {
    render(<Strip />);
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'a' });
    expect(selected()).toBe('chart');
  });
});
