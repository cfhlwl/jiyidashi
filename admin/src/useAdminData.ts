import { useCallback, useEffect, useRef, useState } from 'react'

export function useAdminData<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[],
) {
  const generation = useRef(0)
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    generation.current += 1
    const current = generation.current
    setLoading(true)
    setError(null)
    try {
      const value = await loader()
      if (generation.current !== current) return
      setData(value)
    } catch (err) {
      if (generation.current !== current) return
      setError(err instanceof Error ? err.message : '页面暂时无法加载')
    } finally {
      if (generation.current === current) setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    void reload()
    return () => {
      generation.current += 1
    }
  }, [reload])

  return { data, loading, error, reload, setData }
}
