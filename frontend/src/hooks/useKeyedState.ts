import { useCallback, useState, type SetStateAction } from 'react';

/**
 * State that starts over whenever `key` changes — an open article when the
 * symbol switches. Derived during render, so the old value is never painted and
 * no effect has to chase it.
 */
export function useKeyedState<T>(key: string, initial: T): [T, (next: SetStateAction<T>) => void] {
  const [state, setState] = useState({ key, value: initial });
  const value = state.key === key ? state.value : initial;

  const set = useCallback(
    (next: SetStateAction<T>) =>
      setState((current) => {
        const base = current.key === key ? current.value : initial;
        return { key, value: typeof next === 'function' ? (next as (previous: T) => T)(base) : next };
      }),
    [key, initial],
  );

  return [value, set];
}
