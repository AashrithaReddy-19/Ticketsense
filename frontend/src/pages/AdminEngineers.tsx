import { useEffect, useState, type FormEvent } from "react";
import { api, type EngineerSummary } from "../api/client";
import { Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";

const LEVEL_LABEL: Record<string, string> = { none: "None", basic: "Basic", intermediate: "Intermediate", advanced: "Advanced", expert: "Expert" };

function SkillBadges({ engineer }: { engineer: EngineerSummary }) {
  if (engineer.skills?.length) {
    return <span className="skill-badge-row">{engineer.skills.map(skill => (
      <span className={`skill-badge${skill.is_primary ? " skill-badge-primary" : ""}`} key={skill.specialization} title={skill.skill_level ? `${LEVEL_LABEL[skill.skill_level] ?? skill.skill_level} level` : undefined}>
        {skill.specialization}{skill.skill_level ? ` · ${LEVEL_LABEL[skill.skill_level] ?? skill.skill_level}` : ""}
      </span>
    ))}</span>;
  }
  return <span>{engineer.specializations.join(", ") || "Not specified"}</span>;
}

export default function AdminEngineers(){
  const [engineers,setEngineers]=useState<EngineerSummary[]>([]); const [departments,setDepartments]=useState<Array<{id:string;name:string}>>([]); const [loading,setLoading]=useState(true); const [error,setError]=useState(""); const [open,setOpen]=useState(false); const [busy,setBusy]=useState(false);
  const [form,setForm]=useState({email:"",full_name:"",password:"",department_id:"",specializations:""});
  const [specializationFilter,setSpecializationFilter]=useState(""); const [availableOnly,setAvailableOnly]=useState(false);
  async function load(){setLoading(true);try{const [e,d]=await Promise.all([api.adminEngineers({specialization:specializationFilter||undefined,available_only:availableOnly||undefined}),api.adminDepartments()]);setEngineers(e);setDepartments(d);setError("")}catch(err){setError(err instanceof Error?err.message:"Unable to load engineers")}finally{setLoading(false)}}
  useEffect(()=>{load()},[specializationFilter,availableOnly]);
  async function create(e:FormEvent){e.preventDefault();setBusy(true);try{await api.createEngineer({...form,specializations:form.specializations.split(",").map(x=>x.trim()).filter(Boolean)});setOpen(false);setForm({email:"",full_name:"",password:"",department_id:"",specializations:""});await load()}catch(err){setError(err instanceof Error?err.message:"Unable to create engineer")}finally{setBusy(false)}}
  async function toggle(engineer:EngineerSummary){try{await api.updateEngineer(engineer.id,{is_active:!engineer.is_active});await load()}catch(err){setError(err instanceof Error?err.message:"Unable to update engineer")}}
  const departmentName=(id:string)=>departments.find(d=>d.id===id)?.name||"Not assigned";
  return <div className="content"><div className="page-title"><div><h1>Engineer management</h1><p>Manage department engineers, specializations and live ticket workload.</p></div><Button variant="primary" onClick={()=>setOpen(true)}>Add engineer</Button></div>
    <div className="filter-bar">
      <input placeholder="Filter by specialization (e.g. VPN, SAP)" value={specializationFilter} onChange={e=>setSpecializationFilter(e.target.value)} />
      <label className="ui-field-inline"><input type="checkbox" checked={availableOnly} onChange={e=>setAvailableOnly(e.target.checked)} /> Available only</label>
    </div>
    {loading?<Loading skeleton/>:error&&!engineers.length?<ErrorState message={error} onRetry={load}/>:engineers.length?<div className="panel ticket-list"><div className="list-head admin-engineer-row"><span>Engineer</span><span>Department</span><span>Specializations</span><span>Workload</span><span>Status</span></div>{engineers.map(engineer=><article className="list-row admin-engineer-row" key={engineer.id}><div><b>{engineer.full_name}</b><small>{engineer.email}</small></div><span>{departmentName(engineer.department_id)}</span><SkillBadges engineer={engineer} /><span>{engineer.active_tickets} active · {engineer.resolved_tickets} resolved</span><Button size="sm" variant={engineer.is_active?"outline":"primary"} onClick={()=>toggle(engineer)}>{engineer.is_active?"Deactivate":"Activate"}</Button></article>)}</div>:<Empty label="No department engineers match this filter."/>}
    <Modal open={open} onClose={()=>setOpen(false)} title="Add department engineer" footer={null}><form onSubmit={create} className="admin-engineer-form"><label className="ui-field"><span>Full name</span><input required value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></label><label className="ui-field"><span>Email</span><input type="email" required value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label><label className="ui-field"><span>Temporary password</span><input type="password" minLength={8} required value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></label><label className="ui-field"><span>Department</span><select required value={form.department_id} onChange={e=>setForm({...form,department_id:e.target.value})}><option value="">Select department</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label className="ui-field"><span>Specializations</span><input value={form.specializations} onChange={e=>setForm({...form,specializations:e.target.value})} placeholder="VPN, DNS, Network access"/><small>Separate multiple skills with commas.</small></label><div className="form-actions"><Button type="button" variant="outline" onClick={()=>setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy}>Create engineer</Button></div></form></Modal>
  </div>
}
