import { useEffect, useMemo, useState } from 'react'
import { Building2, Check, Plus, Trash2, UserPlus, Users } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Alert, AlertDescription } from '../components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '../components/ui/alert-dialog'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '../components/ui/empty'
import { Skeleton } from '../components/ui/skeleton'
import { useI18n } from '../lib/i18n'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'

export function Team() {
  const { locale } = useI18n()
  const isZh = locale.startsWith('zh')
  const {
    teams,
    currentWorkspace,
    loading,
    error,
    loadTeams,
    createTeam,
    addMember,
    removeMember,
    deleteTeam,
    selectPersonalWorkspace,
    selectTeamWorkspace,
  } = useTeamStore()
  const [teamName, setTeamName] = useState('')
  const [memberEmail, setMemberEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void loadTeams()
  }, [loadTeams])

  const activeTeam = useMemo(() => {
    if (currentWorkspace.scope !== 'team') {
      return teams[0] ?? null
    }
    return teams.find((team) => team.id === currentWorkspace.teamId) ?? null
  }, [currentWorkspace, teams])

  const workspaceLabel = getWorkspaceLabel(currentWorkspace, teams, isZh ? '个人空间' : 'Personal workspace')

  const handleCreateTeam = async () => {
    if (!teamName.trim()) {
      return
    }
    setSubmitting(true)
    await createTeam(teamName)
    setTeamName('')
    setSubmitting(false)
  }

  const handleAddMember = async () => {
    if (!activeTeam || !memberEmail.trim()) {
      return
    }
    setSubmitting(true)
    const updated = await addMember(activeTeam.id, memberEmail)
    if (updated) {
      setMemberEmail('')
    }
    setSubmitting(false)
  }

  const handleRemoveMember = async (memberId: string) => {
    if (!activeTeam) {
      return
    }
    setSubmitting(true)
    await removeMember(activeTeam.id, memberId)
    setSubmitting(false)
  }

  const handleDeleteTeam = async () => {
    if (!activeTeam) return
    setSubmitting(true)
    await deleteTeam(activeTeam.id)
    setSubmitting(false)
  }

  return (
    <div className="mx-auto grid max-w-[1180px] gap-7 px-6 py-8 lg:px-8">
      <section className="motion-rise">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="grid gap-2">
            <Badge variant="secondary"><Building2 />{isZh ? '团队空间' : 'Team workspace'}</Badge>
            <h2 className="text-3xl font-semibold tracking-[-0.03em]">{isZh ? '团队与成员' : 'Teams and members'}</h2>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              {isZh
                ? `当前工作区：${workspaceLabel}。团队笔记只会出现在对应团队的工作区里，个人笔记仍保留在个人空间。`
                : `Current workspace: ${workspaceLabel}. Team notes stay inside their team workspace, while personal notes remain in your personal workspace.`}
            </p>
          </div>

          <div className="flex flex-wrap gap-2 rounded-xl border bg-card p-1 shadow-sm">
            <Button
              type="button"
              onClick={() => selectPersonalWorkspace()}
              variant={currentWorkspace.scope === 'personal' ? 'default' : 'outline'}
            >
              {currentWorkspace.scope === 'personal' && <Check className="h-4 w-4" />}{isZh ? '个人空间' : 'Personal workspace'}
            </Button>
            {activeTeam ? (
              <Button
                type="button"
                onClick={() => selectTeamWorkspace(activeTeam.id)}
                variant={currentWorkspace.scope === 'team' && currentWorkspace.teamId === activeTeam.id ? 'default' : 'outline'}
              >
                {isZh ? '切到当前团队' : 'Use selected team'}
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <section className="motion-rise grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]" style={{ animationDelay: '70ms' }}>
        <div className="grid content-start gap-4">
          <section className="interactive-card grid gap-4 rounded-2xl border bg-card p-5 shadow-sm">
            <header><h3 className="flex items-center gap-2 font-semibold"><Plus className="size-4" />{isZh ? '新建共享空间' : 'Create a shared space'}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{isZh ? '为一个项目或小组创建独立空间。' : 'Create a dedicated space for a project or group.'}</p></header>
            <div className="grid gap-3">
              <Input
                value={teamName}
                onChange={(event) => setTeamName(event.target.value)}
                className="h-11"
                placeholder={isZh ? '空间名称' : 'Space name'}
              />
              <Button
                type="button"
                onClick={() => void handleCreateTeam()}
                disabled={!teamName.trim() || submitting}
                className="w-full rounded-xl"
              >
                {submitting ? (isZh ? '处理中...' : 'Working...') : (isZh ? '创建并切换' : 'Create and switch')}
              </Button>
            </div>
          </section>

          <section className="rounded-2xl border bg-card p-3 shadow-sm">
            <h3 className="px-2 pb-3 pt-1 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{isZh ? '你的空间' : 'Your spaces'}</h3>
            <div className="grid gap-2">
              {loading ? <><Skeleton className="h-16" /><Skeleton className="h-16" /></> : null}
              {teams.map((team) => (
                <Button
                  key={team.id}
                  type="button"
                  onClick={() => selectTeamWorkspace(team.id)}
                  variant={currentWorkspace.scope === 'team' && currentWorkspace.teamId === team.id ? 'secondary' : 'ghost'}
                  className="h-auto w-full justify-between rounded-xl border-0 px-3 py-3 text-left"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium">{team.name}</div>
                      <div className="mt-1 text-xs font-normal text-muted-foreground">
                        {team.memberCount} {isZh ? '位成员' : team.memberCount === 1 ? 'member' : 'members'}
                      </div>
                    </div>
                    <span className="size-2 rounded-full bg-foreground/25" />
                  </div>
                </Button>
              ))}
              {!loading && teams.length === 0 ? (
                <Empty><EmptyHeader><EmptyMedia variant="icon"><Users /></EmptyMedia><EmptyTitle>{isZh ? '还没有团队' : 'No teams yet'}</EmptyTitle><EmptyDescription>{isZh ? '创建团队后即可共享笔记。' : 'Create one to start saving shared notes.'}</EmptyDescription></EmptyHeader></Empty>
              ) : null}
            </div>
          </section>
        </div>

        <section className="min-h-[480px] overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b px-6 py-5">
            <div><h3 className="flex items-center gap-2 text-lg font-semibold"><UserPlus className="size-5" />{activeTeam ? activeTeam.name : (isZh ? '成员与共享' : 'Members and sharing')}</h3>{activeTeam ? <p className="mt-1 text-sm text-muted-foreground">{activeTeam.memberCount} {isZh ? '位成员可访问此空间' : 'members can access this space'}</p> : null}</div>
            {activeTeam?.currentUserRole === 'owner' ? (
              <AlertDialog>
                <AlertDialogTrigger asChild><Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive"><Trash2 />{isZh ? '删除团队' : 'Delete team'}</Button></AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>{isZh ? `删除“${activeTeam.name}”？` : `Delete “${activeTeam.name}”?`}</AlertDialogTitle>
                    <AlertDialogDescription>{isZh ? '团队空间和成员关系会被删除。团队里的笔记不会丢失，会回到各自创建者的个人空间。此操作无法撤销。' : 'The team space and memberships will be deleted. Team notes are preserved in each creator’s personal workspace. This action cannot be undone.'}</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter><AlertDialogCancel>{isZh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction onClick={() => void handleDeleteTeam()} disabled={submitting} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">{isZh ? '确认删除团队' : 'Delete team'}</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            ) : null}
          </div>
          {activeTeam ? (
            <>
              <p className="px-6 pt-5 text-sm leading-6 text-muted-foreground">
                {isZh
                  ? `当前选中团队：${activeTeam.name}。把已有账号通过邮箱加入团队后，他们就能看到该团队的团队笔记。`
                  : `Selected team: ${activeTeam.name}. Add existing users by email so they can access notes saved inside this team workspace.`}
              </p>

              <div className="mx-6 mt-4 flex flex-col gap-3 rounded-xl bg-muted/35 p-3 md:flex-row">
                <Input
                  value={memberEmail}
                  onChange={(event) => setMemberEmail(event.target.value)}
                  placeholder={isZh ? '输入成员邮箱' : 'Enter member email'}
                  className="h-10 flex-1 border-0 bg-background shadow-sm"
                />
                <Button
                  type="button"
                  onClick={() => void handleAddMember()}
                  disabled={!memberEmail.trim() || submitting}
                >
                  {isZh ? '添加成员' : 'Add member'}
                </Button>
              </div>

              <div className="mt-5 divide-y border-t">
                {activeTeam.members.map((member) => (
                  <div
                    key={member.id}
                    className="flex flex-col gap-3 px-6 py-4 transition-colors hover:bg-muted/20 md:flex-row md:items-center md:justify-between"
                  >
                    <div>
                      <div className="font-medium">{member.email}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {member.role === 'owner' ? (isZh ? '拥有者' : 'Owner') : (isZh ? '成员' : 'Member')} · {new Date(member.joinedAt).toLocaleString(locale)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {member.role !== 'owner' ? (
                        <AlertDialog><AlertDialogTrigger asChild><Button variant="destructive" size="sm" disabled={submitting}>{isZh ? '移除' : 'Remove'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{isZh ? '移除此成员？' : 'Remove this member?'}</AlertDialogTitle><AlertDialogDescription>{isZh ? '该成员将无法继续访问此团队中的共享笔记。' : 'They will lose access to notes in this team workspace.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{isZh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction onClick={() => void handleRemoveMember(member.id)}>{isZh ? '确认移除' : 'Remove'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
                      ) : (
                        <Badge variant="secondary">{isZh ? '拥有者' : 'Owner'}</Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <Empty><EmptyHeader><EmptyMedia variant="icon"><UserPlus /></EmptyMedia><EmptyTitle>{isZh ? '选择一个团队' : 'Select a team'}</EmptyTitle><EmptyDescription>{isZh ? '选择现有团队或先创建一个团队。' : 'Choose an existing team or create one first.'}</EmptyDescription></EmptyHeader></Empty>
          )}

          {error ? (
            <Alert variant="destructive" className="mt-4"><AlertDescription>{error}</AlertDescription></Alert>
          ) : null}
        </section>
      </section>
    </div>
  )
}
