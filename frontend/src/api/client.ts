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

export interface User { id:string; email:string; full_name:string; role:string; department_id:string|null; tenant_id:string|null; permissions:string[] }
export interface Evidence { title:string; excerpt:string; score:number; source?:string }
export interface GroundedEvidence { citation_id:string; article_id:string; title:string; article_version:string; department:string; chunk_text:string; similarity:number; distance:number; is_publishable:boolean }
export interface GroundedDraft { ticket_id:string; draft_text:string|null; citations:Array<{citation_id:string;article_id:string;article_title:string;article_version:string;supported_text:string}>; evidence:GroundedEvidence[]; provider:string|null; model:string|null; generation_status:string; citation_validation_status:string; validation:{valid?:boolean;valid_citation_ids?:string[];invalid_citation_ids?:string[];uncited_claim_warnings?:string[];validation_errors?:string[];insufficient_evidence?:boolean}; generation_error:string|null; insufficient_evidence:boolean; attempt_count:number; created_at?:string; updated_at?:string }
export interface AttachmentMeta {id:string;ticket_id:string;original_filename:string;detected_mime_type:string;file_extension:string;file_size_bytes:number;status:string;extraction_status:string;extraction_method?:string|null;sanitized_text?:string|null;ocr_confidence?:number|null;ocr_confidence_available?:boolean;page_count?:number|null;character_count?:number;truncated?:boolean;processing_duration_ms?:number|null;warnings?:string[];error_code?:string|null;error_summary?:string|null;created_at:string;processed_at?:string|null}
export interface Analysis { category?:string; intent?:string; sentiment?:string; priority_score?:number; sla_risk?:number; confidence?:number; decision?:string; decision_reason?:string; root_causes?:Array<{label:string;probability:number}>; evidence?:Evidence[]; [key:string]:unknown }
export interface Ticket { id:string; subject:string; description:string; status:string; priority:string|null; sentiment:string|null; department_id?:string|null; confidence_score:number|null; ai_draft_reply?:string|null; created_at:string; updated_at?:string; analysis:Analysis }
export interface Analytics { total_tickets:number; open_tickets:number; resolved_tickets:number; escalated_tickets:number; average_confidence:number; status_distribution:Record<string,number> }
export interface Incident { id:string; title:string; service:string; status:string; severity:string; ticket_count:number; growth_rate:number; common_symptom?:string }
export interface Notification { id:string; title:string; message:string; kind:string; is_read:boolean; created_at:string }
export interface QueueTicket {id:string;display_id:string;title:string;requester_id:string;department_id:string|null;assignee_id:string|null;status:string;priority:string;sla_state:string;created_at:string;updated_at:string;analysis_status:string;review_required:boolean;review_reason?:string;confidence_band:string;risk:string}
export interface QueueResponse {items:QueueTicket[];page:number;page_size:number;total:number;queue_type:string}

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
  uploadAttachment: (id:string,file:File) => {const body=new FormData();body.append("file",file);return request<AttachmentMeta>(`/api/tickets/${id}/attachment`,{method:"POST",body})},
  attachment: (id:string) => request<AttachmentMeta>(`/api/tickets/${id}/attachment`),
  processAttachment: (id:string) => request<AttachmentMeta>(`/api/tickets/${id}/attachment/process`,{method:"POST"}),
  deleteAttachment: (id:string) => request<void>(`/api/tickets/${id}/attachment`,{method:"DELETE"}),
  ticketAction: (id:string,payload:{action:string;response?:string;reason?:string}) => request<Ticket>(`/api/tickets/${id}/action`,{method:"POST",body:JSON.stringify(payload)}),
  analysis: (id:string) => request<Analysis>(`/api/tickets/${id}/ai-analysis`),
  evidence: (id:string) => request<Evidence[]>(`/api/tickets/${id}/evidence`),
  groundedDraft: (id:string) => request<GroundedDraft>(`/api/tickets/${id}/ai-draft`),
  generateGroundedDraft: (id:string,article_version="1.0") => request<GroundedDraft>(`/api/tickets/${id}/ai-draft/generate`,{method:"POST",body:JSON.stringify({article_version})}),
  similar: (id:string) => request<Array<{id:string;subject:string;status:string;similarity:number;resolution?:string}>>(`/api/tickets/${id}/similar`),
  trace: (id:string) => request<Array<{action:string;detail:Record<string,unknown>;timestamp:string}>>(`/api/tickets/${id}/trace`),
  analytics: () => request<Analytics>("/api/analytics"),
  aiMetrics: () => request<{agents:Array<Record<string,number|string>>;provider:string;external_cost_usd:number}>("/api/ai/metrics"),
  incidents: () => request<Incident[]>("/api/incidents"),
  knowledge: (q="") => request<Array<{id:string;title:string;excerpt:string;source?:string;updated_at:string}>>(`/api/knowledge?${new URLSearchParams({q})}`),
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
