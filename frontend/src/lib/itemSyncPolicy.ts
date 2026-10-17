/** Account-scoped choices. A choice never deletes a cloud copy or an original. */
export type ItemSyncMode = 'local' | 'sync';
export type ItemSyncPolicies = Record<string, ItemSyncMode>;
type IdentityState = {
  itemPolicies?: ItemSyncPolicies;
  mappings: Record<string, { key: string; revision: number }>;
  items: Array<{ key: string; revision?: number }>;
};

export function itemSyncReference(reference: string, state: IdentityState): string {
  return state.mappings[reference]?.key || reference;
}

export function itemSyncMode(reference: string, state: IdentityState): ItemSyncMode {
  const key = itemSyncReference(reference, state);
  const explicit = state.itemPolicies?.[key] ?? state.itemPolicies?.[reference];
  if (explicit) return explicit;
  // Existing acknowledged copies keep their original behavior. Merely assigning
  // an identity or retaining an unsent draft is not permission to upload it.
  return state.items.some(item => item.key === key && (item.revision ?? 0) > 0) ||
    Object.values(state.mappings).some(mapping => mapping.key === key && mapping.revision > 0)
    ? 'sync' : 'local';
}
