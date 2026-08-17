import { useEffect, useRef, useState, type RefObject } from 'react'

/**
 * Custom hook for running animation frames with optional frame skipping.
 * @param callback - Function to call on each animation frame, receives current time in seconds
 * @param enabled - Whether the animation should run
 * @param frameSkip - Number of frames to skip between invocations (default 2 = ~20fps)
 */
export function useAnimationFrame(
  callback: (time: number) => void,
  enabled: boolean,
  frameSkip: number = 2
) {
  const callbackRef = useRef(callback)

  // Update callback ref on each render to avoid stale closures
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled) return

    let count = 0
    let animationId: number

    const animate = () => {
      if (count % (frameSkip + 1) === 0) {
        const time = Date.now() / 1000
        callbackRef.current(time)
      }
      count++
      animationId = requestAnimationFrame(animate)
    }

    animationId = requestAnimationFrame(animate)

    return () => {
      cancelAnimationFrame(animationId)
    }
  }, [enabled, frameSkip])
}

interface Dimensions {
  width: number
  height: number
}

/**
 * Custom hook for tracking graph canvas dimensions
 * Uses ResizeObserver to measure the actual container element
 */
export function useDimensions(containerRef: RefObject<HTMLElement | null>): Dimensions {
  const [dimensions, setDimensions] = useState<Dimensions>({
    width: 800,
    height: 600,
  })

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const updateDimensions = () => {
      setDimensions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    }

    // Initial measurement
    updateDimensions()

    // Use ResizeObserver for accurate container size tracking
    const resizeObserver = new ResizeObserver(updateDimensions)
    resizeObserver.observe(container)

    return () => resizeObserver.disconnect()
  }, [containerRef])

  return dimensions
}