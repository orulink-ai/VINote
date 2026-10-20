// No store imports: auth publishes only after its Zustand store exists.
// This also observes synchronous A -> B -> A transitions between React renders.
let epoch = 0
let owner: string | undefined
const listeners = new Set<() => void>()

export function setModelConnectionOwner(nextOwner: string | undefined) {
  if (nextOwner === owner) return
  owner = nextOwner
  epoch++
  listeners.forEach(listener => listener())
}

export function onModelConnectionIdentityChange(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function modelConnectionScope() {
  const started = epoch
  const identity = owner
  return () => epoch === started && owner === identity
}
