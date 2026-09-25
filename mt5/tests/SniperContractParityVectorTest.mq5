#property strict
#property script_show_inputs

#include "../include/SniperContractParityV1.mqh"

// DEMO / PAPER ONLY. Run as an MT5 Script after compilation.
// Exit convention is visible in Experts log; any mismatch prints FAIL.

void AssertEqual(const string label,const string actual,const string expected)
{
   if(actual!=expected)
      Print("SNIPER_PARITY_VECTOR FAIL ",label," actual=",actual," expected=",expected);
   else
      Print("SNIPER_PARITY_VECTOR PASS ",label," ",actual);
}

void OnStart()
{
   string raw1=TZ_SniperCanonicalContract(
      "AN-20260925-001","XAUUSD-SELL-A+-01","SELL","A+",0,
      "TREND",1.0,"HTF_CORE_HANDOFF");
   string expected_raw1="analysis_id=AN-20260925-001|zone_id=XAUUSD-SELL-A+-01|direction=SELL|current_grade=A+|qualified_mitigations=0|risk_context=TREND|base_risk_pct=1.00000000|execution_authority=HTF_CORE_HANDOFF";
   AssertEqual("canonical-1",raw1,expected_raw1);
   AssertEqual("sha256-abc",TZ_SniperSHA256("abc"),"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

   string raw2=TZ_SniperCanonicalContract(
      "  AN-2  "," Z-2 "," BUY "," A ",2,
      " COUNTER_TREND ",0.25," HTF_ZONE_SWEEP_HANDOFF ");
   string expected_raw2="analysis_id=AN-2|zone_id=Z-2|direction=BUY|current_grade=A|qualified_mitigations=2|risk_context=COUNTER_TREND|base_risk_pct=0.25000000|execution_authority=HTF_ZONE_SWEEP_HANDOFF";
   AssertEqual("canonical-2",raw2,expected_raw2);

   // Contract hashes are printed for direct comparison with the frozen Python
   // vectors in tests/test_sniper_contract_parity_vectors.py.
   Print("SNIPER_PARITY_VECTOR HASH1 ",TZ_SniperSHA256(raw1));
   Print("SNIPER_PARITY_VECTOR HASH2 ",TZ_SniperSHA256(raw2));
}
