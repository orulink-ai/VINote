import { useEffect, useMemo, useState } from 'react'
import { Building2, Check, Plus, UserPlus, Users } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
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

  return (
    <div className="mx-auto max-w-[1380px] grid gap-6 p-6 lg:p-8">
      <section className="rounded-[28px] border border-border bg-gradient-to-br from-card to-muted/35 p-7">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="grid gap-2">
            <Badge variant="secondary" className="gap-1.5"><Building2 className="h-3.5 w-3.5" />{isZh ? '团队空间' : 'Team workspace'}</Badge>
            <h2 className="text-3xl font-semibold tracking-tight">{isZh ? '成员、空间和共享笔记' : 'Members, spaces and shared notes'}</h2>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              {isZh
                ? `当前工作区：${workspaceLabel}。团队笔记只会出现在对应团队的工作区里，个人笔记仍保留在个人空间。`
                : `Current workspace: ${workspaceLabel}. Team notes stay inside their team workspace, while personal notes remain in your personal workspace.`}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
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

      <section className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <div className="grid gap-6">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Plus className="h-4 w-4 text-primary" />{isZh ? '创建团队' : 'Create a team'}</CardTitle><CardDescription>{isZh ? '创建后自动切换到新的共享空间。' : 'Switch to the shared space after creation.'}</CardDescription></CardHeader>
            <CardContent className="grid gap-3">
              <Input
                value={teamName}
                onChange={(event) => setTeamName(event.target.value)}
                placeholder={isZh ? '例如：产品组 / 内容团队' : 'Example: Product / Research / Content'}
              />
              <Button
                type="button"
                onClick={() => void handleCreateTeam()}
                disabled={!teamName.trim() || submitting}
                className="w-full"
              >
                {submitting ? (isZh ? '处理中...' : 'Working...') : (isZh ? '创建并切换' : 'Create and switch')}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Users className="h-4 w-4 text-primary" />{isZh ? '你的团队' : 'Your teams'}</CardTitle></CardHeader><CardContent>
            <div className="grid gap-2">
              {loading ? <><Skeleton className="h-16" /><Skeleton className="h-16" /></> : null}
              {teams.map((team) => (
                <Button
                  key={team.id}
                  type="button"
                  onClick={() => selectTeamWorkspace(team.id)}
                  variant={currentWorkspace.scope === 'team' && currentWorkspace.teamId === team.id ? 'secondary' : 'outline'}
                  className="h-auto w-full justify-between rounded-xl px-4 py-3 text-left"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium">{team.name}</div>
                      <div className="mt-1 text-xs font-normal text-muted-foreground">
                        {team.memberCount} {isZh ? '位成员' : team.memberCount === 1 ? 'member' : 'members'}
                      </div>
                    </div>
                    <Badge variant="outline">{team.currentUserRole}</Badge>
                  </div>
                </Button>
              ))}
              {!loading && teams.length === 0 ? (
                <Empty><EmptyHeader><EmptyMedia variant="icon"><Users /></EmptyMedia><EmptyTitle>{isZh ? '还没有团队' : 'No teams yet'}</EmptyTitle><EmptyDescription>{isZh ? '创建团队后即可共享笔记。' : 'Create one to start saving shared notes.'}</EmptyDescription></EmptyHeader></Empty>
              ) : null}
            </div>
            </CardContent>
          </Card>
        </div>

        <Card className="min-h-[520px]">
          <CardHeader><CardTitle className="flex items-center gap-2"><UserPlus className="h-5 w-5 text-primary" />{isZh ? '团队成员与访问权限' : 'Members and access'}</CardTitle></CardHeader><CardContent>
          {activeTeam ? (
            <>
              <p className="mt-1 text-sm text-muted-foreground">
                {isZh
                  ? `当前选中团队：${activeTeam.name}。把已有账号通过邮箱加入团队后，他们就能看到该团队的团队笔记。`
                  : `Selected team: ${activeTeam.name}. Add existing users by email so they can access notes saved inside this team workspace.`}
              </p>

              <div className="mt-4 flex flex-col gap-3 md:flex-row">
                <Input
                  value={memberEmail}
                  onChange={(event) => setMemberEmail(event.target.value)}
                  placeholder={isZh ? '输入成员邮箱' : 'Enter member email'}
                  className="flex-1"
                />
                <Button
                  type="button"
                  onClick={() => void handleAddMember()}
                  disabled={!memberEmail.trim() || submitting}
                >
                  {isZh ? '添加成员' : 'Add member'}
                </Button>
              </div>

              <div className="mt-6 grid gap-3">
                {activeTeam.members.map((member) => (
                  <div
                    key={member.id}
                    className="flex flex-col gap-3 rounded-xl border px-4 py-3 md:flex-row md:items-center md:justify-between"
                  >
                    <div>
                      <div className="font-medium">{member.email}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {member.role} · {new Date(member.joinedAt).toLocaleString(locale)}
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
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
