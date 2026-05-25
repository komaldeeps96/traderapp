import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchIndicators } from '../services/httpClient';

export function useIndicatorConfig() {
  const [config, setConfig] = useState([]);
  const [visibility, setVisibility] = useState({});
  const configRef = useRef([]);
  const visibilityRef = useRef({});

  useEffect(() => {
    fetchIndicators()
      .then((cfg) => {
        const c = Array.isArray(cfg) ? cfg : [];
        setConfig(c);
        configRef.current = c;
        const defaults = getDefaults(c, '1m');
        setVisibility(defaults);
        visibilityRef.current = defaults;
      })
      .catch((err) => console.error('Failed to fetch indicators:', err));
  }, []);

  const setTimeframe = useCallback((newTf, oldTf) => {
    const stored = JSON.parse(localStorage.getItem('traderapp_visibility') || '{}');
    if (oldTf) {
      stored[oldTf] = { ...visibilityRef.current };
    }
    localStorage.setItem('traderapp_visibility', JSON.stringify(stored));
    const saved = stored[newTf] || {};
    const defaults = getDefaults(configRef.current, newTf);
    const v = { ...defaults, ...saved };
    setVisibility(v);
    visibilityRef.current = v;
  }, []);

  const toggleIndicator = useCallback((indId) => {
    setVisibility((prev) => {
      const next = { ...prev, [indId]: !prev[indId] };
      visibilityRef.current = next;
      return next;
    });
  }, []);

  return { config, visibility, configRef, visibilityRef, setTimeframe, toggleIndicator };
}

function getDefaults(config, tf) {
  const defs = {};
  for (const ind of config) {
    if (ind.timeframes && ind.timeframes[tf] !== undefined) {
      defs[ind.id] = ind.timeframes[tf].default_enabled ?? true;
    }
  }
  return defs;
}
