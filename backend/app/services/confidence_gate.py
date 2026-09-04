from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.models.confidence_model import predict_confidence
from app.models.operations import DepartmentConfidencePolicy


def build_confidence_features(analysis: dict, description: str, ocr_quality: float | None = None) -> dict:
    evidence=analysis.get("evidence") or []
    scores=sorted((float(item.get("score",0)) for item in evidence),reverse=True)
    breakdown=analysis.get("confidence_breakdown") or {}
    words=len(description.split())
    return {
        "classification_probability": float(analysis.get("classification_probability",analysis.get("confidence",0))),
        "classification_margin": float(analysis.get("classification_margin",0)),
        "retrieval_similarity": scores[0] if scores else float(breakdown.get("retrieval",0)),
        "retrieval_score_gap": scores[0]-scores[1] if len(scores)>1 else 0,
        "citation_coverage": float(analysis.get("citation_coverage",0)),
        "valid_evidence_count": len(evidence),
        "ocr_quality": 1.0 if ocr_quality is None else float(ocr_quality),
        "description_completeness": min(1.0,words/50),
        "draft_validation": 1.0 if analysis.get("safety",True) else 0.0,
    }


async def evaluate_confidence(db:AsyncSession,tenant_id,department_id,analysis:dict,description:str,ocr_quality:float|None=None):
    features=build_confidence_features(analysis,description,ocr_quality); score,version,trained=predict_confidence(features)
    policy=None
    if department_id:
        policy=await db.scalar(select(DepartmentConfidencePolicy).where(DepartmentConfidencePolicy.tenant_id==tenant_id,DepartmentConfidencePolicy.department_id==department_id).order_by(DepartmentConfidencePolicy.version.desc()).limit(1))
    low=float(policy.low_threshold) if policy else .55; high=float(policy.high_threshold) if policy else .80
    gate="high" if score>=high else "low" if score<low else "borderline"
    return {"score":score,"features":features,"model_version":version,"trained_artifact":trained,"gate":gate,"low_threshold":low,"high_threshold":high,"policy_version":policy.version if policy else 0}
