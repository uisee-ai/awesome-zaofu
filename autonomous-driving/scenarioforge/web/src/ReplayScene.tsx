import { useEffect, useRef } from 'react'
import * as THREE from 'three'

import type { ReplayFrame } from './types'

interface ReplaySceneProps {
  frame: ReplayFrame | undefined
}

export function ReplayScene({ frame }: ReplaySceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.OrthographicCamera | null>(null)
  const vehiclesRef = useRef<Map<string, THREE.Mesh>>(new Map())
  const eventMarkerRef = useRef<THREE.Mesh | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    try {
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.setSize(680, 360, false)
      renderer.setClearColor(0x07121c, 1)

      const scene = new THREE.Scene()
      const camera = new THREE.OrthographicCamera(-8, 8, 4.2, -4.2, 0.1, 100)
      camera.position.set(0, 0, 10)

      const grid = new THREE.GridHelper(20, 20, 0x365063, 0x1d3444)
      grid.rotation.x = Math.PI / 2
      scene.add(grid)

      const route = new THREE.Mesh(
        new THREE.PlaneGeometry(20, 3.5),
        new THREE.MeshBasicMaterial({ color: 0x162f3e }),
      )
      route.position.z = -0.01
      scene.add(route)

      const eventMarker = new THREE.Mesh(
        new THREE.ConeGeometry(0.18, 0.55, 4),
        new THREE.MeshBasicMaterial({ color: 0xff6b57 }),
      )
      eventMarker.rotation.z = Math.PI
      eventMarker.visible = false
      scene.add(eventMarker)
      eventMarkerRef.current = eventMarker
      rendererRef.current = renderer
      sceneRef.current = scene
      cameraRef.current = camera
      canvas.dataset.renderer = 'three-webgl'

      const render = () => renderer.render(scene, camera)
      render()
      const resize = () => {
        const width = Math.max(320, Math.floor(canvas.getBoundingClientRect().width))
        renderer.setSize(width, Math.floor(width * 0.529), false)
        render()
      }
      window.addEventListener('resize', resize)
      resize()
      return () => {
        window.removeEventListener('resize', resize)
        renderer.dispose()
        rendererRef.current = null
        sceneRef.current = null
        cameraRef.current = null
        vehiclesRef.current.clear()
        eventMarkerRef.current = null
      }
    } catch {
      canvas.dataset.renderer = 'three-unavailable'
      return undefined
    }
  }, [])

  useEffect(() => {
    const renderer = rendererRef.current
    const scene = sceneRef.current
    const camera = cameraRef.current
    if (!renderer || !scene || !camera || !frame) return
    const actors = frame.actors.length > 0 ? frame.actors : [{
      actor_id: 'ego', role: 'ego' as const, position: frame.position,
      speed_mps: frame.speed_km_h / 3.6, heading: frame.heading, state: 'active',
    }]
    const visible = new Set(actors.map((actor) => actor.actor_id))
    for (const [actorId, vehicle] of vehiclesRef.current) vehicle.visible = visible.has(actorId)
    for (const actor of actors) {
      let vehicle = vehiclesRef.current.get(actor.actor_id)
      if (!vehicle) {
        vehicle = new THREE.Mesh(
          new THREE.BoxGeometry(0.85, 0.42, 0.12),
          new THREE.MeshBasicMaterial({ color: actor.role === 'ego' ? 0xffb547 : 0x62c5ff }),
        )
        vehiclesRef.current.set(actor.actor_id, vehicle)
        scene.add(vehicle)
      }
      vehicle.visible = true
      vehicle.position.set(actor.position[0] - 10, actor.position[1] - 3.5, 0.1)
      vehicle.rotation.z = actor.heading
    }
    const eventMarker = eventMarkerRef.current
    if (eventMarker) {
      const receipt = frame.event_receipts[0]
      const target = actors.find((actor) => actor.actor_id === receipt?.target_actor_id)
      eventMarker.visible = Boolean(target)
      if (target) eventMarker.position.set(target.position[0] - 10, target.position[1] - 2.75, 0.1)
    }
    renderer.render(scene, camera)
  }, [frame])

  return (
    <canvas
      ref={canvasRef}
      data-testid="replay-canvas"
      data-renderer="three-pending"
      aria-label="Three.js exact replay viewport"
      width="680"
      height="360"
    />
  )
}
