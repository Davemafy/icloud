#ifndef __SNIPER_CONTRACT_PARITY_V1_MQH__
#define __SNIPER_CONTRACT_PARITY_V1_MQH__

// Master Sniper contract parity v1.
// DEMO / PAPER ONLY until end-to-end parity release gates pass.
// This file deliberately separates canonical serialization from hashing so the
// wire contract can be validated independently before Sequence 3.42 promotion.

#define TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"

string TZ_SniperTrim(const string value)
{
   string out=value;
   StringTrimLeft(out);
   StringTrimRight(out);
   return out;
}

string TZ_SniperCanonicalRisk(const double value)
{
   return DoubleToString(value,8);
}

string TZ_SniperCanonicalContract(
   const string analysis_id,
   const string zone_id,
   const string direction,
   const string current_grade,
   const int qualified_mitigations,
   const string risk_context,
   const double base_risk_pct,
   const string execution_authority)
{
   return
      "analysis_id="+TZ_SniperTrim(analysis_id)+
      "|zone_id="+TZ_SniperTrim(zone_id)+
      "|direction="+TZ_SniperTrim(direction)+
      "|current_grade="+TZ_SniperTrim(current_grade)+
      "|qualified_mitigations="+IntegerToString(qualified_mitigations)+
      "|risk_context="+TZ_SniperTrim(risk_context)+
      "|base_risk_pct="+TZ_SniperCanonicalRisk(base_risk_pct)+
      "|execution_authority="+TZ_SniperTrim(execution_authority);
}

// SHA-256 is intentionally not implemented here yet. The release transformer
// remains fail-closed until the MQL hash implementation is validated against
// the frozen Python vectors in tests/test_sniper_contract_parity_vectors.py.

#endif
