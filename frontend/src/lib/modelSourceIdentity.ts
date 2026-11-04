// No store imports: auth publishes only after its Zustand store exists.
// This also observes synchronous A -> B -> A transitions between React renders.
// Account identity is not a model connection: VINote uses one fixed deployment.
let epoch = 0
let owner: string | undefined
const listeners = new Set<() => void>()

export function setModelSourceOwner(nextOwner: string | undefined) {
  if (nextOwner === owner) return
  owner = nextOwner
  epoch++
  listeners.forEach(listener => listener())
}

export function onModelSourceIdentityChange(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function modelSourceScope() {
  const started = epoch
  const identity = owner
  return () => epoch === started && owner === identity
}
