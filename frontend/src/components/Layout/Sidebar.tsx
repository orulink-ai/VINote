import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, ChevronsLeftRight, FileText, Folder, Home, Mic, Video, Plus, Settings, Users } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { AppFooter } from './AppFooter'
import { useI18n } from '../../lib/i18n'
import { getWorkspaceLabel, useTeamStore } from '../../stores/teamStore'

interface FolderItem {
  id: string
  name: string
  children?: FolderItem[]
}

interface SidebarProps {
  collapsed: boolean
}

export function Sidebar({ collapsed }: SidebarProps) {
  const [folders] = useState<FolderItem[]>([])
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const navigate = useNavigate()
  const location = useLocation()
  const { copy, locale } = useI18n()
  const isZh = locale.startsWith('zh')
  const {
    teams,
    currentWorkspace,
    loadTeams,
    initialized,
    selectPersonalWorkspace,
    selectTeamWorkspace,
  } = useTeamStore()

  useEffect(() => {
    if (!initialized) {
      void loadTeams()
    }
  }, [initialized, loadTeams])

  const toggleFolder = (id: string) => {
    setExpandedFolders((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const navItems = [
    { path: '/', icon: Home, label: copy.sidebar.home },
    { path: '/meetings', icon: Mic, label: isZh ? '会议记录' : 'Meetings' },
    { path: '/generate', icon: Video, label: isZh ? '视频总结' : 'Video summary' },
    { path: '/notes', icon: FileText, label: copy.sidebar.notes },
    { path: '/team', icon: Users, label: copy.sidebar.team },
    { path: '/settings', icon: Settings, label: copy.sidebar.settings },
  ]

  return (
    <aside
      className={clsx(
        'relative flex h-full shrink-0 flex-col overflow-hidden border-r border-gray-200 bg-gray-50 transition-[width] duration-200 dark:border-gray-700 dark:bg-[#202020]',
        collapsed ? 'w-[72px]' : 'w-60'
      )}
    >
      <nav className="p-2 space-y-1">
        {navItems.map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            title={collapsed ? item.label : undefined}
            className={clsx(
              'w-full rounded-xl text-left transition-colors',
              collapsed ? 'flex h-11 items-center justify-center px-0' : 'flex items-center gap-2 px-3 py-2.5',
              location.pathname === item.path
                ? 'bg-primary-light/10 text-primary-light dark:bg-primary-dark/10 dark:text-primary-dark'
                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
            )}
          >
            <item.icon className={clsx('shrink-0', collapsed ? 'h-[18px] w-[18px]' : 'h-4 w-4')} />
            {collapsed ? null : <span className="text-sm">{item.label}</span>}
          </button>
        ))}
      </nav>

      <div className={clsx('min-h-0 flex-1 p-2', collapsed ? 'pb-24' : 'pb-32')}>
        {collapsed ? (
          <div className="flex h-full flex-col items-center gap-2 pt-3">
            <button
              type="button"
              onClick={() => selectPersonalWorkspace()}
              title={isZh ? '个人空间' : 'Personal workspace'}
              className={clsx(
                'inline-flex h-10 w-10 items-center justify-center rounded-xl transition-colors',
                currentWorkspace.scope === 'personal'
                  ? 'bg-primary-light/10 text-primary-light dark:bg-primary-dark/10 dark:text-primary-dark'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-[#2a2a2a] dark:hover:text-gray-100'
              )}
            >
              <Home className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => navigate('/team')}
              title={isZh ? '管理团队' : 'Manage teams'}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-[#2a2a2a] dark:hover:text-gray-100"
            >
              <ChevronsLeftRight className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="stealth-scroll h-full min-h-0 overflow-auto">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-gray-500">
                {copy.sidebar.workspace}
              </span>
              <button
                onClick={() => navigate('/team')}
                className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-200 hover:text-gray-700 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                title={isZh ? '管理团队' : 'Manage teams'}
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-1">
              <button
                type="button"
                onClick={() => selectPersonalWorkspace()}
                className={clsx(
                  'w-full rounded-xl px-3 py-2.5 text-left text-sm transition-colors',
                  currentWorkspace.scope === 'personal'
                    ? 'bg-primary-light/10 text-primary-light dark:bg-primary-dark/10 dark:text-primary-dark'
                    : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                )}
              >
                {isZh ? '个人空间' : 'Personal workspace'}
              </button>

              {teams.map((team) => (
                <button
                  key={team.id}
                  type="button"
                  onClick={() => selectTeamWorkspace(team.id)}
                  className={clsx(
                    'w-full rounded-xl px-3 py-2.5 text-left text-sm transition-colors',
                    currentWorkspace.scope === 'team' && currentWorkspace.teamId === team.id
                      ? 'bg-primary-light/10 text-primary-light dark:bg-primary-dark/10 dark:text-primary-dark'
                      : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                  )}
                >
                  <div className="truncate font-medium">{team.name}</div>
                  <div className="mt-0.5 text-xs text-gray-400">
                    {team.memberCount} {isZh ? '成员' : team.memberCount === 1 ? 'member' : 'members'}
                  </div>
                </button>
              ))}

              {folders.length === 0 ? (
                <p className="px-3 py-2 text-xs text-gray-400">
                  {getWorkspaceLabel(currentWorkspace, teams, isZh ? '个人空间' : 'Personal workspace')}
                </p>
              ) : (
                folders.map((folder) => (
                  <FolderItemComponent
                    key={folder.id}
                    folder={folder}
                    expanded={expandedFolders.has(folder.id)}
                    onToggle={() => toggleFolder(folder.id)}
                  />
                ))
              )}

              {teams.length === 0 ? (
                <p className="px-3 py-2 text-xs text-gray-400">{isZh ? '还没有团队。' : 'No teams yet.'}</p>
              ) : null}
            </div>
          </div>
        )}
      </div>

      <AppFooter placement="sidebar" collapsed={collapsed} />
    </aside>
  )
}

function FolderItemComponent({ folder, expanded, onToggle }: {
  folder: FolderItem
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-left hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
      >
        {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <Folder className="w-4 h-4 text-yellow-500" />
        <span className="text-sm truncate">{folder.name}</span>
      </button>
      {expanded && folder.children && (
        <div className="ml-4">
          {folder.children.map((child) => (
            <FolderItemComponent key={child.id} folder={child} expanded={false} onToggle={() => {}} />
          ))}
        </div>
      )}
    </div>
  )
}
