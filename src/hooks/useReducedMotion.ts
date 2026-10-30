import { useEffect, useState } from 'react';

export function useReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setPrefersReduced(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return prefersReduced;
}

export function useShouldUseStatic3DFallback(): boolean {
  const reduced = useReducedMotion();
  const [isMobileOrLowPower, setIsMobileOrLowPower] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const check = () => {
      const mobile = window.innerWidth < 640;
      const lowCores = typeof navigator !== 'undefined' && navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2;
      setIsMobileOrLowPower(Boolean(mobile || lowCores));
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  return reduced || isMobileOrLowPower;
}

