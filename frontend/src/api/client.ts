export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "ticketsense_token";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  let response: Response;
  try { response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  }); } catch { throw new ApiError("Unable to connect to the TicketSense API. Check that the backend service is running.", 0); }
  if (response.status === 401 && path !== "/api/auth/refresh" && !(init.headers as Record<string,string>|undefined)?.["X-No-Refresh"]) {
    if (await refreshAccessToken()) return request<T>(path,{...init,headers:{...init.headers,"X-No-Refresh":"1"}});
    tokenStore.clear(); window.dispatchEvent(new Event("ticketsense:unauthorized"));
  }
  if (!response.ok) {
    let message = "Unable to complete the request. Please try again.";
    try { const body = await response.json(); message = body.detail || message; } catch { /* non-JSON error */ }
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}

function cookie(name:string){return document.cookie.split("; ").find(x=>x.startsWith(`${name}=`))?.split("=").slice(1).join("=")||""}
async function refreshAccessToken(){try{const response=await fetch(`${API_BASE_URL}/api/auth/refresh`,{method:"POST",credentials:"include",headers:{"X-CSRF-Token":decodeURIComponent(cookie("ticketsense_csrf"))}});if(!response.ok)return false;tokenStore.set((await response.json()).access_token);return true}catch{return false}}

export interface User { id:string; email:string; full_name:string; role:string; public_role?:"customer"|"engineer"|"admin"; department_id:string|null; tenant_id:string|null; permissions:string[] }
export interface Evidence { title:string; excerpt:string; score:number; source?:string }
export interface GroundedEvidence { citation_id:string; article_id:string; title:string; article_version:string; department:string; chunk_text:string; similarity:number; distance:number; is_publishable:boolean }
export interface GroundedDraft { ticket_id:string; draft_text:string|null; citations:Array<{citation_id:string;article_id:string;article_title:string;article_version:string;supported_text:string}>; evidence:GroundedEvidence[]; provider:string|null; model:string|null; generation_status:string; citation_validation_status:string; validation:{valid?:boolean;valid_citation_ids?:string[];invalid_citation_ids?:string[];uncited_claim_warnings?:string[];validation_errors?:string[];insufficient_evidence?:boolean}; generation_error:string|null; insufficient_evidence:boolean; attempt_count:number; created_at?:string; updated_at?:string }
export interface AttachmentMeta {id:string;ticket_id:string;original_filename:string;detected_mime_type:string;file_extension:string;file_size_bytes:number;status:string;extraction_status:string;extraction_method?:string|null;sanitized_text?:string|null;ocr_confidence?:number|null;ocr_confidence_available?:boolean;page_count?:number|null;character_count?:number;truncated?:boolean;processing_duration_ms?:number|null;warnings?:string[];error_code?:string|null;error_summary?:string|null;created_at:string;processed_at?:string|null}
export interface Analysis { category?:string; intent?:string; sentiment?:string; priority_score?:number; sla_risk?:number; confidence?:number; decision?:string; decision_reason?:string; root_causes?:Array<{label:string;probability:number}>; evidence?:Evidence[]; [key:string]:unknown }
export interface Ticket { id:string; subject:string; description:string; status:string; category?:string|null; required_specialization?:string|null; resolution_type?:string|null; priority:string|null; sentiment:string|null; department_id?:string|null; department_name?:string|null; assignee_id?:string|null; confidence_score:number|null; ai_draft_reply?:string|null; final_response?:string|null; final_responder_name?:string|null; approved_at?:string|null; resolved_at?:string|null; public_status_message?:string|null; sla_due_at?:string|null; reopened_count?:number; created_at:string; updated_at?:string; analysis:Analysis }
export interface TicketDecision {id:string;ticket_id:string;decision:string;reason_code:string;explanation:string;overall_confidence:number|null;applicable_threshold:number|null;passed_gates:string[];failed_gates:string[];factors:Record<string,{score?:number|null;threshold?:number|null;detail?:string}>;created_at:string}
export interface TicketMessage {id:string;ticket_id:string;author_id:string;author_name:string;visibility:"public"|"internal";body:string;original_language:string;translated_body?:string|null;translated_language?:string|null;machine_translated:boolean;attachment_ids:string[];is_read:boolean;created_at:string;edited_at?:string|null}
export interface Experience {public_role:"customer"|"engineer"|"admin";internal_role:string;landing_path:string;capabilities:string[];modules:string[];skills:Array<{specialization:string;level:string;primary:boolean}>}
export interface FeatureFlag {id:string;key:string;description:string;owner:string;global_default:boolean;kill_switch:boolean;prerequisites:string[];starts_at?:string|null;ends_at?:string|null;evaluation:{enabled:boolean;reason_code:string;reason:string;source:string;rollout_bucket?:number|null;rollout_percentage?:number|null}}
export interface ProviderModel {id:string;provider_type:string;model_identifier:string;immutable_version:string;task_type:string;deployment_environment:string;config_reference?:string|null;enabled:boolean;cost_metadata:Record<string,unknown>;latency_limit_ms?:number|null;data_residency_policy:string;approved_scopes:Record<string,unknown>;evaluation_status:string;lifecycle_role:string;rollback_target_id?:string|null;approved_at?:string|null;deployed_at?:string|null}
export interface AIUsageSummary {window_days:number;metrics_source:string;groups:Array<{task_type:string;provider:string;model_version:string;calls:number;latency_ms:{average:number;p50:number;p95:number};measured_cost_usd:number|null;failures:number;cache_hits:number}>;empty_state?:string|null}
export interface Dataset {id:string;key:string;name:string;kind:"ticket_labels"|"retrieval_judgments";description:string;license_notes:string;created_at:string}
export interface DatasetVersion {id:string;dataset_id:string;version_number:number;content_hash:string;row_count:number;label_distribution:Record<string,Record<string,number>>;missing_data_stats:Record<string,number>;duplicate_rate:number;corruption_rate:number;near_duplicate_cross_split_count:number;near_duplicate_check_skipped:boolean;split_ratio:Record<string,number>;split_seed:string;status:string;provenance:Record<string,unknown>;created_at:string}
export interface EvaluationRun {id:string;dataset_version_id:string;target:"department"|"priority"|"sentiment";model_artifact_path:string;model_artifact_hash:string|null;git_commit:string|null;environment_info:Record<string,unknown>;config_snapshot:Record<string,unknown>;split_used:string;status:"completed"|"failed"|"insufficient_data";row_count_considered:number;row_count_excluded:number;exclusion_reasons:Record<string,unknown>;started_at:string;completed_at:string|null;notes:string|null;created_at:string}
export interface EvaluationRunDetail extends EvaluationRun {overall_metrics:Record<string,number>;per_class_metrics:Record<string,{support:number;precision?:number;recall?:number;f1?:number}>;confusion_matrix:{labels:string[];matrix:number[][]}|null}
export interface EvaluationExample {id:string;dataset_row_id:string;true_label:string;predicted_label:string;correct:boolean;top_3_hit:boolean|null;predicted_confidence:number|null;redacted_text:string}
export interface KnowledgeConflictView { id:string; article_a_id:string; article_b_id:string|null; conflict_type:string; severity:string; evidence_excerpt_a:string; evidence_excerpt_b:string|null; confidence:number|null; sample_size:number|null; affected_ticket_ids:string[]; review_state:string; resolved_by:string|null; resolved_at:string|null; resolution_note:string|null; created_at:string }
export interface OcrEngineStatus { available:boolean; reason:string|null }
export interface OcrBenchmarkDatasetView { id:string; key:string; name:string; description:string; case_count:number; created_at:string }
export interface OcrBenchmarkCaseView { id:string; dataset_id:string; image_sha256:string; ground_truth_text:string; source_label:string; tags:string[]; created_at:string }
export interface OcrBenchmarkResultView { id:string; case_id:string; extracted_text:string; character_error_rate:number; word_error_rate:number; latency_ms:number }
export interface OcrBenchmarkRunView { id:string; dataset_id:string; engine:string; status:string; unavailable_reason:string|null; row_count_considered:number; mean_character_error_rate:number|null; mean_word_error_rate:number|null; mean_latency_ms:number|null; environment_info:Record<string,unknown>; started_at:string; completed_at:string|null; created_at:string; results?:OcrBenchmarkResultView[] }
export interface RedTeamResultView { case_key:string; category:string; severity:string; title:string; expected_result:string; observed_result:string; passed:boolean; applicable:boolean; gate_responsible:string|null; detail:string }
export interface RedTeamRunSummary { run_id:string; suite_version:number; status:string; started_at:string; completed_at:string|null; total_cases:number; applicable_cases:number; not_applicable_cases:number; attack_success_rate:number|null; block_rate:number|null; by_category:Record<string,{total:number;failed:number}>; by_severity:Record<string,{total:number;failed:number}>; results:RedTeamResultView[] }
export interface RedTeamRunListItem { id:string; suite_version:number; status:string; started_at:string; completed_at:string|null }
export interface ShadowSampleResult { status:string; sample_size:number; missing:string[]; reason:string|null }
export interface ChampionChallengerComparison { sample_size:number; data_sufficient:boolean; reason:string|null; agreement_rate:number|null; champion_accuracy:number|null; challenger_accuracy:number|null; challenger_accuracy_ci:[number,number]|null; avg_champion_latency_ms:number|null; avg_challenger_latency_ms:number|null }
export interface ChampionHealthResult { action:string; reason:string; accuracy?:number; sample_size?:number }
export interface GraphNodeView { id:string; node_type:string; external_id:string; label:string; attributes:Record<string,unknown>; confirmed:boolean }
export interface GraphEdgeView { id:string; source_node_id:string; target_node_id:string; edge_type:string; confidence:number|null; provenance:string|null; confirmed:boolean; path:string }
export interface GraphNeighborhood { nodes:GraphNodeView[]; edges:GraphEdgeView[]; truncated:boolean; depth_reached:number; disclaimer:string }
export interface CounterfactualExplanationView {
  ticket_id: string; ticket_decision_id?: string; decision_outcome: string;
  blocking_gates?: Array<{ code: string; category: "immutable" | "evidence"; label: string; score: number | null; threshold: number | null; detail: string | null; narrative: string }>;
  immutable_reasons?: string[];
  evidence_gaps?: Array<{ code: string; narrative: string; minimal_safe_change: string | null }>;
  narrative: string; requires_human_review?: boolean; created_at?: string;
}
export interface ResolutionPassportView {
  ticket_id: string; resolution_type: "ai" | "engineer";
  public_citations?: Array<{ citation_id: string | null; article_version: string | null }>;
  confirmation_state?: string; integrity_verified?: boolean; created_at?: string;
  citations?: Array<{ citation_id?: string | null }>;
  passed_gates?: string[]; failed_gates?: string[];
  overall_confidence?: number | null; applicable_threshold?: number | null;
  engineer_edit_ratio?: number | null; integrity_hash?: string; integrity_valid?: boolean; is_backfilled?: boolean;
}
export interface ThresholdSimulation {id:string;department_id:string|null;category:string|null;proposed_threshold:number;sample_size:number;auto_resolved_at_threshold:number;data_sufficient:boolean;insufficiency_reasons:string[];estimated_coverage:number|null;estimated_referral_rate:number|null;historical_false_resolution_rate:number|null;confidence_interval:[number,number]|null;sensitive_category_override:boolean;based_on:string;created_at:string}
export interface ResponseDraft {id:string;ticket_id:string;version_number:number;content:string;author_type:"ai"|"engineer"|"reviewer";created_by_user_id?:string|null;based_on_draft_id?:string|null;citations:unknown[];status:string;citation_validation_status?:string|null;validation?:{status?:string;citation?:{valid?:boolean;citation_coverage?:number;validation_errors?:string[]};grounding?:{overall_status?:string;blocked?:boolean;claims?:unknown[]}};created_at:string;updated_at:string}
export interface DraftComparison {from_version:number;to_version:number;from_author_type:string;to_author_type:string;edit_percentage:number;added_word_count:number;removed_word_count:number;changes:Array<{operation:string;before:string;after:string}>;citations_added:unknown[];citations_removed:unknown[]}
export interface TechnicalEntity {id:string;entity_type:string;raw_value:string;normalized_value:string;source:string;extraction_method:string;confidence:number;validation_status:string;created_at:string}
export interface PipelineTrace {execution:null|{id:string;pipeline_version:string;trigger_type:string;status:string;started_at:string;completed_at:string|null;total_duration_ms:number|null;failure_stage:string|null;fallback_used:boolean;correlation_id:string};stages:Array<{id:string;stage_name:string;sequence_number:number;status:string;output_summary:string|null;provider_name:string|null;provider_version:string|null;confidence:number|null;started_at:string;completed_at:string;duration_ms:number;error_category:string|null;safe_error_summary:string|null;fallback_used:boolean}>;claims:Array<{claim_text:string;citation_id:string|null;validation_status:string;risk_level:string;reason:string;validator_version:string}>}
export interface TicketExplanation {predicted_department:string|null;candidate_department_probabilities:Record<string,number>|null;predicted_category:string|null;predicted_priority:string|null;important_keywords:string[]|null;technical_entities:Array<{type:string;value:string}>;routing_reason:string|null;assignment_reason:string|null;top_retrieval_similarity:number|null;retrieval_score_gap:number|null;valid_evidence_count:number;citation_coverage:number|null;confidence_score:number|null;low_threshold:number|null;high_threshold:number|null;confidence_band:string|null;positive_factors:string[];risk_factors:string[];grounding_status:string|null;human_review_decision:string|null;disclaimer:string}
export interface TicketEvent {id:string;event_type:string;old_status?:string|null;new_status?:string|null;comment?:string|null;draft_version?:number|null;actor_role?:string|null;created_at:string;visibility:string}
export interface EngineerSkill {specialization:string;skill_level:string|null;is_primary:boolean}
export interface EngineerSummary {id:string;email:string;full_name:string;department_id:string;is_active:boolean;is_available?:boolean;max_active_workload?:number;active_tickets:number;resolved_tickets:number;specializations:string[];skills?:EngineerSkill[]}
export interface EngineerWorkload {id:string;name:string;department_id:string|null;department:string|null;specializations:string[];is_active:boolean;is_available:boolean;capacity:number;active_workload:number;capacity_percent:number;assigned:number;in_progress:number;under_review:number;returned:number;escalated:number;resolved:number;average_resolution_hours:number|null}
export interface DepartmentPerformance {department_id:string;department:string;total_tickets:number;resolved_tickets:number;average_confidence:number|null}
export interface PipelineStageLatency {stage:string;average_duration_ms:number|null;sample_count:number;failure_count:number}
export interface Analytics { total_tickets:number; open_tickets:number; resolved_tickets:number; escalated_tickets:number; average_confidence:number; status_distribution:Record<string,number>; ai_acceptance_rate:number|null; engineer_edit_rate:number|null; reviewer_modification_rate:number|null; rejection_rate:number|null; escalation_rate:number|null; ai_human_agreement:number|null; confidence_distribution:Record<"low"|"borderline"|"high",number>; average_response_time_hours:number|null; average_resolution_time_hours:number|null; department_performance:DepartmentPerformance[]; pipeline_stage_latency:PipelineStageLatency[] }
export interface Incident { id:string; title:string; service:string; status:string; severity:string; department_id?:string|null; category?:string|null; ticket_count:number; growth_rate:number; common_symptom?:string; detection_reason?:string|null; confirmed_by?:string|null; confirmed_at?:string|null; resolved_at?:string|null; created_at?:string }
export interface IncidentTicketSummary { id:string; subject:string; status:string; priority:string|null; created_at:string }
export interface RootCauseHypothesis { incident_id:string; status:"hypothesis"; disclaimer:string; likely_symptom:string|null; recurring_error_codes:Array<{code:string;occurrences:number}>; supporting_ticket_ids:string[]; ticket_count:number }
export interface SafeActionDefinition { action_key:string; display_name:string; description:string; category:string; risk_level:"low"|"medium"|"high"; required_capability:string; parameter_schema:Record<string,{type:string;required:boolean}>; requires_confirmation:boolean; requires_customer_consent:boolean; enabled:boolean; connector:string; timeout_seconds:number; supports_dry_run:boolean; supports_rollback:boolean }
export interface SafeActionResultPayload { summary:string; data:Record<string,unknown>; evidence:unknown[]; sandbox:boolean; rollback_available:boolean; rolled_back:boolean }
export interface SafeActionExecution { id:string; action_key:string; ticket_id:string|null; department_id:string|null; requested_by:string; mode:"preview"|"execute"; status:string; requires_approval:boolean; error_summary:string|null; started_at:string|null; completed_at:string|null; duration_ms:number|null; created_at:string; result?:SafeActionResultPayload }
export interface SafeActionPreview { action_key:string; mode:"preview"; would_do:string; would_not_do:string; parameters:Record<string,unknown>; risk_level:string; requires_confirmation:boolean; requires_customer_consent:boolean; department_id:string|null }
export interface PreventionRecommendation { id:string; department_id:string|null; category:string|null; recommendation_type:string; title:string; description:string; window_days:number; supporting_ticket_count:number; evidence_strength:"low"|"medium"|"high"; expected_benefit:string; status:string; decision_reason:string|null; linked_incident_id:string|null; linked_knowledge_article_id:string|null; generated_at:string; decided_by:string|null; decided_at:string|null; created_at:string }
export interface PreventionRecommendationDetail extends PreventionRecommendation { evidence:Array<{evidence_type:string;reference_id:string|null;detail:Record<string,unknown>}>; actions:Array<{action_type:string;actor_id:string;reason:string|null;created_at:string}> }
export interface KnowledgeArticleSummary { id:string; title:string; status:"draft"|"pending_review"|"published"|"rejected"; version:string; department_id:string|null; source_ticket_ids:string[]; source_signal:string|null; published_knowledge_base_id:string|null; rejected_reason:string|null; created_at:string }
export interface KnowledgeGapCategory { category:string; count:number; example_ticket_ids?:string[]; average_edit_ratio?:number }
export interface KnowledgeGaps { window_days:number; weak_evidence_by_category:KnowledgeGapCategory[]; heavy_edit_by_category:KnowledgeGapCategory[] }
export interface KnowledgeHealthArticle { id:string; title:string; department_id:string|null; version:string; age_days:number|null; stale:boolean }
export interface KnowledgeHealth { stale_after_days:number; articles:KnowledgeHealthArticle[] }
export interface PlaybookStep { title:string; instruction:string; safety_warning?:string|null; evidence_required:boolean }
export interface Playbook { id:string; playbook_key:string; title:string; category:string; version:number; status:"draft"|"approved"|"active"|"inactive"|"superseded"; applicable_error_codes:string[]; clarification_questions:string[]; evidence_requirements:string[]; diagnostic_steps_template:PlaybookStep[]; approved_actions:string[]; safety_warnings:string[]; resolution_template:string|null; escalation_rules:string[]; auto_resolution_eligible:boolean; superseded_by_id:string|null; reason:string|null; created_at:string; updated_at:string }
export interface PlaybookCreate { playbook_key:string; title:string; category:string; applicable_error_codes?:string[]; clarification_questions?:string[]; evidence_requirements?:string[]; diagnostic_steps_template?:PlaybookStep[]; approved_actions?:string[]; safety_warnings?:string[]; resolution_template?:string|null; escalation_rules?:string[]; auto_resolution_eligible?:boolean; reason:string }
export interface Notification { id:string; title:string; message:string; kind:string; is_read:boolean; created_at:string }
export interface QueueTicket {id:string;display_id:string;title:string;requester_id:string;department_id:string|null;assignee_id:string|null;status:string;priority:string;sla_state:string;created_at:string;updated_at:string;analysis_status:string;review_required:boolean;review_reason?:string;confidence_band:string;risk:string}
export interface QueueResponse {items:QueueTicket[];page:number;page_size:number;total:number;queue_type:string}
export interface DescriptionSuggestion {original:string;suggested:string;missing_information_questions:string[];mode:string}

export const api = {
  login: async (email:string,password:string) => {
    const body = new URLSearchParams({ username: email, password });
    let response:Response; try{response=await fetch(`${API_BASE_URL}/api/auth/login`, { method:"POST", credentials:"include",headers:{"Content-Type":"application/x-www-form-urlencoded"}, body })}catch{throw new ApiError("Unable to connect to the TicketSense API. Check that the backend service is running.",0)}
    if (!response.ok) { let msg="Incorrect email or password"; try {msg=(await response.json()).detail||msg}catch{}; throw new ApiError(msg,response.status); }
    const data = await response.json(); tokenStore.set(data.access_token); return data.access_token as string;
  },
  me: () => request<User>("/api/auth/me"),
  logout: async () => {try{await fetch(`${API_BASE_URL}/api/auth/logout`,{method:"POST",credentials:"include",headers:{"X-CSRF-Token":decodeURIComponent(cookie("ticketsense_csrf"))}})}finally{tokenStore.clear()}},
  tickets: (query="",status="") => request<Ticket[]>(`/api/tickets?${new URLSearchParams({q:query,status_filter:status})}`),
  ticket: (id:string) => request<Ticket>(`/api/tickets/${id}`),
  createTicket: (payload:Record<string,string>) => request<Ticket>("/api/tickets",{method:"POST",body:JSON.stringify(payload)}),
  processTicket: (id:string) => request<{ticket_id:string;status:string;public_status_message?:string;resolution_available?:boolean}|TicketDecision>(`/api/tickets/${id}/process`,{method:"POST"}),
  ticketDecision: (id:string) => request<TicketDecision>(`/api/tickets/${id}/decision`),
  experience: () => request<Experience>("/api/experience"),
  featureFlags: () => request<{items:FeatureFlag[];page:number;page_size:number;total:number}>("/api/v2/features"),
  updateFeatureFlag: (key:string,payload:{global_default?:boolean;kill_switch?:boolean;reason:string}) => request<FeatureFlag>(`/api/v2/features/${key}`,{method:"PATCH",body:JSON.stringify(payload)}),
  setFeatureOverride: (key:string,payload:{scope_type:string;scope_value:string;enabled:boolean;rollout_percentage:number;reason:string}) => request<Record<string,unknown>>(`/api/v2/features/${key}/overrides`,{method:"POST",body:JSON.stringify(payload)}),
  providerModels: () => request<{items:ProviderModel[];page:number;page_size:number}>("/api/v2/models"),
  aiUsage: (days=30) => request<AIUsageSummary>(`/api/v2/observability/ai-usage?window_days=${days}`),
  datasets: () => request<{items:Dataset[];page:number;page_size:number;total:number}>("/api/v2/datasets"),
  createDataset: (payload:{key:string;name:string;kind:string;description:string;license_notes?:string}) => request<Dataset>("/api/v2/datasets",{method:"POST",body:JSON.stringify(payload)}),
  datasetVersions: (datasetId:string) => request<{items:DatasetVersion[]}>(`/api/v2/datasets/${datasetId}/versions`),
  importDataset: (datasetId:string,form:FormData) => request<{version:DatasetVersion;quality_report:Record<string,unknown>}>(`/api/v2/datasets/${datasetId}/import`,{method:"POST",body:form}),
  evaluationRuns: () => request<{items:EvaluationRun[];page:number;page_size:number;total:number}>("/api/v2/evaluation/runs"),
  createEvaluationRun: (payload:{dataset_version_id:string;target:string;notes?:string}) => request<EvaluationRun>("/api/v2/evaluation/runs",{method:"POST",body:JSON.stringify(payload)}),
  evaluationRunDetail: (id:string) => request<EvaluationRunDetail>(`/api/v2/evaluation/runs/${id}`),
  evaluationRunExamples: (id:string,onlyIncorrect=false) => request<{items:EvaluationExample[];page:number;page_size:number;total:number}>(`/api/v2/evaluation/runs/${id}/examples${onlyIncorrect?"?correct=false":""}`),
  simulateThreshold: (payload:{proposed_threshold:number;department_id?:string;category?:string}) => request<ThresholdSimulation>("/api/v2/adaptive-thresholds/simulate",{method:"POST",body:JSON.stringify(payload)}),
  thresholdSimulations: () => request<{items:ThresholdSimulation[];page:number;page_size:number;total:number}>("/api/v2/adaptive-thresholds/simulations"),
  resolutionPassport: (ticketId:string) => request<ResolutionPassportView>(`/api/v2/passports/${ticketId}`),
  counterfactualExplanation: (ticketId:string) => request<CounterfactualExplanationView>(`/api/v2/tickets/${ticketId}/counterfactual`),
  graphNeighborhood: (ticketId:string) => request<GraphNeighborhood>(`/api/v2/graph/tickets/${ticketId}`),
  runShadowSample: (task_type:string,sample_size=20) => request<ShadowSampleResult>("/api/v2/experiments/shadow-runs",{method:"POST",body:JSON.stringify({task_type,sample_size})}),
  compareChampionChallenger: (task_type:string) => request<ChampionChallengerComparison>(`/api/v2/experiments/compare?task_type=${task_type}`),
  championHealthCheck: (task_type:string) => request<ChampionHealthResult>("/api/v2/experiments/champion-health-check",{method:"POST",body:JSON.stringify({task_type})}),
  runRedTeamSuite: () => request<RedTeamRunSummary>("/api/v2/red-team/runs",{method:"POST"}),
  redTeamRuns: () => request<{items:RedTeamRunListItem[];page:number;page_size:number;total:number}>("/api/v2/red-team/runs"),
  redTeamRunDetail: (id:string) => request<RedTeamRunSummary>(`/api/v2/red-team/runs/${id}`),
  knowledgeConflicts: (reviewState?:string) => request<{items:KnowledgeConflictView[];page:number;page_size:number;total:number}>(`/api/v2/knowledge-conflicts${reviewState?`?review_state=${reviewState}`:""}`),
  scanKnowledgeConflicts: () => request<{new_conflicts:number;conflicts:KnowledgeConflictView[]}>("/api/v2/knowledge-conflicts/scan",{method:"POST"}),
  reviewKnowledgeConflict: (id:string,payload:{review_state:string;resolution_note:string}) => request<KnowledgeConflictView>(`/api/v2/knowledge-conflicts/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  ocrEngines: () => request<{engines:Record<string,OcrEngineStatus>}>("/api/v2/ocr-benchmark/engines"),
  ocrDatasets: () => request<{items:OcrBenchmarkDatasetView[]}>("/api/v2/ocr-benchmark/datasets"),
  createOcrDataset: (payload:{key:string;name:string;description?:string}) => request<OcrBenchmarkDatasetView>("/api/v2/ocr-benchmark/datasets",{method:"POST",body:JSON.stringify(payload)}),
  ocrCases: (datasetId:string) => request<{items:OcrBenchmarkCaseView[]}>(`/api/v2/ocr-benchmark/datasets/${datasetId}/cases`),
  createOcrCase: (datasetId:string,payload:{image_base64:string;ground_truth_text:string;tags?:string[]}) => request<OcrBenchmarkCaseView>(`/api/v2/ocr-benchmark/datasets/${datasetId}/cases`,{method:"POST",body:JSON.stringify(payload)}),
  ocrRuns: (datasetId?:string) => request<{items:OcrBenchmarkRunView[];page:number;page_size:number;total:number}>(`/api/v2/ocr-benchmark/runs${datasetId?`?dataset_id=${datasetId}`:""}`),
  createOcrRun: (payload:{dataset_id:string;engine:string}) => request<OcrBenchmarkRunView>("/api/v2/ocr-benchmark/runs",{method:"POST",body:JSON.stringify(payload)}),
  ocrRunDetail: (id:string) => request<OcrBenchmarkRunView>(`/api/v2/ocr-benchmark/runs/${id}`),
  assistDescription: (subject:string,description:string) => request<DescriptionSuggestion>("/api/tickets/assist-description",{method:"POST",body:JSON.stringify({subject,description})}),
  uploadAttachment: (id:string,file:File) => {const body=new FormData();body.append("file",file);return request<AttachmentMeta>(`/api/tickets/${id}/attachment`,{method:"POST",body})},
  attachment: (id:string) => request<AttachmentMeta>(`/api/tickets/${id}/attachment`),
  processAttachment: (id:string) => request<AttachmentMeta>(`/api/tickets/${id}/attachment/process`,{method:"POST"}),
  deleteAttachment: (id:string) => request<void>(`/api/tickets/${id}/attachment`,{method:"DELETE"}),
  ticketAction: (id:string,payload:{action:string;response?:string;reason?:string}) => request<Ticket>(`/api/tickets/${id}/action`,{method:"POST",body:JSON.stringify(payload)}),
  timeline: (id:string) => request<TicketEvent[]>(`/api/tickets/${id}/timeline`),
  messages: (id:string) => request<TicketMessage[]>(`/api/tickets/${id}/messages`),
  createMessage: (id:string,payload:{body:string;visibility:"public"|"internal";original_language?:string},idempotencyKey=crypto.randomUUID()) => request<TicketMessage>(`/api/tickets/${id}/messages`,{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:JSON.stringify(payload)}),
  readMessage: (ticketId:string,messageId:string) => request<{message_id:string;is_read:boolean}>(`/api/tickets/${ticketId}/messages/${messageId}/read`,{method:"POST"}),
  confirmResolution: (id:string,outcome:"solved"|"needs_help",reason?:string,idempotencyKey=crypto.randomUUID()) => request<{ticket_id:string;status:string;outcome:string;reopened_count:number}>(`/api/tickets/${id}/resolution-confirmation`,{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:JSON.stringify({outcome,reason})}),
  drafts: (id:string) => request<ResponseDraft[]>(`/api/tickets/${id}/drafts`),
  draftComparison: (id:string,fromVersion?:number,toVersion?:number) => request<DraftComparison>(`/api/tickets/${id}/draft-comparison?${new URLSearchParams({...fromVersion?{from_version:String(fromVersion)}:{},...toVersion?{to_version:String(toVersion)}:{}})}`),
  pipelineTrace: (id:string) => request<PipelineTrace>(`/api/tickets/${id}/pipeline-trace`),
  technicalEntities: (id:string) => request<TechnicalEntity[]>(`/api/tickets/${id}/technical-entities`),
  ticketExplanation: (id:string) => request<TicketExplanation>(`/api/tickets/${id}/explanation`),
  startWork: (id:string,comment?:string) => request<{ticket_id:string;status:string}>(`/api/tickets/${id}/start-work`,{method:"POST",body:JSON.stringify({comment})}),
  createResponseDraft: (id:string,payload:{content:string;based_on_draft_id?:string;citations?:unknown[]}) => request<ResponseDraft>(`/api/tickets/${id}/drafts`,{method:"POST",body:JSON.stringify(payload)}),
  submitForReview: (id:string,comment?:string) => request<{ticket_id:string;status:string;draft:ResponseDraft}>(`/api/tickets/${id}/submit-for-review`,{method:"POST",body:JSON.stringify({comment})}),
  reviewResponse: (id:string,payload:{action:"approve"|"modify_and_approve"|"request_changes"|"reject"|"escalate";response_content?:string;review_comment:string;customer_visible_note?:string}) => request<{ticket_id:string;status:string;final_response?:string;approved_draft?:ResponseDraft}>(`/api/tickets/${id}/review`,{method:"POST",body:JSON.stringify(payload)}),
  reopenTicket: (id:string,comment?:string) => request<{ticket_id:string;status:string}>(`/api/tickets/${id}/reopen`,{method:"POST",body:JSON.stringify({comment})}),
  departmentEngineers: (departmentId:string) => request<EngineerSummary[]>(`/api/departments/${departmentId}/engineers`),
  assignTicket: (id:string,engineerId:string,comment?:string) => request<{ticket_id:string;status:string;assignee_id:string}>(`/api/tickets/${id}/assign`,{method:"POST",body:JSON.stringify({engineer_id:engineerId,comment})}),
  adminEngineers: (filters?:{specialization?:string;available_only?:boolean}) => {
    const params = new URLSearchParams();
    if (filters?.specialization) params.set("specialization", filters.specialization);
    if (filters?.available_only) params.set("available_only", "true");
    const query = params.toString();
    return request<EngineerSummary[]>(`/api/admin/engineers${query ? `?${query}` : ""}`);
  },
  adminDepartments: () => request<Array<{id:string;name:string;description?:string}>>("/api/admin/departments"),
  engineerWorkloads: () => request<EngineerWorkload[]>("/api/workloads/engineers"),
  createEngineer: (payload:{email:string;full_name:string;password:string;department_id:string;specializations:string[]}) => request<EngineerSummary>("/api/admin/engineers",{method:"POST",body:JSON.stringify(payload)}),
  updateEngineer: (id:string,payload:{full_name?:string;department_id?:string;is_active?:boolean;specializations?:string[]}) => request<EngineerSummary>(`/api/admin/engineers/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  analysis: (id:string) => request<Analysis>(`/api/tickets/${id}/ai-analysis`),
  evidence: (id:string) => request<Evidence[]>(`/api/tickets/${id}/evidence`),
  groundedDraft: (id:string) => request<GroundedDraft>(`/api/tickets/${id}/ai-draft`),
  generateGroundedDraft: (id:string,article_version="1.0") => request<GroundedDraft>(`/api/tickets/${id}/ai-draft/generate`,{method:"POST",body:JSON.stringify({article_version})}),
  similar: (id:string) => request<Array<{id:string;subject:string;status:string;similarity:number;resolution?:string}>>(`/api/tickets/${id}/similar`),
  trace: (id:string) => request<Array<{action:string;detail:Record<string,unknown>;timestamp:string}>>(`/api/tickets/${id}/trace`),
  analytics: () => request<Analytics>("/api/analytics"),
  aiMetrics: () => request<{agents:Array<Record<string,number|string>>;provider:string;external_cost_usd:number}>("/api/ai/metrics"),
  incidents: (statusFilter="") => request<Incident[]>(`/api/incidents${statusFilter ? `?status_filter=${statusFilter}` : ""}`),
  scanForIncidents: () => request<Incident[]>("/api/incidents/scan", { method: "POST" }),
  incidentTickets: (id:string) => request<IncidentTicketSummary[]>(`/api/incidents/${id}/tickets`),
  incidentRootCause: (id:string) => request<RootCauseHypothesis>(`/api/incidents/${id}/root-cause`),
  confirmIncident: (id:string) => request<Incident>(`/api/incidents/${id}/confirm`, { method: "POST" }),
  dismissIncident: (id:string) => request<Incident>(`/api/incidents/${id}/dismiss`, { method: "POST" }),
  notifyIncidentCustomers: (id:string) => request<{incident_id:string;notified:number}>(`/api/incidents/${id}/notify-customers`, { method: "POST" }),
  resolveIncident: (id:string) => request<Incident>(`/api/incidents/${id}/resolve`, { method: "POST" }),
  safeActions: () => request<SafeActionDefinition[]>("/api/safe-actions"),
  safeAction: (key:string) => request<SafeActionDefinition>(`/api/safe-actions/${key}`),
  previewSafeAction: (key:string,payload:{parameters:Record<string,unknown>;ticket_id?:string}) => request<SafeActionPreview>(`/api/safe-actions/${key}/preview`,{method:"POST",body:JSON.stringify(payload)}),
  executeSafeAction: (key:string,payload:{parameters:Record<string,unknown>;ticket_id?:string;confirm:boolean;customer_consent?:boolean},idempotencyKey:string) =>
    request<SafeActionExecution>(`/api/safe-actions/${key}/execute`,{method:"POST",body:JSON.stringify(payload),headers:{"Idempotency-Key":idempotencyKey}}),
  approveSafeActionExecution: (id:string) => request<SafeActionExecution>(`/api/safe-actions/executions/${id}/approve`,{method:"POST"}),
  rejectSafeActionExecution: (id:string,reason?:string) => request<SafeActionExecution>(`/api/safe-actions/executions/${id}/reject${reason?`?reason=${encodeURIComponent(reason)}`:""}`,{method:"POST"}),
  safeActionExecutions: (filters?:{ticket_id?:string;action_key?:string}) => {
    const params = new URLSearchParams();
    if (filters?.ticket_id) params.set("ticket_id", filters.ticket_id);
    if (filters?.action_key) params.set("action_key", filters.action_key);
    const query = params.toString();
    return request<SafeActionExecution[]>(`/api/safe-actions/executions${query ? `?${query}` : ""}`);
  },
  safeActionExecution: (id:string) => request<SafeActionExecution>(`/api/safe-actions/executions/${id}`),
  scanForPreventionRecommendations: () => request<PreventionRecommendation[]>("/api/prevention/scan", { method: "POST" }),
  preventionRecommendations: (filters?:{department_id?:string;recommendation_type?:string;status_filter?:string}) => {
    const params = new URLSearchParams();
    if (filters?.department_id) params.set("department_id", filters.department_id);
    if (filters?.recommendation_type) params.set("recommendation_type", filters.recommendation_type);
    if (filters?.status_filter) params.set("status_filter", filters.status_filter);
    const query = params.toString();
    return request<PreventionRecommendation[]>(`/api/prevention/recommendations${query ? `?${query}` : ""}`);
  },
  preventionRecommendation: (id:string) => request<PreventionRecommendationDetail>(`/api/prevention/recommendations/${id}`),
  acceptRecommendation: (id:string) => request<PreventionRecommendation>(`/api/prevention/recommendations/${id}/accept`, { method: "POST" }),
  rejectRecommendation: (id:string,reason:string) => request<PreventionRecommendation>(`/api/prevention/recommendations/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  investigateRecommendation: (id:string) => request<PreventionRecommendation>(`/api/prevention/recommendations/${id}/investigate`, { method: "POST" }),
  dismissRecommendation: (id:string,reason:string) => request<PreventionRecommendation>(`/api/prevention/recommendations/${id}/dismiss`, { method: "POST", body: JSON.stringify({ reason }) }),
  convertRecommendationToKnowledge: (id:string) => request<{recommendation:PreventionRecommendation;knowledge_article_id:string}>(`/api/prevention/recommendations/${id}/convert-to-knowledge`, { method: "POST" }),
  linkRecommendationToIncident: (id:string,incidentId:string) => request<PreventionRecommendation>(`/api/prevention/recommendations/${id}/link-incident`, { method: "POST", body: JSON.stringify({ incident_id: incidentId }) }),
  knowledge: (q="") => request<Array<{id:string;title:string;excerpt:string;source?:string;updated_at:string}>>(`/api/knowledge?${new URLSearchParams({q})}`),
  knowledgeArticles: (statusFilter="") => request<KnowledgeArticleSummary[]>(`/api/knowledge/articles${statusFilter ? `?status_filter=${statusFilter}` : ""}`),
  generateKnowledgeArticle: (payload:{title:string;body:string;source_ticket_ids?:string[]}) => request<{id:string;status:string;title:string}>("/api/knowledge/articles/generate",{method:"POST",body:JSON.stringify(payload)}),
  approveKnowledgeArticle: (id:string) => request<{id:string;status:string;knowledge_base_id:string}>(`/api/knowledge/articles/${id}/approve`,{method:"POST"}),
  rejectKnowledgeArticle: (id:string,reason:string) => request<{id:string;status:string}>(`/api/knowledge/articles/${id}/reject`,{method:"POST",body:JSON.stringify({reason})}),
  knowledgeGaps: (days?:number) => request<KnowledgeGaps>(`/api/knowledge/gaps${days ? `?days=${days}` : ""}`),
  knowledgeHealth: (staleAfterDays?:number) => request<KnowledgeHealth>(`/api/knowledge/health${staleAfterDays ? `?stale_after_days=${staleAfterDays}` : ""}`),
  playbooks: (statusFilter="") => request<Playbook[]>(`/api/playbooks${statusFilter ? `?status_filter=${statusFilter}` : ""}`),
  createPlaybook: (payload:PlaybookCreate) => request<Playbook>("/api/playbooks",{method:"POST",body:JSON.stringify(payload)}),
  newPlaybookVersion: (id:string,payload:PlaybookCreate) => request<Playbook>(`/api/playbooks/${id}/version`,{method:"POST",body:JSON.stringify(payload)}),
  approvePlaybook: (id:string) => request<Playbook>(`/api/playbooks/${id}/approve`,{method:"POST"}),
  activatePlaybook: (id:string) => request<Playbook>(`/api/playbooks/${id}/activate`,{method:"POST"}),
  deactivatePlaybook: (id:string) => request<Playbook>(`/api/playbooks/${id}/deactivate`,{method:"POST"}),
  recommendedPlaybook: (ticketId:string) => request<Playbook>(`/api/tickets/${ticketId}/recommended-playbook`),
  applyPlaybook: (ticketId:string,playbookId:string) => request<{diagnostic_plan_id:string;playbook_id:string;step_count:number}>(`/api/tickets/${ticketId}/playbooks/${playbookId}/apply`,{method:"POST"}),
  notifications: () => request<Notification[]>("/api/notifications"),
  markNotificationRead: (id:string) => request<{id:string;is_read:boolean}>(`/api/notifications/${id}/read`,{method:"POST"}),
  auditLogs: () => request<Array<Record<string,unknown>>>("/api/audit-logs"),
  integrations: () => request<Array<{id:string;provider:string;name:string;enabled:boolean}>>("/api/integrations"),
  queue: (type:string) => request<QueueResponse>(`/api/queues/${type}`),
  acceptTicket: (id:string) => request<QueueTicket>(`/api/queues/tickets/${id}/accept`,{method:"POST"}),
  reviewTicket: (id:string,payload:{decision:string;reason:string;final_response?:string}) => request<{stored:boolean;ticket:QueueTicket}>(`/api/queues/reviews/${id}`,{method:"POST",body:JSON.stringify(payload)}),
};

export type HealthResponse = {status:string;database:string};
export const fetchHealth = () => request<HealthResponse>("/api/health");
export const fetchTickets = () => api.tickets();
export const createTicket = (payload:Record<string,string>) => api.createTicket(payload);
