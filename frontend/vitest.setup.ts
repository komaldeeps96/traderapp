import '@testing-library/jest-dom/vitest';

// This jsdom build ships without Web Storage. The app already treats storage
// as optional — every access is guarded, so preferences simply stop persisting
// — but the persistence tests need somewhere real to write.
if (!globalThis.localStorage) {
  class MemoryStorage implements Storage {
    private entries = new Map<string, string>();

    get length(): number {
      return this.entries.size;
    }

    clear(): void {
      this.entries.clear();
    }

    getItem(key: string): string | null {
      return this.entries.get(key) ?? null;
    }

    key(index: number): string | null {
      return [...this.entries.keys()][index] ?? null;
    }

    removeItem(key: string): void {
      this.entries.delete(key);
    }

    setItem(key: string, value: string): void {
      this.entries.set(key, String(value));
    }
  }

  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'localStorage', { value: storage, configurable: true });
  }
}

// jsdom implements neither of these, and both are used by the chart host.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!globalThis.matchMedia) {
  globalThis.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}
