"""Train the independent confidence model from real recorded reviewer outcomes.

Run inside the API container:
  python /workspace/ai/models/train_confidence.py             # train + compare only
  python /workspace/ai/models/train_confidence.py --deploy     # train, then promote if improved
  python /workspace/ai/models/train_confidence.py --deploy --force   # promote regardless of comparison
  python /workspace/ai/models/train_confidence.py --rollback   # revert to the previously promoted version
The script refuses to train when fewer than 30 usable labelled outcomes exist.

This is the controlled offline retraining workflow (Phase 13): dataset extraction,
validation, training and evaluation happen every run; a candidate is only ever
written to a new version file. It becomes the version the live API loads (see
ai/models/confidence_model.py's registry-backed default) only through an explicit
--deploy, which itself only promotes when the candidate's ROC-AUC is at least as
good as the currently active version, unless --force overrides that gate. --rollback
restores the previously active version without retraining anything.
"""
import argparse, asyncio, json, os, re
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from sklearn.calibration import calibration_curve
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ai.models.confidence_model import FEATURE_SCHEMA, normalized_features
from ai.models.confidence_registry import compare_to_active, promote, rollback, save_candidate


def pg_url(value:str)->str: return re.sub(r"^postgresql\+asyncpg://","postgresql://",value)


async def load_rows():
    url=os.environ.get("DATABASE_URL")
    if not url: raise SystemExit("DATABASE_URL is required")
    conn=await asyncpg.connect(pg_url(url))
    try:
        return await conn.fetch("""SELECT f.action,t.confidence_features FROM feedback f JOIN tickets t ON t.id=f.ticket_id WHERE f.action IN ('accept','edit','reject','escalate') AND t.confidence_features IS NOT NULL ORDER BY f.created_at""")
    finally: await conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deploy",action="store_true",help="Promote the candidate to active if it compares favorably (or always, with --force)")
    parser.add_argument("--force",action="store_true",help="With --deploy, promote regardless of the comparison result")
    parser.add_argument("--rollback",action="store_true",help="Revert to the previously active version and exit; no training")
    args=parser.parse_args()

    if args.rollback:
        restored=rollback()
        print(json.dumps({"rolled_back_to":restored} if restored else {"error":"No previous version to roll back to."}))
        return

    rows=asyncio.run(load_rows())
    usable=[]
    for row in rows:
        payload=row["confidence_features"] if isinstance(row["confidence_features"],dict) else json.loads(row["confidence_features"])
        features=(payload or {}).get("confidence_model",{}).get("features")
        if features: usable.append((normalized_features(features),1 if row["action"] in {"accept","edit"} else 0))
    if len(usable)<30: raise SystemExit(f"Insufficient labelled outcomes: {len(usable)} usable; at least 30 required. No artifact was changed.")
    X=[row[0] for row in usable];y=[row[1] for row in usable]
    if len(set(y))<2: raise SystemExit("Both accepted and rejected/escalated outcomes are required. No artifact was changed.")
    X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=.25,random_state=42,stratify=y)
    pipeline=Pipeline([("imputer",SimpleImputer(strategy="median")),("scale",StandardScaler()),("model",LogisticRegression(max_iter=2000,class_weight="balanced",random_state=42))]);pipeline.fit(X_train,y_train)
    pred=pipeline.predict(X_test);prob=pipeline.predict_proba(X_test)[:,1]
    metrics={"samples":len(usable),"train_samples":len(X_train),"test_samples":len(X_test),"accuracy":accuracy_score(y_test,pred),"precision":precision_score(y_test,pred,zero_division=0),"recall":recall_score(y_test,pred,zero_division=0),"f1":f1_score(y_test,pred,zero_division=0),"roc_auc":roc_auc_score(y_test,prob),"pr_auc":average_precision_score(y_test,prob),"brier":brier_score_loss(y_test,prob),"confusion_matrix":confusion_matrix(y_test,pred).tolist()}
    fraction_positive,mean_predicted=calibration_curve(y_test,prob,n_bins=min(5,len(y_test)),strategy="quantile");metrics["calibration"]={"mean_predicted":mean_predicted.tolist(),"fraction_positive":fraction_positive.tolist()}
    trained_at=datetime.now(timezone.utc).isoformat();version=f"confidence-logreg-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    artifact_path=save_candidate(version,{"pipeline":pipeline,"feature_schema":FEATURE_SCHEMA,"model_version":version,"trained_at":trained_at,"dataset_snapshot":{"source":"feedback+ticket confidence feature snapshots","rows":len(usable)},"metrics":metrics})
    comparison=compare_to_active(metrics)
    report={"model_version":version,"trained_at":trained_at,"metrics":metrics,"artifact":str(artifact_path),"comparison_to_active":comparison,"deployed":False}
    if args.deploy:
        if comparison["improved_or_first"] or args.force:
            promote(version,note="deploy" if comparison["improved_or_first"] else "deploy --force despite regression")
            report["deployed"]=True
        else:
            report["deploy_skipped_reason"]=f"Candidate {comparison['metric']}={comparison['candidate_value']} did not beat active {comparison['active_value']}; rerun with --force to override."
    print(json.dumps(report,indent=2))


if __name__=="__main__": main()
