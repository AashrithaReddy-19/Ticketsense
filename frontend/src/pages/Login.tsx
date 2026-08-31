import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const accounts=["customer@demo.com","agent@demo.com","reviewer@demo.com","kbmanager@demo.com","teamlead@demo.com","sysadmin@demo.com","auditor@demo.com"];
const landing:Record<string,string>={customer:"/portal",support_agent:"/agent",reviewer:"/review",knowledge_manager:"/knowledge",team_lead:"/operations",system_admin:"/admin",auditor:"/audit"};

export default function Login(){
  const {user,login}=useAuth(); const nav=useNavigate(); const location=useLocation();
  const [email,setEmail]=useState("agent@demo.com"); const [password,setPassword]=useState("Demo@123");
  const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  if(user)return <Navigate to={landing[user.role]||"/dashboard"} replace/>;
  async function submit(e:FormEvent){e.preventDefault();setBusy(true);setError("");try{const current=await login(email,password);nav((location.state as {from?:string})?.from||landing[current.role]||"/dashboard",{replace:true})}catch(err){setError(err instanceof Error?err.message:"Unable to sign in")}finally{setBusy(false)}}
  return <main className="login-page"><form className="login-card" onSubmit={submit}><div className="login-brand"><div className="brandmark">T</div><div><b>Ticket<span>Sense</span></b><small>AI SUPPORT INTELLIGENCE</small></div></div><h1>Welcome back</h1><p>Sign in to your enterprise support workspace.</p><label>Email<select value={email} onChange={e=>setEmail(e.target.value)}>{accounts.map(a=><option key={a}>{a}</option>)}</select></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required/></label>{error&&<div className="error-box">{error}</div>}<button className="primary login-submit" disabled={busy}>{busy?"Signing in…":"Sign in"}</button><small className="demo-note">Development accounts use Demo@123</small></form></main>
}
