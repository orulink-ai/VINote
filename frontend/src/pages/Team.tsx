import { useEffect, useMemo, useState } from 'react'
import { PageReturn } from '@/components/Layout/PageReturn'
import { Check, ChevronRight, Plus, Trash2, Users } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Alert, AlertDescription } from '../components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '../components/ui/alert-dialog'
import { Skeleton } from '../components/ui/skeleton'
import { useI18n } from '../lib/i18n'
import { useTeamStore } from '../stores/teamStore'

export function Team() {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const { teams, currentWorkspace, loading, error, loadTeams, createTeam, addMember, removeMember, deleteTeam, selectPersonalWorkspace, selectTeamWorkspace } = useTeamStore()
  const [teamName, setTeamName] = useState('')
  const [memberEmail, setMemberEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  useEffect(() => { void loadTeams() }, [loadTeams])
  const activeTeam = useMemo(() => currentWorkspace.scope === 'team' ? teams.find(team => team.id === currentWorkspace.teamId) ?? null : null, [currentWorkspace, teams])
  const canManage = activeTeam?.currentUserRole === 'owner' || activeTeam?.currentUserRole === 'admin'
  const runAction = async (action: () => Promise<unknown>) => {
    setSubmitting(true)
    setActionError(null)
    try { await action() } catch (failure) { setActionError(failure instanceof Error ? failure.message : (zh ? '操作未完成，请重试。' : 'Could not complete this action. Try again.')) } finally { setSubmitting(false) }
  }
  return <div className="mx-auto w-full max-w-[720px] px-6 py-8 md:px-10">
    <div className="mb-4"><PageReturn to="/settings?tab=spaces" label="返回空间与协作" /></div>
    <header className="mb-7"><h1 className="text-2xl font-medium tracking-tight">{zh ? '空间与成员' : 'Spaces and members'}</h1><p className="mt-2 text-sm leading-6 text-muted-foreground">{zh ? '个人记录保存在个人工作区。团队空间用于共享笔记与会议资料。' : 'Keep personal recordings in your workspace and share notes in a team space.'}</p></header>
    {(error || actionError) && <Alert variant="destructive" className="mb-5"><AlertDescription className="flex items-center justify-between gap-3"><span>{actionError || error}</span>{error && <Button size="sm" variant="outline" disabled={loading} onClick={() => void loadTeams()}>{zh ? '重新加载' : 'Reload'}</Button>}</AlertDescription></Alert>}
    <section className="border-b pb-6">
      <h2 className="mb-3 text-sm font-medium">{zh ? '工作区' : 'Workspaces'}</h2>
      <button type="button" onClick={selectPersonalWorkspace} className="flex w-full items-center gap-3 rounded-md px-2 py-3 text-left hover:bg-muted/50"><span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs">{zh ? '个' : 'P'}</span><span className="flex-1 text-sm">{zh ? '个人工作区' : 'Personal workspace'}</span>{currentWorkspace.scope === 'personal' ? <Check className="size-4" /> : <ChevronRight className="size-4 text-muted-foreground" />}</button>
      {loading ? <Skeleton className="mt-2 h-12" /> : teams.map(team => <button type="button" key={team.id} onClick={() => selectTeamWorkspace(team.id)} className="flex w-full items-center gap-3 rounded-md px-2 py-3 text-left hover:bg-muted/50"><Users className="mx-1 size-5 text-muted-foreground" /><span className="flex-1"><span className="block text-sm">{team.name}</span><span className="text-xs text-muted-foreground">{team.memberCount} {zh ? '位成员' : 'members'}</span></span>{activeTeam?.id === team.id ? <Check className="size-4" /> : <ChevronRight className="size-4 text-muted-foreground" />}</button>)}
      {!loading && !teams.length && <p className="px-2 py-3 text-xs leading-5 text-muted-foreground">{zh ? '尚未加入团队。新建一个空间后，可通过邮箱添加已有 VINote 账号。' : 'No team spaces yet. Create one and add existing VINote users by email.'}</p>}
      {creating ? <form className="mt-4 flex gap-2" onSubmit={event => { event.preventDefault(); if (teamName.trim()) void runAction(async () => { const created = await createTeam(teamName.trim()); if (created) { setTeamName(''); setCreating(false) } }) }}><Input autoFocus aria-label={zh ? '空间名称' : 'Space name'} placeholder={zh ? '空间名称' : 'Space name'} value={teamName} onChange={event => setTeamName(event.target.value)} disabled={submitting} /><Button disabled={!teamName.trim() || submitting}>{submitting ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建' : 'Create')}</Button><Button type="button" variant="ghost" disabled={submitting} onClick={() => setCreating(false)}>{zh ? '取消' : 'Cancel'}</Button></form> : <Button variant="outline" size="sm" className="mt-3" onClick={() => setCreating(true)}><Plus className="size-4" />{zh ? '新建团队空间' : 'New team space'}</Button>}
    </section>
    {activeTeam && <section className="border-b py-6">
      <header className="mb-4"><h2 className="text-sm font-medium">{activeTeam.name} · {zh ? '成员' : 'Members'}</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">{zh ? '成员可访问保存在这个团队空间的笔记。' : 'Members can access notes saved in this team space.'}</p></header>
      {canManage && <form className="mb-4 flex gap-2" onSubmit={event => { event.preventDefault(); if (memberEmail.trim()) void runAction(async () => { const updated = await addMember(activeTeam.id, memberEmail.trim()); if (updated) setMemberEmail('') }) }}><Input type="email" aria-label={zh ? '成员邮箱' : 'Member email'} placeholder={zh ? '输入已有账号的邮箱' : 'Existing user email'} value={memberEmail} onChange={event => setMemberEmail(event.target.value)} disabled={submitting} /><Button disabled={!memberEmail.trim() || submitting}>{zh ? '添加成员' : 'Add member'}</Button></form>}
      <div className="divide-y">{activeTeam.members.map(member => <div key={member.id} className="flex items-center gap-3 py-3"><span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs">{member.email[0]?.toUpperCase()}</span><div className="min-w-0 flex-1"><p className="truncate text-sm">{member.email}</p><p className="mt-1 text-xs text-muted-foreground">{member.role === 'owner' ? (zh ? '拥有者' : 'Owner') : (zh ? '成员' : 'Member')}</p></div>{canManage && member.role !== 'owner' && <AlertDialog><AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={submitting}>{zh ? '移除' : 'Remove'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '移除此成员？' : 'Remove this member?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '该成员将无法继续访问此团队中的共享笔记。' : 'They will lose access to notes in this team space.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction onClick={() => void runAction(() => removeMember(activeTeam.id, member.id))}>{zh ? '确认移除' : 'Remove'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}</div>)}</div>
      {activeTeam.currentUserRole === 'owner' && <div className="mt-5 border-t pt-4"><AlertDialog><AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={submitting} className="text-destructive"><Trash2 className="size-4" />{zh ? '删除团队空间' : 'Delete team space'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? `删除“${activeTeam.name}”？` : `Delete “${activeTeam.name}”?`}</AlertDialogTitle><AlertDialogDescription>{zh ? '团队空间和成员关系会被删除。团队里的笔记会回到各自创建者的个人空间。此操作无法撤销。' : 'The space and memberships will be deleted. Notes return to their creators’ personal workspaces. This cannot be undone.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction disabled={submitting} className="bg-destructive text-destructive-foreground" onClick={() => void runAction(() => deleteTeam(activeTeam.id))}>{zh ? '确认删除团队' : 'Delete team'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></div>}
    </section>}
  </div>
}
