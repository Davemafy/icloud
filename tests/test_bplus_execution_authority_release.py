from pathlib import Path
from app.models import Grade
from app.risk_matrix import EXECUTION_GRADES, risk_pct_for_grade
import app.thesis_ownership_policy as ownership
import app.liquidity_reversal_handoff as liquidity_reversal
ROOT=Path(__file__).resolve().parents[1]
SEQ=ROOT/"mt5"/"stable"/"InstitutionalSMC_SequenceEA_v3_41_BPlusAuthority_Demo.mq5"
def test_cloud_bplus_contract():
 assert Grade.B_PLUS in EXECUTION_GRADES
 assert risk_pct_for_grade(Grade.B_PLUS,"TREND")==0.10
 assert risk_pct_for_grade(Grade.B_PLUS,"COUNTERTREND")==0.10
def test_sequence_bplus_contract_is_not_zeroed():
 t=SEQ.read_text(encoding="utf-8")
 assert "ResearchRiskPctBPlus=0.25" in t
 assert 'if(grade=="B+")return ResearchRiskPctBPlus;' in t
 assert 'if(grade=="B+"){original=0.0;flipPct=0.0;}' not in t
 assert 'if(grade!="A+"&&grade!="A"&&grade!="B+")return 0.0;' in t


def test_cloud_ai_contracts_do_not_reintroduce_bplus_watch_only():
 assert "B+ is watch/research only" not in ownership._AI_RULE
 assert "A+, A and B+ are execution grades" in ownership._AI_RULE
 assert "(A+, A or B+)" in liquidity_reversal._AI_RULE
