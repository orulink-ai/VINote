import { create } from 'zustand'
import { apiJson } from '../lib/api'

export interface TeamMemberRecord {
  id: string
  userId: string
  email: string
  role: 'owner' | 'admin' | 'member'
  joinedAt: string
}

export interface TeamRecord {
  id: string
  name: string
  ownerId: string
  currentUserRole: 'owner' | 'admin' | 'member'
  memberCount: number
  createdAt: string
  updatedAt: string
  members: TeamMemberRecord[]
}

export type WorkspaceSelection =
  | { scope: 'personal' }
  | { scope: 'team'; teamId: string }

type TeamRow = {
  id: string
  name: string
  owner_id: string
  current_user_role: 'owner' | 'admin' | 'member'
  member_count: number
  created_at: string
  updated_at: string
  members: Array<{
    id: string
    user_id: string
    email: string
    role: 'owner' | 'admin' | 'member'
    joined_at: string
  }>
}

interface TeamState {
  teams: TeamRecord[]
  currentWorkspace: WorkspaceSelection
  loading: boolean
  initialized: boolean
  error: string
  loadTeams: () => Promise<void>
  createTeam: (name: string) => Promise<TeamRecord | null>
  addMember: (teamId: string, email: string) => Promise<TeamRecord | null>
  removeMember: (teamId: string, memberId: string) => Promise<TeamRecord | null>
  deleteTeam: (teamId: string) => Promise<boolean>
  selectPersonalWorkspace: () => void
  selectTeamWorkspace: (teamId: string) => void
  reset: () => void
}

const initialState = {
  teams: [] as TeamRecord[],
  currentWorkspace: { scope: 'personal' } as WorkspaceSelection,
  loading: false,
  initialized: false,
  error: '',
}

const mapTeam = (row: TeamRow): TeamRecord => ({
  id: row.id,
  name: row.name,
  ownerId: row.owner_id,
  currentUserRole: row.current_user_role,
  memberCount: row.member_count,
  createdAt: row.created_at,
  updatedAt: row.updated_at,
  members: row.members.map((member) => ({
    id: member.id,
    userId: member.user_id,
    email: member.email,
    role: member.role,
    joinedAt: member.joined_at,
  })),
})

function ensureValidWorkspace(teams: TeamRecord[], currentWorkspace: WorkspaceSelection): WorkspaceSelection {
  if (currentWorkspace.scope === 'team') {
    const exists = teams.some((team) => team.id === currentWorkspace.teamId)
    if (exists) {
      return currentWorkspace
    }
  }
  return { scope: 'personal' }
}

function replaceTeam(teams: TeamRecord[], nextTeam: TeamRecord) {
  const existing = teams.some((team) => team.id === nextTeam.id)
  if (!existing) {
    return [...teams, nextTeam]
  }
  return teams.map((team) => (team.id === nextTeam.id ? nextTeam : team))
}

export function getWorkspaceLabel(
  workspace: WorkspaceSelection,
  teams: TeamRecord[],
  fallbackPersonal: string,
) {
  if (workspace.scope === 'personal') {
    return fallbackPersonal
  }
  return teams.find((team) => team.id === workspace.teamId)?.name || fallbackPersonal
}

export const useTeamStore = create<TeamState>((set) => ({
  ...initialState,
  loadTeams: async () => {
    set({ loading: true, error: '' })
    try {
      const data = await apiJson<TeamRow[]>('/api/teams')
      const teams = data.map(mapTeam)
      set((state) => ({
        teams,
        currentWorkspace: ensureValidWorkspace(teams, state.currentWorkspace),
        loading: false,
        initialized: true,
        error: '',
      }))
    } catch (error) {
      set({
        loading: false,
        initialized: true,
        error: error instanceof Error ? error.message : 'Failed to load teams',
      })
    }
  },
  createTeam: async (name) => {
    try {
      const data = await apiJson<TeamRow>('/api/teams', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      })
      const team = mapTeam(data)
      set((state) => ({
        teams: replaceTeam(state.teams, team),
        currentWorkspace: { scope: 'team', teamId: team.id },
        initialized: true,
        error: '',
      }))
      return team
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to create team' })
      return null
    }
  },
  addMember: async (teamId, email) => {
    try {
      const data = await apiJson<TeamRow>(`/api/teams/${teamId}/members`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })
      const team = mapTeam(data)
      set((state) => ({
        teams: replaceTeam(state.teams, team),
        currentWorkspace: ensureValidWorkspace(replaceTeam(state.teams, team), state.currentWorkspace),
        initialized: true,
        error: '',
      }))
      return team
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to add member' })
      return null
    }
  },
  removeMember: async (teamId, memberId) => {
    try {
      await apiJson<TeamRow>(`/api/teams/${teamId}/members/${memberId}`, {
        method: 'DELETE',
      })
      const data = await apiJson<TeamRow[]>('/api/teams')
      const teams = data.map(mapTeam)
      set((state) => ({
        teams,
        currentWorkspace: ensureValidWorkspace(teams, state.currentWorkspace),
        initialized: true,
        error: '',
      }))
      return teams.find((team) => team.id === teamId) ?? null
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to remove member' })
      return null
    }
  },
  deleteTeam: async (teamId) => {
    try {
      await apiJson<void>(`/api/teams/${teamId}`, { method: 'DELETE' })
      set((state) => ({
        teams: state.teams.filter((team) => team.id !== teamId),
        currentWorkspace: state.currentWorkspace.scope === 'team' && state.currentWorkspace.teamId === teamId
          ? { scope: 'personal' }
          : state.currentWorkspace,
        initialized: true,
        error: '',
      }))
      return true
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to delete team' })
      return false
    }
  },
  selectPersonalWorkspace: () => set({ currentWorkspace: { scope: 'personal' } }),
  selectTeamWorkspace: (teamId) => set((state) => ({
    currentWorkspace: ensureValidWorkspace(state.teams, { scope: 'team', teamId }),
  })),
  reset: () => set(initialState),
}))
