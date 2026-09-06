import { useEffect, useState } from "react";
import { api, type AIUsageSummary, type ChampionChallengerComparison, type FeatureFlag, type ProviderModel } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Tabs, TabPanel } from "../components/ui/Tabs";
import { useToast } from "../components/ui/Toast";

export default function AdminV2Governance(){
  const toast=useToast();const [flags,setFlags]=useState<FeatureFlag[]>([]);const [models,setModels]=useState<ProviderModel[]>([]);const [usage,setUsage]=useState<AIUsageSummary|null>(null);const [tab,setTab]=useState("features");const [loading,setLoading]=useState(true);const [error,setError]=useState("");const [busy,setBusy]=useState("");
  async function load(){setLoading(true);setError("");try{const [flagResult,modelResult,usageResult]=await Promise.allSettled([api.featureFlags(),api.providerModels(),api.aiUsage()]);if(flagResult.status==="fulfilled")setFlags(flagResult.value.items);if(modelResult.status==="fulfilled")setModels(modelResult.value.items);if(usageResult.status==="fulfilled")setUsage(usageResult.value);if([flagResult,modelResult,usageResult].every(result=>result.status==="rejected"))throw new Error("No V2 governance module is available for this account.")}catch(e){setError(e instanceof Error?e.message:"Unable to load V2 governance")}finally{setLoading(false)}}
  useEffect(()=>{load()},[]);
  async function killSwitch(flag:FeatureFlag){setBusy(flag.key);try{await api.updateFeatureFlag(flag.key,{kill_switch:!flag.kill_switch,reason:`${!flag.kill_switch?"Activate":"Release"} emergency kill switch from Admin governance UI`});await load();toast(`Kill switch ${!flag.kill_switch?"activated":"released"}.`,!flag.kill_switch?"danger":"success")}catch(e){toast(e instanceof Error?e.message:"Unable to update feature","danger")}finally{setBusy("")}}
  if(loading)return <div className="content"><Loading label="Loading V2 governance…"/></div>;
  if(error&&!flags.length&&!models.length)return <div className="content"><ErrorState message={error} onRetry={load}/></div>;
  return <div className="content"><div className="page-title"><div><p className="eyebrow">TicketSense V2 control plane</p><h1>AI governance</h1><p>Server-enforced feature rollout, immutable model versions and measured provider usage.</p></div><div className="live"><span/>No sample metrics</div></div>
    <Tabs idPrefix="v2-governance" active={tab} onChange={setTab} tabs={[{key:"features",label:"Feature flags"},{key:"models",label:"Model registry"},{key:"usage",label:"Observability"},{key:"experiments",label:"Shadow & challenger"}]}/>
    <TabPanel id="v2-governance" tabKey="features" active={tab}><div className="panel governance-table"><div className="list-head governance-row"><span>Feature</span><span>Owner</span><span>Evaluation</span><span>Safety</span></div>{flags.map(flag=><article className="list-row governance-row" key={flag.key}><div><b>{flag.key.replaceAll("_"," ")}</b><small>{flag.description}</small>{flag.prerequisites.length>0&&<small>Requires: {flag.prerequisites.join(", ")}</small>}</div><span>{flag.owner}</span><div><Badge value={flag.evaluation.enabled?"enabled":"disabled"}/><small>{flag.evaluation.reason}</small></div><Button size="sm" variant={flag.kill_switch?"primary":"destructive"} loading={busy===flag.key} onClick={()=>killSwitch(flag)}>{flag.kill_switch?"Release kill switch":"Kill switch"}</Button></article>)}</div></TabPanel>
    <TabPanel id="v2-governance" tabKey="models" active={tab}>{models.length?<div className="panel governance-table"><div className="list-head model-registry-row"><span>Task / model</span><span>Immutable version</span><span>Role</span><span>Status</span></div>{models.map(model=><article className="list-row model-registry-row" key={model.id}><div><b>{model.task_type}</b><small>{model.provider_type} · {model.model_identifier}</small></div><code>{model.immutable_version}</code><Badge value={model.lifecycle_role}/><div><Badge value={model.enabled?model.evaluation_status:"disabled"}/><small>{model.deployment_environment} · {model.data_residency_policy}</small></div></article>)}</div>:<Empty label="No provider/model versions are registered for this tenant."/>}</TabPanel>
    <TabPanel id="v2-governance" tabKey="usage" active={tab}>{usage?.groups.length?<div className="panel governance-table"><div className="list-head usage-row"><span>Provider task</span><span>Calls</span><span>Latency</span><span>Measured cost</span></div>{usage.groups.map(group=><article className="list-row usage-row" key={`${group.task_type}-${group.provider}-${group.model_version}`}><div><b>{group.task_type}</b><small>{group.provider} · {group.model_version}</small></div><strong>{group.calls}</strong><span>p50 {group.latency_ms.p50} ms · p95 {group.latency_ms.p95} ms</span><span>{group.measured_cost_usd==null?"Unavailable":`$${group.measured_cost_usd.toFixed(4)}`}</span></article>)}</div>:<Empty label={usage?.empty_state||"No measured provider usage exists."}/>}</TabPanel>
    <TabPanel id="v2-governance" tabKey="experiments" active={tab}><ExperimentsPanel toast={toast}/></TabPanel>
  </div>
}

const EXPERIMENT_TASKS = ["department","priority","sentiment"] as const;

function ExperimentsPanel({toast}:{toast:(message:string,tone?:"success"|"danger")=>void}){
  const [taskType,setTaskType]=useState<typeof EXPERIMENT_TASKS[number]>("department");
  const [comparison,setComparison]=useState<ChampionChallengerComparison|null>(null);
  const [loading,setLoading]=useState(false);
  const [busy,setBusy]=useState("");

  async function loadComparison(task:string){
    setLoading(true);
    try{ setComparison(await api.compareChampionChallenger(task)); }
    catch(e){ setComparison(null); toast(e instanceof Error?e.message:"Shadow/challenger comparison is not available","danger"); }
    finally{ setLoading(false); }
  }
  useEffect(()=>{ loadComparison(taskType); },[taskType]); // eslint-disable-line react-hooks/exhaustive-deps

  async function sample(){
    setBusy("sample");
    try{ const result=await api.runShadowSample(taskType,20); toast(result.reason||`Sampled ${result.sample_size} ticket(s).`, result.status==="sampled"?"success":"danger"); await loadComparison(taskType); }
    catch(e){ toast(e instanceof Error?e.message:"Unable to run shadow sample","danger"); }
    finally{ setBusy(""); }
  }
  async function healthCheck(){
    setBusy("health");
    try{ const result=await api.championHealthCheck(taskType); toast(result.reason, result.action==="rolled_back"?"danger":"success"); }
    catch(e){ toast(e instanceof Error?e.message:"Unable to run champion health check","danger"); }
    finally{ setBusy(""); }
  }

  return <div className="panel" style={{display:"flex",flexDirection:"column",gap:"1rem"}}>
    <p>Private, non-publishing comparison of the active champion against a registered challenger model on real ticket text. A challenger's output is never shown to a customer or used to route a ticket — this is measurement only.</p>
    <div style={{display:"flex",gap:"0.5rem",alignItems:"center"}}>
      <label>Task<select value={taskType} onChange={e=>setTaskType(e.target.value as typeof taskType)}>{EXPERIMENT_TASKS.map(t=><option key={t} value={t}>{t}</option>)}</select></label>
      <Button size="sm" variant="outline" loading={busy==="sample"} onClick={sample}>Run shadow sample (20)</Button>
      <Button size="sm" variant="outline" loading={busy==="health"} onClick={healthCheck}>Check champion health</Button>
    </div>
    {loading?<Loading label="Loading comparison…"/>:!comparison||comparison.sample_size===0?<Empty label="No shadow runs recorded yet for this task — register a challenger model and run a sample."/>:<div className="panel governance-table">
      <div><Badge value={comparison.data_sufficient?"data sufficient":"insufficient data"}/> {comparison.reason && <small>{comparison.reason}</small>}</div>
      <div className="list-head eval-metric-row"><span>Metric</span><span>Value</span></div>
      <div className="list-row eval-metric-row"><span>Sample size</span><span>{comparison.sample_size}</span></div>
      <div className="list-row eval-metric-row"><span>Agreement rate</span><span>{comparison.agreement_rate==null?"unavailable":`${(comparison.agreement_rate*100).toFixed(1)}%`}</span></div>
      <div className="list-row eval-metric-row"><span>Champion accuracy</span><span>{comparison.champion_accuracy==null?"unavailable":`${(comparison.champion_accuracy*100).toFixed(1)}%`}</span></div>
      <div className="list-row eval-metric-row"><span>Challenger accuracy</span><span>{comparison.challenger_accuracy==null?"unavailable":`${(comparison.challenger_accuracy*100).toFixed(1)}% (95% CI ${comparison.challenger_accuracy_ci?`${(comparison.challenger_accuracy_ci[0]*100).toFixed(1)}–${(comparison.challenger_accuracy_ci[1]*100).toFixed(1)}%`:"n/a"})`}</span></div>
      <div className="list-row eval-metric-row"><span>Avg. champion latency</span><span>{comparison.avg_champion_latency_ms==null?"unavailable":`${comparison.avg_champion_latency_ms} ms`}</span></div>
      <div className="list-row eval-metric-row"><span>Avg. challenger latency</span><span>{comparison.avg_challenger_latency_ms==null?"unavailable":`${comparison.avg_challenger_latency_ms} ms`}</span></div>
    </div>}
  </div>;
}
